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
from inkage.quotes import QuoteError, check_quote, parse_tencent, parse_tencent_many
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


def test_parse_multi_capture():
    # Values read off the capture (2026-10-12 11:10 Shanghai, mid-session; US from the 2026-10-09 close).
    us = parse_tencent_many(text("tencent_multi.txt"), ["usAAPL", "usNVDA"], "us")
    assert [(q.code, q.name, q.price, q.change_pct) for q in us] == [
        ("AAPL.OQ", "苹果", 336.64, -1.11),
        ("NVDA.OQ", "英伟达", 229.28, -0.52),
    ]
    cn = parse_tencent_many(text("tencent_multi.txt"), ["sh000001", "sh000300"], "cn")  # request order kept
    assert [(q.code, q.name, q.price, q.change) for q in cn] == [
        ("000001", "上证指数", 3810.89, -2.90),
        ("000300", "沪深300", 4313.43, -3.82),
    ]
    assert cn[0].time == datetime(2026, 10, 12, 11, 10, 45, tzinfo=SH)


def test_multi_missing_code_raises():
    # Tencent drops unknown codes from a multi-code answer (seen live for q=sh000300,zzzzz9,usAAPL).
    with pytest.raises(QuoteError, match="sh000905"):
        parse_tencent_many(text("tencent_multi.txt"), ["sh000300", "sh000905"], "cn")
    one_sh = text("tencent_sh000300.txt").strip()
    with pytest.raises(QuoteError, match="unknown symbol"):
        parse_tencent_many(one_sh + "\n" + text("tencent_missing.txt"), ["sh000300", "sh000001"], "cn")


def test_stale_quote_raises():
    q = parse_tencent(text("tencent_sh000300.txt"), "cn")
    check_quote(q, q.time + timedelta(hours=72), timedelta(hours=240))  # weekend: fine
    with pytest.raises(QuoteError, match="older than"):
        check_quote(q, q.time + timedelta(hours=241), timedelta(hours=240))


def source_config(source: str, panel: str, **params):
    return parse_config({"sources": {source: {"panels": [panel], **params}}}).sources[0]


def fetched(monkeypatch, sc, fixture: str, now: datetime) -> dict:
    async def fake(codes: list[str], market):
        return parse_tencent_many(text(fixture), codes, market)

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
    sc = source_config("stock", "800x480-bwr", symbols=["aapl"])
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


def test_index_watchlist_renders_table(monkeypatch):
    sc = source_config("index", "800x480-bwr", symbols=["sh000300", "sh000001"], label="ignored")
    now = datetime(2026, 10, 12, 11, 30, tzinfo=SH)
    src = sc.cls()
    data = src.check_data(fetched(monkeypatch, sc, "tencent_multi.txt", now))
    assert [q["name"] for q in data["quotes"]] == ["沪深300", "上证指数"]
    assert (data["name"], data["price"], data["change"]) == ("沪深300", "4,313.43", "-3.82")
    ctx = context_for(sc, now)
    html = src.render(ctx, sc.panels[0], data)
    assert isinstance(html, str)
    assert "沪深300" in html and "上证指数" in html and "<table>" in html

    async def go():
        async with Renderer() as r:
            return await frame_from_data(r, src, ctx, sc.panels[0], sc, data)

    frame = asyncio.run(go())
    assert frame.size == (800, 480)
    assert (palette := frame.getpalette()) is not None and len(palette) // 3 == 3


@pytest.mark.parametrize("symbols", [[], "sh000300", ["sh000300", 1]])
def test_bad_symbols_raise(monkeypatch, symbols):
    sc = source_config("index", "800x480-bwr", symbols=symbols)
    with pytest.raises(ValueError, match="symbols"):
        fetched(monkeypatch, sc, "tencent_multi.txt", datetime(2026, 10, 12, 11, 30, tzinfo=SH))
