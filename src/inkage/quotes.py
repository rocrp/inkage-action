"""Market quotes from Tencent's key-less endpoint, shared by the ``index`` and ``stock`` Sources.

``https://qt.gtimg.cn/q=<code>`` (``sh000300``, ``usAAPL``) answers GBK text
``v_<code>="f0~f1~...";``. Fields: 1 name, 2 code, 3 last, 4 previous close,
30 quote time, 31 change, 32 change %, 33 high, 34 low. China quote time is
``YYYYMMDDHHMMSS`` in Asia/Shanghai, US is ``YYYY-MM-DD HH:MM:SS`` in
America/New_York. An unknown code answers ``v_pv_none_match="1";``.
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

TENCENT_URL = "https://qt.gtimg.cn/q={code}"
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


def check_quote(quote: Quote, now: datetime, max_age: timedelta) -> None:
    """Raise unless the quote is fresh enough and has a positive price."""
    if now - quote.time > max_age:
        raise QuoteError(f"{quote.code}: quote from {quote.time.isoformat()} is older than {max_age}")
    if quote.price <= 0:
        raise QuoteError(f"{quote.code}: non-positive price {quote.price}")


async def fetch_tencent(code: str, market: Market) -> Quote:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(TENCENT_URL.format(code=code))
        resp.raise_for_status()
        return parse_tencent(resp.content.decode("gbk"), market)


class QuoteSource(Source):
    """Shared fetch + layout. Subclasses set ``market``, ``code()`` and the color convention."""

    sizes = ((800, 480), (250, 122))
    dither = "threshold"
    fields = ("name", "price", "change", "change_pct", "time")
    market: ClassVar[Market]
    prev_label: ClassVar[str] = "Prev"
    # Ink for rising / falling prices, first available on the Panel wins.
    up_inks: ClassVar[tuple[str, ...]]
    down_inks: ClassVar[tuple[str, ...]]

    def code(self, ctx: Context) -> str:
        raise NotImplementedError

    def label(self, ctx: Context, quote: Quote) -> str:
        return quote.name

    @property
    def template_dir(self) -> Path:
        return Path(__file__).parent / "quote_templates"

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        quote = await fetch_tencent(self.code(ctx), self.market)
        check_quote(quote, ctx.now, timedelta(hours=ctx.params["max_age_hours"]))
        local = quote.time.astimezone(ctx.tz)
        return {
            "name": ctx.params["label"] or self.label(ctx, quote),
            "code": quote.code,
            "price": f"{quote.price:,.2f}",
            "change": f"{quote.change:+,.2f}",
            "change_pct": f"{quote.change_pct:+.2f}%",
            "direction": "up" if quote.change > 0 else ("down" if quote.change < 0 else "flat"),
            "high": f"{quote.high:,.2f}",
            "low": f"{quote.low:,.2f}",
            "prev_close": f"{quote.prev_close:,.2f}",
            "time": local.strftime("%Y-%m-%d %H:%M %Z"),
        }

    def render(self, ctx: Context, panel: Panel, data: dict[str, Any]) -> str:
        hexes = panel.ink_hex

        def pick(inks: tuple[str, ...]) -> str:
            return hexes[next((i for i in inks if i in panel.inks), "black")]

        colors = {"up": pick(self.up_inks), "down": pick(self.down_inks), "flat": hexes["black"]}
        extra = {"color": colors[data["direction"]], "prev_label": self.prev_label}
        return self.render_template(ctx, panel, {**data, **extra})
