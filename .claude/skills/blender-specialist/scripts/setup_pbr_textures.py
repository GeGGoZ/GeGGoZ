"""setup_pbr_textures.py - wire an image-based PBR texture set into a material.

Purpose      : Build a correct Principled BSDF graph from texture files:
               base colour (sRGB), roughness / metallic / AO / height (Non-Color),
               normal map (Non-Color via Normal Map node, OpenGL or DirectX).
               Optionally adds true displacement and edge wear (Cycles pointiness).
               Files are auto-detected from a folder by common suffixes
               (_basecolor/_albedo/_diffuse, _roughness, _metallic, _normal/_nor_gl,
               _height/_disp, _ao).
Blender      : Tested headless on 5.2.3 LTS (with generated test images).
Run          : CONFIG_OVERRIDE = {"material": "M_Crate", "folder": "C:/tex/crate",
                                  "assign_to": ["Crate"], "normal_convention": "OPENGL"}
               or pass explicit files: {"files": {"base_color": "...png", ...}}
Output       : `result` = {"material", "maps": {slot: path}, "missing": [...], "warnings": [...]}
Safety       : Rebuilds only the named material's node tree. Loads images (no packing,
               no writes). Paths must exist on the machine running Blender.
Limits       : Assumes UVs exist (warns if the target object has none).
               ORM/packed maps: set "packed_orm" to a path; channels R=AO G=Rough B=Metal.
               DirectX normals: green channel is inverted with a Separate/Combine pair.
"""
import bpy
import os
import json

CONFIG = {
    "material": "M_Textured",
    "folder": None,
    "files": {},                 # slot -> path; overrides folder detection
    "packed_orm": None,
    "normal_convention": "OPENGL",   # OPENGL (Blender, glTF) or DIRECTX (Unreal, some libs)
    "normal_strength": 1.0,
    "use_displacement": False,       # true displacement needs dense mesh / adaptive subdiv
    "displacement_scale": 0.02,      # metres
    "displacement_midlevel": 0.5,
    "ao_into_base_color": False,     # physically wrong for Cycles; acceptable for stylised/eevee
    "edge_wear": False,              # Cycles-only pointiness-based lighter edges
    "assign_to": [],
    "projection": "UV",              # UV or BOX (triplanar-ish, no UVs needed)
    "box_blend": 0.2,
    "mapping_scale": (1.0, 1.0, 1.0),
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))

SUFFIXES = {
    "base_color": ["basecolor", "base_color", "albedo", "diffuse", "diff", "color", "col"],
    "roughness": ["roughness", "rough", "rgh"],
    "metallic": ["metallic", "metalness", "metal", "mtl"],
    "normal": ["normal_gl", "nor_gl", "normal", "nrm", "nor"],
    "height": ["height", "displacement", "disp", "bump"],
    "ao": ["ambientocclusion", "ao", "occlusion"],
}
EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".webp", ".tga")


def detect(folder):
    found = {}
    files = [f for f in os.listdir(folder) if f.lower().endswith(EXT)]
    for slot, keys in SUFFIXES.items():
        for k in keys:
            hit = next((f for f in files
                        if os.path.splitext(f)[0].lower().replace("-", "_").endswith("_" + k)
                        or os.path.splitext(f)[0].lower().endswith(k)), None)
            if hit:
                found[slot] = os.path.join(folder, hit)
                break
    if "normal" in found and "_dx" in found["normal"].lower():
        CONFIG["normal_convention"] = "DIRECTX"
    return found


def img_node(nt, path, non_color, loc, vec):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.location = loc
    n.image = bpy.data.images.load(path, check_existing=True)
    n.image.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    if CONFIG["projection"] == "BOX":
        n.projection = "BOX"
        n.projection_blend = CONFIG["box_blend"]
    nt.links.new(vec, n.inputs["Vector"])
    return n


def main():
    warn, missing = [], []
    files = dict(CONFIG["files"])
    if CONFIG["folder"] and not files:
        files = detect(CONFIG["folder"])
    for slot, p in list(files.items()):
        if not os.path.exists(p):
            warn.append(f"{slot}: file not found {p}")
            files.pop(slot)
    for slot in ("base_color", "roughness", "normal"):
        if slot not in files and not (CONFIG["packed_orm"] and slot == "roughness"):
            missing.append(slot)

    mat = bpy.data.materials.get(CONFIG["material"]) or bpy.data.materials.new(CONFIG["material"])
    if bpy.app.version < (5, 0, 0):
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (500, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (100, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    tc = nt.nodes.new("ShaderNodeTexCoord"); tc.location = (-1300, 0)
    mp = nt.nodes.new("ShaderNodeMapping"); mp.location = (-1100, 0)
    mp.inputs["Scale"].default_value = CONFIG["mapping_scale"]
    nt.links.new(tc.outputs["UV" if CONFIG["projection"] == "UV" else "Object"], mp.inputs["Vector"])
    vec = mp.outputs["Vector"]

    y = 400
    base_out = None
    if "base_color" in files:
        n = img_node(nt, files["base_color"], False, (-700, y), vec)
        base_out = n.outputs["Color"]
    y -= 300
    if "ao" in files and CONFIG["ao_into_base_color"] and base_out is not None:
        ao = img_node(nt, files["ao"], True, (-700, y), vec)
        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
        mix.location = (-300, 350)
        mix.inputs["Factor"].default_value = 1.0
        nt.links.new(base_out, mix.inputs["A"])
        nt.links.new(ao.outputs["Color"], mix.inputs["B"])
        base_out = mix.outputs["Result"]
        y -= 300
    if base_out is not None:
        nt.links.new(base_out, bsdf.inputs["Base Color"])
    if CONFIG["packed_orm"]:
        orm = img_node(nt, CONFIG["packed_orm"], True, (-700, y), vec)
        sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-400, y)
        nt.links.new(orm.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        y -= 300
    else:
        if "roughness" in files:
            n = img_node(nt, files["roughness"], True, (-700, y), vec)
            nt.links.new(n.outputs["Color"], bsdf.inputs["Roughness"]); y -= 300
        if "metallic" in files:
            n = img_node(nt, files["metallic"], True, (-700, y), vec)
            nt.links.new(n.outputs["Color"], bsdf.inputs["Metallic"]); y -= 300
    if "normal" in files:
        n = img_node(nt, files["normal"], True, (-700, y), vec)
        nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (-200, y)
        nmap.inputs["Strength"].default_value = CONFIG["normal_strength"]
        col = n.outputs["Color"]
        if CONFIG["normal_convention"] == "DIRECTX":
            sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-450, y - 150)
            inv = nt.nodes.new("ShaderNodeMath"); inv.operation = "SUBTRACT"
            inv.inputs[0].default_value = 1.0; inv.location = (-450, y - 300)
            comb = nt.nodes.new("ShaderNodeCombineColor"); comb.location = (-350, y - 150)
            nt.links.new(col, sep.inputs["Color"])
            nt.links.new(sep.outputs["Red"], comb.inputs["Red"])
            nt.links.new(sep.outputs["Green"], inv.inputs[1])
            nt.links.new(inv.outputs["Value"], comb.inputs["Green"])
            nt.links.new(sep.outputs["Blue"], comb.inputs["Blue"])
            col = comb.outputs["Color"]
        nt.links.new(col, nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        y -= 300
    if "height" in files:
        n = img_node(nt, files["height"], True, (-700, y), vec)
        if CONFIG["use_displacement"]:
            d = nt.nodes.new("ShaderNodeDisplacement"); d.location = (200, -500)
            d.inputs["Scale"].default_value = CONFIG["displacement_scale"]
            d.inputs["Midlevel"].default_value = CONFIG["displacement_midlevel"]
            nt.links.new(n.outputs["Color"], d.inputs["Height"])
            nt.links.new(d.outputs["Displacement"], out.inputs["Displacement"])
            mat.displacement_method = "BOTH"
            warn.append("True displacement: needs enough geometry (Subdivision modifier) "
                        "and Cycles; EEVEE shows bump only.")
        elif "normal" not in files:
            b = nt.nodes.new("ShaderNodeBump"); b.location = (-200, y)
            b.inputs["Distance"].default_value = CONFIG["displacement_scale"]
            nt.links.new(n.outputs["Color"], b.inputs["Height"])
            nt.links.new(b.outputs["Normal"], bsdf.inputs["Normal"])
    if CONFIG["edge_wear"] and base_out is not None:
        geo = nt.nodes.new("ShaderNodeNewGeometry"); geo.location = (-700, 700)
        ramp = nt.nodes.new("ShaderNodeValToRGB"); ramp.location = (-450, 700)
        ramp.color_ramp.elements[0].position = 0.5
        ramp.color_ramp.elements[1].position = 0.56
        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "SCREEN"
        mix.location = (-150, 500)
        nt.links.new(geo.outputs["Pointiness"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], mix.inputs["Factor"])
        nt.links.new(base_out, mix.inputs["A"])
        mix.inputs["B"].default_value = (0.6, 0.6, 0.6, 1)
        nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
        warn.append("edge_wear uses Pointiness: Cycles only and needs dense geometry.")

    assigned = []
    for oname in CONFIG["assign_to"]:
        o = bpy.data.objects.get(oname)
        if not o or o.type != "MESH":
            continue
        if CONFIG["projection"] == "UV" and not o.data.uv_layers:
            warn.append(f"{o.name} has no UV map; textures will not map. Unwrap or use BOX.")
        if o.data.materials:
            o.data.materials[0] = mat
        else:
            o.data.materials.append(mat)
        assigned.append(o.name)
    return {"material": mat.name, "maps": files, "missing": missing,
            "normal_convention": CONFIG["normal_convention"], "assigned_to": assigned,
            "warnings": warn}


result = main()
print(json.dumps(result, indent=1))
