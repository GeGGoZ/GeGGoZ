"""create_pbr_material.py - Principled BSDF material presets with optional imperfections.

Purpose      : Create (or rebuild) a named material from a physically plausible preset
               and optionally assign it. Presets are STARTING POINTS that must be
               judged in a render under real lighting, not final answers.
               Optional procedural layers: roughness variation (noise) and colour
               variation, so surfaces are not CG-uniform.
Blender      : Tested headless on 5.2.3 LTS. Socket names are those of the
               Blender 4.0+ Principled BSDF ("Subsurface Weight", "Coat Weight",
               "Specular IOR Level", "Transmission Weight", "Emission Color").
               Will NOT work unmodified on 3.x (old socket names).
Run          : CONFIG_OVERRIDE = {"preset": "skin", "name": "M_Skin",
                                  "assign_to": ["Head"], "imperfections": True}
Output       : `result` = {"material", "preset", "assigned_to", "inputs_set"}
Safety       : Creates/overwrites ONLY the material named CONFIG["name"]
               (rebuilds its node tree if CONFIG["rebuild"]). Assigning replaces the
               object's FIRST material slot (or appends one if it has none).
Notes        : Colours are linear RGB (what Blender's node sockets store).
               Metal base colours are approximate linear F0 reflectances commonly
               quoted in real-time rendering references; "sRGB-looking" values
               typed from a colour picker are not linear.
               Subsurface Scale is in scene units (metres). The skin value assumes a
               real-scale (~0.22 m tall) head; tune it by render, not by number.
"""
import bpy
import json

CONFIG = {
    "preset": "plastic_glossy",
    "name": None,                 # default "M_<preset>"
    "assign_to": [],              # object names
    "rebuild": True,              # clear nodes and rebuild
    "imperfections": False,       # add noise-driven roughness + colour variation
    "imperfection_scale": 40.0,   # noise scale (object space)
    "roughness_variation": 0.12,  # +/- amount around preset roughness
    "color_variation": 0.06,      # 0..1 value variation
    "base_color": None,           # override (linear RGB 3-tuple)
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))

# value keys are Principled BSDF socket names; "_method" sets subsurface_method.
PRESETS = {
    "plastic_glossy": {"Base Color": (0.6, 0.05, 0.04), "Roughness": 0.25, "IOR": 1.46},
    "plastic_matte": {"Base Color": (0.2, 0.2, 0.22), "Roughness": 0.6, "IOR": 1.46},
    "rubber": {"Base Color": (0.02, 0.02, 0.02), "Roughness": 0.85, "IOR": 1.52,
               "Specular IOR Level": 0.35},
    "gold": {"Base Color": (1.0, 0.766, 0.336), "Metallic": 1.0, "Roughness": 0.2},
    "silver": {"Base Color": (0.972, 0.960, 0.915), "Metallic": 1.0, "Roughness": 0.15},
    "copper": {"Base Color": (0.955, 0.637, 0.538), "Metallic": 1.0, "Roughness": 0.25},
    "aluminium_brushed": {"Base Color": (0.913, 0.922, 0.924), "Metallic": 1.0,
                          "Roughness": 0.35, "Anisotropic": 0.7},
    "iron_raw": {"Base Color": (0.56, 0.57, 0.58), "Metallic": 1.0, "Roughness": 0.45},
    "chrome": {"Base Color": (0.55, 0.556, 0.554), "Metallic": 1.0, "Roughness": 0.05},
    "car_paint": {"Base Color": (0.25, 0.0, 0.0), "Metallic": 0.6, "Roughness": 0.35,
                  "Coat Weight": 1.0, "Coat Roughness": 0.03, "Coat IOR": 1.5},
    "glass": {"Base Color": (1, 1, 1), "Roughness": 0.0, "IOR": 1.5,
              "Transmission Weight": 1.0},
    "frosted_glass": {"Base Color": (1, 1, 1), "Roughness": 0.3, "IOR": 1.5,
                      "Transmission Weight": 1.0},
    "water": {"Base Color": (1, 1, 1), "Roughness": 0.0, "IOR": 1.333,
              "Transmission Weight": 1.0},
    "wood_varnished": {"Base Color": (0.25, 0.11, 0.045), "Roughness": 0.5, "IOR": 1.5,
                       "Coat Weight": 0.6, "Coat Roughness": 0.15},
    "wood_raw": {"Base Color": (0.35, 0.2, 0.1), "Roughness": 0.75, "IOR": 1.5},
    "stone": {"Base Color": (0.3, 0.29, 0.27), "Roughness": 0.8, "IOR": 1.5},
    "concrete": {"Base Color": (0.4, 0.39, 0.37), "Roughness": 0.9, "IOR": 1.5},
    "ceramic_glazed": {"Base Color": (0.8, 0.8, 0.78), "Roughness": 0.08, "IOR": 1.5,
                       "Coat Weight": 0.3},
    "leather": {"Base Color": (0.12, 0.05, 0.025), "Roughness": 0.55, "IOR": 1.5,
                "Sheen Weight": 0.1},
    "fabric_cotton": {"Base Color": (0.3, 0.32, 0.4), "Roughness": 0.9,
                      "Specular IOR Level": 0.3, "Sheen Weight": 0.6, "Sheen Roughness": 0.5},
    "velvet": {"Base Color": (0.15, 0.01, 0.03), "Roughness": 1.0,
               "Specular IOR Level": 0.2, "Sheen Weight": 1.0, "Sheen Roughness": 0.3},
    "painted_metal": {"Base Color": (0.1, 0.25, 0.15), "Metallic": 0.0, "Roughness": 0.4,
                      "IOR": 1.5},
    # Organic / character
    "skin": {"Base Color": (0.62, 0.42, 0.33), "Roughness": 0.45, "IOR": 1.4,
             "Subsurface Weight": 1.0, "Subsurface Radius": (1.0, 0.35, 0.2),
             "Subsurface Scale": 0.008, "Subsurface IOR": 1.4,
             "Specular IOR Level": 0.5, "_method": "RANDOM_WALK_SKIN"},
    "eye_sclera": {"Base Color": (0.8, 0.75, 0.72), "Roughness": 0.3,
                   "Subsurface Weight": 0.5, "Subsurface Radius": (1.0, 0.4, 0.3),
                   "Subsurface Scale": 0.002, "_method": "RANDOM_WALK"},
    "eye_cornea": {"Base Color": (1, 1, 1), "Roughness": 0.0, "IOR": 1.376,
                   "Transmission Weight": 1.0},
    "teeth": {"Base Color": (0.8, 0.76, 0.66), "Roughness": 0.25, "IOR": 1.55,
              "Subsurface Weight": 0.4, "Subsurface Scale": 0.001, "_method": "RANDOM_WALK"},
    "hair_strand_fallback": {"Base Color": (0.08, 0.05, 0.03), "Roughness": 0.35,
                             "Anisotropic": 0.8},
    "wax_candle": {"Base Color": (0.85, 0.8, 0.65), "Roughness": 0.4,
                   "Subsurface Weight": 1.0, "Subsurface Scale": 0.02,
                   "_method": "RANDOM_WALK"},
    "leaf": {"Base Color": (0.05, 0.18, 0.03), "Roughness": 0.45,
             "Transmission Weight": 0.0, "Subsurface Weight": 0.3,
             "Subsurface Scale": 0.002, "_method": "RANDOM_WALK"},
}


def build(mat, preset):
    nt = mat.node_tree
    if CONFIG["rebuild"]:
        nt.nodes.clear()
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None) \
        or nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None) \
        or nt.nodes.new("ShaderNodeBsdfPrincipled")
    out.location = (400, 0)
    bsdf.location = (0, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    done = []
    vals = dict(preset)
    if CONFIG["base_color"]:
        vals["Base Color"] = tuple(CONFIG["base_color"])
    method = vals.pop("_method", None)
    if method:
        bsdf.subsurface_method = method
        done.append(f"subsurface_method={method}")
    for k, v in vals.items():
        sock = bsdf.inputs.get(k)
        if sock is None:
            raise KeyError(f"Principled BSDF has no input '{k}' in Blender {bpy.app.version_string}")
        if k == "Base Color" or (hasattr(sock.default_value, "__len__") and len(sock.default_value) == 4):
            v = tuple(v) + (1.0,) if len(v) == 3 else tuple(v)
        sock.default_value = v
        done.append(k)
    mat.diffuse_color = tuple(vals.get("Base Color", (0.8, 0.8, 0.8)))[:3] + (1.0,)  # viewport solid colour
    if CONFIG["imperfections"]:
        add_imperfections(nt, bsdf, vals)
        done.append("imperfections")
    return done


def add_imperfections(nt, bsdf, vals):
    """Noise-driven roughness and value variation. Breaks CG uniformity cheaply."""
    coord = nt.nodes.new("ShaderNodeTexCoord")
    coord.location = (-1100, 0)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-900, 0)
    noise.inputs["Scale"].default_value = CONFIG["imperfection_scale"]
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.6
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    r0 = vals.get("Roughness", 0.5)
    dv = CONFIG["roughness_variation"]
    rmap = nt.nodes.new("ShaderNodeMapRange")
    rmap.location = (-600, -150)
    rmap.inputs["To Min"].default_value = max(0.0, r0 - dv)
    rmap.inputs["To Max"].default_value = min(1.0, r0 + dv)
    nt.links.new(noise.outputs["Fac"], rmap.inputs["Value"])
    nt.links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])
    if CONFIG["color_variation"] > 0:
        base = tuple(vals.get("Base Color", (0.8, 0.8, 0.8)))[:3]
        cv = CONFIG["color_variation"]
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.location = (-600, 150)
        lo = [max(0.0, c * (1 - cv)) for c in base]
        hi = [min(1.0, c * (1 + cv)) for c in base]
        ramp.color_ramp.elements[0].color = (*lo, 1)
        ramp.color_ramp.elements[1].color = (*hi, 1)
        nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])


def main():
    key = CONFIG["preset"]
    if key not in PRESETS:
        raise KeyError(f"Unknown preset '{key}'. Options: {sorted(PRESETS)}")
    name = CONFIG["name"] or f"M_{key}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):
        mat.use_nodes = True       # 5.x: node trees always exist; property deprecated
    done = build(mat, PRESETS[key])
    assigned = []
    for oname in CONFIG["assign_to"]:
        o = bpy.data.objects.get(oname)
        if o is None or not hasattr(o.data, "materials"):
            continue
        if o.data.materials:
            o.data.materials[0] = mat
        else:
            o.data.materials.append(mat)
        assigned.append(o.name)
    return {"material": mat.name, "preset": key, "assigned_to": assigned, "inputs_set": done,
            "available_presets": sorted(PRESETS)}


result = main()
print(json.dumps(result))
