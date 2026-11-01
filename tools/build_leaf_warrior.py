"""Builds assets/characters/leaf_warrior/leaf_warrior.glb, the perilla forest's
leaf warrior, from the raw Tripo export.

Run:  blender --background --python tools/build_leaf_warrior.py [-- --preview DIR]

The Tripo export (tools/src/warrior_tripo.glb) is 26 separate, unrigged parts
at about 1.2 million vertices. Each part is decimated, a skeleton is built to
fit the body, and every part is skinned to it:

* Hard pieces (head, hair, feet, forearm gauntlets, belt, necklace, shoulder
  pad) follow one bone each, so they move as one lump.
* The torso blends down the spine by height and hands its left side over to the
  left upper arm, which Tripo moulded into it.
* The shorts and leaf skirt hand their lower edge over to the legs.
* The big leaves (the shoulder mantles and the two back capes) ease from the
  chest onto bones of their own away from their roots, so they sway.

The parts are then joined, laid out on one fresh atlas, and the originals'
colour and normal-mapped surface are baked onto it.

Two looping clips are baked in: Idle (4 s: deep breaths, a slow look round,
swaying leaves) and Walk (four heavy stomping steps).

--preview DIR writes renders of the rest pose and of both clips for checking.
"""

import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(ROOT, "tools", "src", "warrior_tripo.glb")
OUT = os.path.join(ROOT, "assets", "characters", "leaf_warrior", "leaf_warrior.glb")

# Tripo parts, by index (Blender: X = the warrior's left, Z up, face towards -Y).
PARTS = ("mantle_r", "mantle_l", "cape_l", "torso", "cape_r", "hair", "skirt",
         "gauntlet_r", "foot_r", "foot_l", "pad_l", "tusk", "head", "bracer_l",
         "necklace", "cape_r_tip", "strap_l", "belt", "shorts", "arm_r", "hand_l",
         "tusk_strap", "strap_r", "chest_leaf", "cord", "head_leaf")
TARGET_VERTS = 60000  # in all, after decimation
MIN_VERTS = 1500  # small parts keep at least this many
ATLAS = 2048  # one colour and one normal texture for the whole warrior
BAKE_REACH = 0.006  # how far the decimated surface may stray from the original

# Joints (metres, rest pose), fitted to the parts.
BONES = {
    # name: (parent, head, tail)
    "Hips": (None, (0, 0.02, 0.20), (0, 0.02, 0.32)),
    "Spine": ("Hips", (0, 0.02, 0.32), (0, 0.02, 0.45)),
    "Chest": ("Spine", (0, 0.02, 0.45), (0, 0.0, 0.56)),
    "Head": ("Chest", (0, -0.08, 0.56), (0, -0.08, 0.80)),
    "Hair": ("Head", (0.02, -0.12, 0.80), (0.02, -0.2, 0.95)),
    "ArmL": ("Chest", (0.17, 0.07, 0.53), (0.27, 0.08, 0.40)),
    "ForeArmL": ("ArmL", (0.27, 0.08, 0.40), (0.30, 0.08, 0.22)),
    "ArmR": ("Chest", (-0.16, 0.0, 0.53), (-0.26, 0.0, 0.40)),
    "ForeArmR": ("ArmR", (-0.26, 0.0, 0.40), (-0.31, -0.05, 0.22)),
    "LegL": ("Hips", (0.10, 0.02, 0.22), (0.15, 0.02, 0.04)),
    "LegR": ("Hips", (-0.10, 0.02, 0.22), (-0.15, 0.02, 0.04)),
    "MantleL": ("Chest", (0.20, 0.05, 0.60), (0.38, 0.10, 0.20)),
    "MantleR": ("Chest", (-0.20, 0.05, 0.60), (-0.38, 0.10, 0.20)),
    "CapeL": ("Chest", (0.20, 0.15, 0.68), (0.25, 0.25, 0.05)),
    "CapeR": ("Chest", (-0.20, 0.15, 0.68), (-0.25, 0.25, 0.05)),
}

# Torso: (height, bone) anchors; weights blend linearly between neighbours.
SPINE = ((0.26, "Hips"), (0.36, "Spine"), (0.48, "Chest"))
LEFT_ARM_X = (0.13, 0.19)  # the torso turns into the left upper arm across this
LEG_SPLIT = 0.06  # half-width of the blend between the legs, either side of x = 0
SHORTS_LEG_Z = (0.12, 0.24)  # the shorts are all leg below, all hips above
SKIRT_LEG_Z = (0.05, 0.25)
SKIRT_LEG = 0.6  # how much the skirt's hem follows the legs
MANTLE_Z = (0.35, 0.62)  # the mantles sway below, are held by the chest above
CAPE_Z = (0.30, 0.68)
HAIR_BEND = (0.84, 0.92)  # the head is open under the hair: its base stays put
PAD_ARM = 0.6  # how much the shoulder pad follows the left arm
TUSK_ARM = 0.5  # the tusk and its strap hang over the right arm

FPS = 30
IDLE_FRAMES = 120
STEP_FRAMES = 20  # one left-right stride
WALK_STEPS = 4

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PREVIEW = args[args.index("--preview") + 1] if "--preview" in args else ""


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def obj(part):
    return bpy.data.objects["tripo_part_%d" % PARTS.index(part)]


def load():
    """Imports the parts, bakes their transforms in and makes a decimated copy of
    each (named as the part); the originals are kept, as hi_<part>, to bake from."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC)
    total = sum(len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH")
    for i, part in enumerate(PARTS):
        hi = bpy.data.objects["tripo_part_%d" % i]
        hi.data.transform(hi.matrix_world)
        hi.parent = None
        hi.matrix_world = Matrix.Identity(4)
        hi.name = "hi_" + part
        lo = bpy.data.objects.new("tripo_part_%d" % i, hi.data.copy())
        hi.users_collection[0].objects.link(lo)
        bm = bmesh.new()
        bm.from_mesh(lo.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)  # Tripo splits at UV seams
        bm.to_mesh(lo.data)
        bm.free()
        n = len(lo.data.vertices)
        mod = lo.modifiers.new("Decimate", "DECIMATE")
        mod.ratio = min(max(TARGET_VERTS / total, MIN_VERTS / n), 1.0)
        with bpy.context.temp_override(object=lo, active_object=lo):
            bpy.ops.object.modifier_apply(modifier=mod.name)
        lo.data.materials.clear()
        for p in lo.data.polygons:
            p.use_smooth = True
    for o in list(bpy.data.objects):
        if o.type != "MESH":
            bpy.data.objects.remove(o)
    print("decimated %d -> %d verts" % (total, sum(len(obj(p).data.vertices) for p in PARTS)))


def bake_textures(body):
    """Lays the joined low mesh out on one atlas and bakes the originals' colour
    and normal-mapped surface onto it.

    Tripo's own UV layout is a mosaic of tiny islands, so a decimated mesh can't
    keep it: collapsed edges reach across the gaps and the texture shatters.
    """
    bpy.context.view_layer.objects.active = body
    for o in bpy.context.selected_objects:
        o.select_set(False)
    body.select_set(True)
    for uv in list(body.data.uv_layers):
        body.data.uv_layers.remove(uv)
    body.data.uv_layers.new(name="UVMap")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")

    mat = bpy.data.materials.new("LeafWarrior")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.8
    images = {}
    for kind, colorspace in (("base", "sRGB"), ("normal", "Non-Color")):
        img = bpy.data.images.new(kind, ATLAS, ATLAS)
        img.colorspace_settings.name = colorspace
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = img
        images[kind] = (img, tex)
    links.new(images["base"][1].outputs["Color"], bsdf.inputs["Base Color"])
    nmap = nodes.new("ShaderNodeNormalMap")
    links.new(images["normal"][1].outputs["Color"], nmap.inputs["Color"])
    links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    body.data.materials.clear()
    body.data.materials.append(mat)

    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 4
    sc.render.bake.use_selected_to_active = True
    sc.render.bake.cage_extrusion = BAKE_REACH
    sc.render.bake.max_ray_distance = 2 * BAKE_REACH
    sc.render.bake.margin = 6
    for o in bpy.data.objects:
        if o.name.startswith("hi_"):
            o.select_set(True)
    for kind, bake_type in (("base", "DIFFUSE"), ("normal", "NORMAL")):
        nodes.active = images[kind][1]
        if bake_type == "DIFFUSE":
            bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"})
        else:
            bpy.ops.object.bake(type="NORMAL")
        images[kind][0].pack()
    for o in list(bpy.data.objects):
        if o.name.startswith("hi_"):
            bpy.data.objects.remove(o)


def verts(part):
    o = obj(part)
    co = np.zeros(len(o.data.vertices) * 3)
    o.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def add_armature():
    data = bpy.data.armatures.new("LeafWarrior")
    arm = bpy.data.objects.new("LeafWarrior", data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, (parent, h, t) in BONES.items():
        b = data.edit_bones.new(name)
        b.head, b.tail = h, t
        b.roll = 0.0
        if parent:
            b.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for o in map(obj, PARTS):
        o.parent = arm
        mod = o.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
    return arm


# ---------------------------------------------------------------- skinning

def blend(x, anchors):
    """Weights per bone for values [param x] along (position, bone) anchors."""
    pos = np.array([a[0] for a in anchors])
    out = {}
    for i, (_, bone) in enumerate(anchors):
        one_hot = np.zeros(len(anchors))
        one_hot[i] = 1.0
        out[bone] = out.get(bone, 0.0) + np.interp(x, pos, one_hot)
    return out


def set_weights(part, weights):
    """Sets the skinning of [param part] to {bone: per-vertex weight}."""
    o = obj(part)
    n = len(o.data.vertices)
    weights = {b: np.broadcast_to(np.asarray(w, dtype=float), (n,)) for b, w in weights.items()}
    total = sum(weights.values())
    assert np.all(total > 0.999) and np.all(total < 1.001), part
    for bone, w in weights.items():
        g = o.vertex_groups.new(name=bone)
        for i in np.nonzero(w > 0.002)[0]:
            g.add([int(i)], float(w[i]), "REPLACE")


def mix(a, b, k):
    """Weights {a} fading into {b} as [param k] goes 0 to 1."""
    out = {bone: w * (1.0 - k) for bone, w in a.items()}
    for bone, w in b.items():
        out[bone] = out.get(bone, 0.0) + w * k
    return out


def legs(v, share):
    """Splits [param share] of each vertex between the legs by side."""
    left = smoothstep(-LEG_SPLIT, LEG_SPLIT, v[:, 0])
    return {"LegL": share * left, "LegR": share * (1.0 - left)}


def skin():
    v = verts("torso")
    set_weights("torso", mix(blend(v[:, 2], SPINE), {"ArmL": 1.0}, smoothstep(*LEFT_ARM_X, v[:, 0])))

    v = verts("shorts")
    leg = 1.0 - smoothstep(*SHORTS_LEG_Z, v[:, 2])
    set_weights("shorts", {"Hips": 1.0 - leg, **legs(v, leg)})
    v = verts("skirt")
    leg = SKIRT_LEG * (1.0 - smoothstep(*SKIRT_LEG_Z, v[:, 2]))
    set_weights("skirt", {"Hips": 1.0 - leg, **legs(v, leg)})

    for part, bone, z in (("mantle_l", "MantleL", MANTLE_Z), ("mantle_r", "MantleR", MANTLE_Z),
                          ("cape_l", "CapeL", CAPE_Z), ("cape_r", "CapeR", CAPE_Z),
                          ("cape_r_tip", "CapeR", CAPE_Z)):
        k = smoothstep(*z, verts(part)[:, 2])
        set_weights(part, {"Chest": k, bone: 1.0 - k})

    k = smoothstep(*HAIR_BEND, verts("hair")[:, 2])
    set_weights("hair", {"Head": 1.0 - k, "Hair": k})

    rigid = {
        "head": "Head", "head_leaf": "Head", "strap_l": "Head", "strap_r": "Head",
        "necklace": "Chest", "chest_leaf": "Chest", "cord": "Chest",
        "belt": "Hips", "foot_l": "LegL", "foot_r": "LegR",
        "arm_r": "ArmR", "gauntlet_r": "ForeArmR", "bracer_l": "ForeArmL", "hand_l": "ForeArmL",
    }
    for part, bone in rigid.items():
        set_weights(part, {bone: 1.0})
    set_weights("pad_l", {"Chest": 1.0 - PAD_ARM, "ArmL": PAD_ARM})
    for part in ("tusk", "tusk_strap"):
        set_weights(part, {"Chest": 1.0 - TUSK_ARM, "ArmR": TUSK_ARM})


def join(arm):
    parts = [obj(p) for p in PARTS]
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in parts:
        o.select_set(True)
    body = obj("torso")
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    body.name = body.data.name = "LeafWarriorMesh"
    return body


# ---------------------------------------------------------------- animation

class Pose:
    """Collects one frame of keys, given in armature space."""

    def __init__(self, arm):
        self.arm = arm
        self.rot = {}
        self.loc = {}

    def turn(self, bone, axis, deg):
        q = Quaternion(Vector(axis), math.radians(deg))
        self.rot[bone] = q @ self.rot.get(bone, Quaternion())

    def move(self, bone, offset):
        self.loc[bone] = Vector(offset)

    def key(self, frame):
        for name in BONES:
            pb = self.arm.pose.bones[name]
            rest = pb.bone.matrix_local.to_quaternion()
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = rest.inverted() @ self.rot.get(name, Quaternion()) @ rest
            pb.location = rest.inverted() @ self.loc.get(name, Vector())
            for path in ("rotation_quaternion", "location"):
                pb.keyframe_insert(path, frame=frame)


X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)
LEG_LEN = 0.21  # hip joint to sole


def idle_pose(arm, f):
    p = Pose(arm)
    slow = 2 * math.pi * f / IDLE_FRAMES  # one sway per clip
    breath = 2 * slow  # two deep breaths per clip
    p.move("Hips", (0, 0, -0.004 + 0.004 * math.sin(breath)))
    p.turn("Hips", Y, 1.5 * math.sin(slow))  # weight from foot to foot
    p.turn("Spine", X, -1.5 * math.sin(breath))
    p.turn("Chest", X, -2.5 * math.sin(breath - 0.5))  # chest swells
    # A slow look round: left, back through the middle, right.
    p.turn("Head", Z, 14.0 * math.sin(slow))
    p.turn("Head", X, 3.0 * math.sin(breath - 1.0))
    p.turn("Head", Y, -1.5 * math.sin(slow))
    for side, s in (("L", 1), ("R", -1)):
        p.turn("Arm" + side, Y, -s * (3.0 + 2.5 * math.sin(breath - 0.4)))
        p.turn("Arm" + side, X, 2.0 * math.sin(slow + s * 0.7))
        p.turn("ForeArm" + side, X, -4.0 - 2.0 * math.sin(breath - 0.8))
        p.turn("Mantle" + side, Y, -s * (1.5 + 2.0 * math.sin(breath - 0.9)))
        p.turn("Cape" + side, X, 2.0 + 2.5 * math.sin(slow + s * 0.9 + 1.2))
        p.turn("Cape" + side, Y, -s * 1.5 * math.sin(breath - 1.4))
    p.turn("Hair", X, -2.5 * math.sin(breath - 1.6))
    p.turn("Hair", Y, 2.0 * math.sin(slow + 0.5))
    return p


def walk_pose(arm, f):
    p = Pose(arm)
    step = 2 * math.pi * f / STEP_FRAMES  # sin > 0: left foot forward
    s = math.sin(step)
    swing = 26.0 * s
    stomp = 0.5 - 0.5 * math.cos(2 * step)  # 0 as each foot lands, 1 mid-stride
    # Both legs splay by the same angle, so the hips drop to keep the feet down.
    drop = LEG_LEN * (1.0 - math.cos(math.radians(swing)))
    p.move("Hips", (0, 0, -drop + 0.012 * stomp))
    p.turn("Hips", Y, -5.0 * s)  # lean over the planted foot
    p.turn("Hips", Z, 7.0 * s)
    p.turn("Spine", X, -3.0)  # chest out, leaning into the stride
    p.turn("Spine", Z, -4.0 * s)
    p.turn("Chest", X, -2.0 * stomp)
    p.turn("Head", Z, -3.0 * s)
    p.turn("Head", X, 3.0 * (1.0 - stomp))  # nods as each foot lands
    p.turn("LegL", X, -swing)
    p.turn("LegR", X, swing)
    lift = math.cos(step - 0.5 * math.pi)
    p.turn("LegL", Y, -5.0 * max(lift, 0.0))
    p.turn("LegR", Y, 5.0 * max(-lift, 0.0))
    for side, k in (("L", 1), ("R", -1)):
        arm_swing = k * 20.0 * s
        p.turn("Arm" + side, X, arm_swing)
        p.turn("Arm" + side, Y, -k * 6.0)
        p.turn("ForeArm" + side, X, -14.0 + 0.4 * min(arm_swing, 0.0))
        # The mantles ride on the arms they cover.
        p.turn("Mantle" + side, X, 0.5 * arm_swing)
        p.turn("Mantle" + side, Y, -k * (2.0 + 2.0 * stomp))
    lag = math.sin(2 * step - 1.2)
    p.turn("CapeL", X, 6.0 + 4.0 * lag)
    p.turn("CapeR", X, 6.0 + 4.0 * lag)
    p.turn("CapeL", Y, 3.0 * s)
    p.turn("CapeR", Y, 3.0 * s)
    p.turn("Hair", X, -3.0 * lag)
    p.turn("Hair", Y, 2.5 * s)
    return p


def bake(arm, name, frames, pose_at):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data_create()
    arm.animation_data.action = act
    for f in range(frames + 1):
        pose_at(arm, f % frames).key(f)
    arm.animation_data.action = None
    return act


def animate(arm):
    bpy.context.scene.render.fps = FPS
    bake(arm, "Idle", IDLE_FRAMES, idle_pose)
    bake(arm, "Walk", STEP_FRAMES * WALK_STEPS, walk_pose)
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)


# ---------------------------------------------------------------- output

def export():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    for o in bpy.context.selected_objects:
        o.select_set(False)
    bpy.ops.export_scene.gltf(
        filepath=OUT,
        export_format="GLB",
        export_animation_mode="ACTIONS",
        export_image_format="JPEG",
        export_jpeg_quality=92,
        export_apply=False,
    )


def preview(arm):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 16
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    sc.world = world
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    sc.collection.objects.link(sun)
    sc.render.resolution_x, sc.render.resolution_y = 600, 650
    cd = bpy.data.cameras.new("Cam")
    cd.type = "ORTHO"
    cd.ortho_scale = 1.3
    cam = bpy.data.objects.new("Cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    target = Vector((0, 0, 0.48))

    def shot(path, yaw, pitch=8.0):
        a, e = math.radians(yaw), math.radians(pitch)
        cam.location = target + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * 3
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(PREVIEW, path)
        bpy.ops.render.render(write_still=True)

    arm.animation_data_create()
    arm.animation_data.action = None
    shot("rest_front.png", 0)
    shot("rest_back.png", 150)
    for act, frames, yaw in (("Idle", (0, 30, 60, 90), 25), ("Walk", (0, 5, 10, 15), 70)):
        arm.animation_data.action = bpy.data.actions[act]
        for f in frames:
            sc.frame_set(f)
            shot("%s_%03d.png" % (act.lower(), f), yaw)


def main():
    load()
    arm = add_armature()
    skin()
    bake_textures(join(arm))
    animate(arm)
    export()
    print("wrote", OUT)
    if PREVIEW:
        os.makedirs(PREVIEW, exist_ok=True)
        preview(arm)


main()
