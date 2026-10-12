"""US equities during NYSE hours (America/New_York). Up = green (black without green), down = red."""

from inkage.quotes import Quote, QuoteSource
from inkage.schedule import Schedule


class Stock(QuoteSource):
    market = "us"
    timezone = "America/New_York"
    schedule = Schedule.parse({"every": "5m", "window": {"time": "09:30-16:00", "days": "mon-fri"}, "fallback": "12h"})
    # symbols: tickers (case-insensitive); several make a watchlist. label: renames a lone symbol, ignored for several.
    # max_age_hours spans a holiday long weekend.
    params = {"symbols": ["AAPL"], "label": "", "max_age_hours": 120}
    up_inks = ("green",)
    down_inks = ("red",)

    def code(self, symbol: str) -> str:
        return "us" + symbol.upper()

    def label(self, symbol: str, quote: Quote) -> str:
        return symbol.upper()
