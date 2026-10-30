"""crypto Source: real Kraken Ticker capture read by hand, error paths, colour by direction, E2E."""

import asyncio
import copy
import io
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data

FIX = Path(__file__).parent / "fixtures" / "crypto"
NOW = datetime(2026, 10, 12, 11, 10, tzinfo=ZoneInfo("Asia/Shanghai"))  # capture time
TICKER = json.loads((FIX / "kraken_ticker.json").read_text())


def source_config(panel: str, **params):
    return parse_config({"sources": {"crypto": {"panels": [panel], **params}}}).sources[0]


def fetched(monkeypatch, sc, body: dict) -> tuple[dict, list[list[str]]]:
    """Fetch with Kraken answering ``body``; also return the pair lists requested."""
    calls: list[list[str]] = []

    async def fake(pairs: list[str]) -> dict:
        calls.append(pairs)
        return body

    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_kraken", fake)
    return asyncio.run(sc.cls().fetch(context_for(sc, NOW))), calls


def test_parse_kraken_capture(monkeypatch):
    # Read off kraken_ticker.json. Result order is ETH, SOL, BTC; rows follow the configured symbols.
    # BTC: c 83621.0, o 83675.6 -> -54.60, -54.6/83675.6 = -0.065%; h[1] 84125.5, l[1] 82716.1.
    # ETH: 2542.69 - 2534.35 = +8.34, +0.329%.  SOL: 111.64 - 111.23 = +0.41, +0.369%.
    data, calls = fetched(monkeypatch, source_config("800x480-bwr"), TICKER)
    assert calls == [["XBTUSD", "ETHUSD", "SOLUSD"]]  # BTC is XBT on Kraken
    assert data["quote"] == "USD"
    btc, eth, sol = data["coins"]
    assert btc == {
        "symbol": "BTC",
        "price": "83,621.00",
        "change": "-54.60",
        "change_pct": "-0.07%",
        "direction": "down",
        "high": "84,125.50",
        "low": "82,716.10",
    }
    assert (eth["symbol"], eth["price"], eth["change"], eth["change_pct"], eth["direction"]) == (
        "ETH",
        "2,542.69",
        "+8.34",
        "+0.33%",
        "up",
    )
    assert (sol["symbol"], sol["price"], sol["change"], sol["change_pct"]) == ("SOL", "111.64", "+0.41", "+0.37%")


def test_kraken_error_list_raises(monkeypatch):
    body = json.loads((FIX / "kraken_unknown.json").read_text())  # real answer to pair=XBTUSD,FOOUSD
    with pytest.raises(RuntimeError, match="Unknown asset pair"):
        fetched(monkeypatch, source_config("800x480-bwr", symbols=["BTC", "FOO"]), body)


def test_missing_pair_raises(monkeypatch):
    sc = source_config("800x480-bwr", symbols=["BTC", "XRP"])
    with pytest.raises(RuntimeError, match="XRPUSD missing"):
        fetched(monkeypatch, sc, TICKER)


def test_non_positive_price_raises(monkeypatch):
    body = copy.deepcopy(TICKER)
    body["result"]["SOLUSD"]["c"][0] = "0.00000"
    with pytest.raises(RuntimeError, match="non-positive"):
        fetched(monkeypatch, source_config("800x480-bwr"), body)


def test_too_many_symbols_raises(monkeypatch):
    sc = source_config("800x480-bwr", symbols=["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "DOT"])
    with pytest.raises(ValueError, match=r"1\.\.6"):
        fetched(monkeypatch, sc, TICKER)


def change_colors(html: object) -> list[str]:
    assert isinstance(html, str)
    return re.findall(r'class="chg" style="color: (#[0-9a-f]{6})"', html)


def test_down_red_up_green_or_black(monkeypatch):
    sc = source_config("800x480-bwr")
    data, _ = fetched(monkeypatch, sc, TICKER)
    ctx = context_for(sc, NOW)
    # BTC down, ETH and SOL up; BWR has no green, so up is black.
    assert change_colors(sc.cls().render(ctx, sc.panels[0], data)) == ["#ff0000", "#000000", "#000000"]
    s6 = source_config("800x480-spectra6")
    assert change_colors(s6.cls().render(ctx, s6.panels[0], data)) == ["#ff0000", "#00ff00", "#00ff00"]


@pytest.mark.parametrize(("panel", "size"), [("800x480-bwr", (800, 480)), ("250x122-bwr", (250, 122))])
def test_e2e_frame(monkeypatch, panel, size):
    sc = source_config(panel)
    data, _ = fetched(monkeypatch, sc, TICKER)
    src, ctx = sc.cls(), context_for(sc, NOW)

    async def go():
        async with Renderer() as r:
            return await frame_from_data(r, src, ctx, sc.panels[0], sc, src.check_data(data))

    png = Image.open(io.BytesIO(png_bytes(asyncio.run(go()))))
    assert png.size == size
    assert len(png.getpalette() or []) == 3 * 3
