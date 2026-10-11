"""The Frame pipeline: RGB image -> framed -> dithered -> indexed PNG (+ RGB Preview)."""

import io
from typing import Literal

import numpy as np
from PIL import Image, ImageOps

from inkage.dither import Dither, dither
from inkage.panel import Panel

type Framing = Literal["fill", "fit"]


def frame_to_panel(img: Image.Image, panel: Panel, framing: Framing = "fill") -> Image.Image:
    """Scale to the Panel size: ``fill`` crops to cover, ``fit`` letterboxes in white."""
    img = img.convert("RGB")
    if img.size == panel.size:
        return img
    if framing == "fill":
        return ImageOps.fit(img, panel.size, Image.Resampling.LANCZOS)
    if framing == "fit":
        return ImageOps.pad(img, panel.size, Image.Resampling.LANCZOS, color=(255, 255, 255))
    raise ValueError(f"unknown framing {framing!r} (expected 'fill' or 'fit')")


def make_frame(img: Image.Image, panel: Panel, spec: Dither, framing: Framing = "fill") -> Image.Image:
    """Return a mode-P image whose palette is exactly the Panel's nominal inks, in Ink Order."""
    indices = dither(frame_to_panel(img, panel, framing), panel.measured, spec)
    frame = Image.fromarray(indices, mode="P")
    frame.putpalette([c for color in panel.nominal for c in color])
    return frame


def check_frame(frame: Image.Image, panel: Panel) -> None:
    """Fail unless ``frame`` is a valid Frame for ``panel``."""
    if frame.mode != "P":
        raise ValueError(f"frame must be mode P, got {frame.mode}")
    if frame.size != panel.size:
        raise ValueError(f"frame is {frame.size}, panel {panel.id} is {panel.size}")
    palette = frame.getpalette() or []
    if len(palette) != 3 * panel.ink_count:
        raise ValueError(f"frame palette has {len(palette) // 3} entries, panel {panel.id} has {panel.ink_count}")
    if (top := int(np.asarray(frame).max())) >= panel.ink_count:
        raise ValueError(f"frame pixel index {top} >= ink count {panel.ink_count}")


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def preview(frame: Image.Image) -> Image.Image:
    """RGB rendering of a Frame in its nominal colors, for humans."""
    return frame.convert("RGB")
