"""Astro: sun times (civil dawn/dusk, sunrise/sunset, solar noon, day length) and moon phase. No network.

Computed with ``astral`` for the local date in the Source's timezone. ``astral.moon.phase``
answers 0..28 over one synodic month (0 new, 7 first quarter, 14 full, 21 last quarter).
"""

import math
from datetime import date
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from astral import Observer, moon
from astral.sun import sun

from inkage.schedule import Schedule
from inkage.source import Context, Source

PHASE_CYCLE = 28.0
# Eight named phases, each centred on its eighth of the cycle.
PHASE_NAMES = (
    "New Moon",
    "Waxing Crescent",
    "First Quarter",
    "Waxing Gibbous",
    "Full Moon",
    "Waning Gibbous",
    "Last Quarter",
    "Waning Crescent",
)


class Astro(Source):
    schedule = Schedule.parse({"at": ["00:05"]})
    dither = "threshold"
    params: ClassVar[dict[str, Any]] = {"latitude": 31.2304, "longitude": 121.4737, "label": "Shanghai"}
    fields = ("label", "date", "dawn", "sunrise", "noon", "sunset", "dusk", "day_length", "moon_phase")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        p = ctx.params
        info = astro_info(ctx.local_now.date(), p["latitude"], p["longitude"], ctx.tz)
        return {"label": p["label"], **info}


def moon_phase(day: date) -> tuple[str, float]:
    """Phase name and illuminated fraction (0..1), from the phase angle with a cosine approximation."""
    phase = moon.phase(day)
    name = PHASE_NAMES[int((phase + PHASE_CYCLE / 16) // (PHASE_CYCLE / 8)) % 8]
    return name, (1 - math.cos(2 * math.pi * phase / PHASE_CYCLE)) / 2


def astro_info(day: date, latitude: float, longitude: float, tz: ZoneInfo) -> dict[str, Any]:
    """Sun events as local datetimes; astral raises ValueError where the sun never rises or sets."""
    s = sun(Observer(latitude=latitude, longitude=longitude), date=day, tzinfo=tz)
    # astral finds each event nearest the zone's date, so a zone far from the location's solar time
    # yields events from neighbouring days (sunset before sunrise).
    if not s["dawn"] < s["sunrise"] < s["noon"] < s["sunset"] < s["dusk"]:
        raise ValueError(
            f"sun events out of order for ({latitude}, {longitude}) in {tz.key} on {day}: "
            "set the Source's timezone to the location's zone"
        )
    length = s["sunset"] - s["sunrise"]
    hours, minutes = divmod(round(length.total_seconds() / 60), 60)
    name, lit = moon_phase(day)
    return {
        "date": day,
        "dawn": s["dawn"],
        "sunrise": s["sunrise"],
        "noon": s["noon"],
        "sunset": s["sunset"],
        "dusk": s["dusk"],
        "day_length": f"{hours}h {minutes:02d}m",
        "moon_phase": name,
        "moon_lit": lit,
        "moon_waxing": moon.phase(day) < PHASE_CYCLE / 2,
    }
