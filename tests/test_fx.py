"""fx Source: parsing a real captured Frankfurter series, staleness, missing rates, E2E render."""

import asyncio
import copy
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data

FIX = Path(__file__).parent / "fixtures" / "fx"
SH = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=SH)  # Monday; latest ECB fix is Friday 2026-10-09


def capture() -> dict:
    return json.loads((FIX / "frankfurter_usd_series.json").read_text())


def source_config(panel: str = "800x480-bwr", **params):
    return parse_config({"sources": {"fx": {"panels": [panel], "timezone": "Asia/Shanghai", **params}}}).sources[0]


def fetched(monkeypatch, sc, raw: dict, now: datetime = NOW) -> dict:
    async def fake(base, symbols, start):
        return raw

    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_frankfurter", fake)
    src = sc.cls()
    return src.check_data(asyncio.run(src.fetch(context_for(sc, now))))


def test_parse_capture_change_vs_previous_business_day(monkeypatch):
    # Read off the capture: 2026-10-09 vs 2026-10-08. Hand-computed:
    # CNY 6.6921 - 6.7023 = -0.0102 (-0.152 %); EUR 0.89238 - 0.89397 = -0.00159 (-0.178 %);
    # JPY 158.25 - 158.28 = -0.03 (-0.019 %); GBP 0.75641 - 0.75718 = -0.00077 (-0.102 %).
    data = fetched(monkeypatch, source_config(), capture())
    assert (data["base"], data["date"], data["prev_date"]) == ("USD", "2026-10-09", "2026-10-08")
    rows = [(r["symbol"], r["rate"], r["change"], r["change_pct"], r["direction"]) for r in data["rates"]]
    assert rows == [
        ("CNY", "6.6921", "-0.0102", "-0.15%", "down"),
        ("EUR", "0.89238", "-0.00159", "-0.18%", "down"),
        ("JPY", "158.25", "-0.03", "-0.02%", "down"),
        ("GBP", "0.75641", "-0.00077", "-0.10%", "down"),
    ]


def test_unchanged_rate_is_flat(monkeypatch):
    # CNY was 6.7046 on both 2026-10-06 and 2026-10-07 in the capture.
    raw = copy.deepcopy(capture())
    raw["rates"] = {d: raw["rates"][d] for d in ("2026-10-06", "2026-10-07")}
    data = fetched(monkeypatch, source_config(symbols=["CNY"]), raw, datetime(2026, 10, 8, 9, 0, tzinfo=SH))
    assert data["rates"] == [
        {"symbol": "CNY", "rate": "6.7046", "change": "+0.0000", "change_pct": "+0.00%", "direction": "flat"}
    ]


def test_stale_rates_raise(monkeypatch):
    sc = source_config()
    fetched(monkeypatch, sc, capture(), datetime(2026, 10, 14, 23, 0, tzinfo=SH))  # 5 days after the fix
    with pytest.raises(RuntimeError, match="older than 5 days"):
        fetched(monkeypatch, sc, capture(), datetime(2026, 10, 15, 0, 30, tzinfo=SH))


@pytest.mark.parametrize(
    ("damage", "symbols", "match"),
    [
        (lambda r: None, ["CNY", "CHF"], r"CHF: missing"),  # CHF not in the capture
        (lambda r: r["rates"]["2026-10-08"].pop("JPY"), ["JPY"], r"JPY: missing"),
        (lambda r: r["rates"]["2026-10-09"].update(EUR=None), ["EUR"], r"EUR: missing"),
        (lambda r: [r["rates"].pop(d) for d in list(r["rates"])[:-1]], ["CNY"], "at least 2 business days"),
        (lambda r: r.update(base="EUR"), ["CNY"], "base 'EUR'"),
    ],
)
def test_missing_rate_raises(monkeypatch, damage, symbols, match):
    raw = copy.deepcopy(capture())
    damage(raw)
    with pytest.raises(RuntimeError, match=match):
        fetched(monkeypatch, source_config(symbols=symbols), raw)


def test_too_many_symbols_raise(monkeypatch):
    with pytest.raises(RuntimeError, match=r"1\.\.6 currency codes"):
        fetched(monkeypatch, source_config(symbols=["CNY", "EUR", "JPY", "GBP", "CHF", "AUD", "CAD"]), capture())


@pytest.mark.parametrize(("panel", "size"), [("800x480-bwr", (800, 480)), ("250x122-bwr", (250, 122))])
def test_e2e_frame_size_and_palette_count(monkeypatch, panel, size):
    sc = source_config(panel)
    data = fetched(monkeypatch, sc, capture())

    async def go():
        async with Renderer() as r:
            return await frame_from_data(r, sc.cls(), context_for(sc, NOW), sc.panels[0], sc, data)

    png = Image.open(io.BytesIO(png_bytes(asyncio.run(go()))))
    assert png.size == size
    assert len(png.getpalette() or []) == 3 * 3
