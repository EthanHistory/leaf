"""Builds assets/characters/leafling.glb, the perilla forest monster, from the raw
Tripo export.

Run:  blender --background --python tools/build_leafling.py [-- --preview DIR]

The Tripo auto-rig (tools/src/creature_tripo.glb) is a human Mixamo skeleton
dropped on a round little plant creature, and its skinning shows it:

* The mitten hands are spread over fifteen finger bones and the upper arms are
  mostly bound to the shoulder, so a hand crumples instead of moving as one lump.
* The leg bones reach far up into the belly, so swinging a leg pulls the body
  into a cone.

All weights are thrown away and rebuilt from the geometry: the torso blends
down the spine by height, each stubby foot follows its thigh bone rigidly, the
arms blend along the shoulder-elbow-wrist chain with the hand in one piece, and
the head and everything on it follows the head bone. The finger bones go.

New bones give the face and leaves life: eye bones (left still, for looking
around later), eyelids (skin-coloured shells over the
eyes that slide down to blink; the eyes alone can't squash, the sockets behind
them are painted dark), a mouth (a dark opening, conformed to the face under the
painted mouth, that opens downward from it), both head leaves, the sprout and
the tail.

Two looping clips are baked in: Idle (4 s: breathing, swaying leaves, a blink, a
double blink and a little "nom nom") and Walk (four waddling steps with a blink).

--preview DIR writes renders of the rest pose and of both clips for checking.
"""

import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(ROOT, "tools", "src", "creature_tripo.glb")
OUT = os.path.join(ROOT, "assets", "characters", "leafling.glb")

# Tripo parts (metres in the rest pose; Blender: X = the creature's left, Z up,
# face towards -Y).
PARTS = ("head", "leaf_r", "leaf_l", "body", "arm_l", "arm_r", "tail", "sprout", "eye_l", "eye_r")
HEAD, LEAF_R, LEAF_L, BODY, ARM_L, ARM_R, TAIL, SPROUT, EYE_L, EYE_R = (
    "tripo_part_%d" % i for i in range(10))
P = "mixamorig:"

# Torso: (height, bone) anchors; weights blend linearly between neighbours.
SPINE = ((0.08, P + "Hips"), (0.16, P + "Spine"), (0.25, P + "Spine1"),
         (0.34, P + "Spine2"), (0.40, P + "Neck"))
# The feet hang below FOOT_Z[1] and are free of the belly below FOOT_Z[0].
FOOT_Z = (0.035, 0.085)
FOOT_SPLIT = 0.008  # x between the feet
FOOT_SPLIT_BLEND = 0.04
# Arm chain blends, in metres of arm length around each joint.
SHOULDER_BLEND, ELBOW_BLEND, WRIST_BLEND = 0.015, 0.035, 0.02
# Leaves and sprout bend over this length from their roots.
LEAF_BEND = 0.10
SPROUT_BEND = 0.04

# Painted mouth: the open mouth hangs from its middle (top edge at MOUTH_TOP).
MOUTH_X = 0.016
MOUTH_TOP = 0.566
MOUTH_HALF_W = 0.027
MOUTH_DEPTH = 0.036
MOUTH_LIFT = 0.0012  # off the face, along the normal
MOUTH_COLOR = (0.16, 0.035, 0.04, 1.0)
MOUTH_CLOSED = (0.75, 0.02, 1.0)  # bone scale (x, up, depth) when shut
LID_GROW = 1.1  # eyelid shell size against the eye
LID_OPEN = 0.02  # lid bone scale (up and depth) when open: tucked into the head
LASH_COLOR = (0.02, 0.03, 0.02, 1.0)
LASH_SAMPLES = 14
LASH_WIDTH = 0.0045
LASH_ARC = (-0.15, 0.35)  # height on the shut lid, in eye half-heights: middle, rise at the ends

FPS = 30
IDLE_FRAMES = 120
STEP_FRAMES = 18  # one left-right stride
WALK_STEPS = 4

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PREVIEW = args[args.index("--preview") + 1] if "--preview" in args else ""


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def load():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    # The importer also adds an icosphere it uses as the bone display shape.
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.parent != arm:
            bpy.data.objects.remove(o)
    assert arm.matrix_world == Matrix.Identity(4)
    # Name the textures after the parts (they are written out next to the .glb).
    for i, part in enumerate(PARTS):
        mat = bpy.data.objects["tripo_part_%d" % i].data.materials[0]
        mat.name = part
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE":
                kind = "base" if n.image.colorspace_settings.name == "sRGB" else "normal"
                n.image.name = "%s_%s" % (part, kind)
    arm.name = "Leafling"
    arm.data.pose_position = "REST"
    return arm


def verts(name):
    o = bpy.data.objects[name]
    return np.array([tuple(o.matrix_world @ v.co) for v in o.data.vertices])


# ---------------------------------------------------------------- bones

def add_bones(arm):
    """Drops the finger bones and adds the face, leaf, sprout and tail bones.

    Returns the new bones' (head, tail) for skinning.
    """
    face = BVHTree.FromObject(bpy.data.objects[HEAD], bpy.context.evaluated_depsgraph_get())
    mouth = face.ray_cast(Vector((MOUTH_X, -1.0, MOUTH_TOP)), Vector((0, 1, 0)))[0]

    def leaf(name):
        v = verts(name)
        root = v[v[:, 2] > v[:, 2].max() - 0.02].mean(0)
        tip = v[np.linalg.norm(v - root, axis=1).argmax()]
        return Vector(root), Vector(tip)

    def eye(name):
        v = verts(name)
        c = Vector((v.min(0) + v.max(0)) / 2)
        return c, c + Vector((0, 0, 0.03))

    def lid(name):
        # Hinged at the top of the eye, at the back where it sinks into the head.
        v = verts(name)
        c = (v.min(0) + v.max(0)) / 2
        top = Vector((c[0], v[:, 1].max(), c[2] + (v[:, 2].max() - c[2]) * LID_GROW))
        return top, top + Vector((0, 0, 0.02))

    sprout = verts(SPROUT)
    s_root = Vector(sprout[sprout[:, 2] < sprout[:, 2].min() + 0.01].mean(0))
    s_tip = Vector(sprout[sprout[:, 2].argmax()])
    tail = verts(TAIL)
    t_mid = (tail.min(0) + tail.max(0)) / 2
    t_root = Vector((t_mid[0], tail[:, 1].min(), t_mid[2]))
    t_tip = Vector((t_mid[0], tail[:, 1].max(), t_mid[2]))

    new = {
        "EyeL": (P + "Head",) + eye(EYE_L),
        "EyeR": (P + "Head",) + eye(EYE_R),
        "LidL": (P + "Head",) + lid(EYE_L),
        "LidR": (P + "Head",) + lid(EYE_R),
        "Mouth": (P + "Head", mouth, mouth + Vector((0, 0, 0.02))),
        "LeafL": (P + "Head",) + leaf(LEAF_L),
        "LeafR": (P + "Head",) + leaf(LEAF_R),
        "Sprout": (P + "Head", s_root, s_tip),
        "Tail": (P + "Hips", t_root, t_tip),
    }
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    for b in list(eb):
        if "Hand" in b.name and not b.name.endswith("Hand"):
            eb.remove(b)
    for name, (parent, h, t) in new.items():
        b = eb.new(name)
        b.head, b.tail = h, t
        b.roll = 0.0
        b.parent = eb[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return {k: (v[1], v[2]) for k, v in new.items()}


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


def set_weights(name, weights):
    """Replaces the skinning of part [param name] with {bone: per-vertex weight}."""
    o = bpy.data.objects[name]
    for g in list(o.vertex_groups):
        o.vertex_groups.remove(g)
    n = len(o.data.vertices)
    weights = {b: np.broadcast_to(np.asarray(w, dtype=float), (n,)) for b, w in weights.items()}
    total = sum(weights.values())
    assert np.all(total > 0.999) and np.all(total < 1.001), name
    for bone, w in weights.items():
        g = o.vertex_groups.new(name=bone)
        for i in np.nonzero(w > 0.002)[0]:
            g.add([int(i)], float(w[i]), "REPLACE")


def skin_body(arm):
    v = verts(BODY)
    torso = blend(v[:, 2], SPINE)
    foot = 1.0 - smoothstep(FOOT_Z[0], FOOT_Z[1], v[:, 2])
    left = smoothstep(FOOT_SPLIT - FOOT_SPLIT_BLEND, FOOT_SPLIT + FOOT_SPLIT_BLEND, v[:, 0])
    w = {b: x * (1.0 - foot) for b, x in torso.items()}
    w[P + "LeftUpLeg"] = foot * left
    w[P + "RightUpLeg"] = foot * (1.0 - left)
    set_weights(BODY, w)


def skin_arm(arm, name, side):
    """Blends the arm along shoulder - elbow - wrist; the mitten hand is one piece."""
    bones = [P + side + b for b in ("Shoulder", "Arm", "ForeArm", "Hand")]
    joints = [Vector(arm.data.bones[b].head_local) for b in bones]
    hand = arm.data.bones[bones[3]]
    joints.append(hand.head_local + (joints[3] - joints[2]).normalized() * 0.06)
    seg_len = [(joints[i + 1] - joints[i]).length for i in range(4)]
    at = np.concatenate(([0.0], np.cumsum(seg_len)))  # arc length of each joint

    v = verts(name)
    s = np.empty(len(v))
    for k, p in enumerate(v):
        best = (1e9, 0.0)
        for i in range(4):
            a, d = joints[i], joints[i + 1] - joints[i]
            t = min(max((Vector(p) - a).dot(d) / d.length_squared, 0.0), 1.0)
            dist = (Vector(p) - (a + d * t)).length
            if dist < best[0]:
                best = (dist, at[i] + t * seg_len[i])
        s[k] = best[1]
    w = blend(s, (
        (at[1] - SHOULDER_BLEND, bones[0]), (at[1] + SHOULDER_BLEND, bones[1]),
        (at[2] - ELBOW_BLEND, bones[1]), (at[2] + ELBOW_BLEND, bones[2]),
        (at[3] - WRIST_BLEND, bones[2]), (at[3] + WRIST_BLEND, bones[3]),
    ))
    set_weights(name, w)


def skin_bend(name, bone, root, length):
    """Eases part [param name] from the head bone onto [param bone] away from its root."""
    v = verts(name)
    k = smoothstep(0.0, length, np.linalg.norm(v - np.array(root), axis=1))
    set_weights(name, {P + "Head": 1.0 - k, bone: k})


def skin(arm, new):
    skin_body(arm)
    skin_arm(arm, ARM_L, "Left")
    skin_arm(arm, ARM_R, "Right")
    set_weights(HEAD, {P + "Head": 1.0})
    set_weights(EYE_L, {"EyeL": 1.0})
    set_weights(EYE_R, {"EyeR": 1.0})
    set_weights(TAIL, {"Tail": 1.0})
    skin_bend(LEAF_L, "LeafL", new["LeafL"][0], LEAF_BEND)
    skin_bend(LEAF_R, "LeafR", new["LeafR"][0], LEAF_BEND)
    skin_bend(SPROUT, "Sprout", new["Sprout"][0], SPROUT_BEND)


# ---------------------------------------------------------------- face

def solid_material(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.55
    mat.diffuse_color = color
    return mat


def skin_color(around, r0=0.05, r1=0.07):
    """Mean head texture colour (linear) in a ring around [param around]."""
    head = bpy.data.objects[HEAD]
    img = next(n for n in head.data.materials[0].node_tree.nodes if n.type == "TEX_IMAGE"
               and n.image.colorspace_settings.name == "sRGB").image
    w, h = img.size
    pix = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    uv = head.data.uv_layers.active.data
    picks = []
    for lp in head.data.loops:
        p = head.matrix_world @ head.data.vertices[lp.vertex_index].co
        if r0 < (p - around).length < r1 and p.y < around.y:
            u, v = uv[lp.index].uv
            picks.append(pix[int(v % 1 * (h - 1)), int(u % 1 * (w - 1)), :3])
    srgb = np.mean(picks, axis=0)
    lin = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    return (*lin, 1.0)


def add_part(arm, name, bm, mat, bone):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.data.objects[HEAD].users_collection[0].objects.link(o)
    o.parent = arm
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    set_weights(name, {bone: 1.0})


def add_lids(arm):
    """Skin-coloured shells just over the eyes, front half only, each with a dark
    lash line curved like a smile, so a shut eye reads as ^^ rather than blank."""
    lash_mat = solid_material("Lash", LASH_COLOR)
    for eye, bone in ((EYE_L, "LidL"), (EYE_R, "LidR")):
        src = bpy.data.objects[eye]
        v = verts(eye)
        c = Vector((v.min(0) + v.max(0)) / 2)
        half = (v.max(0) - v.min(0)) / 2
        bm = bmesh.new()
        bm.from_mesh(src.data)
        bm.transform(src.matrix_world)
        bmesh.ops.scale(bm, vec=Vector((LID_GROW,) * 3), space=Matrix.Translation(-c), verts=bm.verts)
        bm.normal_update()
        back = [f for f in bm.faces if f.normal.y > 0.3]
        bmesh.ops.delete(bm, geom=back, context="FACES")
        for f in bm.faces:
            f.smooth = True
        shell = BVHTree.FromBMesh(bm)
        add_part(arm, bone, bm, solid_material(bone, skin_color(c)), bone)

        lash = bmesh.new()
        rows = []
        for i in range(LASH_SAMPLES):
            u = (i / (LASH_SAMPLES - 1) * 2.0 - 1.0) * 0.8
            z = c.z + half[2] * (LASH_ARC[0] + LASH_ARC[1] * u * u)
            row = []
            for dz in (-LASH_WIDTH / 2, LASH_WIDTH / 2):
                hit, normal, _, _ = shell.ray_cast(Vector((c.x + u * half[0] * LID_GROW, -1.0, z + dz)), Vector((0, 1, 0)))
                row.append(lash.verts.new(hit + normal * 0.0006))
            rows.append(row)
        for a, b in zip(rows, rows[1:]):
            lash.faces.new((a[0], b[0], b[1], a[1]))
        lash.normal_update()
        for f in lash.faces:
            if f.normal.y > 0:
                f.normal_flip()
        add_part(arm, "Lash" + bone[-1], lash, lash_mat, bone)


def add_mouth(arm, top):
    """A dark D-shaped opening hanging from [param top], conformed to the face.

    It is skinned to the Mouth bone, which squashes it up into the painted
    mouth line when shut.
    """
    head = bpy.data.objects[HEAD]
    tree = BVHTree.FromObject(head, bpy.context.evaluated_depsgraph_get())
    rows, cols = 10, 16
    bm = bmesh.new()
    grid = []
    for r in range(rows + 1):
        v = r / rows
        half = MOUTH_HALF_W * math.sqrt(max(1.0 - v * v, 0.0))
        row = []
        for c in range(cols + 1):
            u = c / cols * 2.0 - 1.0
            origin = Vector((top.x + u * half, -1.0, top.z - v * MOUTH_DEPTH))
            loc, normal, _, _ = tree.ray_cast(origin, Vector((0, 1, 0)))
            row.append(bm.verts.new(loc + normal * MOUTH_LIFT))
        grid.append(row)
    for r in range(rows):
        for c in range(cols):
            bm.faces.new((grid[r][c], grid[r + 1][c], grid[r + 1][c + 1], grid[r][c + 1]))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.normal_update()
    for f in bm.faces:
        if f.normal.y > 0:  # face out of the head, towards -Y
            f.normal_flip()
        f.smooth = True
    add_part(arm, "Mouth", bm, solid_material("Mouth", MOUTH_COLOR), "Mouth")


def join(arm):
    parts = [o for o in bpy.data.objects if o.type == "MESH"]
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in parts:
        o.select_set(True)
    body = bpy.data.objects[BODY]
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    body.name = body.data.name = "LeaflingMesh"
    return body


# ---------------------------------------------------------------- animation

class Pose:
    """Collects one frame of keys, given in armature space so the bone rolls the
    importer picked don't matter."""

    def __init__(self, arm):
        self.arm = arm
        self.rot = {}
        self.loc = {}
        self.scale = {}

    def turn(self, bone, axis, deg):
        q = Quaternion(Vector(axis), math.radians(deg))
        self.rot[bone] = q @ self.rot.get(bone, Quaternion())

    def move(self, bone, offset):
        self.loc[bone] = Vector(offset)

    def size(self, bone, s):
        self.scale[bone] = Vector(s)

    def key(self, frame, bones):
        for name in bones:
            pb = self.arm.pose.bones[name]
            rest = pb.bone.matrix_local.to_quaternion()
            pb.rotation_mode = "QUATERNION"
            q = rest.inverted() @ self.rot.get(name, Quaternion()) @ rest
            pb.rotation_quaternion = q
            pb.location = rest.inverted() @ self.loc.get(name, Vector())
            pb.scale = self.scale.get(name, Vector((1, 1, 1)))
            for path in ("rotation_quaternion", "location", "scale"):
                pb.keyframe_insert(path, frame=frame)


X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)
ANIMATED = [P + b for b in ("Hips", "Spine", "Spine1", "Spine2", "Head",
                            "LeftArm", "RightArm", "LeftForeArm", "RightForeArm",
                            "LeftUpLeg", "RightUpLeg")] + \
    ["LidL", "LidR", "Mouth", "LeafL", "LeafR", "Sprout", "Tail"]


def bump(f, centre, half):
    """Smooth 0-1-0 pulse around [param centre], [param half] frames each side."""
    t = 1.0 - min(abs(f - centre) / half, 1.0)
    return t * t * (3 - 2 * t)


def face(p, blink, mouth):
    blink = min(1.5 * blink, 1.0)  # held shut for a couple of frames
    for side in ("L", "R"):
        # The lid gets its full depth early, so it isn't hidden behind the eye
        # while it slides down.
        p.size("Lid" + side, (1.0, max(blink, LID_OPEN), max(min(3.0 * blink, 1.0), LID_OPEN)))
    p.size("Mouth", tuple(c + (1.0 - c) * mouth for c in MOUTH_CLOSED))


def idle_pose(arm, f):
    p = Pose(arm)
    slow = 2 * math.pi * f / IDLE_FRAMES  # one sway per clip
    breath = 2 * slow  # two breaths per clip
    p.move(P + "Hips", (0, 0, 0.003 * math.sin(breath)))
    p.turn(P + "Spine1", X, 1.5 * math.sin(breath))
    p.turn(P + "Spine2", X, 1.5 * math.sin(breath - 0.6))
    p.turn(P + "Head", Y, 3.0 * math.sin(slow))
    p.turn(P + "Head", X, 2.0 * math.sin(breath - 1.2))
    for side, s in (("Left", 1), ("Right", -1)):
        p.turn(P + side + "Arm", Y, -s * (6.0 + 3.0 * math.sin(breath - 0.4)))
        p.turn(P + side + "Arm", X, 4.0 * math.sin(slow + s * 0.5))
        p.turn(P + side + "ForeArm", X, -6.0)
    p.turn("LeafL", Y, 5.0 * math.sin(slow + 0.8) + 2.0 * math.sin(breath - 1.0))
    p.turn("LeafR", Y, -5.0 * math.sin(slow + 1.6) - 2.0 * math.sin(breath - 1.0))
    p.turn("Sprout", X, 6.0 * math.sin(breath - 1.5))
    p.turn("Sprout", Y, 5.0 * math.sin(slow))
    p.turn("Tail", Z, 12.0 * math.sin(slow * 2 + 0.3))
    blink = max(bump(f, 24, 4), bump(f, 86, 3.5), bump(f, 95, 3.5))
    mouth = max(bump(f, 54, 6), 0.7 * bump(f, 67, 5))
    face(p, blink, mouth)
    return p


def walk_pose(arm, f):
    p = Pose(arm)
    step = 2 * math.pi * f / STEP_FRAMES  # sin > 0: left foot forward
    s = math.sin(step)
    p.move(P + "Hips", (0, 0, 0.008 * (0.5 - 0.5 * math.cos(2 * step))))
    p.turn(P + "Hips", Y, -6.0 * s)  # lean over the planted foot
    p.turn(P + "Hips", Z, 6.0 * s)
    p.turn(P + "Spine", X, 4.0)
    p.turn(P + "Spine1", Z, -3.0 * s)
    p.turn(P + "Head", Y, 4.0 * s)
    p.turn(P + "Head", X, 2.0 * math.cos(2 * step))
    p.turn(P + "LeftUpLeg", X, -30.0 * s)
    p.turn(P + "RightUpLeg", X, 30.0 * s)
    # The forward foot lifts as it swings.
    p.turn(P + "LeftUpLeg", Y, -6.0 * max(math.cos(step - 0.5 * math.pi), 0.0))
    p.turn(P + "RightUpLeg", Y, 6.0 * max(-math.cos(step - 0.5 * math.pi), 0.0))
    for side, k in (("Left", 1), ("Right", -1)):
        p.turn(P + side + "Arm", X, k * 24.0 * s)
        p.turn(P + side + "Arm", Y, -k * 12.0)
        p.turn(P + side + "ForeArm", X, -12.0)
    lag = math.sin(2 * step - 1.0)
    p.turn("LeafL", Y, 8.0 * lag)
    p.turn("LeafR", Y, -8.0 * lag)
    p.turn("Sprout", X, 6.0 + 8.0 * lag)
    p.turn("Tail", Z, 18.0 * s)
    face(p, bump(f, 44, 3.5), 0.3 + 0.12 * math.sin(2 * step))
    return p


def bake(arm, name, frames, pose_at):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data_create()
    arm.animation_data.action = act
    for f in range(frames + 1):
        pose_at(arm, f % frames).key(f, ANIMATED)
    arm.animation_data.action = None
    return act


def animate(arm):
    bpy.context.scene.render.fps = FPS
    arm.data.pose_position = "POSE"
    bake(arm, "Idle", IDLE_FRAMES, idle_pose)
    bake(arm, "Walk", STEP_FRAMES * WALK_STEPS, walk_pose)
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)


# ---------------------------------------------------------------- output

def export():
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
    sc.render.resolution_x, sc.render.resolution_y = 600, 700
    cd = bpy.data.cameras.new("Cam")
    cd.type = "ORTHO"
    cd.ortho_scale = 1.1
    cam = bpy.data.objects.new("Cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    target = Vector((0, 0, 0.49))

    def shot(path, yaw, pitch=8.0):
        a, e = math.radians(yaw), math.radians(pitch)
        cam.location = target + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * 3
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(PREVIEW, path)
        bpy.ops.render.render(write_still=True)

    arm.animation_data_create()
    arm.animation_data.action = None
    shot("rest_front.png", 0)
    for act, frames in (("Idle", (0, 21, 24, 54, 67)), ("Walk", (0, 4, 9, 13, 44))):
        arm.animation_data.action = bpy.data.actions[act]
        for f in frames:
            sc.frame_set(f)
            shot("%s_%03d.png" % (act.lower(), f), 30)


def main():
    arm = load()
    new = add_bones(arm)
    skin(arm, new)
    add_lids(arm)
    add_mouth(arm, new["Mouth"][0])
    join(arm)
    animate(arm)
    export()
    print("wrote", OUT)
    if PREVIEW:
        os.makedirs(PREVIEW, exist_ok=True)
        preview(arm)


main()
