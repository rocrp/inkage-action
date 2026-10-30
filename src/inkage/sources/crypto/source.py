"""Crypto spot prices from Kraken's key-less public Ticker, one request for all symbols.

``https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD`` answers
``{"error": [], "result": {"XXBTZUSD": {...}, ...}}``. Result keys are Kraken's
canonical pair names: legacy assets carry X/Z prefixes (``XXBTZUSD``), newer ones
do not (``SOLUSD``). Per pair: ``c[0]`` last trade, ``o`` open since 00:00 UTC,
``h[1]``/``l[1]`` 24 h high/low. An unknown pair fills ``error``. Kraken is 24/7
and reports no quote time, so there is no staleness check.
"""

from typing import Any, ClassVar

import httpx

from inkage.panel import Panel
from inkage.schedule import Schedule
from inkage.source import Context, Source

KRAKEN_URL = "https://api.kraken.com/0/public/Ticker"
# Display symbol -> Kraken asset code, where they differ.
ALIASES = {"BTC": "XBT", "DOGE": "XDG"}
MAX_SYMBOLS = 6


class KrakenError(RuntimeError):
    pass


async def fetch_kraken(pairs: list[str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(KRAKEN_URL, params={"pair": ",".join(pairs)})
        resp.raise_for_status()
        return resp.json()


def _price(value: float) -> str:
    return f"{value:,.2f}" if value >= 1 else f"{value:,.4f}"


def parse_ticker(body: dict[str, Any], symbols: list[str], quote: str) -> list[dict[str, Any]]:
    """One row per symbol, in request order; raise on Kraken errors, missing pairs or bad prices."""
    if body.get("error"):
        raise KrakenError(f"Kraken: {body['error']}")
    result = body.get("result")
    if not isinstance(result, dict):
        raise KrakenError(f"Kraken: no result in {str(body)[:80]!r}")
    rows = []
    for sym in symbols:
        asset = ALIASES.get(sym, sym)
        key = next((k for k in (f"{asset}{quote}", f"X{asset}Z{quote}") if k in result), None)
        if key is None:
            raise KrakenError(f"Kraken: pair {asset}{quote} missing from result {sorted(result)}")
        t = result[key]
        try:
            last, open_, high, low = float(t["c"][0]), float(t["o"]), float(t["h"][1]), float(t["l"][1])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise KrakenError(f"Kraken {key}: missing or malformed field ({e!r})") from None
        if min(last, open_, high, low) <= 0:
            raise KrakenError(f"Kraken {key}: non-positive price in {t}")
        change = last - open_
        rows.append(
            {
                "symbol": sym,
                "price": _price(last),
                "change": f"{change:+,.2f}" if last >= 1 else f"{change:+,.4f}",
                "change_pct": f"{change / open_ * 100:+.2f}%",
                "direction": "up" if change > 0 else ("down" if change < 0 else "flat"),
                "high": _price(high),
                "low": _price(low),
            }
        )
    return rows


class Crypto(Source):
    schedule = Schedule.parse({"every": "5m"})
    dither = "threshold"
    params: ClassVar[dict[str, Any]] = {"symbols": ["BTC", "ETH", "SOL"], "quote": "USD"}
    fields = ("quote", "coins")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        symbols, quote = ctx.params["symbols"], ctx.params["quote"]
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= MAX_SYMBOLS:
            raise ValueError(f"crypto: symbols must be a list of 1..{MAX_SYMBOLS} tickers, got {symbols!r}")
        if not isinstance(quote, str) or not quote:
            raise ValueError(f"crypto: quote must be a currency code, got {quote!r}")
        symbols, quote = [str(s).upper() for s in symbols], quote.upper()
        body = await fetch_kraken([f"{ALIASES.get(s, s)}{quote}" for s in symbols])
        return {"quote": quote, "coins": parse_ticker(body, symbols, quote)}

    def render(self, ctx: Context, panel: Panel, data: dict[str, Any]) -> str:
        hexes = panel.ink_hex

        def pick(inks: tuple[str, ...]) -> str:
            return hexes[next((i for i in inks if i in panel.inks), "black")]

        colors = {"up": pick(("green",)), "down": pick(("red",)), "flat": hexes["black"]}
        coins = [{**c, "color": colors[c["direction"]]} for c in data["coins"]]
        return self.render_template(ctx, panel, {**data, "coins": coins})
