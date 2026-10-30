"""Countdown: days until (or since) configured events; yearly events roll to their next occurrence."""

from datetime import date
from typing import Any, ClassVar

from inkage.schedule import Schedule
from inkage.source import Context, Source

REPEATS = ("yearly", "none")


def next_yearly(day: date, today: date) -> date:
    """First anniversary of ``day`` on or after ``today``; Feb 29 falls on Feb 28 in common years."""
    for year in (today.year, today.year + 1):
        try:
            candidate = day.replace(year=year)
        except ValueError:  # Feb 29 in a common year
            candidate = date(year, 2, 28)
        if candidate >= today:
            return candidate
    raise AssertionError("unreachable: next year's anniversary is always >= today")


def label(days: int) -> str:
    n = abs(days)
    unit = "day" if n == 1 else "days"
    return "TODAY" if days == 0 else (f"{n} {unit} ago" if days < 0 else f"{n} {unit}")


def countdown(events: Any, today: date) -> list[dict[str, Any]]:
    """Each event with its effective date and ``days`` (negative = past); upcoming soonest first, then past."""
    if not isinstance(events, list) or not events:
        raise ValueError(f"countdown: 'events' must be a non-empty list of tables, got {events!r}")
    out = []
    for i, ev in enumerate(events):
        where = f"countdown: events[{i}]"
        if not isinstance(ev, dict):
            raise ValueError(f"{where}: expected a table, got {ev!r}")
        if unknown := set(ev) - {"title", "date", "repeat"}:
            raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
        if not isinstance(title := ev.get("title"), str) or not title.strip():
            raise ValueError(f"{where}: 'title' must be a non-empty string")
        if (repeat := ev.get("repeat", "none")) not in REPEATS:
            raise ValueError(f"{where}: 'repeat' must be one of {REPEATS}, got {repeat!r}")
        try:
            day = date.fromisoformat(ev["date"]) if isinstance(ev.get("date"), str) else ev["date"]
        except (KeyError, ValueError) as e:
            raise ValueError(f"{where}: 'date' must be YYYY-MM-DD ({e})") from None
        if not isinstance(day, date):
            raise ValueError(f"{where}: 'date' must be YYYY-MM-DD, got {day!r}")
        when = next_yearly(day, today) if repeat == "yearly" else day
        days = (when - today).days
        out.append(
            {
                "title": title.strip(),
                "date": when.isoformat(),
                "weekday": when.strftime("%a"),
                "days": days,
                "label": label(days),
            }
        )
    return sorted(out, key=lambda e: (e["days"] < 0, abs(e["days"])))


class Countdown(Source):
    schedule = Schedule.parse({"at": ["00:05"]})
    dither = "threshold"
    params: ClassVar[dict[str, Any]] = {"events": [{"title": "New Year", "date": "2027-01-01", "repeat": "yearly"}]}
    fields = ("events",)

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        return {"events": countdown(ctx.params["events"], ctx.local_now.date())}
