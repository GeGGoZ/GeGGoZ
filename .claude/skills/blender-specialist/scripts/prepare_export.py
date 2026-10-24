"""prepare_export.py - safe save-copy and export (glTF / FBX / OBJ / USD / STL).

Purpose      : 1) Optional recovery copy of the .blend (save_as_mainfile copy=True:
                  the active file path does NOT change).
               2) Pre-export checks (unapplied scale, negative scale, n-gons, missing UVs).
               3) Export selected/listed objects with engine-appropriate settings:
                  - glTF (.glb): Y-up conversion, modifiers applied, for web/Godot/three.js
                  - FBX: -Z forward/Y up, FBX_SCALE_ALL, no leaf bones, for Unity/Unreal
                  - OBJ / USD / STL for interchange, DCC, 3D print
Blender      : Tested headless on 5.2.3 LTS (glTF, FBX, OBJ, STL; USD option untested).
Run          : CONFIG_OVERRIDE = {"format": "GLB", "objects": ["Crate"],
                                  "out_dir": "C:/exports", "backup_copy": True}
Output       : `result` = {"backup", "exported", "warnings", "objects"}
Safety       : Refuses to overwrite an existing export unless "overwrite": True.
               Changes selection (restored afterwards). Never saves over the open file.
"""
import bpy
import os
import time
import json

CONFIG = {
    "format": "GLB",                 # GLB, GLTF, FBX, OBJ, USD, STL
    "objects": None,                 # None = current selection
    "out_dir": None,                 # default: <blend dir>/export or temp dir
    "basename": None,
    "overwrite": False,
    "backup_copy": False,
    "apply_modifiers": True,
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def main():
    warn = []
    blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else bpy.app.tempdir
    out_dir = CONFIG["out_dir"] or os.path.join(blend_dir, "export")
    os.makedirs(out_dir, exist_ok=True)
    backup = None
    if CONFIG["backup_copy"]:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.splitext(os.path.basename(bpy.data.filepath or "untitled.blend"))[0]
        backup = os.path.join(out_dir, f"{base}_backup_{stamp}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=backup, copy=True)

    prev_sel = [o.name for o in bpy.context.selected_objects]
    prev_active = bpy.context.view_layer.objects.active
    objs = ([bpy.data.objects[n] for n in CONFIG["objects"]] if CONFIG["objects"]
            else list(bpy.context.selected_objects))
    if not objs:
        raise ValueError("Nothing to export: pass CONFIG['objects'] or select objects.")
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
        if any(abs(s - 1) > 1e-4 for s in o.scale):
            warn.append(f"{o.name}: unapplied scale (FBX/glTF keep it as node scale)")
        if o.matrix_world.determinant() < 0:
            warn.append(f"{o.name}: negative scale -> flipped normals in engines")
        if o.type == "MESH":
            if not o.data.uv_layers:
                warn.append(f"{o.name}: no UVs")
            if any(len(p.vertices) > 4 for p in o.data.polygons):
                warn.append(f"{o.name}: n-gons will be triangulated by the exporter/engine")
    bpy.context.view_layer.objects.active = objs[0]

    fmt = CONFIG["format"].upper()
    ext = {"GLB": ".glb", "GLTF": ".gltf", "FBX": ".fbx", "OBJ": ".obj", "USD": ".usdc",
           "STL": ".stl"}[fmt]
    name = CONFIG["basename"] or (objs[0].name if len(objs) == 1 else
                                  os.path.splitext(os.path.basename(bpy.data.filepath or "scene"))[0])
    path = os.path.join(out_dir, name + ext)
    if os.path.exists(path) and not CONFIG["overwrite"]:
        raise FileExistsError(f"{path} exists; set overwrite=True")
    am = CONFIG["apply_modifiers"]
    if fmt in ("GLB", "GLTF"):
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB" if fmt == "GLB" else "GLTF_SEPARATE",
                                  use_selection=True, export_apply=am, export_yup=True)
    elif fmt == "FBX":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, apply_scale_options="FBX_SCALE_ALL",
                                 axis_forward="-Z", axis_up="Y", use_mesh_modifiers=am,
                                 add_leaf_bones=False, path_mode="COPY", embed_textures=True)
    elif fmt == "OBJ":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, apply_modifiers=am)
    elif fmt == "USD":
        bpy.ops.wm.usd_export(filepath=path, selected_objects_only=True)
    elif fmt == "STL":
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True, apply_modifiers=am)

    for o in bpy.context.selected_objects:
        o.select_set(False)
    for n in prev_sel:
        if n in bpy.data.objects:
            bpy.data.objects[n].select_set(True)
    bpy.context.view_layer.objects.active = prev_active
    return {"backup": backup, "exported": path, "bytes": os.path.getsize(path),
            "objects": [o.name for o in objs], "warnings": warn}


result = main()
print(json.dumps(result, indent=1))
