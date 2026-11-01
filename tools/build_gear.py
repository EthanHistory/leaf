"""Builds assets/gear/axe.glb and assets/gear/shield.glb from the raw Tripo exports.

Run:  blender --background --python tools/build_gear.py [-- --preview DIR]

The Tripo models (tools/src/axe_tripo.glb, tools/src/shield_tripo.glb; too big
to commit, see .gitignore) are ~1.9M triangles each with 2K textures, normalised
to 1 m tall and posed at an angle. This decimates them, scales them to real
size and puts them in a frame player.gd can mount by (Godot axes):

* axe: origin on the haft where the hand grips it, haft along +Y with the head
  up, edge towards +Z.
* shield: origin in the middle of the back face, top along +Y, boss towards +Z.

--preview DIR writes front and side renders of the results for checking.
"""

import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(ROOT, "tools", "src")
OUT = os.path.join(ROOT, "assets", "gear")

AXE_LENGTH = 0.48  # metres, butt to top of the head
AXE_GRIP = 0.3  # grip point, as a fraction of the haft from the butt
SHIELD_HEIGHT = 0.62
TARGET_TRIS = 12000
TEXTURE_SIZE = 1024

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PREVIEW = args[args.index("--preview") + 1] if "--preview" in args else ""


def load(name):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, name))
    obj = next(o for o in bpy.data.objects if o.type == "MESH")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # glTF splits vertices along UV seams and normals; merging them lets the
    # decimator collapse across those edges.
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.object.mode_set(mode="OBJECT")
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    mod = obj.modifiers.new("decimate", "DECIMATE")
    mod.ratio = min(1.0, TARGET_TRIS / tris)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.ops.object.shade_smooth()
    print(name, tris, "->", sum(len(p.vertices) - 2 for p in obj.data.polygons), "triangles")
    return obj


def verts(obj):
    co = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def place(obj, basis_cols, origin, scale):
    """Moves the mesh so [param origin] is at 0 and the given Blender-space
    axes (columns: new X, Y, Z) line up with X, Y, Z, then scales it."""
    b = Matrix([list(c) for c in basis_cols]).transposed()  # columns -> rows of inverse
    m = Matrix.Diagonal((scale, scale, scale, 1.0)) @ b.inverted().to_4x4() @ Matrix.Translation(-Vector(origin))
    obj.data.transform(m)
    obj.data.update()


def godot_frame(x, y, z):
    """Godot axes (x, y, z) written in Blender space: Godot +Y is Blender +Z and
    Godot +Z is Blender -Y."""
    return Vector(x), Vector(z) * -1.0, Vector(y)


def build_axe():
    obj = load("axe_tripo.glb")
    p = verts(obj)
    # The haft is the long axis; the head end is the one with mass off the axis.
    c = p.mean(axis=0)
    _, _, vt = np.linalg.svd(p - c, full_matrices=False)
    axis = vt[0]
    t = (p - c) @ axis
    head = t > t.min() + 0.75 * (t.max() - t.min())
    butt = t < t.min() + 0.25 * (t.max() - t.min())
    if head.sum() < butt.sum():  # the head is the bulkier end
        axis, t = -axis, -t
        head, butt = butt, head
    # Fit the axis line through the haft alone (the butt quarter and the middle),
    # since the blade drags the overall centroid sideways.
    shaft = t < t.min() + 0.7 * (t.max() - t.min())
    sc = p[shaft].mean(axis=0)
    _, _, vt = np.linalg.svd(p[shaft] - sc, full_matrices=False)
    axis = vt[0] if np.dot(vt[0], axis) > 0 else -vt[0]
    t = (p - sc) @ axis
    # Seen down the haft, the head is a long sliver from poll to edge; its main
    # direction is the edge's, pointing the way it reaches further.
    off = p - sc - np.outer(t, axis)
    off = off[t > t.min() + 0.8 * (t.max() - t.min())]
    off -= off.mean(axis=0)
    _, _, vt = np.linalg.svd(off, full_matrices=False)
    blade = vt[0] - axis * np.dot(vt[0], axis)
    blade /= np.linalg.norm(blade)
    d = off @ blade
    if d.max() < -d.min():
        blade = -blade
    length = t.max() - t.min()
    grip = sc + axis * (t.min() + AXE_GRIP * length)
    y = Vector(axis)
    z = Vector(blade)
    x = y.cross(z)
    place(obj, godot_frame(x, y, z), grip, AXE_LENGTH / length)
    return obj


def build_shield():
    obj = load("shield_tripo.glb")
    p = verts(obj)
    # Tripo exports it upright with the boss towards glTF +Z (Blender -Y).
    lo, hi = p.min(axis=0), p.max(axis=0)
    back = Vector(((lo[0] + hi[0]) / 2, hi[1], (lo[2] + hi[2]) / 2))
    # The back is bowed; sit the origin on the middle of the face, not the rim.
    mid = np.abs(p[:, 0] - back.x) < 0.03
    mid &= np.abs(p[:, 2] - back.z) < 0.03
    back.y = p[mid, 1].max()
    place(obj, godot_frame((1, 0, 0), (0, 0, 1), (0, -1, 0)), back, SHIELD_HEIGHT / (hi[2] - lo[2]))
    return obj


def shrink_textures(obj):
    for mat in obj.data.materials:
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image and max(n.image.size) > TEXTURE_SIZE:
                n.image.scale(TEXTURE_SIZE, TEXTURE_SIZE)


def export(obj, name):
    shrink_textures(obj)
    os.makedirs(OUT, exist_ok=True)
    obj.name = name
    obj.data.name = name
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(OUT, name + ".glb"),
        export_format="GLB",
        use_selection=True,
        export_image_format="JPEG",
        export_jpeg_quality=90,
    )
    if PREVIEW:
        preview(obj, name)


def preview(obj, name):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.color_type = "TEXTURE"
    sc.render.resolution_x = sc.render.resolution_y = 500
    cd = bpy.data.cameras.new("cam")
    cd.type = "ORTHO"
    cd.ortho_scale = 0.8
    cam = bpy.data.objects.new("cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    # Godot front (+Z) is Blender -Y; side looks from Godot +X.
    for view, rot, loc in (("front", (90, 0, 0), (0, -2, 0.1)), ("side", (90, 0, 90), (2, 0, 0.1))):
        cam.rotation_euler = [math.radians(a) for a in rot]
        cam.location = loc
        sc.render.filepath = os.path.join(PREVIEW, f"{name}_{view}.png")
        bpy.ops.render.render(write_still=True)


def main():
    export(build_axe(), "axe")
    export(build_shield(), "shield")


main()
