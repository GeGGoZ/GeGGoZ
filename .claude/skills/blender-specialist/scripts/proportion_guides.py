"""proportion_guides.py - non-rendering proportion guides for character blockout.

Purpose      : Build wireframe guide lines at classical landmark heights so a blockout
               can be checked against a canon BEFORE detailing:
               - body: head-unit lines (chin, nipples, navel, crotch, mid-thigh, knee,
                 mid-shin, sole) plus shoulder-width and hip-width markers
               - head: vertex, hairline, brow, eye line, nose base, mouth, chin, and
                 eye-width columns (head ~5 eye-widths wide)
               Canons are STARTING GUIDES. Real people vary; measured reference photos
               of the specific subject override every number here.
Blender      : Tested headless on 5.2.3 LTS.
Run          : CONFIG_OVERRIDE = {"kind": "body", "height_m": 1.78, "heads": 7.5,
                                  "sex": "male"}
               CONFIG_OVERRIDE = {"kind": "head", "head_height_m": 0.235}
Output       : `result` = {"object", "landmarks_m": {name: z}}
Safety       : Creates/replaces object "REF_Proportions_<kind>" in collection "REF";
               display as wire, hidden from render, unselectable.
"""
import bpy
import bmesh
import json

CONFIG = {
    "kind": "body",          # body | head
    "height_m": 1.75,        # adult average varies by population; use subject data
    "heads": 7.5,            # 7-7.5 realistic adult, 8 heroic/fashion, 6-6.5 teen, ~4 toddler
    "sex": "male",           # affects shoulder / hip width markers only
    "head_height_m": 0.23,   # vertex to chin
    "origin": (0.0, 0.0, 0.0),
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))

# Body landmarks in head units measured DOWN from the top of the head (7.5-head canon,
# scaled when CONFIG["heads"] differs).
BODY = {"top_of_head": 0.0, "chin": 1.0, "nipples": 2.0, "navel": 3.0, "crotch": 3.75,
        "mid_thigh": 4.75, "knee": 5.5, "mid_shin": 6.5, "sole": 7.5}
# Head landmarks as a fraction of head height measured UP from the chin.
HEAD = {"chin": 0.0, "mouth": 0.19, "nose_base": 0.29, "eye_line": 0.5, "brow": 0.57,
        "hairline": 0.85, "vertex": 1.0}


def guide_obj(name, lines):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    for a, b in lines:
        bm.edges.new((bm.verts.new(a), bm.verts.new(b)))
    bm.to_mesh(me)
    bm.free()
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    o = bpy.data.objects.new(name, me)
    coll = bpy.data.collections.get("REF") or bpy.data.collections.new("REF")
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    coll.objects.link(o)
    o.display_type = "WIRE"
    o.show_in_front = True
    o.hide_render = True
    o.hide_select = True
    return o


def main():
    ox, oy, oz = CONFIG["origin"]
    marks, lines = {}, []
    if CONFIG["kind"] == "body":
        H = CONFIG["height_m"]
        hu = H / CONFIG["heads"]
        k = CONFIG["heads"] / 7.5
        half = hu * 1.5
        for n, u in BODY.items():
            z = oz + H - u * k * hu
            marks[n] = round(z, 4)
            lines.append(((ox - half, oy, z), (ox + half, oy, z)))
        sh = hu * (2.0 if CONFIG["sex"] == "male" else 1.75) / 2   # shoulder width ~2 / ~1.75 heads
        hp = hu * (1.5 if CONFIG["sex"] == "male" else 1.75) / 2   # hip width
        zs = oz + H - 1.33 * k * hu
        zh = marks["crotch"] + hu * 0.4
        for x in (-sh, sh):
            lines.append(((ox + x, oy, zs - hu * 0.3), (ox + x, oy, zs + hu * 0.3)))
        for x in (-hp, hp):
            lines.append(((ox + x, oy, zh - hu * 0.3), (ox + x, oy, zh + hu * 0.3)))
        marks["shoulder_line"] = round(zs, 4)
        marks["head_unit_m"] = round(hu, 4)
        lines.append(((ox, oy, oz), (ox, oy, oz + H)))
    else:
        hh = CONFIG["head_height_m"]
        w = hh * 0.75                       # head width ~ 3/4 of height (front view)
        for n, f in HEAD.items():
            z = oz + f * hh
            marks[n] = round(z, 4)
            lines.append(((ox - w / 2, oy, z), (ox + w / 2, oy, z)))
        ew = w / 5                          # five eye-widths across
        for i in range(6):
            x = ox - w / 2 + i * ew
            lines.append(((x, oy, oz + 0.45 * hh), (x, oy, oz + 0.55 * hh)))
        lines.append(((ox, oy, oz), (ox, oy, oz + hh)))
        marks["eye_width_m"] = round(ew, 4)
    o = guide_obj(f"REF_Proportions_{CONFIG['kind']}", lines)
    return {"object": o.name, "landmarks_m": marks,
            "note": "Canon guide only; measured subject reference overrides."}


result = main()
print(json.dumps(result, indent=1))
