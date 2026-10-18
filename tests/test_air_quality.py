"""Real Open-Meteo/CAMS capture, documented U.S. AQI bands and broken forecasts."""

import asyncio
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from inkage.config import parse_config
from inkage.run import context_for

FIX = Path(__file__).parent / "fixtures" / "air_quality" / "open_meteo_shanghai.json"
NOW = datetime(2026, 10, 13, 3, 20, tzinfo=ZoneInfo("UTC"))  # 11:20 Shanghai


def source_config():
    return parse_config({"sources": {"air_quality": {"panels": ["800x480-bwr"]}}}).sources[0]


def capture():
    return json.loads(FIX.read_text())


def parse(raw, now=NOW):
    return source_config().cls.fetch.__globals__["parse_air_quality"](raw, now)


def test_real_capture_uses_location_hour_and_explicit_us_aqi(monkeypatch):
    async def fake(latitude, longitude):
        return capture()

    sc = source_config()
    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_air_quality", fake)
    data = asyncio.run(sc.cls().fetch(context_for(sc, NOW)))
    # Captured current: 106, PM2.5 31.5, PM10 38.0; hourly 12h onwards below.
    assert (data["aqi"], data["status"], data["pm25"], data["pm10"], data["updated"]) == (
        106,
        "Unhealthy for sensitive groups",
        "31.5",
        "38.0",
        "2026-10-13 11:00",
    )
    assert [(h["time"], h["aqi"]) for h in data["hours"]] == [
        ("12", 106),
        ("13", 107),
        ("14", 107),
        ("15", 106),
        ("16", 106),
        ("17", 105),
        ("18", 106),
        ("19", 108),
        ("20", 111),
        ("21", 114),
        ("22", 115),
        ("23", 116),
    ]


@pytest.mark.parametrize(
    ("aqi", "label"),
    [
        (0, "Good"),
        (50, "Good"),
        (51, "Moderate"),
        (100, "Moderate"),
        (101, "Unhealthy for sensitive groups"),
        (150, "Unhealthy for sensitive groups"),
        (151, "Unhealthy"),
        (200, "Unhealthy"),
        (201, "Very unhealthy"),
        (300, "Very unhealthy"),
        (301, "Hazardous"),
        (500, "Hazardous"),
    ],
)
def test_documented_us_aqi_category_boundaries(aqi, label):
    # https://open-meteo.com/en/docs/air-quality-api, U.S. AQI ranges.
    raw = capture()
    raw["current"]["us_aqi"] = aqi
    assert parse(raw)["status"] == label


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda r: r["current"].update(pm2_5=None), "current.pm2_5"),
        (lambda r: r["current"].update(us_aqi=-1), "current.us_aqi"),
        (lambda r: r["hourly"]["us_aqi"].__setitem__(12, None), "hourly\\[12\\].us_aqi"),
        (lambda r: r["hourly"]["us_aqi"].pop(), "mismatched hourly"),
        (lambda r: r["hourly"]["time"].__setitem__(12, "2026-10-13T11:00"), "consecutive hours"),
        (lambda r: r["hourly"].update(time=[], us_aqi=[]), "fewer than 12 upcoming"),
    ],
)
def test_broken_forecast_fails_clearly(damage, message):
    raw = copy.deepcopy(capture())
    damage(raw)
    with pytest.raises(RuntimeError, match=message):
        parse(raw)


def test_stale_and_future_forecast_rejected():
    with pytest.raises(RuntimeError, match="stale or in the future"):
        parse(capture(), NOW + timedelta(hours=3))
    with pytest.raises(RuntimeError, match="stale or in the future"):
        parse(capture(), NOW - timedelta(hours=2))


@pytest.fixture
def skip_retry_delays(monkeypatch):
    # These tests prove recovery/bounds; wall-clock backoff adds no coverage.
    async def skip(_delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", skip)


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout, httpx.ConnectError])
def test_connection_failure_recovers_on_third_attempt(monkeypatch, failure, skip_retry_delays):
    # Replay the captured connection failure, then deliver the real CAMS capture.
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 3:
            raise failure("", request=request)
        return httpx.Response(200, content=FIX.read_bytes())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    sc = source_config()
    data = asyncio.run(sc.cls().fetch(context_for(sc, NOW)))
    assert (data["aqi"], data["pm25"], data["updated"]) == (106, "31.5", "2026-10-13 11:00")
    assert len(attempts) == 3


def test_persistent_connection_timeout_is_bounded_and_names_endpoint(monkeypatch, skip_retry_delays):
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ConnectTimeout("", request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    sc = source_config()
    with pytest.raises(RuntimeError, match=r"3 attempts.*ConnectTimeout.*air-quality-api.open-meteo.com"):
        asyncio.run(sc.cls().fetch(context_for(sc, NOW)))
    assert len(attempts) == 3


@pytest.mark.parametrize("status", [400, 403, 429])
def test_http_rejection_is_not_retried_as_a_connection_failure(monkeypatch, status):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(status, json={"error": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    sc = source_config()
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(sc.cls().fetch(context_for(sc, NOW)))
    assert len(attempts) == 1
