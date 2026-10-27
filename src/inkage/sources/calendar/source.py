"""Calendar: Gregorian date, weekday, Chinese lunar date, solar term, month grid."""

import calendar as pycal
from datetime import date, timedelta
from typing import Any

from lunar_python import Solar

from inkage.schedule import Schedule
from inkage.source import Context, Source

WEEKDAYS_ZH = ("一", "二", "三", "四", "五", "六", "日")


class Calendar(Source):
    sizes = ((800, 480), (250, 122), (528, 792))
    schedule = Schedule.parse({"at": ["00:05"]})
    dither = "threshold"
    fields = ("date", "weekday", "lunar_month", "lunar_day", "year_ganzhi")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        return lunar_info(ctx.local_now.date())


def lunar_info(day: date) -> dict[str, Any]:
    lunar = Solar.fromYmd(day.year, day.month, day.day).getLunar()
    if (next_term := lunar.getNextJieQi(True)) is None:
        raise ValueError(f"lunar_python returned no next solar term for {day}")
    festivals = [*lunar.getFestivals(), *Solar.fromYmd(day.year, day.month, day.day).getFestivals()]
    first = day.replace(day=1)
    weeks = pycal.Calendar(firstweekday=0).monthdatescalendar(day.year, day.month)
    return {
        "date": day.isoformat(),
        "year": day.year,
        "month": day.month,
        "day": day.day,
        "weekday": day.weekday(),
        "weekday_zh": WEEKDAYS_ZH[day.weekday()],
        "weekday_en": day.strftime("%A"),
        "month_en": day.strftime("%B"),
        "lunar_month": lunar.getMonthInChinese() + "月",
        "lunar_day": lunar.getDayInChinese(),
        "year_ganzhi": lunar.getYearInGanZhi(),
        "zodiac": lunar.getYearShengXiao(),
        "solar_term": lunar.getJieQi(),
        "next_term": next_term.getName(),
        "next_term_days": (date.fromisoformat(next_term.getSolar().toYmd()) - day).days,
        "festivals": festivals,
        "grid": [
            [
                {"day": d.day, "in_month": d.month == first.month, "today": d == day, "weekend": d.weekday() >= 5}
                for d in week
            ]
            for week in weeks
        ],
        "week_of_year": day.isocalendar().week,
        "day_of_year": (day - date(day.year, 1, 1) + timedelta(days=1)).days,
    }
