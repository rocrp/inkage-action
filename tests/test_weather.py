"""weather Source: parsing a real captured Open-Meteo response, WMO labels, staleness, E2E render."""

import asyncio
import copy
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data

FIX = Path(__file__).parent / "fixtures" / "weather"
SH = ZoneInfo("Asia/Shanghai")
# Captured 2026-10-12: current.time "2026-10-12T11:00", utc_offset_seconds 28800.
OBSERVED = datetime(2026, 10, 12, 11, 0, tzinfo=SH)


def capture() -> dict:
    return json.loads((FIX / "open_meteo_shanghai.json").read_text())


def source_config(panel: str = "800x480-bwr", **params):
    return parse_config({"sources": {"weather": {"panels": [panel], **params}}}).sources[0]


def module(sc) -> dict:
    """The loaded source.py's globals (the loader does not register it in sys.modules)."""
    return sc.cls.fetch.__globals__


def fetched(monkeypatch, sc, raw: dict, now: datetime) -> dict:
    async def fake(latitude, longitude, units):
        return raw

    monkeypatch.setitem(module(sc), "fetch_open_meteo", fake)
    src = sc.cls()
    return src.check_data(asyncio.run(src.fetch(context_for(sc, now))))


def test_parse_capture(monkeypatch):
    # Read off the capture: 24.8 °C, 59 %, 7.8 km/h, code 0; daily codes 3,3,3,3,51,
    # max 26.5/26.6/23.9/25.3/27.1, min 17.0/18.6/17.9/16.4/19.5, precip 4/0/4/12/33 %.
    data = fetched(monkeypatch, source_config(), capture(), OBSERVED + timedelta(minutes=20))
    assert (data["label"], data["condition"], data["temp"], data["temp_unit"]) == ("Shanghai", "Clear", "25", "°C")
    assert (data["humidity"], data["wind"], data["updated"]) == ("59%", "8 km/h", "2026-10-12 11:00")
    days = data["days"]
    assert [d["weekday"] for d in days] == ["Mon", "Tue", "Wed", "Thu", "Fri"]  # 2026-10-12 is a Monday
    assert [d["condition"] for d in days] == ["Overcast"] * 4 + ["Light drizzle"]
    assert [d["high"] for d in days] == ["27°", "27°", "24°", "25°", "27°"]  # 26.5 rounds half-up
    assert [d["low"] for d in days] == ["17°", "19°", "18°", "16°", "20°"]
    assert [d["precip"] for d in days] == ["4%", "0%", "4%", "12%", "33%"]
    assert days[4]["date"] == "10/16"


def test_wmo_table_covers_the_documented_codes():
    # Codes listed under "WMO Weather interpretation codes" in the Open-Meteo forecast API docs.
    documented = {0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86}
    documented |= {95, 96, 99}
    weather = module(source_config())
    assert set(weather["WMO"]) == documented
    with pytest.raises(weather["WeatherError"], match="unknown WMO"):
        weather["condition"](4)


def test_stale_reading_raises(monkeypatch):
    sc = source_config()
    fetched(monkeypatch, sc, capture(), OBSERVED + timedelta(hours=2, minutes=59))
    with pytest.raises(RuntimeError, match="older than 3:00:00"):
        fetched(monkeypatch, sc, capture(), OBSERVED + timedelta(hours=3, minutes=1))


@pytest.mark.parametrize(
    ("damage", "match"),
    [
        (lambda r: r["current"].pop("temperature_2m"), r"current\.temperature_2m: missing"),
        (lambda r: r["current"].update(weather_code=None), "unknown WMO weather code None"),
        (lambda r: r["daily"]["temperature_2m_min"].__setitem__(2, None), r"daily\[2\]\.temperature_2m_min"),
        (lambda r: r["daily"]["time"].pop(), "fewer than 5 values for \\['time'\\]"),
        (lambda r: r.pop("current"), "missing or malformed field"),
    ],
)
def test_missing_or_null_field_raises(monkeypatch, damage, match):
    raw = copy.deepcopy(capture())
    damage(raw)
    with pytest.raises(RuntimeError, match=match):
        fetched(monkeypatch, source_config(), raw, OBSERVED)


def test_unknown_units_raise(monkeypatch):
    with pytest.raises(RuntimeError, match="units must be one of"):
        fetched(monkeypatch, source_config(units="kelvin"), capture(), OBSERVED)


@pytest.mark.parametrize(("panel", "size"), [("800x480-bwr", (800, 480)), ("250x122-bwr", (250, 122))])
def test_e2e_frame_size_and_palette_count(monkeypatch, panel, size):
    sc = source_config(panel)
    data = fetched(monkeypatch, sc, capture(), OBSERVED)

    async def go():
        async with Renderer() as r:
            return await frame_from_data(r, sc.cls(), context_for(sc, OBSERVED), sc.panels[0], sc, data)

    png = Image.open(io.BytesIO(png_bytes(asyncio.run(go()))))
    assert png.size == size
    assert len(png.getpalette() or []) == 3 * 3
