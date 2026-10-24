"""validate_project.py - one-shot technical validation gate for a .blend project.

Purpose      : Aggregate technical checks into PASS / WARN / FAIL with reasons:
               file saved, missing/unpacked external images, unit scale, objects with
               unapplied/negative scale, meshes with defects (non-manifold, flipped
               normals, loose/duplicate geometry), meshes without materials or with
               empty slots, materials without node output, missing UVs on textured
               objects, render camera, colour management, triangle budget, weights.
               This is TECHNICAL validity only. It says nothing about visual quality;
               run the visual checklist on actual renders separately.
Blender      : Tested headless on 5.2.3 LTS.
Run          : CONFIG_OVERRIDE = {"profile": "game", "tri_budget": 15000}
               Profiles: "render" (cinematic/static), "animation", "game", "print".
Output       : `result` = {"status": PASS|WARN|FAIL, "fail": [...], "warn": [...],
               "info": {...}}
Safety       : Read-only.
"""
import bpy
import bmesh
import os
import json

CONFIG = {"profile": "render", "tri_budget": None, "max_influences": None,
          "require_saved": True, "objects": None}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))

PROFILE = {
    "render": dict(ngons="ok", open_ok=True, max_infl=None, tri_budget=None, need_uv=False),
    "animation": dict(ngons="warn", open_ok=True, max_infl=8, tri_budget=None, need_uv=True),
    "game": dict(ngons="warn", open_ok=True, max_infl=4, tri_budget=50000, need_uv=True),
    "print": dict(ngons="ok", open_ok=False, max_infl=None, tri_budget=None, need_uv=False),
}


def mesh_flags(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    nonman = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    flipped = sum(1 for e in bm.edges if len(e.link_faces) == 2 and not e.is_contiguous)
    loose = sum(1 for v in bm.verts if not v.link_edges) + sum(1 for e in bm.edges if not e.link_faces)
    ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    dup = len(bmesh.ops.find_doubles(bm, verts=bm.verts, dist=1e-5)["targetmap"])
    closed = boundary == 0 and nonman == 0 and len(bm.faces) > 0
    inside_out = closed and bm.calc_volume(signed=True) < 0
    bm.free()
    return dict(nonman=nonman, boundary=boundary, flipped=flipped, loose=loose, ngons=ngons,
                tris=tris, dup=dup, inside_out=inside_out)


def main():
    prof = PROFILE[CONFIG["profile"]]
    fail, warn, info = [], [], {"profile": CONFIG["profile"], "blender": bpy.app.version_string}
    sc = bpy.context.scene
    if not bpy.data.filepath:
        (fail if CONFIG["require_saved"] else warn).append("file has never been saved")
    elif bpy.data.is_dirty:
        warn.append("unsaved changes")
    if abs(sc.unit_settings.scale_length - 1.0) > 1e-6 or sc.unit_settings.system != "METRIC":
        warn.append(f"unit system {sc.unit_settings.system} scale {sc.unit_settings.scale_length} "
                    "(skill assumes metric, 1 unit = 1 m)")
    for img in bpy.data.images:
        if img.source == "FILE" and not img.packed_file:
            p = bpy.path.abspath(img.filepath)
            if not os.path.exists(p):
                fail.append(f"missing texture file: {img.name} -> {img.filepath}")
    if not sc.camera:
        warn.append("no active scene camera")
    if sc.view_settings.view_transform not in ("AgX", "Filmic", "Khronos PBR Neutral"):
        warn.append(f"view transform '{sc.view_settings.view_transform}' "
                    "(Standard clips highlights; AgX is the default for realism)")
    objs = ([bpy.data.objects[n] for n in CONFIG["objects"]] if CONFIG["objects"]
            else [o for o in sc.objects if o.type == "MESH" and not o.hide_render])
    total_tris = 0
    budget = CONFIG["tri_budget"] or prof["tri_budget"]
    max_infl = CONFIG["max_influences"] or prof["max_infl"]
    for o in objs:
        f = mesh_flags(o)
        total_tris += f["tris"]
        n = o.name
        if any(abs(s - 1) > 1e-4 for s in o.scale):
            warn.append(f"{n}: unapplied scale {[round(s, 3) for s in o.scale]}")
        if o.matrix_world.determinant() < 0:
            fail.append(f"{n}: negative scale (flipped normals on export)")
        if f["nonman"]:
            fail.append(f"{n}: {f['nonman']} non-manifold edges (>2 faces)")
        if f["flipped"]:
            fail.append(f"{n}: {f['flipped']} edges with inconsistent normals")
        if f["inside_out"]:
            fail.append(f"{n}: closed mesh is inside-out")
        if f["boundary"] and not prof["open_ok"]:
            fail.append(f"{n}: {f['boundary']} open boundary edges (not watertight)")
        if f["loose"]:
            warn.append(f"{n}: {f['loose']} loose verts/edges")
        if f["dup"]:
            warn.append(f"{n}: {f['dup']} duplicate verts")
        if f["ngons"] and prof["ngons"] == "warn":
            warn.append(f"{n}: {f['ngons']} n-gons (triangulate predictably before export)")
        mats = [s.material for s in o.material_slots]
        if not mats:
            warn.append(f"{n}: no material")
        elif any(m is None for m in mats):
            warn.append(f"{n}: empty material slot")
        for m in [m for m in mats if m]:
            if m.node_tree and not any(nd.type == "OUTPUT_MATERIAL" and nd.is_active_output
                                       for nd in m.node_tree.nodes):
                fail.append(f"{n}: material {m.name} has no active Material Output")
            uses_img = m.node_tree and any(nd.type == "TEX_IMAGE" and nd.projection == "FLAT"
                                           and not nd.inputs["Vector"].is_linked
                                           for nd in m.node_tree.nodes)
            if uses_img and not o.data.uv_layers:
                fail.append(f"{n}: image texture in {m.name} but mesh has no UVs")
        if prof["need_uv"] and not o.data.uv_layers:
            fail.append(f"{n}: no UV map (required for {CONFIG['profile']})")
        if max_infl and o.vertex_groups:
            over = sum(1 for v in o.data.vertices if sum(1 for g in v.groups if g.weight > 1e-4) > max_infl)
            if over:
                warn.append(f"{n}: {over} verts exceed {max_infl} bone influences")
    info["meshes"] = len(objs)
    info["total_tris"] = total_tris
    if budget and total_tris > budget:
        fail.append(f"triangle budget exceeded: {total_tris} > {budget}")
    status = "FAIL" if fail else ("WARN" if warn else "PASS")
    return {"status": status, "fail": fail, "warn": warn, "info": info,
            "note": "Technical validity only. Visual quality needs render review."}


result = main()
print(json.dumps(result, indent=1))
