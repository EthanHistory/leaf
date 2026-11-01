"""Generates a family of cottages in the style of the Jungle Jim house.

Run:  blender --background --python tools/build_houses.py

Style rules taken from the reference house (assets/vendor/sketchfab/house):
  - flat, saturated roof colour made of individual round-bottomed tiles in
    staggered, slightly jittered rows, with deep overhangs
  - a chunky timber ridge beam whose ends curl upward, and thick barge boards
  - hand-painted wood beams (grain along the beam), corner posts that flare at
    the foot, a king post and struts in each gable
  - painted brick or plaster walls on a grey stone plinth
  - arched window lintels, cross mullions, flower boxes under every window
  - an arched plank door with a small deck and steps

Each house is written to assets/houses/<name>.gltf; textures are shared in
assets/houses/textures. A lineup render goes to shots/houses_lineup.png.
"""
import math
import os
import random

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
OUT = os.path.join(ROOT, "assets", "houses")
REF_TEX = os.path.join(ROOT, "assets", "vendor", "sketchfab", "house", "textures")
KIT_TEX = os.path.join(ROOT, "assets", "vendor", "megakit", "glTF")

ROOF_COLORS = {
    "red": (0.82, 0.04, 0.02),
    "blue": (0.06, 0.32, 0.72),
    "green": (0.16, 0.44, 0.12),
    "orange": (0.88, 0.38, 0.06),
    "teal": (0.02, 0.48, 0.5),
    "purple": (0.42, 0.18, 0.58),
}
FLOWER_COLORS = [(0.25, 0.6, 0.95), (0.95, 0.45, 0.65), (0.98, 0.82, 0.2), (0.95, 0.95, 0.9)]

HOUSES = [
    dict(name="cottage_red", walls=["brick"], w=5.0, d=4.2, pitch=50, roof="red",
         door_side="long", door_u=-0.6, chimneys=[(1.3, 1)], porch=True, shutters=None, seed=1),
    dict(name="cottage_blue", walls=["plaster"], w=4.4, d=5.0, pitch=52, roof="blue",
         door_side="gable", door_u=0.0, chimneys=[(-1.0, -1)], porch=True, shutters=(0.2, 0.4, 0.62), seed=2),
    dict(name="townhouse_green", walls=["stone", "plaster"], w=4.2, d=4.4, pitch=56, roof="green",
         door_side="gable", door_u=0.5, chimneys=[(0.8, 1)], porch=False, shutters=(0.55, 0.22, 0.12), seed=3),
    dict(name="hut_orange", walls=["boards"], w=3.4, d=3.0, pitch=45, roof="orange", wall_h=2.2,
         door_side="long", door_u=0.0, chimneys=[], porch=True, shutters=None, seed=4),
    dict(name="tall_teal", walls=["brick", "brick"], w=3.8, d=3.8, pitch=58, roof="teal",
         door_side="gable", door_u=0.0, chimneys=[(-0.7, 1)], porch=False, shutters=None, seed=5),
    dict(name="longhouse_purple", walls=["plaster"], w=7.2, d=4.4, pitch=48, roof="purple",
         door_side="long", door_u=0.9, chimneys=[(-2.4, 1), (2.6, -1)], porch=True, shutters=(0.24, 0.42, 0.2), seed=6),
]

PLINTH_H = 0.45
# How far the plinth, porch posts and steps reach below the origin, so the house
# stays grounded where the terrain under it is not perfectly level.
FOOTING = 0.6
FLOOR_H = 2.4


# ---------------------------------------------------------------- materials

class Materials:
    """Creates each material once; textured ones reuse downscaled copies of the
    reference house textures (and the MegaKit path rocks for stone)."""

    def __init__(self):
        self.cache = {}
        os.makedirs(os.path.join(OUT, "textures"), exist_ok=True)

    def _image(self, src, name):
        dst = os.path.join(OUT, "textures", name + ".png")
        img = bpy.data.images.load(src)
        if img.size[0] > 1024:
            img.scale(1024, 1024)
        img.filepath_raw = dst
        img.file_format = "PNG"
        img.save()
        return img

    def _stone_image(self, size=512, seed=9):
        """Tileable cartoon stonework: Worley cells, flat-ish painted stones,
        dark mortar, a soft highlight toward the top of each stone."""
        rnd = np.random.default_rng(seed)
        gx, gy = 6, 8
        pts = []
        for j in range(gy):
            for i in range(gx):
                pts.append(((i + 0.5 + rnd.uniform(-0.3, 0.3)) / gx, (j + 0.5 + rnd.uniform(-0.25, 0.25)) / gy))
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / size
        d1 = np.full((size, size), 9.0, np.float32)
        d2 = np.full((size, size), 9.0, np.float32)
        idx = np.zeros((size, size), np.int32)
        dyv = np.zeros((size, size), np.float32)
        for k, (px, py) in enumerate(pts):
            dx = np.abs(xx - px)
            dx = np.minimum(dx, 1 - dx) * 0.75
            dy = yy - py
            dy = np.where(dy > 0.5, dy - 1, np.where(dy < -0.5, dy + 1, dy))
            d = np.sqrt(dx * dx + dy * dy)
            closer = d < d1
            d2 = np.where(closer, d1, np.minimum(d2, d))
            dyv = np.where(closer, dy, dyv)
            idx = np.where(closer, k, idx)
            d1 = np.where(closer, d, d1)
        tones = rnd.uniform(0.0, 1.0, len(pts))
        a = np.array((0.5, 0.52, 0.55))
        b = np.array((0.68, 0.64, 0.56))
        base = a[None, None, :] * (1 - tones[idx])[..., None] + b[None, None, :] * tones[idx][..., None]
        shade = 1.0 + 0.6 * np.clip(dyv, -0.1, 0.1)
        edge = np.clip((d2 - d1) / 0.018, 0.0, 1.0)
        img = base * shade[..., None] * (0.35 + 0.65 * edge[..., None])
        mortar = np.array((0.3, 0.29, 0.27))
        img = np.where(edge[..., None] < 0.25, mortar[None, None, :], img)
        rgba = np.concatenate([np.clip(img, 0, 1), np.ones((size, size, 1))], axis=2).astype(np.float32)
        image = bpy.data.images.new("stone", size, size)
        image.pixels.foreach_set(rgba.ravel())
        image.filepath_raw = os.path.join(OUT, "textures", "stone.png")
        image.file_format = "PNG"
        image.save()
        return image

    def get(self, key):
        if key in self.cache:
            return self.cache[key]
        textures = {
            "brick": (os.path.join(REF_TEX, "bricks_wall_03_baseColor.png"), "brick"),
            "wood": (os.path.join(REF_TEX, "wood_01_baseColor.png"), "wood"),
        }
        flats = {
            "plaster": (0.93, 0.85, 0.67),
            "plinth": (0.42, 0.4, 0.36),
            "cap": (0.52, 0.5, 0.46),
            "glass": (0.84, 0.92, 0.97),
            "metal": (0.18, 0.18, 0.2),
            "leaf": (0.18, 0.5, 0.12),
        }
        mat = bpy.data.materials.new(key)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Roughness"].default_value = 0.75
        if key in textures or key == "stone":
            tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex.image = self._stone_image() if key == "stone" else self._image(*textures[key])
            mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        else:
            if key in flats:
                color = flats[key]
            elif key.startswith("roof_"):
                color = ROOF_COLORS[key[5:].replace("_under", "")]
                if key.endswith("_under"):
                    color = tuple(c * 0.55 for c in color)
                bsdf.inputs["Roughness"].default_value = 0.45
            elif key.startswith("flower"):
                color = FLOWER_COLORS[int(key[6:])]
            elif key.startswith("shutter"):
                color = tuple(int(key[8 + i * 2:10 + i * 2], 16) / 255.0 for i in range(3))
            else:
                raise KeyError(key)
            bsdf.inputs["Base Color"].default_value = (*color, 1.0)
            if key == "glass":
                bsdf.inputs["Roughness"].default_value = 0.1
        self.cache[key] = mat
        return mat


# ---------------------------------------------------------------- geometry

UV_SCALE = {"brick": 2.5, "wood": 1.5, "stone": 2.0}


def uv_project(bm, scale, grain_axis=None, offset=(0.0, 0.0)):
    """Planar UVs per face along its dominant axis; grain_axis maps to V."""
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = f.normal
        a = max(range(3), key=lambda i: abs(n[i]))
        u_axis, v_axis = [i for i in range(3) if i != a]
        if grain_axis is not None and grain_axis == u_axis:
            u_axis, v_axis = v_axis, u_axis
        for loop in f.loops:
            co = loop.vert.co
            loop[uv].uv = (co[u_axis] / scale + offset[0], co[v_axis] / scale + offset[1])


class Builder:
    """Accumulates geometry per material, then emits one joined object."""

    def __init__(self, mats, rnd):
        self.mats = mats
        self.rnd = rnd
        self.parts = {}

    def _merge(self, key, src, matrix):
        bmesh.ops.transform(src, matrix=matrix, verts=src.verts)
        me = bpy.data.meshes.new("tmp")
        src.to_mesh(me)
        src.free()
        if key not in self.parts:
            bm = bmesh.new()
            bm.loops.layers.uv.new("UVMap")
            self.parts[key] = bm
        self.parts[key].from_mesh(me)
        bpy.data.meshes.remove(me)

    def jitter(self, deg=1.5):
        r = self.rnd
        return (Matrix.Rotation(math.radians(r.uniform(-deg, deg)), 4, "X")
                @ Matrix.Rotation(math.radians(r.uniform(-deg, deg)), 4, "Y")
                @ Matrix.Rotation(math.radians(r.uniform(-deg, deg)), 4, "Z"))

    def box(self, key, size, matrix, bevel=0.03, segments=2, flare=0.0, grain=None):
        """Bevelled box centred on the origin of [matrix]; flare widens the foot."""
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
            if flare and v.co.z < 0:
                v.co.x *= 1.0 + flare
                v.co.y *= 1.0 + flare
        b = min(bevel, min(size) * 0.45)
        if b > 0.001:
            bmesh.ops.bevel(bm, geom=list(bm.edges), offset=b, segments=segments,
                            affect="EDGES", profile=0.5, clamp_overlap=True)
        if grain is None:
            grain = max(range(3), key=lambda i: size[i])
        uv_project(bm, UV_SCALE.get(key, 1.0), grain, (self.rnd.random(), self.rnd.random()))
        self._merge(key, bm, matrix)

    def beam(self, key, p0, p1, w, h, up=Vector((0, 0, 1)), bevel=0.04, jitter=1.0):
        p0, p1 = Vector(p0), Vector(p1)
        x = (p1 - p0).normalized()
        if abs(x.dot(up)) > 0.95:
            up = Vector((1, 0, 0))
        y = up.cross(x).normalized()
        z = x.cross(y)
        rot = Matrix((x, y, z)).transposed().to_4x4()
        m = Matrix.Translation((p0 + p1) / 2) @ rot @ self.jitter(jitter)
        self.box(key, ((p1 - p0).length + 0.02, w, h), m, bevel=bevel, grain=0)

    def curve_beam(self, key, pts, w, h, up=Vector((0, 0, 1))):
        for a, b in zip(pts, pts[1:]):
            d = (Vector(b) - Vector(a)) * 0.06
            self.beam(key, Vector(a) - d, Vector(b) + d, w, h, up, jitter=0.0)

    def prism(self, key, outline, depth, matrix, bevel=0.0, grain=None):
        """Extrudes a 2D (x, z) outline along local +Y by [depth]."""
        bm = bmesh.new()
        front = [bm.verts.new((x, 0.0, z)) for x, z in outline]
        back = [bm.verts.new((x, depth, z)) for x, z in outline]
        faces = [bm.faces.new(front), bm.faces.new(list(reversed(back)))]
        n = len(outline)
        for i in range(n):
            j = (i + 1) % n
            faces.append(bm.faces.new((front[i], front[j], back[j], back[i])))
        bmesh.ops.recalc_face_normals(bm, faces=faces)
        if bevel:
            bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=1,
                            affect="EDGES", profile=0.5, clamp_overlap=True)
        uv_project(bm, UV_SCALE.get(key, 1.0), grain, (self.rnd.random(), self.rnd.random()))
        self._merge(key, bm, matrix)

    def blob(self, key, center, radius, squash=0.6):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=radius)
        for v in bm.verts:
            v.co.z *= squash
        uv_project(bm, 1.0)
        self._merge(key, bm, Matrix.Translation(center))

    def finish(self, name):
        objs = []
        for key, bm in self.parts.items():
            for f in bm.faces:
                f.smooth = True
            for e in bm.edges:
                if e.is_manifold and e.calc_face_angle(0.0) > math.radians(38):
                    e.smooth = False
            me = bpy.data.meshes.new(name + "_" + key)
            bm.to_mesh(me)
            bm.free()
            me.materials.append(self.mats.get(key))
            obj = bpy.data.objects.new(name + "_" + key, me)
            bpy.context.scene.collection.objects.link(obj)
            objs.append(obj)
        for o in bpy.context.scene.objects:
            o.select_set(False)
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.object.join()
        house = bpy.context.view_layer.objects.active
        house.name = name
        return house


# ---------------------------------------------------------------- house parts

def tile_template(w, length, t):
    """Round-bottomed roof tile outline in (across, down-slope)."""
    r = w / 2
    pts = [(-w / 2, 0.0), (w / 2, 0.0), (w / 2, length - r)]
    for i in range(1, 5):
        a = math.pi * i / 5
        pts.append((r * math.cos(a), length - r + r * math.sin(a)))
    pts.append((-w / 2, length - r))
    return pts


def add_roof(b, spec, w, d, wall_h, pitch, roof_key):
    rnd = b.rnd
    tan = math.tan(math.radians(pitch))
    ov, ovx = 0.5, 0.4
    half = d / 2 + ov
    ridge_z = wall_h + (d / 2) * tan
    slope_len = half / math.cos(math.radians(pitch))
    length = w + 2 * ovx
    s, c = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    tile_w, tile_l, tile_t = 0.6, 0.56, 0.08
    outline = tile_template(tile_w, tile_l, tile_t)

    for sg in (-1, 1):
        across = Vector((1, 0, 0)) if sg > 0 else Vector((-1, 0, 0))
        down = Vector((0, sg * c, -s))
        normal = across.cross(down)
        rot = Matrix((across, down, normal)).transposed().to_4x4()
        top = Vector((0, 0, ridge_z))
        # Underlay slab so no daylight shows between the tiles.
        b.box(roof_key + "_under", (length, slope_len, 0.1),
              Matrix.Translation(top + down * (slope_len / 2) + normal * 0.05) @ rot, bevel=0.02)
        row_step = tile_l * 0.58
        rows = int(slope_len / row_step) + 1
        for k in range(rows):
            along = slope_len - tile_l - k * row_step + 0.12
            if along < -0.1:
                break
            n_across = int(length / (tile_w * 0.96)) + 2
            shift = (tile_w / 2) if k % 2 else 0.0
            for i in range(n_across):
                x = -length / 2 + i * tile_w * 0.96 + shift
                if x > length / 2 + 0.05:
                    continue
                # Keep the gable edges clean: pull edge tiles in rather than letting them overhang.
                x = max(-length / 2 + tile_w * 0.5, min(length / 2 - tile_w * 0.5, x))
                tilt = math.radians(9 + rnd.uniform(-3, 3))
                local = (Matrix.Translation((x + rnd.uniform(-0.02, 0.02), max(along, 0.0), 0.11))
                         @ Matrix.Rotation(tilt, 4, "X")
                         @ Matrix.Rotation(math.radians(rnd.uniform(-4, 4)), 4, "Z")
                         @ Matrix.Diagonal((rnd.uniform(0.95, 1.06), 1, 1, 1)))
                # The prism helper extrudes along +Y; turn it so the outline
                # lies in the roof plane and the thickness points up its normal.
                lay = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
                m = Matrix.Translation(top) @ rot @ local @ lay
                b.prism(roof_key, [(px, -py) for px, py in outline], tile_t, m, bevel=0.018)

    # Ridge beam with curled-up ends, and barge boards along both gables.
    pts = []
    for i in range(11):
        u = -1 + 2 * i / 10
        x = u * (length / 2 + 0.25)
        pts.append((x, 0.0, ridge_z + 0.24 + 0.32 * u ** 4))
    b.curve_beam("wood", pts, 0.34, 0.26)
    for xs in (-1, 1):
        x = xs * (length / 2 - 0.05)
        for sg in (-1, 1):
            eave = Vector((x, sg * half, ridge_z - half * tan + 0.12))
            b.beam("wood", eave, Vector((x, 0, ridge_z + 0.16)), 0.18, 0.24, up=Vector((0, sg * s, c)))
    return ridge_z, tan


def add_window(b, m, width, height, spec, flowers=True):
    """Window in a facade frame: local X along the wall, -Y outward, Z up."""
    rnd = b.rnd
    hw, hh = width / 2, height / 2
    b.box("glass", (width, 0.03, height), m @ Matrix.Translation((0, 0.02, 0)), bevel=0)
    for sx in (-1, 1):
        b.box("wood", (0.13, 0.14, height + 0.2), m @ Matrix.Translation((sx * (hw + 0.06), -0.05, 0)) @ b.jitter())
    b.box("wood", (0.05, 0.06, height), m @ Matrix.Translation((0, -0.03, 0)), bevel=0.015)
    b.box("wood", (width, 0.06, 0.05), m @ Matrix.Translation((0, -0.03, 0.05)), bevel=0.015)
    b.box("wood", (width + 0.42, 0.2, 0.1), m @ Matrix.Translation((0, -0.09, -hh - 0.06)) @ b.jitter())
    # Arched lintel.
    pts = []
    for i in range(7):
        a = math.pi * (0.15 + 0.7 * i / 6)
        pts.append(m @ Vector((-math.cos(a) * (hw + 0.2), -0.07, hh + 0.04 + math.sin(a) * 0.22 - 0.1)))
    b.curve_beam("wood", pts, 0.16, 0.15, up=(m.to_3x3() @ Vector((0, -1, 0))).normalized())
    if spec.get("shutters"):
        col = "shutter_%02x%02x%02x" % tuple(int(c * 255) for c in spec["shutters"])
        for sx in (-1, 1):
            ang = math.radians(sx * rnd.uniform(18, 30))
            b.box(col, (hw * 0.95, 0.05, height + 0.05),
                  m @ Matrix.Translation((sx * (hw + 0.12), -0.12, 0)) @ Matrix.Rotation(ang, 4, "Z")
                  @ Matrix.Translation((sx * hw * 0.48, 0, 0)), bevel=0.015)
    if flowers:
        b.box("wood", (width + 0.25, 0.26, 0.22), m @ Matrix.Translation((0, -0.2, -hh - 0.24)) @ b.jitter(2))
        n = max(3, int(width / 0.22))
        col = rnd.randrange(len(FLOWER_COLORS))
        for i in range(n):
            u = -hw + (i + 0.5) * width / n
            b.blob("leaf", m @ Vector((u + rnd.uniform(-0.04, 0.04), -0.2 + rnd.uniform(-0.05, 0.05), -hh - 0.1)), 0.08)
            if rnd.random() < 0.75:
                b.blob("flower%d" % col, m @ Vector((u, -0.2 + rnd.uniform(-0.06, 0.06), -hh - 0.02 + rnd.uniform(0, 0.06))),
                       0.09, squash=0.75)


def add_door(b, m, porch):
    w, h = 1.05, 1.6
    r = w / 2
    outline = [(-r, 0.0), (r, 0.0)] + [(r * math.cos(math.pi * i / 10), h + r * math.sin(math.pi * i / 10)) for i in range(11)]
    b.prism("wood", outline, 0.08, m @ Matrix.Translation((0, -0.04, 0)), grain=2)
    for z in (0.35, 1.25):
        b.box("wood", (w * 0.95, 0.05, 0.13), m @ Matrix.Translation((0, -0.07, z)) @ b.jitter(2), bevel=0.02)
    for sx in (-1, 1):
        b.box("wood", (0.16, 0.18, h + 0.05), m @ Matrix.Translation((sx * (r + 0.08), -0.08, h / 2)) @ b.jitter(), flare=0.2)
    pts = [m @ Vector(((r + 0.08) * math.cos(math.pi * i / 8), -0.08, h + (r + 0.08) * math.sin(math.pi * i / 8))) for i in range(9)]
    b.curve_beam("wood", pts, 0.18, 0.16, up=(m.to_3x3() @ Vector((0, -1, 0))).normalized())
    b.blob("metal", m @ Vector((r * 0.6, -0.1, h * 0.55)), 0.05, squash=1.0)
    if porch:
        for i in range(7):
            x = -1.05 + i * 0.35
            b.box("wood", (0.33, 1.4, 0.1), m @ Matrix.Translation((x, -0.7, PLINTH_H - 0.05)) @ b.jitter(1), bevel=0.025, grain=1)
        for i, z in enumerate((0.3, 0.15)):
            b.box("wood", (1.2, 0.35, 0.1), m @ Matrix.Translation((0, -1.55 - i * 0.35, z)) @ b.jitter(), bevel=0.025, grain=0)
            b.box("plinth", (1.1, 0.3, z + FOOTING), m @ Matrix.Translation((0, -1.55 - i * 0.35, (z - FOOTING) / 2 - 0.05)), bevel=0.04)
        for sx in (-1, 1):
            h = PLINTH_H + FOOTING
            b.box("wood", (0.14, 0.14, h), m @ Matrix.Translation((sx * 1.0, -1.3, PLINTH_H - 0.05 - h / 2)))


def build_house(spec, mats):
    rnd = random.Random(spec["seed"])
    b = Builder(mats, rnd)
    w, d = spec["w"], spec["d"]
    floors = len(spec["walls"])
    floor_h = spec.get("wall_h", FLOOR_H)
    wall_h = PLINTH_H + floors * floor_h
    roof_key = "roof_" + spec["roof"]

    # Plinth and walls, floor by floor.
    b.box("plinth", (w + 0.2, d + 0.2, PLINTH_H + FOOTING), Matrix.Translation((0, 0, (PLINTH_H - FOOTING) / 2)), bevel=0.06)
    # Facades: front/back are the long walls (ridge along X), left/right the gables.
    facades = {
        "front": (Vector((0, -d / 2, 0)), 0, w),
        "back": (Vector((0, d / 2, 0)), 180, w),
        "left": (Vector((-w / 2, 0, 0)), -90, d),
        "right": (Vector((w / 2, 0, 0)), 90, d),
    }
    for f, key in enumerate(spec["walls"]):
        z0 = PLINTH_H + f * floor_h
        if key == "boards":
            # A hidden core plus individual vertical boards on every side.
            b.box("wood", (w - 0.1, d - 0.1, floor_h), Matrix.Translation((0, 0, z0 + floor_h / 2)), bevel=0.0)
            for origin, rot, length in facades.values():
                base = Matrix.Translation(origin) @ Matrix.Rotation(math.radians(rot), 4, "Z")
                n = int(length / 0.3)
                for i in range(n):
                    u = -length / 2 + (i + 0.5) * length / n
                    hgt = floor_h - rnd.uniform(0.0, 0.08)
                    b.box("wood", (length / n - 0.015, 0.08, hgt), base @ Matrix.Translation((u, 0.0, z0 + hgt / 2)) @ b.jitter(0.8),
                          bevel=0.02, grain=2)
        else:
            b.box(key, (w, d, floor_h), Matrix.Translation((0, 0, z0 + floor_h / 2)), bevel=0.01, grain=2)

    ridge_z, tan = add_roof(b, spec, w, d, wall_h, spec["pitch"], roof_key)

    # Gable triangles in the top floor's wall material, with king post and struts.
    gable_key = "wood" if spec["walls"][-1] == "boards" else spec["walls"][-1]
    for xs in (-1, 1):
        tri = [(-d / 2, wall_h - 0.01), (d / 2, wall_h - 0.01), (0, ridge_z - 0.05)]
        m = Matrix.Translation((xs * w / 2, 0, 0)) @ Matrix.Rotation(math.radians(90), 4, "Z")
        b.prism(gable_key, tri, 0.2, m @ Matrix.Translation((0, -0.1, 0)), grain=2)
        x = xs * (w / 2 + 0.06)
        b.beam("wood", (x, 0, wall_h), (x, 0, ridge_z), 0.2, 0.2, up=Vector((1, 0, 0)))
        for sg in (-1, 1):
            b.beam("wood", (x, sg * d * 0.32, wall_h + 0.05), (x, 0, wall_h + (ridge_z - wall_h) * 0.55), 0.16, 0.16,
                   up=Vector((1, 0, 0)))

    # Timber: flared corner posts and wall plates at every floor line.
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.box("wood", (0.3, 0.3, wall_h - 0.1), Matrix.Translation((sx * w / 2, sy * d / 2, wall_h / 2 + 0.05)) @ b.jitter(1),
                  flare=0.35, grain=2)
    for f in range(floors + 1):
        z = PLINTH_H + f * floor_h
        for sy in (-1, 1):
            b.beam("wood", (-w / 2 - 0.15, sy * (d / 2 + 0.03), z), (w / 2 + 0.15, sy * (d / 2 + 0.03), z), 0.22, 0.22)
        for sx in (-1, 1):
            b.beam("wood", (sx * (w / 2 + 0.03), -d / 2 - 0.15, z), (sx * (w / 2 + 0.03), d / 2 + 0.15, z), 0.22, 0.22)

    door_face = "front" if spec["door_side"] == "long" else "left"
    for name, (origin, rot, length) in facades.items():
        base = Matrix.Translation(origin) @ Matrix.Rotation(math.radians(rot), 4, "Z")
        slots = max(1, int((length - 0.6) / 1.9))
        for f in range(floors):
            z0 = PLINTH_H + f * floor_h
            for i in range(slots):
                u = -length / 2 + (i + 0.5) * length / slots
                if name == door_face and f == 0 and abs(u - spec["door_u"]) < 1.1:
                    continue
                win_h = min(1.05, floor_h - 1.0)
                add_window(b, base @ Matrix.Translation((u, 0, z0 + floor_h * 0.55)), 0.82, win_h, spec)
            # Plaster walls get half-timber studs between the windows.
            if spec["walls"][f] == "plaster":
                for i in range(1, slots):
                    u = -length / 2 + i * length / slots
                    b.box("wood", (0.16, 0.12, floor_h), base @ Matrix.Translation((u, -0.04, z0 + floor_h / 2)) @ b.jitter())
        if name in ("left", "right") and ridge_z - wall_h > 1.5:
            add_window(b, base @ Matrix.Translation((0, 0, wall_h + (ridge_z - wall_h) * 0.33)), 0.6, 0.6, spec, flowers=False)
        if name == door_face:
            add_door(b, base @ Matrix.Translation((spec["door_u"], 0, PLINTH_H if spec["porch"] else 0.0)), spec["porch"])

    # Brick chimneys on the chosen slope.
    for x, sg in spec["chimneys"]:
        y = sg * d * 0.22
        top = ridge_z + 1.0
        bottom = wall_h - 0.5
        b.box("brick", (0.72, 0.72, top - bottom), Matrix.Translation((x, y, (top + bottom) / 2)) @ b.jitter(2),
              bevel=0.03)
        b.box("cap", (0.9, 0.9, 0.16), Matrix.Translation((x, y, top + 0.05)), bevel=0.04)

    house = b.finish(spec["name"])
    if door_face == "left":
        # Turn the gable with the door toward -Y, the house's front.
        house.data.transform(Matrix.Rotation(math.radians(90), 4, "Z"))
    return house


def export(house):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    house.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(OUT, house.name + ".gltf"),
        export_format="GLTF_SEPARATE",
        export_texture_dir="textures",
        use_selection=True,
    )
    tris = sum(len(p.vertices) - 2 for p in house.data.polygons)
    print("wrote", house.name, "tris", tris)


def render_lineup(houses):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 2000, 700
    sc.view_settings.view_transform = "Standard"
    world = bpy.data.worlds.new("w")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.72, 0.82, 0.9, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(35))
    sc.collection.objects.link(sun)
    x = 0.0
    for h in houses:
        h.location.x = x
        x += max(h.dimensions.x, 5.0) + 2.5
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    mid = (x - 2.5 - max(houses[-1].dimensions.x, 5.0)) / 2
    target = Vector((mid, 0, 3.0))
    cam.location = target + Vector((-8, -40, 14))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = x + 1.0
    sc.render.filepath = os.path.join(ROOT, "shots", "houses_lineup.png")
    bpy.ops.render.render(write_still=True)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)
    mats = Materials()
    houses = []
    for spec in HOUSES:
        house = build_house(spec, mats)
        export(house)
        houses.append(house)
    render_lineup(houses)


main()
