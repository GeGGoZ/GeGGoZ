"""select_problem_geometry.py - select defective elements in Edit Mode for visual review.

Purpose      : Put one mesh in Edit Mode with only the chosen defect selected, so a
               viewport screenshot shows exactly where the problem is.
               Kinds: non_manifold, boundary, ngons, triangles, poles, loose,
               zero_area, flipped (inconsistent winding).
Blender      : Tested headless on 5.2.3 LTS (bmesh edit-mesh path).
Run          : CONFIG_OVERRIDE = {"object": "Body", "kind": "non_manifold"}
Output       : `result` = {"object", "kind", "selected_verts", "selected_edges",
               "selected_faces"}.
Safety       : Changes the active object, mode and selection only. No geometry edits.
               Exit with bpy.ops.object.mode_set(mode="OBJECT") when done.
"""
import bpy
import bmesh
import json

CONFIG = {"object": None, "kind": "non_manifold"}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def main():
    obj = bpy.data.objects.get(CONFIG["object"]) if CONFIG["object"] else bpy.context.active_object
    if obj is None or obj.type != "MESH":
        raise ValueError("Need a mesh object (CONFIG['object'] or active object).")
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    for seq in (bm.verts, bm.edges, bm.faces):
        for el in seq:
            el.select = False
    k = CONFIG["kind"]
    if k == "non_manifold":
        for e in bm.edges:
            if not e.is_manifold and not e.is_boundary:
                e.select = True
        for v in bm.verts:
            if v.link_edges and not v.is_manifold and not v.is_boundary:
                v.select = True
    elif k == "boundary":
        for e in bm.edges:
            e.select = e.is_boundary
    elif k == "ngons":
        for f in bm.faces:
            f.select = len(f.verts) > 4
    elif k == "triangles":
        for f in bm.faces:
            f.select = len(f.verts) == 3
    elif k == "poles":
        for v in bm.verts:
            v.select = (not v.is_boundary) and bool(v.link_faces) and len(v.link_edges) not in (4,)
    elif k == "loose":
        for v in bm.verts:
            v.select = not v.link_edges
        for e in bm.edges:
            e.select = not e.link_faces
    elif k == "zero_area":
        for f in bm.faces:
            f.select = f.calc_area() < 1e-10
    elif k == "flipped":
        for e in bm.edges:
            e.select = len(e.link_faces) == 2 and not e.is_contiguous
    else:
        raise ValueError(f"unknown kind {k}")
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return {"object": obj.name, "kind": k,
            "selected_verts": sum(v.select for v in bm.verts),
            "selected_edges": sum(e.select for e in bm.edges),
            "selected_faces": sum(f.select for f in bm.faces)}


result = main()
print(json.dumps(result))
