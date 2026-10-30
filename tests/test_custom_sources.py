"""Custom Sources from a consumer sources dir: template-only, Python fetch, collision, fonts."""

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from inkage.config import ConfigError, parse_config
from inkage.run import run

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=ZoneInfo("UTC"))


def run_site(raw: dict, out: Path, fonts_dir: Path | None = None) -> np.ndarray:
    cfg = parse_config(raw, sources_dir=FIXTURES / "sources")
    result = asyncio.run(run(cfg, lambda _p: None, out, NOW, fonts_dir=fonts_dir))
    assert result.ok, result.errors
    from PIL import Image

    sc = cfg.sources[0]
    return np.asarray(Image.open(out / sc.id / f"{sc.panels[0].id}.png"))


def test_template_only_source_renders_through_run(tmp_path):
    raw = {"sources": {"tmpl": {"panels": ["250x122-bw"], "schedule": {"every": "1h"}}}}
    px = run_site(raw, tmp_path)
    assert px.shape == (122, 250)
    assert (px[20:60, 20:100] == 0).all()  # the black box from the template
    assert px[100, 10] == 1


def test_template_only_source_needs_schedule():
    with pytest.raises(ConfigError, match=r"sources\.tmpl\.schedule"):
        parse_config({"sources": {"tmpl": {"panels": ["250x122-bw"]}}}, sources_dir=FIXTURES / "sources")


def test_python_source_custom_fetch(tmp_path):
    px = run_site({"sources": {"pyfetch": {"panels": ["250x122-bw"], "bars": 4}}}, tmp_path)
    # Bars at x = 0, 20, 40, 60 (10px wide); none at 80.
    assert all((px[:, x : x + 10] == 0).all() for x in (0, 20, 40, 60))
    assert (px[:, 80:90] == 1).all()


def test_custom_source_named_like_builtin_rejected():
    with pytest.raises(ConfigError, match=r"'calendar'.*collides"):
        parse_config({"sources": {"calendar": {"panels": ["250x122-bw"]}}}, sources_dir=FIXTURES / "collide")


def blocky_font(path: Path) -> None:
    """A font whose 'A' is a solid 1000x1000-unit square."""
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({ord("A"): "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 1000))
    pen.lineTo((1000, 1000))
    pen.lineTo((1000, 0))
    pen.closePath()
    square = pen.glyph()
    fb.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "A": square})
    fb.setupHorizontalMetrics({".notdef": (0, 0), "A": (1000, 0)})
    fb.setupHorizontalHeader(ascent=1000, descent=0)
    fb.setupNameTable({"familyName": "Blocky", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=1000, sTypoDescender=0, usWinAscent=1000, usWinDescent=0)
    fb.setupPost()
    fb.save(str(path))


def test_fonts_dir_available_to_templates(tmp_path):
    raw = {"sources": {"tmpl": {"panels": ["250x122-bw"], "schedule": {"every": "1h"}}}}
    without = run_site(raw, tmp_path / "a")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    blocky_font(fonts / "Blocky.ttf")
    with_font = run_site(raw, tmp_path / "b", fonts_dir=fonts)
    # 80px font-size 'A' in Blocky is an 80x80 solid square starting at x=140.
    glyph = with_font[10:90, 140:220]
    assert (glyph == 0).mean() > 0.95
    assert (without[10:90, 140:220] == 0).mean() < 0.5  # a serif 'A' is mostly white
