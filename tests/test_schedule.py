"""Schedule due decisions against a hand-written truth table.

Calendar facts used: 2026-10-12 is a Monday, 2026-10-16 a Friday. US DST ends
2026-11-01 (first Sunday of November): New York is UTC-4 before, UTC-5 after.
Asia/Shanghai is UTC+8 all year.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from inkage.config import ConfigError, parse_config
from inkage.schedule import Schedule

SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")

MARKET = Schedule.parse({"every": "5m", "window": {"time": "09:30-15:00", "days": "mon-fri"}, "fallback": "6h"})
NIGHT = Schedule.parse({"every": "10m", "window": {"time": "22:00-02:00", "days": "fri"}})
AT = Schedule.parse({"at": ["00:05", "12:00"]})
HOURLY = Schedule.parse({"every": "1h"})
NYSE = Schedule.parse({"every": "5m", "window": {"time": "09:30-16:00", "days": "mon-fri"}, "fallback": "12h"})


def sh(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=SH)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# (name, schedule, tz, now, last generated, expected due)
TRUTH = [
    ("in window, interval elapsed", MARKET, SH, sh("2026-10-12 10:00"), sh("2026-10-12 09:55"), True),
    # Tolerance is 4 min (one 5-min tick minus a minute): a Run at :09 (late) then :12 (on time) still regenerates.
    ("tolerance: late tick then on-time tick", MARKET, SH, sh("2026-10-12 10:12"), sh("2026-10-12 10:09"), True),
    ("tolerance: 1m00s of 5m counts", MARKET, SH, sh("2026-10-12 10:00:00"), sh("2026-10-12 09:59:00"), True),
    ("tolerance: 0m59s of 5m does not", MARKET, SH, sh("2026-10-12 10:00:00"), sh("2026-10-12 09:59:01"), False),
    ("hourly: 55m on the 5-min grid is not due", HOURLY, SH, sh("2026-10-12 01:57"), sh("2026-10-12 01:02"), False),
    ("hourly: 56m is due", HOURLY, SH, sh("2026-10-12 01:58"), sh("2026-10-12 01:02"), True),
    ("outside window uses fallback", MARKET, SH, sh("2026-10-12 16:00"), sh("2026-10-12 14:58"), False),
    ("fallback elapsed", MARKET, SH, sh("2026-10-12 21:00"), sh("2026-10-12 15:00"), True),
    ("weekend is outside window", MARKET, SH, sh("2026-10-17 10:00"), sh("2026-10-17 09:55"), False),
    ("entering window", MARKET, SH, sh("2026-10-12 09:32"), sh("2026-10-12 06:00"), True),
    ("missing manifest entry", MARKET, SH, sh("2026-10-17 10:00"), None, True),
    ("cross-midnight, evening part", NIGHT, SH, sh("2026-10-16 23:00"), sh("2026-10-16 22:50"), True),
    ("cross-midnight, after midnight belongs to Fri", NIGHT, SH, sh("2026-10-17 01:00"), sh("2026-10-17 00:50"), True),
    ("cross-midnight, Sat evening not listed", NIGHT, SH, sh("2026-10-17 23:00"), sh("2026-10-17 22:00"), False),
    ("cross-midnight, before start, no fallback", NIGHT, SH, sh("2026-10-16 21:59"), sh("2026-10-16 20:00"), False),
    ("at across day boundary", AT, SH, sh("2026-10-13 00:06"), sh("2026-10-12 12:00:30"), True),
    ("at, nothing new passed", AT, SH, sh("2026-10-13 00:11"), sh("2026-10-13 00:06"), False),
    ("at, tolerance just under", AT, SH, sh("2026-10-13 00:01:00"), sh("2026-10-12 23:00"), True),
    ("at, tolerance just over", AT, SH, sh("2026-10-13 00:00:59"), sh("2026-10-12 23:00"), False),
    ("at, early run already covered it", AT, SH, sh("2026-10-13 00:09"), sh("2026-10-13 00:01:30"), False),
    ("at, after a gap of days", AT, SH, sh("2026-10-19 10:00"), sh("2026-10-17 13:00"), True),
    # 14:00Z = 10:00 EDT: inside NYSE hours (but 22:00 in Shanghai).
    ("other timezone, inside its window", NYSE, NY, utc("2026-10-12 14:00"), utc("2026-10-12 13:55"), True),
    ("same instant in default tz is outside", NYSE, SH, utc("2026-10-12 14:00"), utc("2026-10-12 13:55"), False),
    # DST: 14:00Z is 10:00 EDT on Fri 2026-10-30 but 09:00 EST on Mon 2026-11-02.
    ("New York EDT, 10:00 local", NYSE, NY, utc("2026-10-30 14:00"), utc("2026-10-30 13:55"), True),
    ("New York EST, 09:00 local is pre-open", NYSE, NY, utc("2026-11-02 14:00"), utc("2026-11-02 13:55"), False),
    ("New York EST, 09:35 local", NYSE, NY, utc("2026-11-02 14:35"), utc("2026-11-02 14:30"), True),
]


@pytest.mark.parametrize(("name", "schedule", "tz", "now", "last", "due"), TRUTH, ids=[t[0] for t in TRUTH])
def test_due_truth_table(name, schedule, tz, now, last, due):
    assert schedule.is_due(now, last, tz)[0] is due


# (schedule, tz, last generated, expected next_due)
NEXT = [
    (MARKET, SH, sh("2026-10-12 10:00"), sh("2026-10-12 10:05")),
    # 15:03 is past the window close, so the 6h fallback applies.
    (MARKET, SH, sh("2026-10-12 14:58"), sh("2026-10-12 20:58")),
    # Window ends 02:00 Sat; no fallback -> next Friday 22:00.
    (NIGHT, SH, sh("2026-10-17 01:55"), sh("2026-10-23 22:00")),
    (AT, SH, sh("2026-10-12 12:00:30"), sh("2026-10-13 00:05")),
    (AT, SH, sh("2026-10-12 08:00"), sh("2026-10-12 12:00")),
    # Friday after close, 12h fallback: Sat 04:00 local (EDT) = 08:00Z.
    (NYSE, NY, utc("2026-10-30 20:00"), utc("2026-10-31 08:00")),
]


@pytest.mark.parametrize(("schedule", "tz", "last", "expected"), NEXT)
def test_next_due(schedule, tz, last, expected):
    assert schedule.next_due(last, tz) == expected.astimezone(UTC)


def test_next_due_is_due_and_earlier_is_not():
    """next_due agrees with is_due: due there, not 5 minutes earlier (beyond the 4-minute tolerance)."""
    last = sh("2026-10-12 14:58")
    nd = MARKET.next_due(last, SH)
    assert MARKET.is_due(nd, last, SH)[0]
    assert not MARKET.is_due(nd - timedelta(minutes=5), last, SH)[0]


def test_window_days_must_be_text():
    raw = {
        "sources": {
            "calendar": {
                "panels": ["800x480-bwr"],
                "schedule": {"every": "5m", "window": {"time": "09:30-15:00", "days": 5}},
            }
        }
    }
    with pytest.raises(ConfigError, match=r"sources\.calendar\.schedule.*days"):
        parse_config(raw)
