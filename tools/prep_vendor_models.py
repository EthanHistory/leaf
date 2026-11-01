"""Cleans the Sketchfab house and bridge downloads into scene-ready .glb files.

Run:  blender --background --python tools/prep_vendor_models.py

Each model loses its showcase ground (sky dome, sand plates, grass blocks) and static smoke, is
joined into one object (one draw call per material), and is moved so its
ground contact point sits at the origin. Scale and placement happen in main.gd.
"""
import os

import bpy
from mathutils import Matrix, Vector

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
SRC = os.path.join(ROOT, "vendor", "sketchfab")

MODELS = [
    {
        "src": "house/scene.gltf",
        "out": "house.glb",
        # Sky dome, infinite sand plane, sand base disc, smoke trail card, frozen smoke puffs.
        "drop": ["Object_10", "Object_4", "Object_14", "Object_8", "Object_6"],
        # Blender coordinates (Z up): the porch floor sits on the sand plane.
        "origin": Vector((0.0, 0.0, 0.26)),
    },
    {
        "src": "bridge/scene.gltf",
        "out": "bridge.glb",
        # Earth blocks and grass plates on both banks.
        "drop": ["pCube22", "pCube23", "pPlane6", "pPlane7", "pPlane8", "pPlane9"],
        # Deck centre between the main posts, at the banks' grass level.
        "origin": Vector((3.3, -3.0, 0.2)),
    },
]


def prep(model):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, model["src"]))

    for o in list(bpy.context.scene.objects):
        if o.type == "MESH" and any(o.name.startswith(d) for d in model["drop"]):
            bpy.data.objects.remove(o, do_unlink=True)

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in meshes:
        world = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = world
    # Bake transforms into the mesh data, then shift everything to the new origin.
    shift = Matrix.Translation(-model["origin"])
    for o in meshes:
        if o.data.users > 1:
            o.data = o.data.copy()
        o.data.transform(shift @ o.matrix_world)
        o.matrix_world = Matrix.Identity(4)
    for o in list(bpy.context.scene.objects):
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)

    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = os.path.splitext(model["out"])[0].capitalize()

    bpy.ops.export_scene.gltf(
        filepath=os.path.join(ROOT, model["out"]),
        export_format="GLB",
        use_selection=True,
    )
    tris = sum(len(p.vertices) - 2 for p in joined.data.polygons)
    print("wrote", model["out"], "tris", tris, "materials", len(joined.data.materials))


for m in MODELS:
    prep(m)
