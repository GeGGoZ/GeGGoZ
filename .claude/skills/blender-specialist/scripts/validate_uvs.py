"""validate_uvs.py - UV map health: presence, islands, bounds, overlaps, stretch, texel density.

Purpose      : Catch UV problems before baking/texturing:
               - missing UV map, multiple maps (which is active for render)
               - degenerate (zero UV area) faces
               - faces outside 0-1 (allowed when "udim": True; then tiles are reported)
               - overlapping faces (2D triangle intersection test, spatial hashed)
               - area stretch: per-face (UV area / 3D area) relative to the mesh median
               - texel density in px/m for a given texture resolution, and the spread
               - island count and UV space usage
Blender      : Tested headless on 5.2.3 LTS.
Run          : CONFIG_OVERRIDE = {"objects": ["Crate"], "texture_size": 2048}
Output       : `result` = {"objects": {name: {...metrics..., "issues": [...]}}}
Safety       : Read-only. Uses a triangulated bmesh copy.
Limits       : Overlap test caps at CONFIG["overlap_max_tris"] triangles. Intentional
               overlaps (mirrored/stacked islands) are reported too; decide per asset.
               Stretch is area-based (catches scale distortion, not pure shear).
"""
import bpy
import bmesh
import json
import math
from collections import defaultdict
from mathutils import Vector
from mathutils.geometry import intersect_tri_tri_2d, area_tri

CONFIG = {
    "objects": None,
    "texture_size": 2048,
    "udim": False,
    "overlap_max_tris": 60000,
    "overlap_grid": 128,
    "stretch_ratio_warn": 2.0,     # face density differs from median by this factor
    "shrink": 0.995,               # shrink tris toward centroid to ignore shared edges
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def pick():
    if CONFIG["objects"]:
        return [bpy.data.objects[n] for n in CONFIG["objects"]
                if n in bpy.data.objects and bpy.data.objects[n].type == "MESH"]
    sel = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    return sel or [o for o in bpy.context.scene.objects if o.type == "MESH"]


def islands(bm, uv):
    """Union-find faces connected by an edge whose two loops share UV coordinates."""
    parent = list(range(len(bm.faces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) != 2:
            continue
        f1, f2 = lf
        uvs1 = {l.vert.index: l[uv].uv.copy().freeze() for l in f1.loops}
        uvs2 = {l.vert.index: l[uv].uv.copy().freeze() for l in f2.loops}
        a, b = e.verts
        if all((uvs1[v.index] - uvs2[v.index]).length < 1e-6 for v in (a, b)):
            ra, rb = find(f1.index), find(f2.index)
            if ra != rb:
                parent[ra] = rb
    return len({find(i) for i in range(len(bm.faces))})


def check(obj):
    me = obj.data
    rep = {"uv_layers": [u.name for u in me.uv_layers],
           "active_render": next((u.name for u in me.uv_layers if u.active_render), None),
           "issues": []}
    if not me.uv_layers:
        rep["issues"].append("no UV map")
        return rep
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(obj.matrix_world)          # world-space areas for texel density
    bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.active
    rep["islands"] = islands(bm, uv)

    out_of_bounds, degenerate, tiles = 0, 0, set()
    ratios, uv_total, area_total = [], 0.0, 0.0
    for f in bm.faces:
        pts = [l[uv].uv for l in f.loops]
        a2 = 0.0
        for i in range(1, len(pts) - 1):
            a2 += area_tri(pts[0], pts[i], pts[i + 1])
        a3 = f.calc_area()
        uv_total += a2
        area_total += a3
        if a2 < 1e-12:
            degenerate += 1
            continue
        if a3 > 1e-12:
            ratios.append(a2 / a3)
        for p in pts:
            if p.x < 0 or p.y < 0 or p.x > 1 or p.y > 1:
                out_of_bounds += 1
                break
        cu = sum(p.x for p in pts) / len(pts)
        cv = sum(p.y for p in pts) / len(pts)
        tiles.add((math.floor(cu), math.floor(cv)))     # tile by face centre, not corners
    rep["degenerate_uv_faces"] = degenerate
    rep["faces_outside_0_1"] = out_of_bounds
    rep["udim_tiles"] = sorted(1001 + u + 10 * v for u, v in tiles if u >= 0 and v >= 0 and u < 10)
    rep["uv_space_used_pct"] = round(100 * uv_total / max(1, len(tiles) if CONFIG["udim"] else 1), 1)

    if ratios and area_total > 0:
        ratios.sort()
        med = ratios[len(ratios) // 2]
        k = CONFIG["stretch_ratio_warn"]
        bad = sum(1 for r in ratios if r > med * k or r < med / k)
        rep["stretched_faces"] = bad
        rep["stretched_pct"] = round(100 * bad / len(ratios), 2)
        size = CONFIG["texture_size"]
        rep["texel_density_px_per_m"] = round(math.sqrt(uv_total / area_total) * size, 1)
        rep["texel_density_spread"] = [round(math.sqrt(ratios[int(len(ratios) * q)]) * size, 1)
                                       for q in (0.05, 0.5, 0.95)]
    # Overlaps
    tris = []
    for f in bm.faces:
        pts = [l[uv].uv.copy() for l in f.loops]
        for i in range(1, len(pts) - 1):
            tris.append((f.index, (pts[0], pts[i], pts[i + 1])))
    overlap_faces = set()
    if len(tris) <= CONFIG["overlap_max_tris"]:
        g = CONFIG["overlap_grid"]
        grid = defaultdict(list)
        shrunk = []
        for ti, (fi, t) in enumerate(tris):
            c = (t[0] + t[1] + t[2]) / 3
            s = [c + (p - c) * CONFIG["shrink"] for p in t]
            shrunk.append(s)
            xs = [p.x for p in s]; ys = [p.y for p in s]
            for gx in range(math.floor(min(xs) * g), math.floor(max(xs) * g) + 1):
                for gy in range(math.floor(min(ys) * g), math.floor(max(ys) * g) + 1):
                    grid[(gx, gy)].append(ti)
        tested = set()
        for cell in grid.values():
            for i in range(len(cell)):
                for j in range(i + 1, len(cell)):
                    a, b = cell[i], cell[j]
                    fa, fb = tris[a][0], tris[b][0]
                    if fa == fb or (a, b) in tested:
                        continue
                    tested.add((a, b))
                    if intersect_tri_tri_2d(*shrunk[a], *shrunk[b]):
                        overlap_faces.add(fa); overlap_faces.add(fb)
        rep["overlapping_faces"] = len(overlap_faces)
    else:
        rep["overlapping_faces"] = None
        rep["issues"].append("overlap test skipped (too many triangles)")
    bm.free()

    if degenerate:
        rep["issues"].append(f"{degenerate} faces with zero UV area (texture smears)")
    if out_of_bounds and not CONFIG["udim"]:
        rep["issues"].append(f"{out_of_bounds} faces outside 0-1 UV space")
    if rep.get("overlapping_faces"):
        rep["issues"].append(f"{rep['overlapping_faces']} faces overlap in UV "
                             "(bad for baking/lightmaps unless intentionally stacked)")
    if rep.get("stretched_pct", 0) > 5:
        rep["issues"].append(f"{rep['stretched_pct']}% faces have >{CONFIG['stretch_ratio_warn']}x "
                             "texel density deviation (stretch or uneven scale)")
    if rep["islands"] > max(50, len(me.polygons) / 4):
        rep["issues"].append(f"{rep['islands']} islands is highly fragmented (seams everywhere)")
    if len(me.uv_layers) > 1:
        rep["issues"].append(f"{len(me.uv_layers)} UV maps; render uses '{rep['active_render']}'")
    return rep


def main():
    return {"texture_size": CONFIG["texture_size"],
            "objects": {o.name: check(o) for o in pick()}}


result = main()
print(json.dumps(result, indent=1))
