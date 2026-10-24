"""render_preview.py - render evidence images for visual review.

Purpose      : Produce images the agent (and user) can actually look at:
               - "camera": one render through the scene camera
               - "turnaround": N renders orbiting the target with a temporary camera
                 (front / 3-4 / side / back reads for silhouette and proportion)
               - "clay": same as above with a grey override material, to judge form
                 without materials hiding problems
               Saves PNGs to out_dir and returns their paths.
Blender      : Tested headless on 5.2.3 LTS with Cycles CPU (EEVEE/Workbench also
               render headless when an OpenGL/EGL driver is present).
Run          : CONFIG_OVERRIDE = {"mode": "turnaround", "target": "Head", "views": 4,
                                  "out_dir": "C:/renders", "engine": "CYCLES"}
Output       : `result` = {"images": [paths], "seconds": float}
Safety       : Temporary camera (HLP_PreviewCam) and override are removed afterwards;
               scene camera, engine, resolution and samples are restored.
Notes        : Over MCP, prefer the server's own screenshot/look tool for quick
               viewport checks; use this for engine-true lighting/material evidence.
"""
import bpy
import os
import json
import math
import time
from mathutils import Vector

CONFIG = {
    "mode": "camera",              # camera | turnaround | clay
    "target": None,
    "views": 4,
    "elevation_deg": 10.0,
    "focal_mm": 85.0,
    "engine": None,                # None = keep scene engine
    "samples": 32,
    "resolution": (640, 640),
    "out_dir": None,
    "prefix": "preview",
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def target_bounds():
    sc = bpy.context.scene
    objs = ([bpy.data.objects[CONFIG["target"]]] if CONFIG["target"] else
            [o for o in sc.objects if o.type == "MESH" and o.visible_get()
             and not o.name.startswith("GEO_Backdrop")])
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    mn = Vector([min(p[i] for p in pts) for i in range(3)])
    mx = Vector([max(p[i] for p in pts) for i in range(3)])
    return (mn + mx) / 2, (mx - mn)


def main():
    sc = bpy.context.scene
    r = sc.render
    saved = dict(cam=sc.camera, engine=r.engine, rx=r.resolution_x, ry=r.resolution_y,
                 pct=r.resolution_percentage, path=r.filepath,
                 override=bpy.context.view_layer.material_override,
                 samples=sc.cycles.samples if hasattr(sc, "cycles") else None)
    out_dir = CONFIG["out_dir"] or os.path.join(
        os.path.dirname(bpy.data.filepath) if bpy.data.filepath else bpy.app.tempdir, "previews")
    os.makedirs(out_dir, exist_ok=True)
    if CONFIG["engine"]:
        r.engine = CONFIG["engine"]
    r.resolution_x, r.resolution_y = CONFIG["resolution"]
    r.resolution_percentage = 100
    if r.engine == "CYCLES":
        sc.cycles.samples = CONFIG["samples"]
    images, tmp = [], []
    t0 = time.time()
    try:
        if CONFIG["mode"] == "clay" or CONFIG["mode"] == "turnaround_clay":
            clay = bpy.data.materials.new("M_PreviewClay")
            b = clay.node_tree.nodes.get("Principled BSDF")
            b.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1)
            b.inputs["Roughness"].default_value = 0.55
            bpy.context.view_layer.material_override = clay
            tmp.append(clay)
        if CONFIG["mode"] == "camera" or (CONFIG["mode"] == "clay" and sc.camera and not CONFIG["target"]):
            if not sc.camera:
                raise ValueError("No scene camera; use mode='turnaround' or add a camera")
            p = os.path.join(out_dir, f"{CONFIG['prefix']}_camera.png")
            r.filepath = p
            bpy.ops.render.render(write_still=True)
            images.append(p)
        else:
            center, size = target_bounds()
            cd = bpy.data.cameras.new("HLP_PreviewCam")
            cd.lens = CONFIG["focal_mm"]
            cam = bpy.data.objects.new("HLP_PreviewCam", cd)
            sc.collection.objects.link(cam)
            tmp += [cam, cd]
            sc.camera = cam
            fov = 2 * math.atan(cd.sensor_width / 2 / cd.lens)
            dist = (max(size) * 1.25) / 2 / math.tan(fov / 2) + max(size) / 2
            cd.clip_end = dist * 20
            el = math.radians(CONFIG["elevation_deg"])
            for i in range(CONFIG["views"]):
                az = 2 * math.pi * i / CONFIG["views"]
                cam.location = center + Vector((math.sin(az) * math.cos(el),
                                                -math.cos(az) * math.cos(el), math.sin(el))) * dist
                cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
                p = os.path.join(out_dir, f"{CONFIG['prefix']}_{i:02d}_{round(math.degrees(az))}deg.png")
                r.filepath = p
                bpy.ops.render.render(write_still=True)
                images.append(p)
    finally:
        sc.camera = saved["cam"]
        r.engine = saved["engine"]
        r.resolution_x, r.resolution_y, r.resolution_percentage = saved["rx"], saved["ry"], saved["pct"]
        r.filepath = saved["path"]
        bpy.context.view_layer.material_override = saved["override"]
        if saved["samples"] is not None:
            sc.cycles.samples = saved["samples"]
        for d in tmp:
            if isinstance(d, bpy.types.Object):
                bpy.data.objects.remove(d, do_unlink=True)
            elif isinstance(d, bpy.types.Camera):
                bpy.data.cameras.remove(d)
            elif isinstance(d, bpy.types.Material):
                bpy.data.materials.remove(d)
    return {"images": images, "seconds": round(time.time() - t0, 2)}


result = main()
print(json.dumps(result, indent=1))
