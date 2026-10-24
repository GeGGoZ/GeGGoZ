"""inspect_scene.py - read-only overview of the current Blender scene.

Purpose      : One JSON report of objects, transforms, sizes, hierarchy, materials,
               modifiers, cameras, lights, render/colour/unit settings.
Blender      : Tested headless on 5.2.3 LTS (bpy wheel). Written for 4.2+.
Run          : Paste into an MCP "execute code" tool, Blender's Text Editor, or
               `blender -b file.blend --python inspect_scene.py`.
Output       : Prints JSON and assigns it to the global `result`.
Safety       : Read-only. Does not change selection, mode or data.
Config       : Define CONFIG_OVERRIDE = {...} before running to change CONFIG.
"""
import bpy
import json
import math
from mathutils import Vector

CONFIG = {
    "max_objects": 200,        # cap object lines to keep MCP replies small
    "include_hidden": True,
    "name_filter": "",         # substring filter, case-insensitive
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def _r(v, n=4):
    return [round(x, n) for x in v]


def world_bbox(obj):
    """World-space axis-aligned bounds from the object's evaluated bound_box."""
    if not hasattr(obj, "bound_box") or obj.type in {"EMPTY", "LIGHT", "CAMERA"}:
        return None
    mw = obj.matrix_world
    pts = [mw @ Vector(c) for c in obj.bound_box]
    mn = [min(p[i] for p in pts) for i in range(3)]
    mx = [max(p[i] for p in pts) for i in range(3)]
    return {"min": _r(mn), "max": _r(mx), "size": _r([mx[i] - mn[i] for i in range(3)])}


def object_entry(obj):
    e = {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "collections": [c.name for c in obj.users_collection],
        "location": _r(obj.location),
        "rotation_deg": _r([math.degrees(a) for a in obj.rotation_euler], 2),
        "scale": _r(obj.scale),
        "hidden_viewport": obj.hide_get() if obj.name in bpy.context.view_layer.objects else None,
        "hidden_render": obj.hide_render,
        "bbox": world_bbox(obj),
    }
    if obj.type == "MESH":
        me = obj.data
        e["mesh"] = {"verts": len(me.vertices), "faces": len(me.polygons),
                     "uv_layers": [u.name for u in me.uv_layers],
                     "vertex_groups": len(obj.vertex_groups),
                     "shape_keys": len(me.shape_keys.key_blocks) if me.shape_keys else 0}
    if hasattr(obj, "material_slots"):
        e["materials"] = [s.material.name if s.material else None for s in obj.material_slots]
    if obj.modifiers:
        e["modifiers"] = [f"{m.name}:{m.type}" for m in obj.modifiers]
    if obj.type == "CAMERA":
        c = obj.data
        e["camera"] = {"lens_mm": round(c.lens, 2), "sensor_mm": c.sensor_width,
                       "dof": c.dof.use_dof, "fstop": round(c.dof.aperture_fstop, 2),
                       "clip": [c.clip_start, c.clip_end]}
    if obj.type == "LIGHT":
        l = obj.data
        e["light"] = {"type": l.type, "energy_W": l.energy, "color": _r(l.color, 3)}
        if l.type == "AREA":
            e["light"]["size"] = [l.size, l.size_y]
    if obj.type == "ARMATURE":
        e["bones"] = len(obj.data.bones)
    return e


def main():
    sc = bpy.context.scene
    flt = CONFIG["name_filter"].lower()
    objs = [o for o in sc.objects if (CONFIG["include_hidden"] or o.visible_get())
            and flt in o.name.lower()]
    rep = {
        "blender_version": bpy.app.version_string,
        "file": bpy.data.filepath or "<unsaved>",
        "dirty": bpy.data.is_dirty,
        "scene": sc.name,
        "mode": bpy.context.mode,
        "active": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        "frame": [sc.frame_start, sc.frame_current, sc.frame_end],
        "units": {"system": sc.unit_settings.system, "scale_length": sc.unit_settings.scale_length,
                  "length_unit": sc.unit_settings.length_unit},
        "render": {"engine": sc.render.engine,
                   "resolution": [sc.render.resolution_x, sc.render.resolution_y,
                                  sc.render.resolution_percentage],
                   "camera": sc.camera.name if sc.camera else None,
                   "film_transparent": sc.render.film_transparent},
        "color_management": {"view_transform": sc.view_settings.view_transform,
                             "look": sc.view_settings.look,
                             "exposure": sc.view_settings.exposure},
        "world": sc.world.name if sc.world else None,
        "counts": {},
        "collections": [c.name for c in bpy.data.collections],
        "objects": [],
        "truncated": False,
    }
    if sc.render.engine == "CYCLES":
        rep["render"]["cycles"] = {"samples": sc.cycles.samples, "device": sc.cycles.device,
                                   "denoise": sc.cycles.use_denoising}
    for o in sc.objects:
        rep["counts"][o.type] = rep["counts"].get(o.type, 0) + 1
    for o in objs[: CONFIG["max_objects"]]:
        rep["objects"].append(object_entry(o))
    rep["truncated"] = len(objs) > CONFIG["max_objects"]
    return rep


result = main()
print(json.dumps(result, indent=1))
