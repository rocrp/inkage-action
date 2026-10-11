"""US equity during NYSE hours (America/New_York). Up = green (black without green), down = red."""

from inkage.quotes import Quote, QuoteSource
from inkage.schedule import Schedule
from inkage.source import Context


class Stock(QuoteSource):
    market = "us"
    timezone = "America/New_York"
    schedule = Schedule.parse({"every": "5m", "window": {"time": "09:30-16:00", "days": "mon-fri"}, "fallback": "12h"})
    # max_age_hours spans a holiday long weekend.
    params = {"symbol": "AAPL", "label": "", "max_age_hours": 120}
    up_inks = ("green",)
    down_inks = ("red",)

    def code(self, ctx: Context) -> str:
        return "us" + ctx.params["symbol"].upper()

    def label(self, ctx: Context, quote: Quote) -> str:
        return ctx.params["symbol"].upper()
