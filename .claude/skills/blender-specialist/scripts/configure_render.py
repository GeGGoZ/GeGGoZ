"""configure_render.py - render engine, sampling, denoising, colour management presets.

Purpose      : Apply a named preset:
               - "lookdev_fast": Cycles 64 spp adaptive + denoise, 50% res (iteration)
               - "preview_eevee": EEVEE, quick feedback (needs GPU/OpenGL)
               - "final_cycles": Cycles 512 spp adaptive 0.01, denoise, 100% res
               - "portrait_cycles": final_cycles + 1600x2000 portrait aspect
               - "product_cycles": final_cycles + transparent film option, square
               - "clay": Workbench-style clay check (Cycles with override material)
               Colour management: AgX view transform, chosen look, exposure.
Blender      : Tested headless on 5.2.3 LTS. CPU Cycles verified; GPU device selection
               requires Preferences > System compute device (see "gpu" option).
Run          : CONFIG_OVERRIDE = {"preset": "final_cycles", "resolution": [1920, 1080]}
Output       : `result` = {"engine", "samples", "resolution", "view_transform", "look", ...}
Safety       : Changes scene render settings only. With "gpu": True it changes user
               preferences compute device type (not saved unless prefs auto-save).
"""
import bpy
import json

CONFIG = {
    "preset": "lookdev_fast",
    "resolution": None,           # [x, y] override
    "percentage": None,
    "look": "None",               # AgX looks e.g. "AgX - Medium High Contrast"
    "exposure": 0.0,
    "film_transparent": None,
    "gpu": False,                 # try CUDA/OPTIX/HIP/METAL/ONEAPI
    "output_path": None,
    "file_format": "PNG",
    "color_depth": "16",
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))

PRESETS = {
    "lookdev_fast": dict(engine="CYCLES", samples=64, threshold=0.05, denoise=True, pct=50,
                         res=(1920, 1080), bounces=8),
    "preview_eevee": dict(engine="BLENDER_EEVEE", samples=32, pct=50, res=(1920, 1080)),
    "final_cycles": dict(engine="CYCLES", samples=512, threshold=0.01, denoise=True, pct=100,
                         res=(1920, 1080), bounces=12),
    "portrait_cycles": dict(engine="CYCLES", samples=768, threshold=0.01, denoise=True, pct=100,
                            res=(1600, 2000), bounces=12),
    "product_cycles": dict(engine="CYCLES", samples=512, threshold=0.01, denoise=True, pct=100,
                           res=(2000, 2000), bounces=16, transparent=False),
    "clay": dict(engine="CYCLES", samples=32, threshold=0.05, denoise=True, pct=50,
                 res=(1920, 1080), bounces=4, clay=True),
}


def enable_gpu():
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        devs = [d for d in prefs.devices if d.type == kind]
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            bpy.context.scene.cycles.device = "GPU"
            return kind
    return None


def main():
    p = PRESETS[CONFIG["preset"]]
    sc = bpy.context.scene
    r = sc.render
    r.engine = p["engine"]
    res = CONFIG["resolution"] or p["res"]
    r.resolution_x, r.resolution_y = res
    r.resolution_percentage = CONFIG["percentage"] or p["pct"]
    info = {"engine": r.engine}
    if p["engine"] == "CYCLES":
        c = sc.cycles
        c.samples = p["samples"]
        c.use_adaptive_sampling = True
        c.adaptive_threshold = p["threshold"]
        c.use_denoising = p["denoise"]
        c.max_bounces = p["bounces"]
        c.device = "CPU"
        if CONFIG["gpu"]:
            info["gpu"] = enable_gpu() or "none found, using CPU"
        info.update(samples=c.samples, adaptive_threshold=c.adaptive_threshold,
                    denoise=c.use_denoising, device=c.device)
    elif p["engine"].startswith("BLENDER_EEVEE"):
        sc.eevee.taa_render_samples = p["samples"]
        info["samples"] = p["samples"]
    vl = bpy.context.view_layer
    if p.get("clay"):
        clay = bpy.data.materials.get("M_Clay") or bpy.data.materials.new("M_Clay")
        b = clay.node_tree.nodes.get("Principled BSDF")
        if b:
            b.inputs["Base Color"].default_value = (0.55, 0.55, 0.55, 1)
            b.inputs["Roughness"].default_value = 0.6
        vl.material_override = clay
        info["material_override"] = "M_Clay (remove with view_layer.material_override = None)"
    else:
        if vl.material_override and vl.material_override.name == "M_Clay":
            vl.material_override = None
    vs = sc.view_settings
    sc.display_settings.display_device = "sRGB"
    vs.view_transform = "AgX"
    try:
        vs.look = CONFIG["look"]
    except TypeError:
        info["look_warning"] = f"look '{CONFIG['look']}' not available; kept '{vs.look}'"
    vs.exposure = CONFIG["exposure"]
    ft = CONFIG["film_transparent"]
    if ft is None:
        ft = p.get("transparent", False)
    r.film_transparent = ft
    r.image_settings.file_format = CONFIG["file_format"]
    if CONFIG["file_format"] in ("PNG", "TIFF"):
        r.image_settings.color_depth = CONFIG["color_depth"]
        r.image_settings.color_mode = "RGBA" if ft else "RGB"
    if CONFIG["output_path"]:
        r.filepath = CONFIG["output_path"]
    info.update(resolution=[r.resolution_x, r.resolution_y, r.resolution_percentage],
                view_transform=vs.view_transform, look=vs.look, exposure=vs.exposure,
                film_transparent=r.film_transparent, output=r.filepath)
    return info


result = main()
print(json.dumps(result, indent=1))
