"""example_build_mug.py - worked example: real-scale ceramic mug, built in stages.

Purpose      : Demonstrates the skill's staged production loop on a simple prop and
               doubles as an acceptance test on a new machine:
               Stage 1 requirements  : 85 mm diameter, 95 mm tall, 4 mm walls,
                                       glazed ceramic, product shot.
               Stage 2 blockout      : revolved profile (bmesh spin) at real scale.
               Stage 3 primary forms : handle from a curve swept with a round profile.
               Stage 4 refinement    : Subdivision + support loops from profile spacing,
                                       smooth shading, weighted rim.
               Stage 5 UV + material : smart UV project, glazed ceramic preset values.
               It does NOT light/render; run setup_camera_lighting.py and
               render_preview.py next (the test harness does).
Blender      : Tested headless on 5.2.3 LTS.
Run          : Execute in an empty or scratch scene. CONFIG_OVERRIDE = {"replace": True}
Output       : `result` = {"objects": [...], "dimensions_m": [...], "faces": int}
Safety       : Creates GEO_Mug_Body / GEO_Mug_Handle / M_MugGlaze; with replace=True it
               deletes previous objects with those exact names only.
"""
import bpy
import bmesh
import json
import math
from mathutils import Vector

CONFIG = {"diameter": 0.085, "height": 0.095, "wall": 0.004, "base": 0.006,
          "segments": 48, "replace": True, "color": (0.05, 0.12, 0.25)}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def clear(name):
    o = bpy.data.objects.get(name)
    if o and CONFIG["replace"]:
        bpy.data.objects.remove(o, do_unlink=True)


def body():
    R, H, t, b = CONFIG["diameter"] / 2, CONFIG["height"], CONFIG["wall"], CONFIG["base"]
    # Profile in XZ from inner bottom centre, around the rim, to outer bottom centre.
    # Extra closely spaced points near edges act as support loops under subdivision.
    prof = [
        (0.0, b), (R - t - 0.006, b), (R - t - 0.0015, b + 0.0005), (R - t, b + 0.003),
        (R - t, H - 0.004), (R - t, H - 0.001), (R - t * 0.5, H), (R, H - 0.001),
        (R, H - 0.004), (R + 0.0005, H * 0.5), (R, 0.006), (R - 0.0005, 0.0015),
        (R - 0.003, 0.0), (R - 0.008, 0.0), (R - 0.010, 0.0015), (R - 0.012, 0.0015),
        (0.0, 0.0015),
    ]
    me = bpy.data.meshes.new("GEO_Mug_Body")
    bm = bmesh.new()
    verts = [bm.verts.new((x, 0, z)) for x, z in prof]
    edges = [bm.edges.new((verts[i], verts[i + 1])) for i in range(len(verts) - 1)]
    bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=(0, 0, 1),
                   angle=math.tau, steps=CONFIG["segments"], use_duplicate=False)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    # Close the poles at the centre axis (verts on axis already merged by remove_doubles)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    clear("GEO_Mug_Body")
    o = bpy.data.objects.new("GEO_Mug_Body", me)
    bpy.context.scene.collection.objects.link(o)
    return o


def handle():
    R, H = CONFIG["diameter"] / 2, CONFIG["height"]
    cu = bpy.data.curves.new("CRV_Mug_Handle", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("BEZIER")
    pts = [(R - 0.002, 0, H * 0.78), (R + 0.022, 0, H * 0.72), (R + 0.024, 0, H * 0.35),
           (R - 0.002, 0, H * 0.25)]
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    cu.bevel_depth = 0.0055
    cu.bevel_resolution = 4
    cu.resolution_u = 16
    cu.use_fill_caps = True
    tmp = bpy.data.objects.new("tmp_handle", cu)
    bpy.context.scene.collection.objects.link(tmp)
    deps = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(deps))
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.curves.remove(cu)
    me.name = "GEO_Mug_Handle"
    # Curve fill caps come out as separate n-gons: weld them so the solid is closed.
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    clear("GEO_Mug_Handle")
    o = bpy.data.objects.new("GEO_Mug_Handle", me)
    o.scale = (1.0, 1.4, 1.0)      # oval cross-section reads better than round
    bpy.context.scene.collection.objects.link(o)
    o.data.transform(o.matrix_basis)   # apply scale into mesh data
    o.matrix_basis.identity()
    return o


def finish(o, mat):
    for p in o.data.polygons:
        p.use_smooth = True
    sub = o.modifiers.new("Subdivision", "SUBSURF")
    sub.levels, sub.render_levels = 1, 2
    o.data.materials.append(mat)
    # UVs: smart project needs edit mode on this object only.
    for s in bpy.context.selected_objects:
        s.select_set(False)
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01)
    bpy.ops.object.mode_set(mode="OBJECT")


def material():
    m = bpy.data.materials.get("M_MugGlaze") or bpy.data.materials.new("M_MugGlaze")
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*CONFIG["color"], 1)
    b.inputs["Roughness"].default_value = 0.08
    b.inputs["IOR"].default_value = 1.5
    b.inputs["Coat Weight"].default_value = 0.3
    m.diffuse_color = (*CONFIG["color"], 1)
    return m


def main():
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    m = material()
    b, h = body(), handle()
    finish(b, m)
    finish(h, m)
    deps = bpy.context.evaluated_depsgraph_get()
    pts = [o.matrix_world @ Vector(c) for o in (b, h) for c in o.evaluated_get(deps).bound_box]
    dims = [round(max(p[i] for p in pts) - min(p[i] for p in pts), 4) for i in range(3)]
    return {"objects": [b.name, h.name], "dimensions_m": dims,
            "faces": len(b.data.polygons) + len(h.data.polygons),
            "requirement": {"diameter": CONFIG["diameter"], "height": CONFIG["height"]}}


result = main()
print(json.dumps(result, indent=1))
