"""China market index (CSI 300 by default) during Shanghai trading hours. Up = red, per Chinese convention."""

from inkage.quotes import QuoteSource
from inkage.schedule import Schedule
from inkage.source import Context


class Index(QuoteSource):
    market = "cn"
    timezone = "Asia/Shanghai"
    schedule = Schedule.parse({"every": "5m", "window": {"time": "09:30-15:00", "days": "mon-fri"}, "fallback": "6h"})
    # symbol: Tencent code, exchange prefix included (sh000300 = CSI 300, sh000001 = SSE Composite).
    # max_age_hours: older quotes raise; long enough to span Golden Week.
    params = {"symbol": "sh000300", "label": "", "max_age_hours": 240}
    prev_label = "昨收"
    up_inks = ("red",)
    down_inks = ("green",)

    def code(self, ctx: Context) -> str:
        return ctx.params["symbol"]
