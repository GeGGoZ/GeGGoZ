"""run_tests.py - headless acceptance tests for the blender-specialist script library.

Runs every script against fixtures with KNOWN defects and asserts the reports find them.
Usage (any of):
    blender -b --factory-startup --python scripts/tests/run_tests.py -- --out <dir>
    python run_tests.py --out <dir>         # with the `bpy` wheel installed (pip install bpy)
Options:
    --out DIR       where renders/exports/report go (default: temp dir)
    --no-render     skip render tests (fast)
    --eevee         also render with EEVEE (needs GPU/OpenGL or EGL software driver)
Exit code 0 = all passed. Writes DIR/test_report.json.
Safety: resets to factory settings (empty scene) between tests IN THIS PROCESS.
        Never run it inside a Blender session holding unsaved work.
"""
import bpy
import bmesh
import json
import math
import os
import runpy
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
OUT = argv[argv.index("--out") + 1] if "--out" in argv else tempfile.mkdtemp(prefix="bls_")
RENDER = "--no-render" not in argv
EEVEE = "--eevee" in argv
os.makedirs(OUT, exist_ok=True)
RESULTS = []


def run(script, **override):
    g = runpy.run_path(os.path.join(SCRIPTS, script), init_globals={"CONFIG_OVERRIDE": override},
                       run_name="__blender_specialist__")
    return g["result"]


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def test(fn):
    name = fn.__name__
    t = time.time()
    try:
        reset()
        detail = fn()
        RESULTS.append({"test": name, "ok": True, "s": round(time.time() - t, 2), "detail": detail})
        print(f"PASS {name}")
    except Exception as e:
        RESULTS.append({"test": name, "ok": False, "s": round(time.time() - t, 2),
                        "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]})
        print(f"FAIL {name}: {e}")
    return fn


def mesh_obj(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def cube(name="GEO_Cube", size=1.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    return mesh_obj(name, bm)


def broken_mesh():
    """Cube with: 1 deleted face (4 boundary edges), 1 flipped face, 1 loose vert,
    1 extra fin face on an edge (non-manifold), unapplied scale."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.faces.ensure_lookup_table()
    top = max(bm.faces, key=lambda f: f.calc_center_median().z)
    bot = min(bm.faces, key=lambda f: f.calc_center_median().z)
    bmesh.ops.delete(bm, geom=[top], context="FACES_ONLY")
    bmesh.ops.reverse_faces(bm, faces=[bot])
    bm.verts.new((3, 3, 3))
    bm.edges.ensure_lookup_table()
    e = next(e for e in bm.edges if len(e.link_faces) == 2 and all(f is not bot for f in e.link_faces))
    v1, v2 = e.verts
    v3 = bm.verts.new((v1.co + v2.co) * 1.5)   # fin face: 3rd face on one edge
    bm.faces.new((v1, v2, v3))
    o = mesh_obj("GEO_Broken", bm)
    o.scale = (2, 2, 2)
    return o


# ---------------------------------------------------------------- tests
@test
def t_inspect_scene():
    cube()
    bpy.data.objects.new("CAM_x", bpy.data.cameras.new("c"))
    r = run("inspect_scene.py")
    assert r["counts"].get("MESH") == 1, r["counts"]
    o = r["objects"][0]
    assert abs(o["bbox"]["size"][0] - 1.0) < 1e-4
    return {"objects": len(r["objects"]), "version": r["blender_version"]}


@test
def t_mesh_diagnostics_clean():
    cube()
    r = run("mesh_diagnostics.py")["objects"]["GEO_Cube"]
    assert r["issues"] == [], r["issues"]
    assert r["closed"] and r["signed_volume_local"] > 0
    assert r["quads"] == 6 and r["poles"]["3"] == 8
    return {"issues": r["issues"]}


@test
def t_mesh_diagnostics_broken():
    broken_mesh()
    r = run("mesh_diagnostics.py")["objects"]["GEO_Broken"]
    assert r["boundary_edges"] >= 4, r
    assert r["nonmanifold_edges"] == 1, r["nonmanifold_edges"]
    assert r["inconsistent_winding_edges"] >= 3, r["inconsistent_winding_edges"]
    assert r["loose_verts"] == 1
    assert any("unapplied scale" in i for i in r["issues"])
    return {"issues": r["issues"]}


@test
def t_mesh_inside_out_and_doubles():
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.verts.ensure_lookup_table()
    bm.verts.new(bm.verts[0].co.copy())
    mesh_obj("GEO_Inv", bm)
    r = run("mesh_diagnostics.py")["objects"]["GEO_Inv"]
    assert r["duplicate_verts"] == 1, r["duplicate_verts"]
    # loose duplicate vert makes the mesh still closed (no boundary edges)
    assert r["signed_volume_local"] < 0, r["signed_volume_local"]
    assert any("inside-out" in i for i in r["issues"])
    return {"issues": r["issues"]}


@test
def t_self_intersection():
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    g = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.translate(bm, verts=g["verts"], vec=(0.5, 0.3, 0.2))
    mesh_obj("GEO_Overlap", bm)
    r = run("mesh_diagnostics.py")["objects"]["GEO_Overlap"]
    assert r["self_intersecting_pairs"] and r["self_intersecting_pairs"] > 0
    return {"pairs": r["self_intersecting_pairs"]}


@test
def t_select_problem_geometry():
    broken_mesh()
    r = run("select_problem_geometry.py", object="GEO_Broken", kind="non_manifold")
    bpy.ops.object.mode_set(mode="OBJECT")
    assert r["selected_edges"] >= 1, r
    r2 = run("select_problem_geometry.py", object="GEO_Broken", kind="boundary")
    bpy.ops.object.mode_set(mode="OBJECT")
    assert r2["selected_edges"] >= 4, r2
    return {"non_manifold": r, "boundary": r2}


@test
def t_inspect_modifiers():
    o = cube()
    o.modifiers.new("Sub", "SUBSURF")
    o.modifiers.new("Bev", "BEVEL")
    b = o.modifiers.new("Bool", "BOOLEAN")
    r = run("inspect_modifiers.py")
    w = r["objects"]["GEO_Cube"]["warnings"]
    assert any("Subdivision before Bevel" in x for x in w), w
    assert any("no cutter" in x for x in w), w
    assert r["evaluated_face_counts"]["GEO_Cube"]["evaluated"] > 6
    return {"warnings": w}


@test
def t_materials_all_presets():
    cube()
    probe = run("create_pbr_material.py", preset="skin")
    made = []
    for p in probe["available_presets"]:
        r = run("create_pbr_material.py", preset=p, assign_to=["GEO_Cube"],
                imperfections=(p in ("skin", "wood_raw", "stone")))
        made.append(r["material"])
    m = bpy.data.materials["M_skin"]
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    assert bsdf.subsurface_method == "RANDOM_WALK_SKIN"
    assert bsdf.inputs["Roughness"].is_linked     # imperfections connected
    return {"presets": len(made)}


def make_textures(folder, names):
    os.makedirs(folder, exist_ok=True)
    for n in names:
        img = bpy.data.images.new(n, 32, 32)
        img.filepath_raw = os.path.join(folder, n + ".png")
        img.file_format = "PNG"
        img.save()


@test
def t_pbr_textures():
    o = cube()
    folder = os.path.join(OUT, "tex_crate")
    make_textures(folder, ["crate_BaseColor", "crate_Roughness", "crate_Metallic",
                           "crate_Normal_GL", "crate_Height", "crate_AO"])
    r = run("setup_pbr_textures.py", material="M_Crate", folder=folder, assign_to=["GEO_Cube"],
            use_displacement=True, edge_wear=True)
    assert set(r["maps"]) >= {"base_color", "roughness", "metallic", "normal", "height", "ao"}, r
    nt = bpy.data.materials["M_Crate"].node_tree
    cs = {os.path.basename(n.image.filepath): n.image.colorspace_settings.name for n in nt.nodes if n.type == "TEX_IMAGE"}
    assert cs["crate_BaseColor.png"] == "sRGB" and cs["crate_Normal_GL.png"] == "Non-Color", cs
    r2 = run("setup_pbr_textures.py", material="M_DX", files={
        "base_color": os.path.join(folder, "crate_BaseColor.png"),
        "normal": os.path.join(folder, "crate_Normal_GL.png")},
        normal_convention="DIRECTX", packed_orm=os.path.join(folder, "crate_AO.png"))
    assert any(n.type == "COMBINE_COLOR" for n in bpy.data.materials["M_DX"].node_tree.nodes)
    return {"maps": list(r["maps"]), "warnings": r["warnings"] + r2["warnings"]}


@test
def t_uvs():
    o = cube()
    # no UVs on a bmesh-created cube unless calc_uvs; check "no UV map"
    r = run("validate_uvs.py")["objects"]["GEO_Cube"]
    assert "no UV map" in r["issues"], r
    o.data.uv_layers.new(name="UVMap")   # Blender 5.2 fills each face with a full 0-1 square
    r = run("validate_uvs.py")["objects"]["GEO_Cube"]
    assert r["overlapping_faces"] == 6 and r["udim_tiles"] == [1001], r
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    good = run("validate_uvs.py", texture_size=1024)["objects"]["GEO_Cube"]
    assert good["overlapping_faces"] == 0 and good["degenerate_uv_faces"] == 0, good
    assert good["texel_density_px_per_m"] > 0
    # Stack all faces on the same island -> overlaps
    uv = o.data.uv_layers.active.data
    for p in o.data.polygons:
        for k, li in enumerate(p.loop_indices):
            uv[li].uv = [(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)][k]
    bad = run("validate_uvs.py")["objects"]["GEO_Cube"]
    assert bad["overlapping_faces"] == 6, bad
    return {"good": {k: good[k] for k in ("islands", "texel_density_px_per_m", "stretched_pct")},
            "stacked_overlaps": bad["overlapping_faces"]}


@test
def t_weights():
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, depth=2.0, radius=0.2, location=(0, 0, 1))
    body = bpy.context.active_object
    body.name = "GEO_Limb"
    bm = bmesh.new(); bm.from_mesh(body.data)     # loopcut_slice needs a UI region
    vert_edges = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 1.0]
    bmesh.ops.subdivide_edges(bm, edges=vert_edges, cuts=6, use_grid_fill=False)
    bm.to_mesh(body.data); bm.free()
    arm = bpy.data.armatures.new("RIG_Limb")
    rig = bpy.data.objects.new("RIG_Limb", arm)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    b1 = arm.edit_bones.new("upper"); b1.head = (0, 0, 0); b1.tail = (0, 0, 1)
    b2 = arm.edit_bones.new("lower"); b2.head = (0, 0, 1); b2.tail = (0, 0, 2); b2.parent = b1
    b3 = arm.edit_bones.new("unused"); b3.head = (1, 0, 0); b3.tail = (1, 0, 0.2)
    bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    body.select_set(True); rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    r = run("inspect_weights.py", objects=["GEO_Limb"])["objects"]["GEO_Limb"]
    assert r["armature"] == "RIG_Limb" and r["armature_modifier"], r
    assert r["unweighted_verts"] == 0, r
    # break some weights
    for g in body.vertex_groups:
        g.remove([0, 1, 2])
    r2 = run("inspect_weights.py", objects=["GEO_Limb"])["objects"]["GEO_Limb"]
    assert r2["unweighted_verts"] == 3, r2
    return {"auto_weights": {k: r[k] for k in ("influence_histogram", "deform_bones_without_group")},
            "after_break": r2["issues"]}


@test
def t_organize():
    cube("Cube")
    bpy.data.lights.new("L", "POINT")
    lo = bpy.data.objects.new("Light", bpy.data.lights["L"])
    bpy.context.scene.collection.objects.link(lo)
    bpy.data.materials.new("orphan_mat")
    dry = run("organize_scene.py")
    assert dry["dry_run"] and any("Cube" in i for i in dry["naming_issues"])
    assert "materials" in dry["orphans"]
    app = run("organize_scene.py", apply=True, organize=True, rename_with_prefix=True, purge_orphans=True)
    assert "GEO_Cube" in bpy.data.objects and "LGT_Light" in bpy.data.objects
    assert bpy.data.collections.get("GEO") is not None
    assert "orphan_mat" not in bpy.data.materials
    return {"applied": app["applied"]}


@test
def t_proportion_guides():
    b = run("proportion_guides.py", kind="body", height_m=1.8, heads=7.5)
    assert abs(b["landmarks_m"]["crotch"] - 0.9) < 0.01, b   # crotch ~ half height
    h = run("proportion_guides.py", kind="head", head_height_m=0.24)
    assert abs(h["landmarks_m"]["eye_line"] - 0.12) < 1e-3
    return {"body": b["landmarks_m"], "head": h["landmarks_m"]}


@test
def t_camera_lighting_rigs():
    cube()
    out = {}
    for rig in ("three_point", "portrait_loop", "product", "outdoor_sun"):
        r = run("setup_camera_lighting.py", rig=rig, target="GEO_Cube")
        out[rig] = [l["name"] for l in r["lights"]]
    assert bpy.context.scene.camera.name == "CAM_Main"
    return out


@test
def t_configure_render():
    out = {}
    for p in ("lookdev_fast", "final_cycles", "portrait_cycles", "product_cycles", "clay", "preview_eevee"):
        r = run("configure_render.py", preset=p)
        out[p] = r["engine"]
    assert bpy.context.scene.view_settings.view_transform == "AgX"
    return out


def mug_scene(rig="product"):
    run("example_build_mug.py")
    run("setup_camera_lighting.py", rig=rig, focal_mm=85, camera_elevation_deg=18,
        camera_azimuth_deg=-25)


@test
def t_example_mug_technical():
    r = run("example_build_mug.py")
    w, d, h = r["dimensions_m"]
    assert abs(h - 0.095) < 0.002, r
    assert 0.085 < w < 0.13 and abs(d - 0.085) < 0.004, r     # width includes handle
    diag = run("mesh_diagnostics.py", objects=["GEO_Mug_Body", "GEO_Mug_Handle"])["objects"]
    for n, dg in diag.items():
        assert dg["nonmanifold_edges"] == 0 and dg["inconsistent_winding_edges"] == 0, (n, dg["issues"])
        assert dg["closed"] and dg["signed_volume_local"] > 0, (n, dg["issues"])
    uv = run("validate_uvs.py", objects=["GEO_Mug_Body"])["objects"]["GEO_Mug_Body"]
    return {"dims": r["dimensions_m"], "faces": r["faces"],
            "mesh_issues": {n: d["issues"] for n, d in diag.items()},
            "uv": {k: uv.get(k) for k in ("islands", "overlapping_faces", "stretched_pct")}}


@test
def t_validate_project_and_export():
    mug_scene()
    path = os.path.join(OUT, "mug_test.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    v = run("validate_project.py", profile="render")
    assert v["status"] in ("PASS", "WARN"), v
    g = run("validate_project.py", profile="game", tri_budget=100)
    assert g["status"] == "FAIL" and any("budget" in f for f in g["fail"]), g
    ex = {}
    for fmt in ("GLB", "FBX", "OBJ", "STL"):
        e = run("prepare_export.py", format=fmt, objects=["GEO_Mug_Body", "GEO_Mug_Handle"],
                out_dir=os.path.join(OUT, "export"), basename="mug", overwrite=True,
                backup_copy=(fmt == "GLB"))
        ex[fmt] = e["bytes"]
    try:
        run("prepare_export.py", format="GLB", objects=["GEO_Mug_Body"],
            out_dir=os.path.join(OUT, "export"), basename="mug")
        raise AssertionError("overwrite protection failed")
    except FileExistsError:
        pass
    return {"render_profile": v["status"], "warn": v["warn"], "export_bytes": ex}


if RENDER:
    @test
    def t_render_product_cycles():
        mug_scene("product")
        run("configure_render.py", preset="product_cycles", resolution=[800, 800], percentage=100)
        bpy.context.scene.cycles.samples = 128
        bpy.context.scene.render.filepath = os.path.join(OUT, "mug_product_cycles.png")
        t = time.time()
        bpy.ops.render.render(write_still=True)
        assert os.path.getsize(bpy.context.scene.render.filepath) > 10000
        return {"image": bpy.context.scene.render.filepath, "s": round(time.time() - t, 1)}

    @test
    def t_render_turnaround_clay():
        mug_scene("three_point")
        r = run("render_preview.py", mode="turnaround", target=None, views=4, engine="CYCLES",
                samples=16, resolution=(320, 320), out_dir=os.path.join(OUT, "turn"))
        assert len(r["images"]) == 4 and all(os.path.exists(p) for p in r["images"])
        assert "HLP_PreviewCam" not in bpy.data.objects
        assert bpy.context.scene.camera.name == "CAM_Main"
        c = run("render_preview.py", mode="clay", engine="CYCLES", samples=16,
                resolution=(320, 320), out_dir=os.path.join(OUT, "clay"))
        assert bpy.context.view_layer.material_override is None
        return {"images": r["images"] + c["images"], "s": r["seconds"] + c["seconds"]}

    if EEVEE:
        @test
        def t_render_eevee():
            mug_scene("product")
            run("configure_render.py", preset="preview_eevee", resolution=[400, 400], percentage=100)
            bpy.context.scene.render.filepath = os.path.join(OUT, "mug_eevee.png")
            bpy.ops.render.render(write_still=True)
            return {"image": bpy.context.scene.render.filepath}


report = {"blender": bpy.app.version_string, "out": OUT,
          "passed": sum(r["ok"] for r in RESULTS), "failed": sum(not r["ok"] for r in RESULTS),
          "results": RESULTS}
with open(os.path.join(OUT, "test_report.json"), "w") as f:
    json.dump(report, f, indent=1, default=str)
print(f"\n{report['passed']} passed, {report['failed']} failed. Report: {OUT}/test_report.json")
if report["failed"]:
    sys.exit(1)
