"""Preset catalog checked against the Ink Order spec table (CONTEXT.md, ADR-0002)."""

from inkage.panel import PRESETS

# Spec table: palette -> inks in canonical order (CONTEXT.md "Ink Order").
SPEC_INKS = {
    "bw": ["black", "white"],
    "bwr": ["black", "white", "red"],
    "bwry": ["black", "white", "red", "yellow"],
    "spectra6": ["black", "white", "red", "yellow", "blue", "green"],
}
# Sizes the catalog must ship (issue #1 / design.md "Panel").
SPEC_SIZES = {(250, 122), (296, 128), (400, 300), (648, 480), (800, 480)}
SPEC_SPECTRA6 = {(800, 480), (400, 600)}


def test_catalog_covers_spec_sizes():
    for w, h in SPEC_SIZES:
        for palette in ("bw", "bwr", "bwry"):
            assert f"{w}x{h}-{palette}" in PRESETS
    for w, h in SPEC_SPECTRA6:
        assert f"{w}x{h}-spectra6" in PRESETS


def test_every_preset_palette_is_ink_order_prefix_with_white_at_1():
    for preset in PRESETS.values():
        assert list(preset.inks) == SPEC_INKS[preset.palette], preset.id
        assert preset.nominal[1] == (255, 255, 255), preset.id
        assert preset.measured[1] == (255, 255, 255), preset.id
        assert len(preset.measured) == len(SPEC_INKS[preset.palette]), preset.id


def test_spectra6_measured_is_white_balanced_epdoptimize():
    # epdoptimize spectra6 measured red #62201E divided by measured white #B9C7C9:
    # 0x62/0xB9*255 = 135.08, 0x20/0xC7*255 = 41.0, 0x1E/0xC9*255 = 38.06
    assert PRESETS["800x480-spectra6"].measured[2] == (135, 41, 38)
