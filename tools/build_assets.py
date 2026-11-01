"""Generates the stream scene assets and exports them as .glb for Godot.

Run:  blender --background --python tools/build_assets.py

All geometry is authored in Godot coordinates (Y up, -Z forward) and converted
to Blender's Z-up space on vertex creation; the glTF exporter converts back.
"""
import math
import os

import bmesh
import bpy
from mathutils import Vector, noise

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")

# Keep in sync with main.gd.
WATER_Y = -0.2


def river_cx(z):
    return 1.2 * math.sin(z * 0.12) + 0.5 * math.sin(z * 0.31 + 1.0)


def river_w(z):
    return 3.0 + 0.6 * math.sin(z * 0.2 + 2.0)


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def fbm(x, z, octaves=4):
    v, amp, f = 0.0, 1.0, 1.0
    for _ in range(octaves):
        v += amp * noise.noise(Vector((x * f, 0.37, z * f)))
        amp *= 0.5
        f *= 2.0
    return v


# Building plots, levelled so houses sit flat (keep in sync with HOUSE_* and VILLAGE
# in main.gd): offset from the stream centre, z, yaw in degrees, scale, then the
# model's footprint in its own space: half width along x, z extent (back, front).
PLOTS = [
    (8.0, -26.0, -20.0, 1.6, 3.0, -3.0, 3.1),  # main house (assets/house.glb)
    (19.0, -17.5, -75.0, 1.15, 2.4, -2.3, 3.6),  # hut_orange
    (20.0, -30.5, -65.0, 1.15, 2.7, -2.6, 2.6),  # tall_teal
    (-22.5, -29.0, 60.0, 1.15, 3.3, -2.9, 4.3),  # cottage_blue
    (12.0, -41.5, -10.0, 1.15, 4.3, -3.0, 4.3),  # longhouse_purple
    (-10.0, -26.0, 55.0, 1.15, 3.0, -2.8, 2.8),  # townhouse_green
    (-11.5, -38.0, 70.0, 1.15, 3.2, -2.9, 4.2),  # cottage_red
]
PLOT_BLEND = 2.5


def plot_local(plot, x, z):
    """World (x, z) -> the plot model's unscaled local (x, z)."""
    off, pz, yaw, s = plot[:4]
    a = math.radians(yaw)
    dx, dz = x - (river_cx(pz) + off), z - pz
    return (math.cos(a) * dx - math.sin(a) * dz) / s, (math.sin(a) * dx + math.cos(a) * dz) / s


def height(x, z):
    h = natural_height(x, z)
    for plot in PLOTS:
        off, pz, yaw, s, hx, z0, z1 = plot
        lx, lz = plot_local(plot, x, z)
        # Distance (in metres) outside the footprint rectangle.
        ox = max(abs(lx) - hx, 0.0) * s
        oz = max(z0 - lz, lz - z1, 0.0) * s
        w = 1.0 - smoothstep(0.0, PLOT_BLEND, math.hypot(ox, oz))
        if w > 0.0:
            h += (plot_level(plot) - h) * w
    return h


_levels = {}


def plot_level(plot):
    """Average natural ground height over the footprint, so cut and fill balance."""
    if plot not in _levels:
        off, pz, yaw, s, hx, z0, z1 = plot
        a = math.radians(yaw)
        cx = river_cx(pz) + off
        hs = []
        for i in range(5):
            for j in range(5):
                lx, lz = -hx + 2 * hx * i / 4, z0 + (z1 - z0) * j / 4
                hs.append(natural_height(cx + s * (math.cos(a) * lx + math.sin(a) * lz),
                                         pz + s * (-math.sin(a) * lx + math.cos(a) * lz)))
        _levels[plot] = sum(hs) / len(hs)
    return _levels[plot]


def natural_height(x, z):
    dx = abs(x - river_cx(z))
    d = dx / river_w(z) + 0.18 * fbm(x * 0.35 + 5.0, z * 0.35)
    bed = -0.65 + 0.12 * d * d + 0.05 * fbm(x * 0.6, z * 0.6)
    t = smoothstep(0.85, 1.4, d)
    bank = 0.3 + 0.12 * fbm(x * 0.25, z * 0.25)
    h = bed + (bank - bed) * t
    h += max(0.0, dx - 9.0) * 0.12
    h += 0.35 * fbm(x * 0.07 + 10.0, z * 0.07) * t
    return h


def to_b(v):
    """Godot (x, y, z) -> Blender (x, -z, y)."""
    return Vector((v[0], -v[2], v[1]))


def new_object(name, bm):
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def export(objs, filename):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(OUT, filename),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
    )


# ---------------------------------------------------------------- terrain

def build_terrain():
    bm = bmesh.new()
    x0, x1, z0, z1 = -32.0, 32.0, -48.0, 16.0
    nx, nz = 160, 160
    grid = []
    for j in range(nz + 1):
        z = z0 + (z1 - z0) * j / nz
        row = []
        for i in range(nx + 1):
            x = x0 + (x1 - x0) * i / nx
            row.append(bm.verts.new(to_b((x, height(x, z), z))))
        grid.append(row)
    for j in range(nz):
        for i in range(nx):
            # CCW seen from above (+Y) in Godot space.
            bm.faces.new((grid[j][i], grid[j + 1][i], grid[j + 1][i + 1], grid[j][i + 1]))
    # "-col" makes Godot generate a trimesh collider for ground raycasts.
    return new_object("Terrain-col", bm)


# ---------------------------------------------------------------- rocks

def build_rock(name, seed):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1.0)
    s = Vector((seed * 3.1, seed * 1.7, seed * 5.3))
    stretch = Vector((1.0 + 0.15 * math.sin(seed), 0.55 + 0.1 * math.cos(seed * 2.0), 0.85))
    for v in bm.verts:
        p = v.co.copy()
        r = 1.0 + 0.22 * noise.noise(p * 1.2 + s) + 0.06 * noise.noise(p * 3.5 + s)
        p *= r
        p = Vector((p.x * stretch.x, p.y * stretch.y, p.z * stretch.z))
        if p.y < -0.15:
            p.y = -0.15 + (p.y + 0.15) * 0.35
        v.co = to_b(p)
    return new_object(name, bm)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)

    export([build_terrain()], "terrain.glb")
    export([build_rock("Rock%d" % i, i * 2.7 + 0.5) for i in range(6)], "rocks.glb")
    print("assets written to", os.path.abspath(OUT))


main()
