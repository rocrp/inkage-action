"""pcim byte layout against hand-computed bytes."""

import numpy as np
import pytest
from PIL import Image

from inkage.encoders import encode_pcim


def indexed(rows: list[list[int]], n: int) -> Image.Image:
    img = Image.fromarray(np.array(rows, dtype=np.uint8), mode="P")
    img.putpalette([0] * 3 * n)
    return img


def test_3x2_hand_computed_bytes():
    frame = indexed([[0, 1, 2], [3, 4, 5]], 6)
    expected = bytes(
        [
            *b"PCIM",  # magic
            0x01,  # version
            0x04,  # bpp
            0x06,  # palette count
            0x00,  # reserved
            0x03, 0x00,  # width 3 (LE u16)
            0x02, 0x00,  # height 2
            0x04, 0x00, 0x00, 0x00,  # payload: 2 bytes/row (3 px padded to 4 nibbles) x 2 rows
            0x01, 0x20,  # row 0: 0|1, 2|pad
            0x34, 0x50,  # row 1: 3|4, 5|pad
        ]
    )  # fmt: skip
    assert encode_pcim(frame, 6) == expected


def test_800x480_spectra6_size():
    frame = indexed(np.random.default_rng(1).integers(0, 6, (480, 800)).tolist(), 6)
    assert len(encode_pcim(frame, 6)) == 16 + 192_000


def test_index_beyond_ink_count_fails():
    with pytest.raises(ValueError, match="exceeds ink count"):
        encode_pcim(indexed([[0, 3]], 4), 3)
