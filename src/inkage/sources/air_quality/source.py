"""CAMS model air-quality forecast via keyless Open-Meteo; explicit U.S. AQI."""

import asyncio
import itertools
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from loguru import logger

from inkage.schedule import Schedule
from inkage.source import Context, Source

URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
MAX_AGE = timedelta(hours=3)
HOURS = 12


class AirQualityError(RuntimeError):
    pass


class AirQuality(Source):
    schedule = Schedule.parse({"every": "1h"})
    dither = "threshold"
    params = {"latitude": 31.2304, "longitude": 121.4737, "label": "Shanghai"}
    fields = ("label", "aqi", "status", "pm25", "pm10", "updated", "hours")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        raw = await fetch_air_quality(ctx.params["latitude"], ctx.params["longitude"])
        return {"label": ctx.params["label"], **parse_air_quality(raw, ctx.now)}


async def fetch_air_quality(latitude: float, longitude: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await client.get(
                    URL,
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "current": "us_aqi,pm2_5,pm10",
                        "hourly": "us_aqi",
                        "forecast_days": 2,
                        "timezone": "auto",
                    },
                )
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                if attempt == 3:
                    raise AirQualityError(
                        f"Open-Meteo air quality: connection failed after 3 attempts ({type(error).__name__}) at {URL}"
                    ) from error
                logger.warning("Open-Meteo air quality: {} at {}; retrying in {}s", type(error).__name__, URL, attempt)
                await asyncio.sleep(attempt)
        resp.raise_for_status()
        return resp.json()


def number(block: dict[str, Any], key: str, where: str) -> float:
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        raise AirQualityError(f"Open-Meteo {where}.{key}: missing or invalid value {value!r}")
    return value


def status(aqi: int) -> str:
    # U.S. AQI categories, Open-Meteo air-quality API documentation.
    for ceiling, label in (
        (50, "Good"),
        (100, "Moderate"),
        (150, "Unhealthy for sensitive groups"),
        (200, "Unhealthy"),
        (300, "Very unhealthy"),
    ):
        if aqi <= ceiling:
            return label
    return "Hazardous"


def parse_air_quality(raw: dict[str, Any], now: datetime) -> dict[str, Any]:
    try:
        tz = timezone(timedelta(seconds=raw["utc_offset_seconds"]))
        current = raw["current"]
        observed = datetime.fromisoformat(current["time"]).replace(tzinfo=tz)
        hourly = raw["hourly"]
        times = [datetime.fromisoformat(t).replace(tzinfo=tz) for t in hourly["time"]]
        values = hourly["us_aqi"]
    except (KeyError, TypeError, ValueError):
        raise AirQualityError("Open-Meteo air quality: missing or malformed current/hourly fields") from None
    if not -timedelta(hours=1) <= now - observed <= MAX_AGE:
        raise AirQualityError(f"Open-Meteo air quality: forecast time {observed.isoformat()} is stale or in the future")
    if not isinstance(values, list) or len(values) != len(times):
        raise AirQualityError("Open-Meteo air quality: mismatched hourly time/us_aqi columns")
    if any(b - a != timedelta(hours=1) for a, b in itertools.pairwise(times)):
        raise AirQualityError("Open-Meteo air quality: timestamps must be consecutive hours")
    upcoming = [i for i, t in enumerate(times) if t > now][:HOURS]
    if len(upcoming) != HOURS:
        raise AirQualityError(f"Open-Meteo air quality: fewer than {HOURS} upcoming hours")
    aqi = math.floor(number(current, "us_aqi", "current") + 0.5)
    hours = [
        {
            "time": times[i].strftime("%H"),
            "aqi": math.floor(number({"us_aqi": values[i]}, "us_aqi", f"hourly[{i}]") + 0.5),
        }
        for i in upcoming
    ]
    # Keep labels alongside every bar; vertical scale is shared within this frame.
    maximum = max(150, *(h["aqi"] for h in hours))
    for h in hours:
        h["height"] = round(100 * h["aqi"] / maximum)
    return {
        "aqi": aqi,
        "status": status(aqi),
        "pm25": f"{number(current, 'pm2_5', 'current'):.1f}",
        "pm10": f"{number(current, 'pm10', 'current'):.1f}",
        "updated": observed.strftime("%Y-%m-%d %H:%M"),
        "hours": hours,
    }
