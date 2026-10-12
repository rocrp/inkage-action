"""Weather: current conditions plus a 5-day forecast from Open-Meteo (key-less).

``https://api.open-meteo.com/v1/forecast`` with ``timezone=auto`` answers times
in the location's local zone (``utc_offset_seconds`` beside them).
"""

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from inkage.schedule import Schedule
from inkage.source import Context, Source

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DAYS = 5
MAX_AGE = timedelta(hours=3)
CURRENT = ("temperature_2m", "relative_humidity_2m", "wind_speed_10m", "weather_code")
DAILY = ("weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_probability_max")
# units param -> (Open-Meteo temperature_unit, wind_speed_unit, temperature suffix, wind suffix)
UNITS = {"celsius": ("celsius", "kmh", "°C", "km/h"), "fahrenheit": ("fahrenheit", "mph", "°F", "mph")}

# WMO weather interpretation codes, as listed in the Open-Meteo forecast API docs.
WMO = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Heavy frz. drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy frz. rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "T-storm, hail",
    99: "T-storm, heavy hail",
}


class WeatherError(RuntimeError):
    pass


class Weather(Source):
    schedule = Schedule.parse({"every": "30m"})
    dither = "threshold"
    params = {"latitude": 31.2304, "longitude": 121.4737, "label": "Shanghai", "units": "celsius"}
    fields = ("label", "condition", "temp", "humidity", "wind", "updated", "days")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        p = ctx.params
        if p["units"] not in UNITS:
            raise WeatherError(f"units must be one of {sorted(UNITS)}, got {p['units']!r}")
        raw = await fetch_open_meteo(p["latitude"], p["longitude"], p["units"])
        return {"label": p["label"], **parse_forecast(raw, ctx.now, p["units"])}


async def fetch_open_meteo(latitude: float, longitude: float, units: str) -> dict[str, Any]:
    temp_unit, wind_unit, _, _ = UNITS[units]
    query = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join(CURRENT),
        "daily": ",".join(DAILY),
        "forecast_days": DAYS,
        "timezone": "auto",
        "temperature_unit": temp_unit,
        "wind_speed_unit": wind_unit,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(OPEN_METEO_URL, params=query)
        resp.raise_for_status()
        return resp.json()


def condition(code: Any) -> str:
    if (label := WMO.get(code)) is None:
        raise WeatherError(f"unknown WMO weather code {code!r}")
    return label


def _whole(block: dict[str, Any], key: str, where: str) -> int:
    """The value rounded half-up (26.5 -> 27, as people read thermometers); raise if absent."""
    if not isinstance(value := block.get(key), int | float):
        raise WeatherError(f"Open-Meteo {where}.{key}: missing or not a number ({value!r})")
    return math.floor(value + 0.5)


def parse_forecast(raw: dict[str, Any], now: datetime, units: str) -> dict[str, Any]:
    """Display-ready values; raise on missing fields, a stale reading or a short forecast."""
    _, _, t_sfx, w_sfx = UNITS[units]
    try:
        tz = timezone(timedelta(seconds=raw["utc_offset_seconds"]))
        cur, daily = raw["current"], raw["daily"]
        observed = datetime.fromisoformat(cur["time"]).replace(tzinfo=tz)
    except (KeyError, TypeError, ValueError) as e:
        raise WeatherError(f"Open-Meteo: missing or malformed field ({e!r})") from None
    if now - observed > MAX_AGE:
        raise WeatherError(f"Open-Meteo: current reading from {observed.isoformat()} is older than {MAX_AGE}")
    cols = {k: daily.get(k) for k in ("time", *DAILY)}
    if bad := [k for k, v in cols.items() if not isinstance(v, list) or len(v) < DAYS]:
        raise WeatherError(f"Open-Meteo daily: fewer than {DAYS} values for {bad}")
    days = []
    for i in range(DAYS):
        row = {k: v[i] for k, v in cols.items()}
        day = date.fromisoformat(row["time"])
        days.append(
            {
                "weekday": day.strftime("%a"),
                "date": f"{day.month}/{day.day}",
                "condition": condition(row["weather_code"]),
                "high": f"{_whole(row, 'temperature_2m_max', f'daily[{i}]')}°",
                "low": f"{_whole(row, 'temperature_2m_min', f'daily[{i}]')}°",
                "precip": f"{_whole(row, 'precipitation_probability_max', f'daily[{i}]')}%",
            }
        )
    return {
        "condition": condition(cur.get("weather_code")),
        "temp": f"{_whole(cur, 'temperature_2m', 'current')}",
        "temp_unit": t_sfx,
        "humidity": f"{_whole(cur, 'relative_humidity_2m', 'current')}%",
        "wind": f"{_whole(cur, 'wind_speed_10m', 'current')} {w_sfx}",
        "updated": observed.strftime("%Y-%m-%d %H:%M"),
        "days": days,
    }
