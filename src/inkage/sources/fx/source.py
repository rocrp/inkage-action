"""FX: ECB reference rates from Frankfurter (key-less), each with its change vs the previous business day.

``https://api.frankfurter.dev/v1/<start>..?base=USD&symbols=CNY,EUR`` answers
``{"base", "start_date", "end_date", "rates": {"YYYY-MM-DD": {"CNY": 6.69, ...}}}``
with one entry per ECB business day; the last entry is the latest rate.
(``api.frankfurter.app`` 301-redirects here.)
"""

import math
from datetime import date, timedelta
from typing import Any

import httpx

from inkage.schedule import Schedule
from inkage.source import Context, Source

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/{start}.."
LOOKBACK = timedelta(days=10)  # spans a weekend plus a long holiday
MAX_AGE = timedelta(days=5)
MAX_SYMBOLS = 6  # what the 800x480 layout fits


class FxError(RuntimeError):
    pass


class Fx(Source):
    schedule = Schedule.parse({"every": "6h"})
    dither = "threshold"
    params = {"base": "USD", "symbols": ["CNY", "EUR", "JPY", "GBP"]}
    fields = ("base", "date", "prev_date", "rates")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        base, symbols = ctx.params["base"], ctx.params["symbols"]
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= MAX_SYMBOLS:
            raise FxError(f"symbols must be a list of 1..{MAX_SYMBOLS} currency codes, got {symbols!r}")
        today = ctx.local_now.date()
        raw = await fetch_frankfurter(base, symbols, today - LOOKBACK)
        return parse_series(raw, base, symbols, today)


async def fetch_frankfurter(base: str, symbols: list[str], start: date) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            FRANKFURTER_URL.format(start=start.isoformat()), params={"base": base, "symbols": ",".join(symbols)}
        )
        resp.raise_for_status()
        return resp.json()


def _decimals(rate: float) -> int:
    """Five significant digits, as the ECB publishes them (6.6921, 0.89238, 158.25)."""
    return max(0, 4 - math.floor(math.log10(rate)))


def parse_series(raw: dict[str, Any], base: str, symbols: list[str], today: date) -> dict[str, Any]:
    """Latest rate per symbol and its change vs the previous business day; raise if stale or incomplete."""
    if raw.get("base") != base:
        raise FxError(f"Frankfurter: base {raw.get('base')!r}, expected {base!r}")
    series = raw.get("rates")
    if not isinstance(series, dict) or len(series) < 2:
        raise FxError(f"Frankfurter: need at least 2 business days of rates, got {series!r:.80}")
    prev_day, last_day = sorted(series)[-2:]
    latest, prev = series[last_day], series[prev_day]
    if today - date.fromisoformat(last_day) > MAX_AGE:
        raise FxError(f"Frankfurter: latest rates from {last_day} are older than {MAX_AGE.days} days")
    rates = []
    for sym in symbols:
        now_rate, then = latest.get(sym), prev.get(sym)
        if not all(isinstance(v, int | float) and v > 0 for v in (now_rate, then)):
            raise FxError(
                f"Frankfurter {sym}: missing or non-positive rate ({prev_day}: {then!r}, {last_day}: {now_rate!r})"
            )
        n = _decimals(now_rate)
        change = now_rate - then
        rates.append(
            {
                "symbol": sym,
                "rate": f"{now_rate:.{n}f}",
                "change": f"{change:+.{n}f}",
                "change_pct": f"{change / then * 100:+.2f}%",
                "direction": "up" if change > 0 else ("down" if change < 0 else "flat"),
            }
        )
    return {"base": base, "date": last_day, "prev_date": prev_day, "rates": rates}
