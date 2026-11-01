"""Bakes a roughness map for the heroine from her Tripo base colour texture.

Tripo gives skin and clothes one material with a single roughness. Both live in
one texture, but skin is bright and the clothes are dark, so classify each texel
by brightness and write a roughness value. The hair is its own mesh since
tools/build_heroine.py and gets its roughness in player.gd.

Run:  python tools/bake_heroine_roughness.py   (needs Pillow)
"""

import colorsys
import os

from PIL import Image

ROOT = os.path.join(os.path.dirname(__file__), "..", "assets", "characters")
SRC = "heroine_heroine_base.jpg"  # extracted by Godot from heroine.glb
OUT = "heroine_roughness.png"

SKIN = 0.55
CLOTH = 0.88
EYE = 0.25  # whites of the eyes: bright and unsaturated


def smoothstep(a: float, b: float, x: float) -> float:
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def roughness(r: int, g: int, b: int) -> float:
    _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    dark = 1.0 - smoothstep(0.38, 0.50, v)
    eye = smoothstep(0.75, 0.85, v) * (1.0 - smoothstep(0.15, 0.25, s))
    light_value = SKIN + (EYE - SKIN) * eye
    return light_value + (CLOTH - light_value) * dark


def main() -> None:
    src = Image.open(os.path.join(ROOT, SRC)).convert("RGB")
    lut = {}  # the texture has far fewer distinct colours than texels
    px = []
    for c in src.getdata():
        if c not in lut:
            lut[c] = round(roughness(*c) * 255)
        px.append(lut[c])
    out = Image.new("L", src.size)
    out.putdata(px)
    out.save(os.path.join(ROOT, OUT), optimize=True)
    print("wrote", OUT, out.size)


if __name__ == "__main__":
    main()
