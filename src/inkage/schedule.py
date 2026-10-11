"""Schedules: when a Frame is due, and when it will next be due.

Two forms (mutually exclusive):

- ``every`` + optional active ``window`` + optional ``fallback``: due once
  ``every`` has elapsed inside the window, ``fallback`` outside it (no fallback
  = never outside the window).
- ``at``: a list of local times; due on the first Run after a listed time since
  the last generation.

All comparisons allow ``TOLERANCE`` of slack so cron jitter (late or early
ticks) never pushes a regeneration back a whole tick.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

# One cron tick (5 min) minus a minute: a late Run followed by an on-time one
# never skips a cycle, yet two Runs a minute apart don't both regenerate.
TOLERANCE = timedelta(minutes=4)
# next_due search horizon; longer intervals are rejected at parse time.
HORIZON = timedelta(days=8)

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DURATION = re.compile(r"^(\d+)([smhd])$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


class ScheduleError(ValueError):
    pass


def parse_duration(text: str) -> timedelta:
    if not isinstance(text, str) or not (m := _DURATION.match(text)):
        raise ScheduleError(f"bad duration {text!r} (expected e.g. '5m', '6h', '1d')")
    delta = timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})
    if not timedelta(0) < delta <= timedelta(days=7):
        raise ScheduleError(f"duration {text!r} must be > 0 and <= 7d")
    return delta


def parse_time(text: str) -> time:
    if not isinstance(text, str) or not re.fullmatch(r"\d{2}:\d{2}", text):
        raise ScheduleError(f"bad local time {text!r} (expected HH:MM)")
    try:
        return time.fromisoformat(text)
    except ValueError:
        raise ScheduleError(f"bad local time {text!r} (expected HH:MM)") from None


def parse_days(text: str) -> frozenset[int]:
    """'mon-fri', 'sat,sun', 'mon,wed-fri' -> weekday numbers (Monday = 0)."""
    days: set[int] = set()
    for part in text.split(","):
        bounds = part.strip().split("-")
        if len(bounds) > 2 or any(b not in DAY_NAMES for b in bounds):
            raise ScheduleError(f"bad days {text!r} (expected e.g. 'mon-fri' or 'sat,sun')")
        lo, hi = DAY_NAMES.index(bounds[0]), DAY_NAMES.index(bounds[-1])
        days.update(range(lo, hi + 1) if lo <= hi else (*range(lo, 7), *range(hi + 1)))
    return frozenset(days)


@dataclass(slots=True, frozen=True)
class Window:
    start: time
    end: time
    days: frozenset[int] = frozenset(range(7))

    @classmethod
    def parse(cls, time_range: str, days: str = "mon-sun") -> Window:
        parts = time_range.split("-") if isinstance(time_range, str) else []
        if len(parts) != 2:
            raise ScheduleError(f"bad window time {time_range!r} (expected 'HH:MM-HH:MM')")
        start, end = parse_time(parts[0]), parse_time(parts[1])
        if start == end:
            raise ScheduleError(f"window {time_range!r} is empty")
        return cls(start=start, end=end, days=parse_days(days))

    def contains(self, local: datetime) -> bool:
        """A window crossing midnight belongs to the weekday it starts on."""
        t, day = local.time(), local.weekday()
        if self.start < self.end:
            return day in self.days and self.start <= t < self.end
        return (t >= self.start and day in self.days) or (t < self.end and (day - 1) % 7 in self.days)


@dataclass(slots=True, frozen=True)
class Schedule:
    every: timedelta | None = None
    window: Window | None = None
    fallback: timedelta | None = None
    at: tuple[time, ...] = ()

    def __post_init__(self) -> None:
        if (self.every is None) == (not self.at):
            raise ScheduleError("schedule needs exactly one of 'every' or 'at'")
        if self.at and (self.window or self.fallback):
            raise ScheduleError("'window' and 'fallback' only apply to 'every'")
        if self.fallback and not self.window:
            raise ScheduleError("'fallback' needs a 'window'")

    @classmethod
    def parse(cls, raw: dict) -> Schedule:
        if not isinstance(raw, dict):
            raise ScheduleError(f"schedule must be a table, got {raw!r}")
        if unknown := set(raw) - {"every", "window", "fallback", "at"}:
            raise ScheduleError(f"unknown schedule keys {sorted(unknown)}")
        if "every" in raw and "at" in raw:
            raise ScheduleError("'every' and 'at' are mutually exclusive")
        window = None
        if (w := raw.get("window")) is not None:
            if not isinstance(w, dict) or set(w) - {"time", "days"} or "time" not in w:
                raise ScheduleError(f"window must be {{ time = 'HH:MM-HH:MM', days = 'mon-fri' }}, got {w!r}")
            if not isinstance(days := w.get("days", "mon-sun"), str):
                raise ScheduleError(f"window days must be a string like 'mon-fri', got {days!r}")
            window = Window.parse(w["time"], days)
        at = raw.get("at", [])
        if not isinstance(at, list) or ("at" in raw and not at):
            raise ScheduleError(f"'at' must be a non-empty list of 'HH:MM', got {at!r}")
        return cls(
            every=parse_duration(raw["every"]) if "every" in raw else None,
            window=window,
            fallback=parse_duration(raw["fallback"]) if "fallback" in raw else None,
            at=tuple(sorted(parse_time(t) for t in at)),
        )

    def describe(self) -> str:
        if self.at:
            return "at " + ", ".join(t.strftime("%H:%M") for t in self.at)
        text = f"every {_fmt(self.every)}"
        if self.window:
            days = ",".join(DAY_NAMES[d] for d in sorted(self.window.days))
            text += f" in {self.window.start:%H:%M}-{self.window.end:%H:%M} {days}"
            text += f", else every {_fmt(self.fallback)}" if self.fallback else ", else never"
        return text

    def _interval(self, now: datetime, tz: ZoneInfo) -> timedelta | None:
        if self.window is None or self.window.contains(now.astimezone(tz)):
            return self.every
        return self.fallback

    def _at_times(self, after: datetime, tz: ZoneInfo, days: int) -> list[datetime]:
        """Listed local times as aware datetimes, from the local day before ``after`` on."""
        base = after.astimezone(tz).date() - timedelta(days=1)
        return [datetime.combine(base + timedelta(days=d), t, tzinfo=tz) for d in range(days + 2) for t in self.at]

    def is_due(self, now: datetime, last: datetime | None, tz: ZoneInfo) -> tuple[bool, str]:
        """Decide whether a Frame last generated at ``last`` is due at ``now``; returns (due, reason)."""
        if last is None:
            return True, "never generated"
        if self.at:
            hit = [t for t in self._at_times(last, tz, (now - last).days + 1) if last < t - TOLERANCE <= now]
            if hit:
                return True, f"passed {hit[-1].astimezone(tz):%H:%M} since last generation"
            return False, "no listed time passed since last generation"
        interval = self._interval(now, tz)
        if interval is None:
            return False, "outside window, no fallback"
        elapsed = now - last
        where = "in window" if interval == self.every and self.window else ("outside window" if self.window else "")
        detail = f"{_fmt(elapsed)} elapsed of {_fmt(interval)}{' ' + where if where else ''}"
        return elapsed >= interval - TOLERANCE, detail

    def next_due(self, last: datetime, tz: ZoneInfo) -> datetime | None:
        """Earliest time after ``last`` at which the Frame becomes due (without tolerance)."""
        if self.at:
            return next(t for t in self._at_times(last, tz, 2) if t - TOLERANCE > last).astimezone(UTC)
        t = last
        while (t := t + timedelta(minutes=1)) <= last + HORIZON:
            if (interval := self._interval(t, tz)) is not None and t - last >= interval:
                return t.astimezone(UTC)
        return None


def _fmt(delta: timedelta | None) -> str:
    if delta is None:
        return "never"
    minutes = int(delta.total_seconds() // 60)
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"
