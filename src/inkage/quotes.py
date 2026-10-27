"""Market quotes from Tencent's key-less endpoint, shared by the ``index`` and ``stock`` Sources.

``https://qt.gtimg.cn/q=<code>[,<code>...]`` (``sh000300``, ``usAAPL``) answers GBK text,
one ``v_<code>="f0~f1~...";`` line per requested code. Fields: 1 name, 2 code, 3 last, 4 previous close,
30 quote time, 31 change, 32 change %, 33 high, 34 low. China quote time is
``YYYYMMDDHHMMSS`` in Asia/Shanghai, US is ``YYYY-MM-DD HH:MM:SS`` in
America/New_York. A lone unknown code answers ``v_pv_none_match="1";``; among
several, an unknown code's line is simply absent. Both raise.

Params: ``symbols`` is the watchlist; the first symbol also fills the flat
single-quote keys. ``label`` renames it only when exactly one symbol is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Literal
from zoneinfo import ZoneInfo

import httpx

from inkage.panel import Panel
from inkage.source import Context, Source

TENCENT_URL = "https://qt.gtimg.cn/q={codes}"
_LINE = re.compile(r'^v_(\w+)="(.*)";?\s*$', re.DOTALL)
_TIME_FORMATS = {"cn": ("%Y%m%d%H%M%S", "Asia/Shanghai"), "us": ("%Y-%m-%d %H:%M:%S", "America/New_York")}

type Market = Literal["cn", "us"]


class QuoteError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class Quote:
    code: str
    name: str
    price: float
    prev_close: float
    change: float
    change_pct: float
    high: float
    low: float
    time: datetime


def parse_tencent(text: str, market: Market) -> Quote:
    """Parse one Tencent quote line; raise on unknown symbols or missing/garbled fields."""
    if not (m := _LINE.match(text.strip())):
        raise QuoteError(f"unrecognised Tencent response: {text[:80]!r}")
    code, body = m.groups()
    if code == "pv_none_match":
        raise QuoteError("Tencent: unknown symbol")
    f = body.split("~")
    if len(f) < 35:
        raise QuoteError(f"Tencent {code}: only {len(f)} fields")
    fmt, zone = _TIME_FORMATS[market]
    try:
        return Quote(
            code=f[2] or code,
            name=f[1],
            price=float(f[3]),
            prev_close=float(f[4]),
            change=float(f[31]),
            change_pct=float(f[32]),
            high=float(f[33]),
            low=float(f[34]),
            time=datetime.strptime(f[30], fmt).replace(tzinfo=ZoneInfo(zone)),
        )
    except ValueError as e:
        raise QuoteError(f"Tencent {code}: missing or malformed field ({e})") from None


def parse_tencent_many(text: str, codes: list[str], market: Market) -> list[Quote]:
    """Parse a multi-code response into one Quote per requested code, in request order; raise if any is absent."""
    lines = {}
    for line in filter(None, (ln.strip() for ln in text.splitlines())):
        if not (m := _LINE.match(line)):
            raise QuoteError(f"unrecognised Tencent response line: {line[:80]!r}")
        lines[m.group(1)] = line
    if "pv_none_match" in lines:
        raise QuoteError(f"Tencent: unknown symbol among {codes}")
    if missing := [c for c in codes if c not in lines]:
        raise QuoteError(f"Tencent: unknown symbol(s) {missing}, no line in response")
    return [parse_tencent(lines[c], market) for c in codes]


def check_quote(quote: Quote, now: datetime, max_age: timedelta) -> None:
    """Raise unless the quote is fresh enough and has a positive price."""
    if now - quote.time > max_age:
        raise QuoteError(f"{quote.code}: quote from {quote.time.isoformat()} is older than {max_age}")
    if quote.price <= 0:
        raise QuoteError(f"{quote.code}: non-positive price {quote.price}")


async def fetch_tencent(codes: list[str], market: Market) -> list[Quote]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(TENCENT_URL.format(codes=",".join(codes)))
        resp.raise_for_status()
        return parse_tencent_many(resp.content.decode("gbk"), codes, market)


def _direction(change: float) -> str:
    return "up" if change > 0 else ("down" if change < 0 else "flat")


class QuoteSource(Source):
    """Shared fetch + layout. Subclasses set ``market``, ``code()``, ``label()`` and the color convention."""

    sizes = ((800, 480), (250, 122), (528, 792))
    dither = "threshold"
    fields = ("name", "price", "change", "change_pct", "time", "quotes")
    market: ClassVar[Market]
    prev_label: ClassVar[str] = "Prev"
    # Ink for rising / falling prices, first available on the Panel wins.
    up_inks: ClassVar[tuple[str, ...]]
    down_inks: ClassVar[tuple[str, ...]]

    def code(self, symbol: str) -> str:
        """Tencent code for one configured symbol."""
        raise NotImplementedError

    def label(self, symbol: str, quote: Quote) -> str:
        """Display name for one symbol when no ``label`` param applies."""
        return quote.name

    def codes(self, ctx: Context) -> list[str]:
        symbols = ctx.params["symbols"]
        if not isinstance(symbols, list) or not symbols or not all(isinstance(s, str) and s for s in symbols):
            raise ValueError(f"{self.name}: symbols must be a non-empty list of strings, got {symbols!r}")
        return [self.code(s) for s in symbols]

    @property
    def template_dir(self) -> Path:
        return Path(__file__).parent / "quote_templates"

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        symbols = ctx.params["symbols"]
        found = await fetch_tencent(self.codes(ctx), self.market)
        max_age = timedelta(hours=ctx.params["max_age_hours"])
        rows = []
        for symbol, quote in zip(symbols, found, strict=True):
            check_quote(quote, ctx.now, max_age)
            rows.append(
                {
                    "name": self.label(symbol, quote),
                    "code": quote.code,
                    "price": f"{quote.price:,.2f}",
                    "change": f"{quote.change:+,.2f}",
                    "change_pct": f"{quote.change_pct:+.2f}%",
                    "direction": _direction(quote.change),
                    "high": f"{quote.high:,.2f}",
                    "low": f"{quote.low:,.2f}",
                    "prev_close": f"{quote.prev_close:,.2f}",
                    "time": quote.time.astimezone(ctx.tz).strftime("%Y-%m-%d %H:%M %Z"),
                }
            )
        if len(rows) == 1 and ctx.params["label"]:
            rows[0]["name"] = ctx.params["label"]
        return {**rows[0], "quotes": rows}

    def render(self, ctx: Context, panel: Panel, data: dict[str, Any]) -> str:
        hexes = panel.ink_hex

        def pick(inks: tuple[str, ...]) -> str:
            return hexes[next((i for i in inks if i in panel.inks), "black")]

        colors = {"up": pick(self.up_inks), "down": pick(self.down_inks), "flat": hexes["black"]}
        quotes = [{**q, "color": colors[q["direction"]]} for q in data["quotes"]]
        extra = {"color": colors[data["direction"]], "prev_label": self.prev_label, "quotes": quotes}
        return self.render_template(ctx, panel, {**data, **extra})
