"""calendar Source: lunar data against published dates; E2E through headless Chromium."""

import asyncio
import io
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PIL import Image

from inkage.config import ConfigError, parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data
from inkage.source import IncompleteData, Source, load_sources

SH = ZoneInfo("Asia/Shanghai")
FIXED = datetime(2026, 9, 25, 8, 0, tzinfo=SH)  # Mid-Autumn Festival 2026


def lunar_info(day: date) -> dict:
    cal = load_sources()["calendar"]
    from inkage.source import Context

    return asyncio.run(cal().fetch(Context(now=datetime.combine(day, datetime.min.time(), SH), tz=SH)))


@pytest.mark.parametrize(
    ("day", "month", "lday", "festival"),
    [
        (date(2026, 2, 17), "正月", "初一", "春节"),  # Spring Festival 2026
        (date(2026, 9, 25), "八月", "十五", "中秋节"),  # Mid-Autumn 2026
    ],
)
def test_lunar_date_matches_published_holidays(day, month, lday, festival):
    info = lunar_info(day)
    assert (info["lunar_month"], info["lunar_day"]) == (month, lday)
    assert festival in info["festivals"]


def test_solar_term_on_its_day():
    assert lunar_info(date(2026, 10, 8))["solar_term"] == "寒露"  # Cold Dew 2026-10-08


def render(panel_id: str) -> tuple[Image.Image, Image.Image]:
    """Return (raw RGB render before dithering, Frame)."""
    sc = parse_config({"sources": {"calendar": {"panels": [panel_id]}}}).sources[0]

    async def go():
        ctx = context_for(sc, FIXED)
        src = sc.cls()
        data = src.check_data(await src.fetch(ctx))
        async with Renderer() as r:
            raw = await r.html_to_image(src.render(ctx, sc.panels[0], data), *sc.panels[0].size, src.template_dir)
            return raw, await frame_from_data(r, src, ctx, sc.panels[0], sc, data)

    return asyncio.run(go())


@pytest.mark.parametrize(("panel", "size", "n"), [("800x480-bwr", (800, 480), 3), ("250x122-bwr", (250, 122), 3)])
def test_e2e_frame_size_and_palette_count(panel, size, n):
    raw, frame = render(panel)
    png = Image.open(io.BytesIO(png_bytes(frame)))
    assert png.size == size
    assert len(png.getpalette()) == 3 * n
    # Text is hard-edged before dithering: the raw render holds only the inks the template uses.
    colors = {tuple(c) for c in np.asarray(raw).reshape(-1, 3)}
    assert colors <= {(0, 0, 0), (255, 255, 255), (255, 0, 0)}, f"{len(colors)} distinct colors"


def test_unsupported_size_fails_at_validation():
    with pytest.raises(ConfigError, match="does not support size 400x300"):
        parse_config({"sources": {"calendar": {"panels": ["400x300-bwr"]}}})


def test_incomplete_fetch_raises_instead_of_rendering():
    class Half(Source):
        name = "half"
        fields = ("price", "change")

    with pytest.raises(IncompleteData, match="change"):
        Half.check_data({"price": 1.0, "change": None})
