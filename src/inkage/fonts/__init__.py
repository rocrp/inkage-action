"""Bundled, unmodified pixel fonts for built-in and consumer templates."""

from pathlib import Path

FONT_DIR = Path(__file__).parent
FONTS = {
    "Fusion Pixel 12": "fusion-pixel-12px-proportional-sc.otf",
    "Fusion Pixel 10": "fusion-pixel-10px-proportional-sc.otf",
    "Unifont": "unifont-18.0.01.otf",
    "Departure Mono": "departure-mono-1.500.otf",
}


def bundled_font_css() -> str:
    """Register packaged fonts without changing a template's typography."""
    rules = []
    for family, filename in FONTS.items():
        path = FONT_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"bundled font missing: {path}; reinstall inkage")
        rules.append(
            f'@font-face{{font-family:"{family}";src:url("{path.resolve().as_uri()}");'
            "font-weight:400;font-style:normal}"
        )
    return "".join(rules)
