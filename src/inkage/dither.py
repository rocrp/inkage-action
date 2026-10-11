"""Dithering: map an RGB image onto a Panel's measured colors, yielding ink indices.

Methods: ``threshold`` (nearest color), error diffusion (``floyd-steinberg``,
``atkinson``, ``stucki``, ``jjn``, ``burkes``, ``sierra``) and ordered
(``bayer4``, ``bayer8``). Options: serpentine scanning, strength 0..2 (scales
diffused error / ordered spread), and ``ycbcr`` weighted color distance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
from PIL import Image

from inkage.panel import RGB


def _kernel(divisor: int, *rows: tuple[int, ...]) -> tuple[tuple[int, int, Fraction], ...]:
    """Kernel from published weight rows, each 5 wide centred on the current column.

    Row 0 holds only the weights right of the current pixel (x+1, x+2).
    """
    first, *rest = rows
    taps = [(dx, 0, w) for dx, w in zip((1, 2), first, strict=True)]
    taps += [(dx, dy, w) for dy, row in enumerate(rest, 1) for dx, w in zip(range(-2, 3), row, strict=True)]
    return tuple((dx, dy, Fraction(w, divisor)) for dx, dy, w in taps if w)


# Published error-diffusion kernels: (dx, dy, weight) relative to the current pixel.
KERNELS: dict[str, tuple[tuple[int, int, Fraction], ...]] = {
    "floyd-steinberg": _kernel(16, (7, 0), (0, 3, 5, 1, 0)),
    "atkinson": _kernel(8, (1, 1), (0, 1, 1, 1, 0), (0, 0, 1, 0, 0)),
    "jjn": _kernel(48, (7, 5), (3, 5, 7, 5, 3), (1, 3, 5, 3, 1)),
    "stucki": _kernel(42, (8, 4), (2, 4, 8, 4, 2), (1, 2, 4, 2, 1)),
    "burkes": _kernel(32, (8, 4), (2, 4, 8, 4, 2)),
    "sierra": _kernel(32, (5, 3), (2, 4, 5, 4, 2), (0, 2, 3, 2, 0)),
}


def _bayer(n: int) -> np.ndarray:
    """Recursive Bayer index matrix (values 0..n*n-1)."""
    m = np.array([[0, 2], [3, 1]])
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return m


ORDERED: dict[str, np.ndarray] = {"bayer4": _bayer(4), "bayer8": _bayer(8)}
METHODS: tuple[str, ...] = ("threshold", *KERNELS, *ORDERED)
DISTANCES = ("rgb", "ycbcr")

# BT.601 RGB -> YCbCr (offsets dropped: only differences matter). Chroma is
# weighted at half of luma so tonal structure wins over hue shifts.
_YCBCR = np.array([[0.299, 0.587, 0.114], [-0.168736, -0.331264, 0.5], [0.5, -0.418688, -0.081312]])
_YCBCR_WEIGHTS = np.array([1.0, 0.5, 0.5])
# Distance as a quadratic form d = e^T Q e on the RGB difference e.
_Q = {"rgb": np.eye(3), "ycbcr": _YCBCR.T @ np.diag(_YCBCR_WEIGHTS) @ _YCBCR}


@dataclass(slots=True, frozen=True)
class Dither:
    method: str = "threshold"
    serpentine: bool = False
    strength: float = 1.0
    distance: str = "rgb"

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"unknown dither {self.method!r} (known: {', '.join(METHODS)})")
        if not 0.0 <= self.strength <= 2.0:
            raise ValueError(f"dither strength must be 0..2, got {self.strength}")
        if self.distance not in DISTANCES:
            raise ValueError(f"unknown distance {self.distance!r} (known: {', '.join(DISTANCES)})")

    @classmethod
    def parse(cls, raw: str | dict | Dither) -> Dither:
        match raw:
            case Dither():
                return raw
            case str():
                return cls(method=raw)
            case dict():
                if unknown := set(raw) - {"method", "serpentine", "strength", "distance"}:
                    raise ValueError(f"unknown dither keys {sorted(unknown)}")
                return cls(**raw)
        raise ValueError(f"dither must be a name or a table, got {raw!r}")


def dither(img: Image.Image, colors: tuple[RGB, ...], spec: Dither) -> np.ndarray:
    """Return an (h, w) uint8 array of indices into ``colors``."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    pal = np.array(colors, dtype=np.float64)
    if spec.method in ORDERED:
        m = ORDERED[spec.method]
        n = m.shape[0]
        h, w = rgb.shape[:2]
        t = (np.tile(m, (h // n + 1, w // n + 1))[:h, :w] + 0.5) / (n * n) - 0.5
        return _nearest_array(np.clip(rgb - t[..., None] * 255.0 * spec.strength, 0, 255), pal, spec.distance)
    if spec.method == "threshold":
        return _nearest_array(rgb, pal, spec.distance)
    return _diffuse(rgb, pal, KERNELS[spec.method], spec)


def _nearest_array(rgb: np.ndarray, pal: np.ndarray, distance: str) -> np.ndarray:
    diff = rgb[:, :, None, :] - pal[None, None, :, :]
    dist = np.einsum("hwki,ij,hwkj->hwk", diff, _Q[distance], diff)
    return np.argmin(dist, axis=2).astype(np.uint8)


def _nearest_fn(pal: np.ndarray, distance: str) -> Callable[[float, float, float], int]:
    colors = [tuple(float(c) for c in p) for p in pal]
    order = range(len(colors))
    if distance == "rgb":

        def nearest(r: float, g: float, b: float) -> int:
            return min(order, key=lambda k: (r - colors[k][0]) ** 2 + (g - colors[k][1]) ** 2 + (b - colors[k][2]) ** 2)

        return nearest
    q = [[float(v) for v in row] for row in _Q[distance]]

    def nearest_q(r: float, g: float, b: float) -> int:
        def d(k: int) -> float:
            e = (r - colors[k][0], g - colors[k][1], b - colors[k][2])
            return sum(e[i] * q[i][j] * e[j] for i in range(3) for j in range(3))

        return min(order, key=d)

    return nearest_q


def _diffuse(rgb: np.ndarray, pal: np.ndarray, kernel: tuple, spec: Dither) -> np.ndarray:
    """Error diffusion with integer pixel values: incoming error is truncated toward zero
    before it is added, as in Pillow's Floyd-Steinberg, then the sum is clipped to 0..255."""
    h, w = rgb.shape[:2]
    base = [rgb[:, :, c].astype(int).ravel().tolist() for c in range(3)]
    acc = [[0.0] * (h * w) for _ in range(3)]
    out = np.zeros(h * w, dtype=np.uint8)
    colors = pal.tolist()
    nearest = _nearest_fn(pal, spec.distance)
    taps = [(dx, dy, float(wt) * spec.strength) for dx, dy, wt in kernel]
    for y in range(h):
        reverse = spec.serpentine and y % 2 == 1
        for x in range(w - 1, -1, -1) if reverse else range(w):
            i = y * w + x
            r, g, b = (min(255, max(0, base[c][i] + int(acc[c][i]))) for c in range(3))
            k = nearest(r, g, b)
            out[i] = k
            err = (r - colors[k][0], g - colors[k][1], b - colors[k][2])
            for dx, dy, wt in taps:
                xx = x - dx if reverse else x + dx
                if 0 <= xx < w and y + dy < h:
                    j = (y + dy) * w + xx
                    for c in range(3):
                        acc[c][j] += err[c] * wt
    return out.reshape(h, w)
