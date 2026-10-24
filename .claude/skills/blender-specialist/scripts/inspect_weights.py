"""inspect_weights.py - vertex groups, skin weights and armature binding health.

Purpose      : For each skinned mesh: unweighted verts (would not follow the rig),
               unnormalised totals, too many influences (game engines often cap at 4
               or 8), vertex groups without a matching deform bone (dead groups),
               deform bones without a group, empty groups, missing/disabled Armature
               modifier, and armature transform problems (unapplied scale).
Blender      : Tested headless on 5.2.3 LTS.
Run          : CONFIG_OVERRIDE = {"objects": ["Body"], "max_influences": 4}
Output       : `result` = {"objects": {name: {...}}}
Safety       : Read-only.
Limits       : Counts weights > CONFIG["weight_epsilon"] as influences. Groups used
               by other modifiers (masks, hair density) are reported as non-deform
               but may be intentional.
"""
import bpy
import json

CONFIG = {"objects": None, "max_influences": 4, "weight_epsilon": 1e-4,
          "normalize_tolerance": 0.01, "max_listed": 15}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def check(obj):
    rep = {"issues": []}
    arm_mods = [m for m in obj.modifiers if m.type == "ARMATURE"]
    arm = arm_mods[0].object if arm_mods and arm_mods[0].object else None
    if obj.parent and obj.parent.type == "ARMATURE" and arm is None:
        arm = obj.parent
    rep["armature"] = arm.name if arm else None
    rep["armature_modifier"] = bool(arm_mods)
    if not arm_mods:
        rep["issues"].append("no Armature modifier")
    elif not arm_mods[0].show_render or not arm_mods[0].show_viewport:
        rep["issues"].append("Armature modifier disabled in viewport or render")
    groups = {g.index: g.name for g in obj.vertex_groups}
    rep["vertex_groups"] = len(groups)
    deform = set()
    if arm:
        deform = {b.name for b in arm.data.bones if b.use_deform}
        rep["deform_bones"] = len(deform)
        if any(abs(s - 1) > 1e-4 for s in arm.scale):
            rep["issues"].append(f"armature '{arm.name}' has unapplied scale {list(arm.scale)}")
    counts = {gi: 0 for gi in groups}
    unweighted, unnormalized, over = [], [], []
    infl_hist = {}
    eps = CONFIG["weight_epsilon"]
    for v in obj.data.vertices:
        ws = [(g.group, g.weight) for g in v.groups
              if g.weight > eps and (not deform or groups.get(g.group) in deform)]
        for gi, _ in ws:
            counts[gi] = counts.get(gi, 0) + 1
        n = len(ws)
        infl_hist[n] = infl_hist.get(n, 0) + 1
        if n == 0:
            unweighted.append(v.index)
            continue
        tot = sum(w for _, w in ws)
        if abs(tot - 1.0) > CONFIG["normalize_tolerance"]:
            unnormalized.append(v.index)
        if n > CONFIG["max_influences"]:
            over.append(v.index)
    lm = CONFIG["max_listed"]
    rep.update({
        "verts": len(obj.data.vertices),
        "unweighted_verts": len(unweighted), "unweighted_sample": unweighted[:lm],
        "unnormalized_verts": len(unnormalized), "unnormalized_sample": unnormalized[:lm],
        "over_influence_verts": len(over),
        "influence_histogram": dict(sorted(infl_hist.items())),
        "empty_groups": [groups[g] for g, c in counts.items() if c == 0 and g in groups],
    })
    if deform:
        names = set(groups.values())
        rep["groups_without_deform_bone"] = sorted(names - deform)
        rep["deform_bones_without_group"] = sorted(deform - names)
    if unweighted:
        rep["issues"].append(f"{len(unweighted)} verts have no deform weight (stay behind when posed)")
    if unnormalized:
        rep["issues"].append(f"{len(unnormalized)} verts weights do not sum to 1 "
                             "(Blender normalises at deform time, engines may not)")
    if over:
        rep["issues"].append(f"{len(over)} verts exceed {CONFIG['max_influences']} influences")
    if rep.get("deform_bones_without_group"):
        rep["issues"].append(f"{len(rep['deform_bones_without_group'])} deform bones have no "
                             "vertex group (bone moves nothing: check use_deform or weights)")
    return rep


def main():
    objs = ([bpy.data.objects[n] for n in CONFIG["objects"] if n in bpy.data.objects]
            if CONFIG["objects"] else
            [o for o in bpy.context.scene.objects if o.type == "MESH" and
             (o.vertex_groups or any(m.type == "ARMATURE" for m in o.modifiers))])
    return {"objects": {o.name: check(o) for o in objs if o.type == "MESH"}}


result = main()
print(json.dumps(result, indent=1))
