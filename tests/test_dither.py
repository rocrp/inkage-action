"""Extended dithering, each kernel checked on a hand-computed 3x2 image.

Input: every pixel grey 100, BW palette; white iff value >= 127.5. Incoming
error is truncated toward zero before it is added (integer pixel values, as in
Pillow); taps falling outside the image are dropped. Hand derivations (pixel
value when reached, raster order p00 p10 p20 p01 p11 p21):

FS (7,3,5,1)/16:  p00 100->0 e100; p10 100+43=143->1 e-112; p20 51->0;
                  p01 110->0; p11 128->1 e-127; p21 54->0
Atkinson 1/8:     p00 ->0; p10 112->0; p20 126->0; p01 126->0; p11 158->1; p21 133->1
JJN /48:          p00 ->0; p10 114->0; p20 127->0; p01 134->1; p11 122->0; p21 141->1
Stucki /42:       p00 ->0; p10 119->0; p20 132->1; p01 124->0; p11 144->1; p21 84->0
Burkes /32:       p00 ->0; p10 125->0; p20 143->1; p01 133->1; p11 100->0; p21 103->0
Sierra /32:       p00 ->0; p10 115->0; p20 127->0; p01 137->1; p11 127->0; p21 149->1
"""

import random

import numpy as np
import pytest
from PIL import Image

from inkage.config import ConfigError, parse_config
from inkage.dither import ORDERED, Dither, dither

BW = ((0, 0, 0), (255, 255, 255))
S6 = ((0, 0, 0), (255, 255, 255), (255, 0, 0), (255, 255, 0), (0, 0, 255), (0, 255, 0))
GREY = Image.new("RGB", (3, 2), (100, 100, 100))

HAND = {
    "floyd-steinberg": [[0, 1, 0], [0, 1, 0]],
    "atkinson": [[0, 0, 0], [0, 1, 1]],
    "jjn": [[0, 0, 0], [1, 0, 1]],
    "stucki": [[0, 0, 1], [0, 1, 0]],
    "burkes": [[0, 0, 1], [1, 0, 0]],
    "sierra": [[0, 0, 0], [1, 0, 1]],
}


@pytest.mark.parametrize("method", HAND)
def test_kernel_hand_computed(method):
    assert dither(GREY, BW, Dither(method)).tolist() == HAND[method]


def test_bayer_matrices_are_standard():
    assert ORDERED["bayer4"].tolist() == [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
    assert ORDERED["bayer8"].tolist() == [
        [0, 32, 8, 40, 2, 34, 10, 42],
        [48, 16, 56, 24, 50, 18, 58, 26],
        [12, 44, 4, 36, 14, 46, 6, 38],
        [60, 28, 52, 20, 62, 30, 54, 22],
        [3, 35, 11, 43, 1, 33, 9, 41],
        [51, 19, 59, 27, 49, 17, 57, 25],
        [15, 47, 7, 39, 13, 45, 5, 37],
        [63, 31, 55, 23, 61, 29, 53, 21],
    ]


def test_bayer4_half_grey_whitens_cells_below_8():
    # Grey 128 = 50.2%: a cell turns white when its threshold (M+0.5)/16 is below that, i.e. M <= 7.
    out = dither(Image.new("RGB", (4, 4), (128, 128, 128)), BW, Dither("bayer4"))
    expected = (np.array(ORDERED["bayer4"]) <= 7).astype(int)
    assert out.tolist() == expected.tolist()


def asymmetric(w: int = 24, h: int = 16) -> Image.Image:
    x, y = np.meshgrid(np.arange(w), np.arange(h))
    arr = np.stack([(x * x * 255) // ((w - 1) ** 2), (y * 255) // (h - 1), ((w - 1 - x) * 160) // (w - 1)], axis=-1)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def test_serpentine_differs_and_both_valid():
    plain = dither(asymmetric(), S6, Dither("floyd-steinberg"))
    snake = dither(asymmetric(), S6, Dither("floyd-steinberg", serpentine=True))
    assert not np.array_equal(plain, snake)
    assert plain.max() < 6 and snake.max() < 6
    assert np.array_equal(plain[0], snake[0])  # row 0 is scanned left-to-right in both


@pytest.mark.parametrize("method", ["floyd-steinberg", "atkinson", "jjn", "stucki", "burkes", "sierra", "bayer8"])
def test_strength_zero_equals_threshold(method):
    rng = random.Random(7)
    img = Image.new("RGB", (20, 12))
    img.putdata([tuple(rng.randrange(256) for _ in range(3)) for _ in range(240)])
    assert np.array_equal(dither(img, S6, Dither(method, strength=0)), dither(img, S6, Dither("threshold")))


def test_ycbcr_distance_prefers_luma_match():
    # (0,224,0) on BWR. RGB: black 224² = 50176 < red 115201 < white 131011 -> black.
    # YCbCr (BT.601, chroma weight 0.5): chroma differences to black and white are identical
    # (Cb -74.20, Cr -93.79), luma differs: to black Y=131.49, to white Y=-123.51 -> white.
    px = Image.new("RGB", (1, 1), (0, 224, 0))
    bwr = BW + ((255, 0, 0),)
    assert dither(px, bwr, Dither("threshold")).item() == 0
    assert dither(px, bwr, Dither("threshold", distance="ycbcr")).item() == 1


def test_source_selects_kernel_by_name_and_unknown_fails():
    ok = {"sources": {"calendar": {"panels": ["800x480-bwr"], "dither": {"method": "stucki", "serpentine": True}}}}
    assert parse_config(ok).sources[0].dither == Dither("stucki", serpentine=True)
    bad = {"sources": {"calendar": {"panels": ["800x480-bwr"], "dither": "stuki"}}}
    with pytest.raises(ConfigError, match=r"sources\.calendar\.dither.*stuki"):
        parse_config(bad)
