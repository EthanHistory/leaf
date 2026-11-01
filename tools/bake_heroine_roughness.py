"""Bakes a roughness map for the heroine from her Tripo base colour texture.

Tripo gives skin, hair and clothes one material with a single roughness, so the
black top shines like the hair. All three live in one texture, but their colours
are distinct: skin is bright, hair is a saturated dark brown, and the clothes are
a near-neutral dark grey. Classify each texel by that and write a roughness value.

Run:  python tools/bake_heroine_roughness.py   (needs Pillow)
"""

import colorsys
import os

from PIL import Image, ImageFilter

ROOT = os.path.join(os.path.dirname(__file__), "..", "assets", "characters")
SRC = "heroine_tripo_image_e894fd3d-702c-408a-a9b4-75fc3fa2389a_0_0.jpg"
OUT = "heroine_roughness.png"

SKIN = 0.55
HAIR = 0.38
CLOTH = 0.88
EYE = 0.25  # whites of the eyes: bright and unsaturated


def smoothstep(a: float, b: float, x: float) -> float:
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def roughness(r: int, g: int, b: int) -> float:
    _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    dark = 1.0 - smoothstep(0.38, 0.50, v)
    # Among dark texels, saturated brown is hair, grey is cloth.
    hair = smoothstep(0.25, 0.38, s)
    dark_value = CLOTH + (HAIR - CLOTH) * hair
    eye = smoothstep(0.75, 0.85, v) * (1.0 - smoothstep(0.15, 0.25, s))
    light_value = SKIN + (EYE - SKIN) * eye
    return light_value + (dark_value - light_value) * dark


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
    # Stray texels in the top's paint pass as hair and glint; a median clears them.
    out = out.filter(ImageFilter.MedianFilter(5))
    out.save(os.path.join(ROOT, OUT), optimize=True)
    print("wrote", OUT, out.size)


if __name__ == "__main__":
    main()
