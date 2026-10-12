"""astro Source: sun times and moon phases against timeanddate.com's published tables; E2E render."""

import asyncio
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data

SH = ZoneInfo("Asia/Shanghai")
TOL = timedelta(minutes=2)


def source_config(panel: str = "800x480-bwr", timezone: str = "Asia/Shanghai", **params):
    return parse_config({"sources": {"astro": {"panels": [panel], "timezone": timezone, **params}}}).sources[0]


def fetched(day: date, **params) -> dict:
    sc = source_config(**params)
    src = sc.cls()
    return src.check_data(asyncio.run(src.fetch(context_for(sc, datetime.combine(day, time(12), sc.tz)))))


@pytest.mark.parametrize(
    ("day", "sunrise", "sunset"),
    [
        # https://www.timeanddate.com/sun/china/shanghai?month=6&year=2026, row 21 Jun 2026 (solstice):
        # sunrise 04:50, sunset 19:01, day length 14:10:46.
        (date(2026, 6, 21), time(4, 50), time(19, 1)),
        # Same site, Shanghai today (12 Oct 2026): 05:54 - 17:26.
        (date(2026, 10, 12), time(5, 54), time(17, 26)),
    ],
)
def test_sun_times_match_published_table(day, sunrise, sunset):
    data = fetched(day)
    for got, want in ((data["sunrise"], sunrise), (data["sunset"], sunset)):
        assert got.tzinfo is not None and got.utcoffset() == timedelta(hours=8)
        assert abs(got - datetime.combine(day, want, SH)) <= TOL, (got, want)
    assert data["dawn"] < data["sunrise"] < data["noon"] < data["sunset"] < data["dusk"]


def test_day_length_on_solstice():
    assert fetched(date(2026, 6, 21))["day_length"] in {"14h 09m", "14h 10m", "14h 11m", "14h 12m"}  # 14:10:46


@pytest.mark.parametrize(
    ("day", "name", "lit_range"),
    [
        # https://www.timeanddate.com/moon/phases/china/shanghai?year=2026 (Shanghai local times):
        # new moon 10 Oct 23:50, first quarter 19 Oct 00:12, full moon 26 Oct 12:11.
        (date(2026, 10, 11), "New Moon", (0.0, 0.05)),
        (date(2026, 10, 19), "First Quarter", (0.4, 0.65)),
        (date(2026, 10, 26), "Full Moon", (0.95, 1.0)),
    ],
)
def test_moon_phase_matches_published_phases(day, name, lit_range):
    data = fetched(day)
    assert data["moon_phase"] == name
    assert lit_range[0] <= data["moon_lit"] <= lit_range[1]


def test_polar_night_raises():
    # Longyearbyen (78.2 N) is in polar night at the December solstice: no sunrise exists.
    with pytest.raises(ValueError, match="never reaches"):
        fetched(
            date(2026, 12, 21), latitude=78.22, longitude=15.65, label="Longyearbyen", timezone="Arctic/Longyearbyen"
        )


def test_zone_far_from_location_raises():
    # Captured failure: Shanghai rendered in UTC gave sunrise 2026-06-20 20:50Z after sunset 11:01Z (day length -10h).
    with pytest.raises(ValueError, match="out of order"):
        fetched(date(2026, 6, 21), timezone="UTC")


@pytest.mark.parametrize(("panel", "size"), [("800x480-bwr", (800, 480)), ("250x122-bwr", (250, 122))])
def test_e2e_frame_size_and_palette_count(panel, size):
    sc = source_config(panel)
    now = datetime(2026, 10, 19, 0, 5, tzinfo=SH)
    ctx = context_for(sc, now)

    async def go():
        src = sc.cls()
        data = src.check_data(await src.fetch(ctx))
        async with Renderer() as r:
            return await frame_from_data(r, src, ctx, sc.panels[0], sc, data)

    png = Image.open(io.BytesIO(png_bytes(asyncio.run(go()))))
    assert png.size == size
    assert len(png.getpalette() or []) == 3 * 3
