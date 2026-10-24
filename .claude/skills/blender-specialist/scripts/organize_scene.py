"""organize_scene.py - naming audit, collection organisation, orphan report.

Purpose      : 1) Report naming problems: default names ("Cube", "Sphere.003"),
                  ".001" duplicate suffixes, missing type prefixes.
               2) Optionally move objects into collections by role
                  (GEO / LGT / CAM / RIG / REF / HELPERS) or by name prefix.
               3) Report orphan datablocks (0 users) and optionally purge them.
Blender      : Tested headless on 5.2.3 LTS.
Run          : Dry run (default):  CONFIG_OVERRIDE = {}
               Apply:              CONFIG_OVERRIDE = {"apply": True, "organize": True}
Output       : `result` = {"naming_issues", "planned_moves", "orphans", "applied"}
Safety       : DRY RUN by default. With apply=True it links objects to new collections
               and unlinks them from old ones (no deletion). Purge deletes 0-user data;
               only runs when apply=True AND purge_orphans=True. Save a copy first.
Convention   : Prefixes used by this skill: GEO_ (mesh), LGT_ (light), CAM_ (camera),
               RIG_ (armature), CRV_ (curve), REF_ (reference), HLP_ (empty/helper),
               M_ (material), T_ (texture image), and _LOW/_HIGH/_CAGE suffixes for baking.
"""
import bpy
import re
import json

CONFIG = {"apply": False, "organize": False, "purge_orphans": False,
          "rename_with_prefix": False, "mode": "type"}   # "type" or "prefix"
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))

PREFIX = {"MESH": "GEO_", "LIGHT": "LGT_", "CAMERA": "CAM_", "ARMATURE": "RIG_",
          "CURVE": "CRV_", "EMPTY": "HLP_", "CURVES": "HAIR_", "GPENCIL": "GP_",
          "GREASEPENCIL": "GP_"}
COLL = {"MESH": "GEO", "CURVE": "GEO", "CURVES": "GEO", "LIGHT": "LGT", "CAMERA": "CAM",
        "ARMATURE": "RIG", "EMPTY": "HELPERS"}
DEFAULT = re.compile(r"^(Cube|Sphere|Icosphere|Cylinder|Cone|Plane|Torus|Suzanne|Circle|"
                     r"Grid|Empty|Light|Point|Area|Sun|Spot|Camera|Armature|BezierCurve|"
                     r"NurbsPath|Text|Material)(\.\d{3})?$")
DUP = re.compile(r"\.\d{3}$")


def orphans():
    res = {}
    for attr in ("meshes", "materials", "images", "node_groups", "textures", "curves",
                 "armatures", "actions", "lights", "cameras", "worlds"):
        coll = getattr(bpy.data, attr)
        names = [d.name for d in coll if d.users == 0 and not d.use_fake_user]
        if names:
            res[attr] = names
    return res


def main():
    sc = bpy.context.scene
    issues, moves, renames = [], [], []
    for o in sc.objects:
        if DEFAULT.match(o.name):
            issues.append(f"{o.name}: default name; use a descriptive name")
        elif DUP.search(o.name):
            issues.append(f"{o.name}: duplicate suffix; rename (suffixes are not stable IDs)")
        pre = PREFIX.get(o.type)
        if pre and not o.name.startswith(pre) and not o.name.startswith(("REF_", "PRP_", "HERO_", "ENV_")):
            renames.append((o.name, pre + DUP.sub("", o.name)))
        key = COLL.get(o.type, "MISC") if CONFIG["mode"] == "type" else (o.name.split("_")[0] or "MISC")
        if all(c.name != key for c in o.users_collection):
            moves.append((o.name, key))
    applied = []
    if CONFIG["apply"]:
        if CONFIG["organize"]:
            for oname, cname in moves:
                o = bpy.data.objects[oname]
                c = bpy.data.collections.get(cname)
                if c is None:
                    c = bpy.data.collections.new(cname)
                    sc.collection.children.link(c)
                for old in list(o.users_collection):
                    old.objects.unlink(o)
                c.objects.link(o)
                applied.append(f"moved {oname} -> {cname}")
        if CONFIG["rename_with_prefix"]:
            for old, new in renames:
                bpy.data.objects[old].name = new
                applied.append(f"renamed {old} -> {bpy.data.objects.get(new, None) and new}")
        if CONFIG["purge_orphans"]:
            before = sum(len(v) for v in orphans().values())
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
            applied.append(f"purged orphans (before={before}, after="
                           f"{sum(len(v) for v in orphans().values())})")
    return {"dry_run": not CONFIG["apply"], "naming_issues": issues,
            "suggested_renames": renames, "planned_moves": moves,
            "orphans": orphans(), "applied": applied}


result = main()
print(json.dumps(result, indent=1))
