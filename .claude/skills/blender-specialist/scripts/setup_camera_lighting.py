"""setup_camera_lighting.py - camera framing and light rigs sized to a target.

Purpose      : Create a camera aimed at a target's bounding box and one of these rigs:
               - "three_point": key / fill / rim area lights (general purpose)
               - "portrait_loop": key 30-45 deg off-axis and above (loop/Rembrandt
                  shadow), soft fill opposite, hair/rim light behind, for faces
               - "product": large overhead softbox, two side strip lights, optional
                  seamless backdrop (cyclorama) for clean product shots
               - "outdoor_sun": sun + sky-coloured world for exterior daylight
               Light power is scaled by distance^2 so results stay consistent with
               object size. Uses Track-To constraints so lights stay aimed.
Blender      : Tested headless on 5.2.3 LTS (Cycles, EEVEE, Workbench renders).
Run          : CONFIG_OVERRIDE = {"target": "Head", "rig": "portrait_loop",
                                  "focal_mm": 85, "backdrop": False}
Output       : `result` = {"camera", "lights", "target_center", "target_size", "distance"}
Safety       : Creates objects named CAM_Main, LGT_*, GEO_Backdrop, HLP_Target.
               With "replace": True it deletes previously created objects of those
               exact names first. Sets scene.camera. Does not touch other objects.
Notes        : Power values are starting points for AgX at exposure 0; judge renders.
               World: sets a dim neutral world colour unless "hdri" path is given.
"""
import bpy
import json
import math
from mathutils import Vector

CONFIG = {
    "target": None,              # object name; None = all visible meshes
    "rig": "three_point",
    "focal_mm": 50.0,            # 85-135 portrait, 50-100 product, 24-35 environment
    "camera_azimuth_deg": 20.0,  # 0 = front (-Y looking +Y)
    "camera_elevation_deg": 8.0,
    "fill_frame": 0.75,          # fraction of frame height the target occupies
    "backdrop": None,            # None = auto (True for product)
    "hdri": None,                # path to .hdr/.exr for world lighting
    "hdri_strength": 1.0,
    "world_color": (0.05, 0.05, 0.055),
    "key_power_scale": 1.0,
    "replace": True,
    "dof": False, "fstop": 2.8,
}
CONFIG.update(globals().get("CONFIG_OVERRIDE", {}))


def bounds():
    if CONFIG["target"]:
        objs = [bpy.data.objects[CONFIG["target"]]]
        objs += [c for c in objs[0].children_recursive if c.type == "MESH"]
    else:
        objs = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.visible_get()
                and not o.name.startswith("GEO_Backdrop")]
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    if not pts:
        raise ValueError("No target geometry")
    mn = Vector([min(p[i] for p in pts) for i in range(3)])
    mx = Vector([max(p[i] for p in pts) for i in range(3)])
    return (mn + mx) / 2, mx - mn, mn


def helper(center):
    h = bpy.data.objects.get("HLP_Target") or bpy.data.objects.new("HLP_Target", None)
    if h.name not in bpy.context.scene.collection.objects and not h.users_collection:
        bpy.context.scene.collection.objects.link(h)
    h.location = center
    h.empty_display_size = 0.1
    return h


def track(obj, target):
    for c in [c for c in obj.constraints if c.type == "TRACK_TO"]:
        obj.constraints.remove(c)
    c = obj.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"


def place(center, dist, az, el):
    az, el = math.radians(az), math.radians(el)
    return center + Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * dist


def new_obj(name, data):
    old = bpy.data.objects.get(name)
    if old and CONFIG["replace"]:
        bpy.data.objects.remove(old, do_unlink=True)
    o = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(o)
    return o


def area(name, loc, size, power, tgt, color=(1, 1, 1), shape="RECTANGLE", size_y=None):
    l = bpy.data.lights.new(name, "AREA")
    l.shape = shape
    l.size = size
    l.size_y = size_y or size
    l.energy = power
    l.color = color
    o = new_obj(name, l)
    o.location = loc
    track(o, tgt)
    return o


def world():
    sc = bpy.context.scene
    w = sc.world or bpy.data.worlds.new("World")
    sc.world = w
    if bpy.app.version < (5, 0, 0):
        w.use_nodes = True
    nt = w.node_tree
    bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None) or nt.nodes.new("ShaderNodeBackground")
    out = next((n for n in nt.nodes if n.type == "OUTPUT_WORLD"), None) or nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    if CONFIG["hdri"]:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(CONFIG["hdri"], check_existing=True)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = CONFIG["hdri_strength"]
    else:
        bg.inputs["Color"].default_value = (*CONFIG["world_color"], 1)
        bg.inputs["Strength"].default_value = 1.0


def main():
    center, size, mn = bounds()
    tgt = helper(center)
    cam_data = bpy.data.cameras.new("CAM_Main")
    cam_data.lens = CONFIG["focal_mm"]
    cam = new_obj("CAM_Main", cam_data)
    sc = bpy.context.scene
    aspect = sc.render.resolution_x / sc.render.resolution_y
    # Distance so the larger of height or width/aspect fills fill_frame of the frame.
    vfov = 2 * math.atan((cam_data.sensor_width / aspect if aspect >= 1 else cam_data.sensor_width) / 2 / cam_data.lens)
    extent = max(size.z, max(size.x, size.y) / aspect)
    dist = (extent / CONFIG["fill_frame"]) / 2 / math.tan(vfov / 2) + max(size.x, size.y) / 2
    cam.location = place(center, dist, CONFIG["camera_azimuth_deg"], CONFIG["camera_elevation_deg"])
    track(cam, tgt)
    cam_data.clip_start = max(0.001, dist / 1000)
    cam_data.clip_end = max(100.0, dist * 50)
    if CONFIG["dof"]:
        cam_data.dof.use_dof = True
        cam_data.dof.focus_object = tgt
        cam_data.dof.aperture_fstop = CONFIG["fstop"]
    sc.camera = cam

    s = max(size.length, 0.05)
    ld = s * 2.0                                  # light distance
    # Inverse-square compensation. Constant calibrated by render comparison (mug test,
    # Cycles, AgX, exposure 0): 60 blew out a navy glaze to pastel; 12 read correctly.
    P = 12.0 * ld * ld * CONFIG["key_power_scale"]
    lights = []
    rig = CONFIG["rig"]
    if rig == "three_point":
        lights.append(area("LGT_Key", place(center, ld, -45, 35), s * 0.8, P, tgt))
        lights.append(area("LGT_Fill", place(center, ld, 50, 15), s * 1.2, P * 0.3, tgt))
        lights.append(area("LGT_Rim", place(center, ld, 160, 40), s * 0.5, P * 0.8, tgt))
    elif rig == "portrait_loop":
        lights.append(area("LGT_Key", place(center, ld, -40, 30), s * 0.9, P, tgt,
                           color=(1.0, 0.95, 0.9)))
        lights.append(area("LGT_Fill", place(center, ld * 1.2, 45, 5), s * 1.5, P * 0.18, tgt,
                           color=(0.92, 0.95, 1.0)))
        lights.append(area("LGT_Rim", place(center, ld, 150, 45), s * 0.4, P * 0.9, tgt))
        lights.append(area("LGT_Hair", place(center, ld, 180, 70), s * 0.4, P * 0.4, tgt))
    elif rig == "product":
        lights.append(area("LGT_Top", center + Vector((0, 0, ld)), s * 2.0, P * 1.2, tgt))
        lights.append(area("LGT_StripL", place(center, ld, -80, 10), s * 0.25, P * 0.6, tgt,
                           size_y=s * 2.0))
        lights.append(area("LGT_StripR", place(center, ld, 80, 10), s * 0.25, P * 0.6, tgt,
                           size_y=s * 2.0))
        lights.append(area("LGT_Front", place(center, ld * 1.3, -15, 20), s * 1.5, P * 0.25, tgt))
    elif rig == "outdoor_sun":
        l = bpy.data.lights.new("LGT_Sun", "SUN")
        l.energy = 4.0
        l.angle = math.radians(0.53)
        o = new_obj("LGT_Sun", l)
        o.rotation_euler = (math.radians(50), 0, math.radians(35))
        lights.append(o)
        CONFIG["world_color"] = (0.35, 0.5, 0.8)
    else:
        raise ValueError(f"unknown rig {rig}")
    backdrop = CONFIG["backdrop"] if CONFIG["backdrop"] is not None else rig == "product"
    if backdrop:
        make_backdrop(center, size, mn, s)
    world()
    return {"camera": cam.name, "lens_mm": cam_data.lens, "distance": round(dist, 3),
            "lights": [{"name": o.name, "power_W": round(o.data.energy, 1)} for o in lights],
            "target_center": [round(c, 3) for c in center], "target_size": [round(c, 3) for c in size],
            "backdrop": backdrop}


def make_backdrop(center, size, mn, s):
    import bmesh
    me = bpy.data.meshes.new("GEO_Backdrop")
    bm = bmesh.new()
    w, d, h, r = s * 6, s * 4, s * 3, s * 0.8   # width, depth, height, curve radius
    prof = [(-d / 2, 0)]
    for i in range(9):                            # quarter-circle cove
        a = math.radians(90 * i / 8)
        prof.append((d / 2 - r + math.sin(a) * r, r - math.cos(a) * r))
    prof.append((d / 2, h))
    rows = []
    for x in (-w / 2, w / 2):
        rows.append([bm.verts.new((x, y, z)) for y, z in prof])
    for i in range(len(prof) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bm.to_mesh(me)
    bm.free()
    o = new_obj("GEO_Backdrop", me)
    o.location = (center.x, center.y + s * 0.5, mn.z)
    for p in me.polygons:
        p.use_smooth = True
    m = bpy.data.materials.get("M_Backdrop") or bpy.data.materials.new("M_Backdrop")
    if bpy.app.version < (5, 0, 0):
        m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        b.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1)
        b.inputs["Roughness"].default_value = 0.6
    me.materials.append(m)


result = main()
print(json.dumps(result, indent=1))
