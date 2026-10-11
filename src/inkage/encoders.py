"""Encoders: device-specific packings of a Frame. Pure functions of the indexed PNG.

``pcim``: 16-byte little-endian header — magic ``PCIM`` (4s), version (u8),
bpp (u8), palette count (u8), reserved (u8), width (u16), height (u16),
payload length (u32) — then 4bpp pixels, high nibble first, rows padded to a
whole byte.
"""

import struct
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PIL import Image

PCIM_HEADER = struct.Struct("<4sBBBBHHI")
PCIM_MAGIC = b"PCIM"
PCIM_VERSION = 1


def encode_pcim(frame: Image.Image, ink_count: int) -> bytes:
    if frame.mode != "P":
        raise ValueError(f"pcim: frame must be mode P, got {frame.mode}")
    if not 0 < ink_count <= 16:
        raise ValueError(f"pcim: ink count must be 1..16, got {ink_count}")
    px = np.asarray(frame, dtype=np.uint8)
    if (top := int(px.max())) >= ink_count:
        raise ValueError(f"pcim: pixel index {top} exceeds ink count {ink_count}")
    h, w = px.shape
    if w % 2:
        px = np.pad(px, ((0, 0), (0, 1)))
    payload = ((px[:, 0::2] << 4) | px[:, 1::2]).astype(np.uint8).tobytes()
    return PCIM_HEADER.pack(PCIM_MAGIC, PCIM_VERSION, 4, ink_count, 0, w, h, len(payload)) + payload


@dataclass(slots=True, frozen=True)
class Encoder:
    ext: str
    encode: Callable[[Image.Image, int], bytes]  # (frame, ink_count) -> bytes


ENCODERS: dict[str, Encoder] = {"pcim": Encoder(ext="pcim", encode=encode_pcim)}
