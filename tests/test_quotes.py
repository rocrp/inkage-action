"""index / stock Sources: parsing real captured Tencent responses, staleness, color convention."""

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from inkage import quotes
from inkage.config import parse_config
from inkage.quotes import QuoteError, check_fresh, parse_tencent
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data

FIX = Path(__file__).parent / "fixtures" / "quotes"
SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")


def text(name: str) -> str:
    return (FIX / name).read_bytes().decode("gbk")


def test_parse_csi300_capture():
    # Values read off the capture (2026-10-09 close): 4317.25, prev 4310.28, +6.97, +0.16%.
    q = parse_tencent(text("tencent_sh000300.txt"), "cn")
    assert (q.name, q.code) == ("沪深300", "000300")
    assert (q.price, q.prev_close, q.change, q.change_pct) == (4317.25, 4310.28, 6.97, 0.16)
    assert (q.high, q.low) == (4330.74, 4239.74)
    assert q.time == datetime(2026, 10, 9, 16, 14, 12, tzinfo=SH)


def test_parse_sse_capture():
    q = parse_tencent(text("tencent_sh000001.txt"), "cn")
    assert (q.name, q.price, q.change, q.change_pct) == ("上证指数", 3813.79, 1.89, 0.05)


def test_parse_us_capture_in_new_york_time():
    q = parse_tencent(text("tencent_usAAPL.txt"), "us")
    assert (q.code, q.price, q.prev_close, q.change, q.change_pct) == ("AAPL.OQ", 336.64, 340.42, -3.78, -1.11)
    assert q.time == datetime(2026, 10, 9, 16, 0, 1, tzinfo=NY)
    assert q.time.utcoffset() == timedelta(hours=-4)  # EDT


def test_unknown_symbol_raises():
    with pytest.raises(QuoteError, match="unknown symbol"):
        parse_tencent(text("tencent_missing.txt"), "cn")


def test_missing_field_raises():
    fields = text("tencent_sh000300.txt").split("~")
    fields[3] = ""  # blank last price
    with pytest.raises(QuoteError, match="missing or malformed"):
        parse_tencent("~".join(fields), "cn")
    with pytest.raises(QuoteError, match="fields"):
        parse_tencent('v_sh000300="1~沪深300~000300~4317.25";', "cn")


def test_stale_quote_raises():
    q = parse_tencent(text("tencent_sh000300.txt"), "cn")
    check_fresh(q, q.time + timedelta(hours=72), timedelta(hours=240))  # weekend: fine
    with pytest.raises(QuoteError, match="older than"):
        check_fresh(q, q.time + timedelta(hours=241), timedelta(hours=240))


def source_config(source: str, panel: str, **params):
    return parse_config({"sources": {source: {"panels": [panel], **params}}}).sources[0]


def fetched(monkeypatch, sc, fixture: str, now: datetime) -> dict:
    async def fake(code: str, market):
        return parse_tencent(text(fixture), market)

    monkeypatch.setattr(quotes, "fetch_tencent", fake)
    return asyncio.run(sc.cls().fetch(context_for(sc, now)))


def chg_color(html: str) -> str:
    return re.search(r"\.chg \{[^}]*color: (#[0-9a-f]{6})", html).group(1)


def test_staleness_bound_is_configurable(monkeypatch):
    sc = source_config("index", "800x480-bwr", max_age_hours=1)
    with pytest.raises(QuoteError, match="older than"):
        fetched(monkeypatch, sc, "tencent_sh000300.txt", datetime(2026, 10, 9, 18, 0, tzinfo=SH))


def test_index_up_is_red_and_frame_uses_red_ink(monkeypatch):
    sc = source_config("index", "800x480-bwr")
    now = datetime(2026, 10, 9, 17, 0, tzinfo=SH)
    data = fetched(monkeypatch, sc, "tencent_sh000300.txt", now)
    assert (data["price"], data["change"], data["change_pct"]) == ("4,317.25", "+6.97", "+0.16%")
    ctx = context_for(sc, now)
    assert chg_color(sc.cls().render(ctx, sc.panels[0], data)) == "#ff0000"

    async def go():
        async with Renderer() as r:
            return await frame_from_data(r, sc.cls(), ctx, sc.panels[0], sc, data)

    assert (np.asarray(asyncio.run(go())) == 2).sum() > 500  # red ink index carries the change line


def test_stock_down_red_up_green_or_black(monkeypatch):
    now = datetime(2026, 10, 9, 17, 0, tzinfo=NY)
    sc = source_config("stock", "800x480-bwr", symbol="aapl")
    data = fetched(monkeypatch, sc, "tencent_usAAPL.txt", now)
    assert (data["name"], data["time"]) == ("AAPL", "2026-10-09 16:00 EDT")
    ctx = context_for(sc, now)
    assert chg_color(sc.cls().render(ctx, sc.panels[0], data)) == "#ff0000"  # down = red
    up = {**data, "direction": "up"}
    assert chg_color(sc.cls().render(ctx, sc.panels[0], up)) == "#000000"  # no green ink on BWR
    s6 = source_config("stock", "800x480-spectra6")
    assert chg_color(s6.cls().render(ctx, s6.panels[0], up)) == "#00ff00"


def test_stock_schedule_in_new_york():
    sc = source_config("stock", "800x480-bwr")
    assert sc.tz.key == "America/New_York"
    # 14:00Z on 2026-11-02 is 09:00 EST: pre-open, so a 5-minute-old Frame is not due.
    now = datetime(2026, 11, 2, 14, 0, tzinfo=ZoneInfo("UTC"))
    assert not sc.schedule.is_due(now, now - timedelta(minutes=5), sc.tz)[0]
    assert sc.schedule.is_due(now + timedelta(minutes=35), now + timedelta(minutes=30), sc.tz)[0]
