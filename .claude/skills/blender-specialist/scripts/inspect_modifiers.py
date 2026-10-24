"""inspect_modifiers.py - modifier stacks, key settings and order problems.

Purpose      : List every modifier per object with its important settings and flag
               common stack mistakes (Subsurf before Bevel, Mirror after Subsurf,
               Armature not first, disabled-in-render, Boolean with missing cutter,
               Bevel on unapplied scale, very high subdivision levels).
Blender      : Tested headless on 5.2.3 LTS.
Run          : CONFIG_OVERRIDE = {"objects": ["Chair"]} or default all objects.
Output       : `result` = {"objects": {name: {"stack": [...], "warnings": [...]}},
               "evaluated_face_counts": {...}}
Safety       : Read-only (evaluates the depsgraph to count evaluated faces).
"""
import bpy
import json

CONFIG = {"objects": None, "count_evaluated": True, "subsurf_level_warn": 3}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))

KEY_PROPS = {
    "SUBSURF": ["levels", "render_levels", "subdivision_type", "use_limit_surface"],
    "MULTIRES": ["levels", "sculpt_levels", "render_levels", "total_levels"],
    "BEVEL": ["width", "segments", "limit_method", "angle_limit", "harden_normals",
              "affect", "offset_type", "profile"],
    "MIRROR": ["use_axis", "use_clip", "use_mirror_merge", "merge_threshold", "mirror_object"],
    "BOOLEAN": ["operation", "solver", "object", "collection", "operand_type"],
    "SOLIDIFY": ["thickness", "offset", "use_even_offset", "use_rim"],
    "ARRAY": ["count", "fit_type", "use_relative_offset", "relative_offset_displace"],
    "ARMATURE": ["object", "use_vertex_groups", "use_deform_preserve_volume"],
    "SHRINKWRAP": ["target", "wrap_method", "wrap_mode", "offset"],
    "WEIGHTED_NORMAL": ["mode", "weight", "keep_sharp"],
    "DECIMATE": ["decimate_type", "ratio"],
    "REMESH": ["mode", "voxel_size", "octree_depth"],
    "DISPLACE": ["strength", "mid_level", "texture", "direction"],
    "NODES": ["node_group"],
    "TRIANGULATE": ["quad_method", "ngon_method"],
    "WELD": ["merge_threshold", "mode"],
}


def val(v):
    if hasattr(v, "name"):
        return v.name
    try:
        return [round(x, 4) if isinstance(x, float) else x for x in v]
    except TypeError:
        return round(v, 4) if isinstance(v, float) else v


def main():
    objs = ([bpy.data.objects[n] for n in CONFIG["objects"] if n in bpy.data.objects]
            if CONFIG["objects"] else list(bpy.context.scene.objects))
    out = {"objects": {}, "evaluated_face_counts": {}}
    deps = bpy.context.evaluated_depsgraph_get() if CONFIG["count_evaluated"] else None
    for o in objs:
        if not getattr(o, "modifiers", None):
            continue
        stack, warn = [], []
        types = [m.type for m in o.modifiers]
        for i, m in enumerate(o.modifiers):
            ent = {"i": i, "name": m.name, "type": m.type,
                   "viewport": m.show_viewport, "render": m.show_render}
            for p in KEY_PROPS.get(m.type, []):
                if hasattr(m, p):
                    ent[p] = val(getattr(m, p))
            stack.append(ent)
            if m.show_viewport and not m.show_render:
                warn.append(f"{m.name}: visible in viewport but disabled for render")
            if m.type == "BOOLEAN" and getattr(m, "operand_type", "OBJECT") == "OBJECT" and not m.object:
                warn.append(f"{m.name}: Boolean has no cutter object")
            if m.type == "SUBSURF" and max(m.levels, m.render_levels) > CONFIG["subsurf_level_warn"]:
                warn.append(f"{m.name}: subdivision level {max(m.levels, m.render_levels)} "
                            "is heavy; use adaptive/lower levels or bake detail")
            if m.type == "BEVEL" and any(abs(s - 1) > 1e-4 for s in o.scale):
                warn.append(f"{m.name}: Bevel on unapplied scale gives uneven widths")
            if m.type == "ARMATURE" and i != 0 and "MIRROR" not in types[:i]:
                warn.append(f"{m.name}: Armature is usually first (after Mirror at most) "
                            "so it deforms the base mesh")
        if "SUBSURF" in types and "BEVEL" in types and types.index("SUBSURF") < types.index("BEVEL"):
            warn.append("Subdivision before Bevel: bevel runs on dense mesh (slow, soft). "
                        "Usual order: Mirror > Bevel > Subdivision > Weighted Normal")
        if "SUBSURF" in types and "MIRROR" in types and types.index("SUBSURF") < types.index("MIRROR"):
            warn.append("Mirror after Subdivision: seam at mirror plane; put Mirror first")
        if "WEIGHTED_NORMAL" in types and types[-1] not in ("WEIGHTED_NORMAL", "TRIANGULATE"):
            warn.append("Weighted Normal should be last (or before Triangulate) in the stack")
        out["objects"][o.name] = {"stack": stack, "warnings": warn}
        if deps and o.type == "MESH":
            ev = o.evaluated_get(deps)
            out["evaluated_face_counts"][o.name] = {"base": len(o.data.polygons),
                                                    "evaluated": len(ev.data.polygons)}
    return out


result = main()
print(json.dumps(result, indent=1))
