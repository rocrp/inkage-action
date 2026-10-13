"""Parse GitHub's anonymous calendar, including exact counts from associated tooltips."""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser


@dataclass(frozen=True, slots=True)
class Day:
    date: date
    count: int
    level: int


@dataclass(frozen=True, slots=True)
class Calendar:
    start: date
    end: date
    total: int
    days: tuple[Day, ...]


class CalendarError(ValueError):
    pass


class CalendarParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cells: dict[str, tuple[date, int]] = {}
        self.tooltips: dict[str, str] = {}
        self.start: date | None = None
        self.end: date | None = None
        self.heading = ""
        self._in_heading = False
        self._tooltip: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if "data-from" in a and "data-to" in a:
            if self.start is not None:
                raise CalendarError("GitHub calendar: multiple date ranges")
            self.start = date.fromisoformat(str(a["data-from"]).split()[0])
            self.end = date.fromisoformat(str(a["data-to"]).split()[0])
        if "data-date" in a:
            key, level = a.get("id"), a.get("data-level")
            if not key or key in self.cells or level not in {"0", "1", "2", "3", "4"}:
                raise CalendarError("GitHub calendar: missing/duplicate cell ID or invalid activity level")
            self.cells[key] = (date.fromisoformat(str(a["data-date"])), int(level))
        if tag == "h2" and a.get("id") == "js-contribution-activity-description":
            self._in_heading = True
        if tag == "tool-tip" and (key := a.get("for")):
            if key in self.tooltips:
                raise CalendarError(f"GitHub calendar: duplicate tooltip for {key}")
            self._tooltip = key
            self.tooltips[key] = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self._in_heading = False
        if tag == "tool-tip":
            self._tooltip = None

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self.heading += data
        if self._tooltip is not None:
            self.tooltips[self._tooltip] += data


_MONTHS = {
    name: i
    for i, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
_TOOLTIP = re.compile(r"(No|[\d,]+) contributions? on ([A-Z][a-z]+) (\d{1,2})(?:st|nd|rd|th)?(?:, (\d{4}))?\.?")


def parse_calendar(html: str) -> Calendar:
    """Reject incomplete/changed pages; totals and dates must agree independently."""
    parser = CalendarParser()
    try:
        parser.feed(html)
        parser.close()
        start, end = parser.start, parser.end
        if start is None or end is None or not 364 <= (end - start).days <= 371:
            raise CalendarError("GitHub calendar: missing or invalid annual date range")
        heading = re.fullmatch(r"([\d,]+) contributions? in the last year", " ".join(parser.heading.split()))
        if heading is None:
            raise CalendarError("GitHub calendar: missing annual contribution total")
        days: list[Day] = []
        for key, (stamp, level) in parser.cells.items():
            tooltip = " ".join(parser.tooltips.get(key, "").split())
            if not (match := _TOOLTIP.fullmatch(tooltip)):
                raise CalendarError(f"GitHub calendar: missing or malformed contribution count for {stamp}")
            count, month, day, year = match.groups()
            if (_MONTHS.get(month), int(day)) != (stamp.month, stamp.day) or (year and int(year) != stamp.year):
                raise CalendarError(f"GitHub calendar: tooltip date disagrees with cell {stamp}")
            value = 0 if count == "No" else int(count.replace(",", ""))
            if (value == 0) != (level == 0):
                raise CalendarError(f"GitHub calendar: activity level disagrees with count for {stamp}")
            days.append(Day(stamp, value, level))
        days.sort(key=lambda d: d.date)
        expected = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        if [d.date for d in days] != expected:
            raise CalendarError("GitHub calendar: duplicate, missing or out-of-range dates")
        total = int(heading[1].replace(",", ""))
        if sum(d.count for d in days) != total:
            raise CalendarError("GitHub calendar: daily counts disagree with annual total")
        return Calendar(start, end, total, tuple(days))
    except (ValueError, KeyError) as error:
        if isinstance(error, CalendarError):
            raise
        raise CalendarError(f"GitHub calendar: malformed response ({error})") from error
