"""Frame pipeline: indexed PNG with exactly N palette entries, threshold and FS mapping, Preview."""

import io
import random
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from inkage.dither import Dither
from inkage.frame import make_frame, png_bytes, preview
from inkage.panel import PRESETS


def reload(frame: Image.Image) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes(frame)))


def noise(w: int, h: int, seed: int = 0) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h))
    img.putdata([tuple(rng.randrange(256) for _ in range(3)) for _ in range(w * h)])
    return img


@pytest.mark.parametrize(
    ("preset", "n"), [("250x122-bw", 2), ("250x122-bwr", 3), ("400x300-bwry", 4), ("400x600-spectra6", 6)]
)
@pytest.mark.parametrize("method", ["threshold", "floyd-steinberg"])
def test_png_palette_has_exactly_n_entries(preset, n, method):
    panel = PRESETS[preset]
    png = reload(make_frame(noise(97, 61), panel, Dither(method)))  # odd size: exercises fill framing
    assert png.mode == "P"
    assert png.size == panel.size
    assert len(png.getpalette()) == 3 * n
    assert int(np.asarray(png).max()) < n


def test_png_keeps_n_entries_even_when_inks_unused():
    """A white-only image on a BWR panel still carries black, white, red (no trimming)."""
    png = reload(make_frame(Image.new("RGB", (250, 122), "white"), PRESETS["250x122-bwr"], Dither()))
    assert png.getpalette() == [0, 0, 0, 255, 255, 255, 255, 0, 0]


def test_threshold_hand_computed():
    # BWR nominal: black (0,0,0), white (255,255,255), red (255,0,0). Squared RGB distances:
    #   (10,10,10):   black 300            -> 0
    #   (128,128,128): black 49152, white 48387, red 48387+? = 127²+128²+128² = 48897 -> white 1
    #   (200,30,40):  red 55²+30²+40² = 5525 (black 42500, white 62725) -> 2
    #   (130,20,20):  black 17700, red 125²+20²+20² = 16425 -> 2
    img = Image.new("RGB", (2, 2))
    img.putdata([(10, 10, 10), (128, 128, 128), (200, 30, 40), (130, 20, 20)])
    panel = replace(PRESETS["250x122-bwr"], width=2, height=2)
    assert np.asarray(make_frame(img, panel, Dither("threshold"))).tolist() == [[0, 1], [2, 2]]


def test_floyd_steinberg_matches_pillow_golden():
    """Pillow's own FS quantizer on the same input and palette gives the same indices.

    Pillow is an exact oracle only where its shortcuts don't bite: grey input on a
    BW palette (its coarse nearest-colour cache is exact there), and away from the
    right edge, where Pillow writes the blue channel's carried error into all three
    channels at each row end (Convert.c ``e[0] = b0; e[1] = b1; e[2] = b2``). That
    contamination moves one column left per row, so compare the triangle x < w-1-y.
    """
    w, h = 64, 32
    x, y = np.meshgrid(np.arange(w), np.arange(h))
    img = Image.fromarray(np.stack([(x + y) * 255 // (w + h - 2)] * 3, axis=-1).astype(np.uint8), "RGB")
    panel = replace(PRESETS["250x122-bw"], width=w, height=h)
    pal = Image.new("P", (1, 1))
    pal.putpalette([0, 0, 0, 255, 255, 255])
    golden = np.asarray(img.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG))
    ours = np.asarray(make_frame(img, panel, Dither("floyd-steinberg")))
    safe = x < (w - 1) - y
    assert np.array_equal(ours[safe], golden[safe])
    # A horizontal ramp keeps every row's carried error grey, so Pillow's edge slip is harmless: whole image matches.
    ramp = Image.fromarray(np.stack([x * 255 // (w - 1)] * 3, axis=-1).astype(np.uint8), "RGB")
    golden = np.asarray(ramp.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG))
    assert np.array_equal(np.asarray(make_frame(ramp, panel, Dither("floyd-steinberg"))), golden)


def test_preview_is_frame_in_nominal_colors():
    panel = PRESETS["250x122-bwr"]
    frame = make_frame(noise(250, 122, seed=3), panel, Dither("floyd-steinberg"))
    idx = np.asarray(frame)
    rgb = np.asarray(preview(frame))
    assert rgb.shape == (122, 250, 3)
    for i, color in enumerate([(0, 0, 0), (255, 255, 255), (255, 0, 0)]):  # BWR inks per CONTEXT.md
        assert (rgb[idx == i] == color).all()


def test_measured_white_changes_mapping():
    # Grey 110 vs nominal white: black 3*110² = 36300 < white 3*145² = 63075 -> black.
    # vs measured white (220,215,205): 110²+105²+95² = 32150 < 36300 -> white.
    grey = Image.new("RGB", (1, 1), (110, 110, 110))
    nominal = replace(PRESETS["250x122-bw"], width=1, height=1)
    measured = replace(nominal, measured=((0, 0, 0), (220, 215, 205)))
    assert np.asarray(make_frame(grey, nominal, Dither())).item() == 0
    assert np.asarray(make_frame(grey, measured, Dither())).item() == 1
    # The PNG still carries nominal colors.
    assert make_frame(grey, measured, Dither()).getpalette() == [0, 0, 0, 255, 255, 255]


def test_fit_letterboxes_in_white():
    # 2x4 into 8x4: scaled 1:1, centred at x = round((8 - 2) / 2) = 3.
    wide = replace(PRESETS["250x122-bw"], width=8, height=4)
    panel = replace(PRESETS["250x122-bw"], width=4, height=2)
    tall_black = Image.new("RGB", (2, 4), "black")
    assert np.asarray(make_frame(tall_black, wide, Dither(), framing="fit")).tolist() == [[1, 1, 1, 0, 0, 1, 1, 1]] * 4
    assert np.asarray(make_frame(tall_black, panel, Dither(), framing="fill")).tolist() == [[0] * 4, [0] * 4]
