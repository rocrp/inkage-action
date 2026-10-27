"""Panels: target display geometry and palette, plus the built-in Preset catalog.

Every palette is a prefix of the Ink Order (ADR-0002), so index ``i`` means the
same ink on every Panel and every Encoder.
"""

from dataclasses import dataclass

type RGB = tuple[int, int, int]

INK_ORDER: tuple[str, ...] = ("black", "white", "red", "yellow", "blue", "green")

# Nominal ink colors: what the indexed PNG's palette holds.
NOMINAL: dict[str, RGB] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "yellow": (255, 255, 0),
    "blue": (0, 0, 255),
    "green": (0, 255, 0),
}

# Palette name -> ink count (always a prefix of INK_ORDER).
PALETTES: dict[str, int] = {"bw": 2, "bwr": 3, "bwry": 4, "spectra6": 6}

# Spectra 6 colors as the panel actually shows them, white-balanced so the
# measured white reads pure white. Derived from the epdoptimize `spectra6`
# measured set (https://github.com/Utzel-Butzel/epdoptimize) divided by its
# measured white #B9C7C9 and clamped. BW/BWR/BWRY use nominal colors, matching
# the EPD-nRF5 web tool's dither palettes.
SPECTRA6_MEASURED: tuple[RGB, ...] = (
    (43, 44, 48),
    (255, 255, 255),
    (135, 41, 38),
    (255, 240, 38),
    (48, 81, 180),
    (73, 110, 74),
)


@dataclass(slots=True, frozen=True)
class Panel:
    id: str
    width: int
    height: int
    palette: str
    measured: tuple[RGB, ...]
    encoders: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.palette not in PALETTES:
            raise ValueError(f"panel {self.id!r}: unknown palette {self.palette!r} (known: {', '.join(PALETTES)})")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"panel {self.id!r}: size must be positive, got {self.width}x{self.height}")
        if len(self.measured) != self.ink_count:
            raise ValueError(
                f"panel {self.id!r}: measured has {len(self.measured)} colors, "
                f"palette {self.palette} has {self.ink_count}"
            )
        if any(not 0 <= c <= 255 for color in self.measured for c in color):
            raise ValueError(f"panel {self.id!r}: measured channels must be 0..255")

    @property
    def ink_count(self) -> int:
        return PALETTES[self.palette]

    @property
    def inks(self) -> tuple[str, ...]:
        return INK_ORDER[: self.ink_count]

    @property
    def nominal(self) -> tuple[RGB, ...]:
        return nominal_measured(self.palette)

    @property
    def ink_hex(self) -> dict[str, str]:
        """CSS color per available ink, e.g. {"black": "#000000", ...}."""
        return {ink: "#{:02x}{:02x}{:02x}".format(*NOMINAL[ink]) for ink in self.inks}

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


def nominal_measured(palette: str) -> tuple[RGB, ...]:
    if palette not in PALETTES:
        raise ValueError(f"unknown palette {palette!r} (known: {', '.join(PALETTES)})")
    return tuple(NOMINAL[ink] for ink in INK_ORDER[: PALETTES[palette]])


def _preset(width: int, height: int, palette: str) -> Panel:
    measured = SPECTRA6_MEASURED if palette == "spectra6" else nominal_measured(palette)
    return Panel(id=f"{width}x{height}-{palette}", width=width, height=height, palette=palette, measured=measured)


PRESETS: dict[str, Panel] = {
    p.id: p
    for p in (
        *(
            _preset(w, h, palette)
            for w, h in ((250, 122), (296, 128), (400, 300), (648, 480), (800, 480))
            for palette in ("bw", "bwr", "bwry")
        ),
        _preset(800, 480, "spectra6"),
        _preset(400, 600, "spectra6"),
        _preset(528, 792, "bw"),
    )
}
