"""mesh_diagnostics.py - topology, manifold and normal health of mesh objects.

Purpose      : Per-mesh statistics and defect counts: tris/quads/ngons, poles,
               boundary / wire / non-manifold edges, non-manifold verts, loose
               geometry, zero-area faces, zero-length edges, duplicate verts,
               inconsistent winding, inside-out closed meshes, unapplied or
               negative scale, optional self-intersection test.
Blender      : Tested headless on 5.2.3 LTS. Uses bmesh API stable since 2.8x.
Run          : MCP execute-code tool, Text Editor, or `blender -b f.blend --python`.
               CONFIG_OVERRIDE = {"objects": ["Body"], "evaluated": True}
Output       : JSON printed + global `result` = {"objects": {...}, "summary": {...}}.
               Each object gets "issues": human-readable strings, worst first.
Safety       : Read-only. Works on a bmesh copy; never writes the mesh.
Limits       : "Inside-out" uses signed volume, meaningful only for closed meshes.
               Self-intersection is O(n log n) via BVH but skipped above
               CONFIG["self_intersection_max_faces"].
               With evaluated=True, modifier results (e.g. Subsurf) are measured.
"""
import bpy
import bmesh
import json
from mathutils.bvhtree import BVHTree

CONFIG = {
    "objects": None,               # list of names; None = all selected meshes, else all meshes
    "evaluated": False,            # measure the modifier-evaluated mesh
    "merge_distance": 1e-5,        # metres, for duplicate-vertex detection
    "area_epsilon": 1e-10,
    "self_intersection": True,
    "self_intersection_max_faces": 200000,
    "max_listed_indices": 20,      # sample indices listed per defect
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def pick_objects():
    if CONFIG["objects"]:
        return [bpy.data.objects[n] for n in CONFIG["objects"] if n in bpy.data.objects
                and bpy.data.objects[n].type == "MESH"]
    sel = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    return sel or [o for o in bpy.context.scene.objects if o.type == "MESH"]


def get_bmesh(obj):
    bm = bmesh.new()
    if CONFIG["evaluated"]:
        deps = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(deps)
        me = ev.to_mesh()
        bm.from_mesh(me)
        ev.to_mesh_clear()
    else:
        bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return bm


def sample(seq):
    return list(seq)[: CONFIG["max_listed_indices"]]


def diagnose(obj):
    bm = get_bmesh(obj)
    lim = CONFIG
    tris = quads = ngons = 0
    for f in bm.faces:
        n = len(f.verts)
        tris += n == 3
        quads += n == 4
        ngons += n > 4

    boundary, wire, nonmanifold_e, flipped_e = [], [], [], []
    zero_len = []
    for e in bm.edges:
        lf = len(e.link_faces)
        if lf == 0:
            wire.append(e.index)
        elif lf == 1:
            boundary.append(e.index)
        elif lf > 2:
            nonmanifold_e.append(e.index)
        elif not e.is_contiguous:
            flipped_e.append(e.index)          # 2 faces with opposite winding
        if e.calc_length() < lim["merge_distance"]:
            zero_len.append(e.index)

    loose_v = [v.index for v in bm.verts if not v.link_edges]
    nonman_v = [v.index for v in bm.verts if v.link_edges and not v.is_manifold]
    zero_area = [f.index for f in bm.faces if f.calc_area() < lim["area_epsilon"]]

    # Poles: interior verts with valence != 4 (only meaningful on quad topology)
    poles3 = poles5 = poles6plus = 0
    for v in bm.verts:
        if v.is_boundary or not v.link_faces:
            continue
        val = len(v.link_edges)
        poles3 += val == 3
        poles5 += val == 5
        poles6plus += val >= 6

    doubles = bmesh.ops.find_doubles(bm, verts=bm.verts, dist=lim["merge_distance"])["targetmap"]

    closed = not boundary and not wire and not nonmanifold_e and len(bm.faces) > 0
    signed_volume = bm.calc_volume(signed=True) if closed else None

    self_hits = None
    if lim["self_intersection"] and 0 < len(bm.faces) <= lim["self_intersection_max_faces"]:
        tree = BVHTree.FromBMesh(bm, epsilon=0.0)
        pairs = tree.overlap(tree)
        # overlap() reports neighbouring faces that merely share verts; filter them.
        real = set()
        for a, b in pairs:
            if a >= b:
                continue
            fa, fb = bm.faces[a], bm.faces[b]
            if set(fa.verts).isdisjoint(fb.verts):
                real.add((a, b))
        self_hits = len(real)

    mw = obj.matrix_world
    scale = list(obj.scale)
    issues = []
    if nonmanifold_e:
        issues.append(f"{len(nonmanifold_e)} edges shared by >2 faces (non-manifold)")
    if flipped_e:
        issues.append(f"{len(flipped_e)} edges between faces with inconsistent winding "
                      "(recalculate normals)")
    if signed_volume is not None and signed_volume < 0:
        issues.append("closed mesh is inside-out (negative volume): normals point inward")
    if mw.determinant() < 0:
        issues.append("negative scale/mirror in transform: normals render flipped "
                      "until scale is applied")
    if any(abs(s - 1.0) > 1e-4 for s in scale):
        issues.append(f"unapplied scale {[round(s, 4) for s in scale]} "
                      "(bevel/solidify/physics/export behave unevenly)")
    if doubles:
        issues.append(f"{len(doubles)} duplicate vertices within {lim['merge_distance']} m")
    if zero_area:
        issues.append(f"{len(zero_area)} zero-area faces")
    if zero_len:
        issues.append(f"{len(zero_len)} zero-length edges")
    if loose_v:
        issues.append(f"{len(loose_v)} loose vertices")
    if wire:
        issues.append(f"{len(wire)} wire edges (no faces)")
    if self_hits:
        issues.append(f"{self_hits} self-intersecting face pairs")
    if boundary:
        issues.append(f"{len(boundary)} open boundary edges (fine for planes/cloth; "
                      "bad for closed solids, 3D print, booleans)")
    if ngons:
        issues.append(f"{ngons} n-gons (fine on flat, non-deforming, unsubdivided areas)")
    if poles6plus:
        issues.append(f"{poles6plus} poles with 6+ edges (pinching under subdivision)")

    rep = {
        "verts": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces),
        "tris": tris, "quads": quads, "ngons": ngons,
        "triangle_count_after_triangulation": sum(len(f.verts) - 2 for f in bm.faces),
        "quad_ratio": round(quads / len(bm.faces), 3) if bm.faces else None,
        "poles": {"3": poles3, "5": poles5, "6plus": poles6plus},
        "boundary_edges": len(boundary), "wire_edges": len(wire),
        "nonmanifold_edges": len(nonmanifold_e), "nonmanifold_edge_sample": sample(nonmanifold_e),
        "inconsistent_winding_edges": len(flipped_e), "inconsistent_sample": sample(flipped_e),
        "nonmanifold_verts": len(nonman_v), "loose_verts": len(loose_v),
        "zero_area_faces": len(zero_area), "zero_length_edges": len(zero_len),
        "duplicate_verts": len(doubles),
        "closed": closed,
        "signed_volume_local": round(signed_volume, 6) if signed_volume is not None else None,
        "self_intersecting_pairs": self_hits,
        "scale": [round(s, 4) for s in scale],
        "negative_scale": mw.determinant() < 0,
        "evaluated": CONFIG["evaluated"],
        "issues": issues,
    }
    bm.free()
    return rep


def main():
    out = {"objects": {}, "summary": {}}
    for o in pick_objects():
        out["objects"][o.name] = diagnose(o)
    out["summary"] = {
        "meshes": len(out["objects"]),
        "with_issues": [n for n, r in out["objects"].items() if r["issues"]],
        "total_faces": sum(r["faces"] for r in out["objects"].values()),
        "total_tris": sum(r["triangle_count_after_triangulation"] for r in out["objects"].values()),
    }
    return out


result = main()
print(json.dumps(result, indent=1))
