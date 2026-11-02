"""Builds assets/characters/heroine.glb from the raw Tripo export.

Run:  blender --background --python tools/build_heroine.py [-- --preview DIR]

The Tripo character (tools/src/heroine_tripo.glb) has two flaws this fixes:

* Eyes and brows are painted about 2.5 mm above and 1.5 mm to the side of the
  sculpted eye openings and brow ridges. The face is rendered from the front with
  the texture, the eye area of that picture is shifted onto the sculpt, and the
  result is projected back into the texture.
* The hair is a separate shell but skinned rigidly to the head and spine. It is
  split into its own mesh and given chains of hair bones, which Godot's
  SpringBoneSimulator3D swings (see player.gd).

It also retargets a three-hit attack combo from Mixamo's Sword and Shield pack
(tools/src/mixamo/, not committed: Mixamo's terms don't allow sharing the raw
files) onto her skeleton as the actions attack1, attack2 and attack3.

--preview DIR writes renders of the intermediate steps for checking.
"""

import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Quaternion, Vector

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(ROOT, "tools", "src", "heroine_tripo.glb")
OUT = os.path.join(ROOT, "assets", "characters", "heroine.glb")

# Eye fix, in metres in the rest pose (Blender: X right, Z up, face towards -Y).
FACE_VIEW = (0.002, 0.926, 0.10, 0.05)  # centre x, centre z, width, height
EYE_AREA = (-0.041, 0.036, 0.911, 0.943)  # x min, x max, z min, z max: eyes and brows
EYE_FALLOFF = 0.004
# Where the painted eyes have to move to sit on the sculpt.
EYE_SHIFT = (0.0015, -0.0024)
FACE_RES = 2048

# Hair chains: one per sector around the head, measured as an angle around the
# vertical axis through HAIR_AXIS (0 = straight back, +90 = the character's left).
# A chain is only made where the hair hangs at least HAIR_MIN_DROP below the root.
HAIR_AXIS = (0.002, -0.01)
HAIR_SECTORS = (-150, -115, -75, -35, 0, 35, 75, 115, 150)
HAIR_SECTOR_HALF = 20.0  # degrees of hair each chain is fitted to
HAIR_SPREAD = 22.0  # degrees: width of the blend between neighbouring chains
HAIR_ROOT_Z = 0.925
HAIR_ROOT_BLEND = 0.025  # above the root the hair eases back onto the head bone
HAIR_MIN_DROP = 0.06
HAIR_BONES = 4

# Attack combo: action name -> Mixamo clip (30 fps, T-pose rest, 1.8 m tall).
MIXAMO = os.path.join(ROOT, "tools", "src", "mixamo")
ATTACKS = {
    "attack1": "sword and shield slash.fbx",
    "attack2": "sword and shield slash (3).fbx",
    "attack3": "sword and shield attack (3).fbx",
}

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PREVIEW = args[args.index("--preview") + 1] if "--preview" in args else ""


def load():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.import_scene.gltf(filepath=SRC)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    # The importer also adds an icosphere it uses as the bone display shape.
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.parent != arm:
            bpy.data.objects.remove(o)
    body = next(o for o in bpy.data.objects if o.type == "MESH")
    body.name = "Heroine"
    arm.data.pose_position = "REST"
    return arm, body


def base_image(obj):
    return next(n for n in obj.data.materials[0].node_tree.nodes if n.type == "TEX_IMAGE").image


# ---------------------------------------------------------------- mesh split

def split_hair(body):
    """Moves the hair shell into its own object.

    With the UV-seam splits welded the mesh falls into a few shells: the body,
    the hair, and small eye pieces. The hair is the shell reaching highest. The
    weld is only for finding the shells; the meshes keep their seams so the
    imported normals survive.
    """
    me = body.data
    bm = bmesh.new()
    bm.from_mesh(me)
    welded = bm.copy()
    bmesh.ops.remove_doubles(welded, verts=welded.verts, dist=1e-5)
    assert len(welded.faces) == len(bm.faces)
    welded.faces.ensure_lookup_table()
    shell = [-1] * len(welded.faces)
    shells = []
    for f in welded.faces:
        if shell[f.index] >= 0:
            continue
        sid = len(shells)
        stack = [f]
        shell[f.index] = sid
        top = -1.0
        while stack:
            g = stack.pop()
            top = max(top, max(v.co.z for v in g.verts))
            for e in g.edges:
                for h in e.link_faces:
                    if shell[h.index] < 0:
                        shell[h.index] = sid
                        stack.append(h)
        shells.append(top)
    hair_id = max(range(len(shells)), key=lambda i: shells[i])
    welded.free()

    hair = body.copy()
    hair.data = me.copy()
    hair.name = hair.data.name = "Hair"
    body.users_collection[0].objects.link(hair)
    for obj, keep_hair in ((body, False), (hair, True)):
        part = bm.copy()
        part.faces.ensure_lookup_table()
        drop = [f for f in part.faces if (shell[f.index] == hair_id) != keep_hair]
        bmesh.ops.delete(part, geom=drop, context="FACES")
        part.to_mesh(obj.data)
        part.free()
    bm.free()
    return hair


# ---------------------------------------------------------------- eye fix

def ortho_camera(cx, cz, w, h):
    cd = bpy.data.cameras.new("FaceCam")
    cd.type = "ORTHO"
    cd.ortho_scale = max(w, h)
    cam = bpy.data.objects.new("FaceCam", cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.rotation_euler = (math.radians(90), 0, 0)
    cam.location = (cx, -1.0, cz)
    return cam


def render_flat(path, res_x, res_y, textured=True):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.view_settings.view_transform = "Standard"
    sh = sc.display.shading
    sh.light = "FLAT" if textured else "STUDIO"
    sh.color_type = "TEXTURE" if textured else "SINGLE"
    sh.single_color = (0.8, 0.8, 0.8)
    sh.show_cavity = not textured
    sc.render.resolution_x = res_x
    sc.render.resolution_y = res_y
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


def eye_weight(x, z):
    """1 inside the eye area, easing to 0 over EYE_FALLOFF outside it."""
    x0, x1, z0, z1 = EYE_AREA

    def ramp(d):
        t = np.clip(1.0 - d / EYE_FALLOFF, 0.0, 1.0)
        return t * t * (3 - 2 * t)

    dx = np.maximum(np.maximum(x0 - x, x - x1), 0.0)
    dz = np.maximum(np.maximum(z0 - z, z - z1), 0.0)
    return ramp(dx) * ramp(dz)


def fix_eyes(body, hair, tmp):
    cx, cz, w, h = FACE_VIEW
    res_x, res_y = FACE_RES, round(FACE_RES * h / w)
    cam = ortho_camera(cx, cz, w, h)
    bpy.context.scene.camera = cam
    hair.hide_render = True
    front = os.path.join(tmp, "face_front.png")
    render_flat(front, res_x, res_y)
    if PREVIEW:
        render_flat(os.path.join(PREVIEW, "face_clay.png"), res_x, res_y, textured=False)
    hair.hide_render = False

    # Warp the front view: each pixel takes its colour from EYE_SHIFT back.
    src = bpy.data.images.load(front)
    pix = np.array(src.pixels[:], dtype=np.float32).reshape(res_y, res_x, 4)
    ys, xs = np.mgrid[0:res_y, 0:res_x].astype(np.float32)
    wx = cx - w / 2 + (xs + 0.5) / res_x * w
    wz = cz - h / 2 + (ys + 0.5) / res_y * h  # Blender image rows run bottom-up
    k = eye_weight(wx, wz)
    sx = xs - k * EYE_SHIFT[0] / w * res_x
    sy = ys - k * EYE_SHIFT[1] / h * res_y
    x0 = np.clip(np.floor(sx).astype(int), 0, res_x - 2)
    y0 = np.clip(np.floor(sy).astype(int), 0, res_y - 2)
    fx = (sx - x0)[..., None]
    fy = (sy - y0)[..., None]
    warped = (pix[y0, x0] * (1 - fx) * (1 - fy) + pix[y0, x0 + 1] * fx * (1 - fy)
              + pix[y0 + 1, x0] * (1 - fx) * fy + pix[y0 + 1, x0 + 1] * fx * fy)
    fixed = bpy.data.images.new("face_fixed", res_x, res_y)
    fixed.colorspace_settings.name = "sRGB"
    fixed.pixels = warped.ravel()
    if PREVIEW:
        fixed.filepath_raw = os.path.join(PREVIEW, "face_fixed.png")
        fixed.file_format = "PNG"
        fixed.save()

    # Bake the fixed picture back into the texture, on the front-facing faces of
    # the eye area only, so the rest of the texture is left byte-for-byte alone.
    patch = body.copy()
    patch.data = body.data.copy()
    patch.modifiers.clear()
    patch.parent = None
    patch.matrix_world = body.matrix_world
    bpy.context.scene.collection.objects.link(patch)
    bm = bmesh.new()
    bm.from_mesh(patch.data)
    bm.transform(patch.matrix_world)
    bm.normal_update()
    drop = []
    for f in bm.faces:
        c = f.calc_center_median()
        inside = eye_weight(np.array(c.x), np.array(c.z)) > 0.0
        if not inside or f.normal.y > -0.2:
            drop.append(f)
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    proj = bm.loops.layers.uv.new("proj")
    for f in bm.faces:
        for lp in f.loops:
            co = lp.vert.co
            lp[proj].uv = ((co.x - (cx - w / 2)) / w, (co.z - (cz - h / 2)) / h)
    bm.to_mesh(patch.data)
    bm.free()
    patch.matrix_world.identity()
    patch.data.uv_layers.active_index = 0

    tex = base_image(body)
    out = tex.copy()
    out.name = "heroine_base"
    out.pack()  # keeps the bake result in memory with the copy
    mat = bpy.data.materials.new("EyeBake")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "proj"
    src_node = nt.nodes.new("ShaderNodeTexImage")
    src_node.image = fixed
    src_node.interpolation = "Cubic"
    nt.links.new(uv.outputs["UV"], src_node.inputs["Vector"])
    emit = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(src_node.outputs["Color"], emit.inputs["Color"])
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emit.outputs["Emission"], outn.inputs["Surface"])
    target = nt.nodes.new("ShaderNodeTexImage")
    target.image = out
    nt.nodes.active = target
    patch.data.materials.clear()
    patch.data.materials.append(mat)

    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 1
    sc.render.bake.use_clear = False
    sc.render.bake.margin = 2
    for o in bpy.context.selected_objects:
        o.select_set(False)
    patch.select_set(True)
    bpy.context.view_layer.objects.active = patch
    bpy.ops.object.bake(type="EMIT")

    bpy.data.objects.remove(patch)
    bpy.data.objects.remove(cam)
    for n in body.data.materials[0].node_tree.nodes:
        if n.type == "TEX_IMAGE":
            n.image = out
    if PREVIEW:
        cam = ortho_camera(cx, cz, w, h)
        bpy.context.scene.camera = cam
        hair.hide_render = True
        render_flat(os.path.join(PREVIEW, "face_after.png"), res_x, res_y)
        hair.hide_render = False
        bpy.data.objects.remove(cam)
    return out


# ---------------------------------------------------------------- hair rig

def azimuth(x, y):
    return math.degrees(math.atan2(x - HAIR_AXIS[0], y - HAIR_AXIS[1]))


def angle_diff(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def fit_chains(hair):
    """Fits a chain of joints down the middle of each hanging sector of hair."""
    verts = [hair.matrix_world @ v.co for v in hair.data.vertices]
    chains = {}
    for sector in HAIR_SECTORS:
        near = [v for v in verts if abs(angle_diff(azimuth(v.x, v.y), sector)) < HAIR_SECTOR_HALF]
        low = min((v.z for v in near), default=HAIR_ROOT_Z)
        if HAIR_ROOT_Z - low < HAIR_MIN_DROP:
            continue
        tip = low + 0.01
        joints = []
        for i in range(HAIR_BONES + 1):
            z = HAIR_ROOT_Z + (tip - HAIR_ROOT_Z) * i / HAIR_BONES
            band = [v for v in near if abs(v.z - z) < 0.025] or near
            joints.append(Vector((sum(v.x for v in band) / len(band),
                                  sum(v.y for v in band) / len(band), z)))
        chains[sector] = joints
    return chains


def chain_name(sector, i):
    side = "C" if sector == 0 else ("L" if sector > 0 else "R")
    return "hair_%s%03d_%d" % (side, abs(sector), i)


def add_hair_bones(arm, chains):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    head = eb["mixamorig:Head"]
    inv = arm.matrix_world.inverted()
    for sector, joints in chains.items():
        parent = head
        for i in range(HAIR_BONES):
            b = eb.new(chain_name(sector, i))
            b.head = inv @ joints[i]
            b.tail = inv @ joints[i + 1]
            b.parent = parent
            b.use_connect = i > 0
            parent = b
    bpy.ops.object.mode_set(mode="OBJECT")


def skin_hair(hair, chains):
    """Replaces the hair's head-and-spine skinning with the hair chains.

    Around the head the weights blend between neighbouring chains by angle; down
    a chain they blend between its bones by height, so the hair bends smoothly.
    """
    for g in list(hair.vertex_groups):
        hair.vertex_groups.remove(g)
    head = hair.vertex_groups.new(name="mixamorig:Head")
    groups = {(s, i): hair.vertex_groups.new(name=chain_name(s, i))
              for s in chains for i in range(HAIR_BONES)}
    for v in hair.data.vertices:
        p = hair.matrix_world @ v.co
        to_chain = min(max((HAIR_ROOT_Z + HAIR_ROOT_BLEND - p.z) / (2 * HAIR_ROOT_BLEND), 0.0), 1.0)
        if to_chain < 1.0:
            head.add([v.index], 1.0 - to_chain, "REPLACE")
        if to_chain <= 0.0:
            continue
        a = azimuth(p.x, p.y)
        shares = {s: math.exp(-0.5 * (angle_diff(a, s) / HAIR_SPREAD) ** 2) for s in chains}
        total = sum(shares.values()) or 1.0
        for s, share in shares.items():
            share *= to_chain / total
            if share < 0.01:
                continue
            joints = chains[s]
            # Position down the chain, in bones: 0 at the root, HAIR_BONES at the tip.
            t = (HAIR_ROOT_Z - p.z) / (HAIR_ROOT_Z - joints[-1].z) * HAIR_BONES
            t = min(max(t - 0.5, 0.0), HAIR_BONES - 1.0)  # weight bone centres
            i = int(t)
            f = t - i
            groups[(s, i)].add([v.index], share * (1.0 - f), "ADD")
            if f > 0.0:
                groups[(s, min(i + 1, HAIR_BONES - 1))].add([v.index], share * f, "ADD")


# ---------------------------------------------------------------- attacks

def world_rot(obj, m):
    return (obj.matrix_world @ m).to_3x3().normalized().to_quaternion()


def heading(src):
    """Which way the source's hips face, as an angle around the vertical."""
    p = src.pose.bones
    across = src.matrix_world @ p["mixamorig:LeftUpLeg"].head - src.matrix_world @ p["mixamorig:RightUpLeg"].head
    return math.atan2(across.y, across.x)


def retarget(arm, path, name):
    """Bakes the Mixamo clip at [path] onto [arm] as the action [name].

    The Mixamo rest pose is a T-pose and hers an A-pose, so rest rotations can't
    be copied across. Each source bone is first swung so it points the way her
    bone does at rest; the offset left between the two frames is then carried
    through every frame. Her bones end up pointing the way the source bones do,
    with the source's twist. The hips' travel is scaled by the hip heights.

    A spin that doesn't come round to where it started (attack (3) turns 396
    degrees) is unwound evenly over the clip, so she ends facing the way she
    began and can go straight back to idle.
    """
    scene = bpy.context.scene
    fps = scene.render.fps
    before = set(bpy.data.objects)
    actions = set(bpy.data.actions)
    bpy.ops.import_scene.fbx(filepath=path)
    src_fps = scene.render.fps
    scene.render.fps = fps  # the importer switches the scene to the clip's rate
    src = next(o for o in bpy.data.objects if o not in before and o.type == "ARMATURE")
    clip = src.animation_data.action
    f0, f1 = clip.frame_range

    sb, tb = src.data.bones, arm.data.bones
    bones = [b for b in tb if b.name in sb]  # parents before children
    offset = {}
    for b in bones:
        s = sb[b.name]
        rs = world_rot(src, s.matrix_local)
        rt = world_rot(arm, b.matrix_local)
        ds = (src.matrix_world.to_3x3() @ (s.tail_local - s.head_local)).normalized()
        dt = (arm.matrix_world.to_3x3() @ (b.tail_local - b.head_local)).normalized()
        offset[b.name] = (ds.rotation_difference(dt) @ rs).inverted() @ rt
    hips = "mixamorig:Hips"
    src_hips = src.matrix_world @ sb[hips].head_local
    tgt_hips = arm.matrix_world @ tb[hips].head_local
    scale = tgt_hips.z / src_hips.z
    arm_rot = arm.matrix_world.to_quaternion().inverted()
    scene.frame_set(int(f0))
    start = heading(src)
    scene.frame_set(int(f1))
    spin = (heading(src) - start + math.pi) % (2 * math.pi) - math.pi

    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data_create()
    arm.animation_data.action = act
    pose = arm.pose.bones
    for p in pose:
        p.rotation_mode = "QUATERNION"
    frames = int(round((f1 - f0) * fps / src_fps))
    for k in range(frames + 1):
        t = f0 + k * src_fps / fps
        scene.frame_set(int(t), subframe=t - int(t))
        unwind = Quaternion((0, 0, 1), -spin * k / frames)
        posed = {}  # armature-space rotation of each of her bones this frame
        for b in tb:
            local = b.matrix_local.to_quaternion()
            parent = posed[b.parent.name] if b.parent else None
            rest = (b.parent.matrix_local.inverted() @ b.matrix_local).to_quaternion() if b.parent else local
            if b.name in offset:
                want = arm_rot @ unwind @ world_rot(src, src.pose.bones[b.name].matrix) @ offset[b.name]
                basis = (parent @ rest).inverted() @ want if parent else local.inverted() @ want
            else:
                basis = pose[b.name].rotation_quaternion.copy()
                basis.identity()
                want = (parent @ rest if parent else local) @ basis
            posed[b.name] = want
            pose[b.name].rotation_quaternion = basis
            pose[b.name].keyframe_insert("rotation_quaternion", frame=k + 1)
        travel = (src.matrix_world @ src.pose.bones[hips].head - src_hips) * scale
        pose[hips].location = tb[hips].matrix_local.to_quaternion().inverted() @ (arm_rot @ travel)
        pose[hips].keyframe_insert("location", frame=k + 1)

    arm.animation_data.action = None
    for p in pose:
        p.rotation_quaternion.identity()
        p.location = (0, 0, 0)
    for o in set(bpy.data.objects) - before:
        bpy.data.objects.remove(o)
    for a in set(bpy.data.actions) - actions - {act}:
        bpy.data.actions.remove(a)
    print("%s: %d frames from %s, unwound %.0f degrees"
          % (name, frames + 1, os.path.basename(path), math.degrees(spin)))


def add_attacks(arm):
    for name, f in ATTACKS.items():
        retarget(arm, os.path.join(MIXAMO, f), name)


def export(arm):
    arm.data.pose_position = "POSE"
    for o in bpy.context.selected_objects:
        o.select_set(False)
    bpy.ops.export_scene.gltf(
        filepath=OUT,
        export_format="GLB",
        export_animation_mode="ACTIONS",
        export_image_format="JPEG",
        export_jpeg_quality=95,
        export_apply=False,
    )


def main():
    tmp = PREVIEW or bpy.app.tempdir
    arm, body = load()
    hair = split_hair(body)
    fix_eyes(body, hair, tmp)
    chains = fit_chains(hair)
    print("hair chains:", {chain_name(s, 0)[:-2]: round(j[-1].z, 3) for s, j in chains.items()})
    add_hair_bones(arm, chains)
    skin_hair(hair, chains)
    add_attacks(arm)
    export(arm)
    print("wrote", OUT)


main()
