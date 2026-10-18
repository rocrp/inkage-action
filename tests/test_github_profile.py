"""External GitHub captures: exact counts, partial-page rejection and offline avatars."""

import asyncio
import base64
import io
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.run import context_for
from inkage.sources.github_profile.calendar import CalendarError, Day, parse_calendar

FIX = Path(__file__).parent / "fixtures" / "github_profile"
HTML = (FIX / "contributions.html").read_text()
SUNDAY_HTML = (FIX / "contributions-sunday.html").read_text()
NOW = datetime(2026, 10, 13, 10, tzinfo=UTC)


def source_config(**params):
    return parse_config({"sources": {"github_profile": {"panels": ["800x480-bwr"], **params}}}).sources[0]


def fetched(monkeypatch, *, html=HTML, now=NOW, **params):
    requests: list[httpx.Request] = []
    bodies = {
        "api.github.com": (FIX / "user.json").read_bytes(),
        "github.com": html.encode(),
        "avatars.githubusercontent.com": (FIX / "avatar.jpg").read_bytes(),
    }

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=bodies[request.url.host])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    config = source_config(**params)
    return asyncio.run(config.cls().fetch(context_for(config, now))), requests


def test_exact_annual_counts_from_real_calendar():
    calendar = parse_calendar(HTML)
    # Independently hand-read capture values; 367-day range proves no fixed-365 assumption.
    assert (calendar.start, calendar.end, calendar.total, len(calendar.days)) == (
        date(2025, 10, 12),
        date(2026, 10, 13),
        21840,
        367,
    )
    assert (calendar.days[0], calendar.days[-3:]) == (
        Day(date(2025, 10, 12), 4, 1),
        (Day(date(2026, 10, 11), 338, 4), Day(date(2026, 10, 12), 1225, 4), Day(date(2026, 10, 13), 459, 4)),
    )
    assert next(day for day in calendar.days if day.date == date(2026, 8, 23)) == Day(date(2026, 8, 23), 0, 0)


def test_sunday_capture_keeps_summary_separate_from_visible_days():
    calendar = parse_calendar(SUNDAY_HTML)
    # Raw 2026-10-18 response: heading includes the prior week; grid starts Oct 19.
    assert (calendar.summary.start, calendar.summary.end, calendar.summary.total) == (
        date(2025, 10, 12),
        date(2026, 10, 18),
        24380,
    )
    assert (calendar.start, calendar.end, calendar.total, len(calendar.days)) == (
        date(2025, 10, 19),
        date(2026, 10, 18),
        24325,
        365,
    )


@pytest.mark.parametrize("stamp", ["2025-10-19", "2026-05-01", "2026-10-18"])
def test_sunday_capture_still_rejects_missing_first_middle_or_last_day(stamp):
    damaged = re.sub(rf'<td[^>]+data-date="{stamp}"[^>]*></td>', "", SUNDAY_HTML)
    with pytest.raises(CalendarError, match="missing or out-of-range dates"):
        parse_calendar(damaged)


@pytest.mark.parametrize("pattern", [r"2025-10-(?:19|2[0-5])", r"\d{4}-\d{2}-\d{2}"])
def test_sunday_capture_rejects_missing_whole_week_or_empty_grid(pattern):
    damaged = re.sub(rf'<td[^>]+data-date="{pattern}"[^>]*></td>', "", SUNDAY_HTML)
    with pytest.raises(CalendarError, match="missing"):
        parse_calendar(damaged)


def test_sunday_capture_rejects_duplicate_date_even_with_a_distinct_cell_id():
    cell = re.search(r'<td[^>]+data-date="2025-10-19"[^>]*></td>', SUNDAY_HTML)[0]
    duplicate = cell.replace('id="contribution-day-component-0-0"', 'id="duplicate-day"')
    with pytest.raises(CalendarError, match="duplicate"):
        parse_calendar(
            SUNDAY_HTML + duplicate + '<tool-tip for="duplicate-day">3 contributions on October 19th.</tool-tip>'
        )


def test_sunday_summary_cannot_be_smaller_than_visible_total():
    with pytest.raises(CalendarError, match="smaller than visible total"):
        parse_calendar(SUNDAY_HTML.replace("24,380", "24,324"))


def test_sunday_summary_may_equal_visible_total_when_hidden_week_has_no_activity():
    calendar = parse_calendar(SUNDAY_HTML.replace("24,380", "24,325"))
    assert calendar.summary.total == 24325


def test_range_mismatch_error_reports_both_ranges_and_totals():
    damaged = SUNDAY_HTML.replace("2025-10-12 00:00:00 UTC", "2025-10-13 00:00:00 UTC")
    with pytest.raises(CalendarError) as error:
        parse_calendar(damaged)
    assert "summary=2025-10-13..2026-10-18 total=24380" in str(error.value)
    assert "visible=2025-10-19..2026-10-18 days=365 total=24325" in str(error.value)


@pytest.mark.parametrize(
    "layout,panel,expected_days,expected_start",
    [
        ("profile", "800x480-bwr", 365, "2025-10-19"),
        ("profile", "250x122-bw", 85, "2026-07-26"),
        ("isometric", "800x480-bw", 365, "2025-10-19"),
        ("isometric", "800x480-spectra6", 365, "2025-10-19"),
    ],
)
def test_sunday_render_shows_summary_total_and_actual_grid_dates(
    monkeypatch, layout, panel, expected_days, expected_start
):
    from inkage.panel import PRESETS

    now = datetime(2026, 10, 18, 10, tzinfo=UTC)
    data, _ = fetched(monkeypatch, html=SUNDAY_HTML, now=now, layout=layout)
    config = source_config(layout=layout)
    html = config.cls().render(context_for(config, now), PRESETS[panel], data)
    shown = re.findall(r"<title>(\d{4}-\d{2}-\d{2}):", html)
    assert (len(shown), min(shown), max(shown)) == (expected_days, expected_start, "2026-10-18")
    assert "24,380" in html and f"{expected_start} → 2026-10-18" in html
    assert "2025-10-12" not in html


def test_tooltip_variation_accepts_markup_whitespace_year_and_comma():
    # Equivalent English tooltip with nested content; IDs, not DOM order, link cells/counts.
    varied = HTML.replace(
        "1225 contributions on October 12th.", "<span>1,225</span>\n contributions on October 12, 2026."
    )
    assert parse_calendar(varied).days[-2] == Day(date(2026, 10, 12), 1225, 4)


@pytest.mark.parametrize(
    "changed, message",
    [
        (re.sub(r'<td[^>]+data-date="2026-10-13"[^>]*></td>', "", HTML), "missing or out-of-range dates"),
        (HTML.replace("459 contributions on October 13th.", ""), "missing or malformed contribution count"),
        (HTML.replace('data-date="2026-10-13"', 'data-date="2026-10-12"'), "tooltip date disagrees"),
        (
            HTML.replace("459 contributions on October 13th.", "458 contributions on October 13th."),
            "disagree with annual total",
        ),
        (
            HTML.replace("No contributions on August 23rd.", "1 contribution on August 23rd."),
            "activity level disagrees",
        ),
        ("<html>rate limit page</html>", "missing or invalid annual date range"),
    ],
)
def test_partial_or_changed_page_fails(changed, message):
    with pytest.raises(CalendarError, match=message):
        parse_calendar(changed)


def test_fetch_ignores_tokens_and_embeds_validated_avatar(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-be-used")
    data, sent = fetched(monkeypatch)
    assert {key: data[key] for key in ("username", "name", "bio", "repos", "followers")} == {
        "username": "RoCry",
        "name": "RoCry",
        "bio": "",
        "repos": 78,
        "followers": 305,
    }
    # Rendering needs no external network once fetch finishes.
    assert Image.open(io.BytesIO(base64.b64decode(data["avatar"].split(",")[1]))).size == (112, 112)
    assert all("authorization" not in request.headers and "cookie" not in request.headers for request in sent)


@pytest.mark.parametrize(
    "params, message",
    [
        ({"username": "../RoCry"}, "username must"),
        ({"layout": "skyline"}, "layout must"),
    ],
)
def test_invalid_configuration_fails(monkeypatch, params, message):
    with pytest.raises(ValueError, match=message):
        fetched(monkeypatch, **params)


def test_stale_calendar_fails(monkeypatch):
    config = source_config()
    context = context_for(config, datetime(2026, 11, 1, tzinfo=UTC))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=(FIX / "user.json").read_bytes() if request.url.host == "api.github.com" else HTML.encode(),
                )
            ),
            **kw,
        ),
    )
    with pytest.raises(CalendarError, match="unexpected cutoff"):
        asyncio.run(config.cls().fetch(context))


def test_missing_public_metric_fails(monkeypatch):
    from inkage.sources.github_profile.source import profile_data

    raw = json.loads((FIX / "user.json").read_bytes())
    del raw["public_repos"]
    with pytest.raises(ValueError, match="public_repos"):
        profile_data(raw, "RoCry")


def test_small_panel_shows_recent_thirteen_weeks_for_either_layout(monkeypatch):
    from inkage.panel import PRESETS

    data, _ = fetched(monkeypatch)
    rendered = []
    for layout in ("profile", "isometric"):
        config = source_config(layout=layout)
        html = config.cls().render(context_for(config, NOW), PRESETS["250x122-bw"], data)
        shown = re.findall(r"<title>(\d{4}-\d{2}-\d{2}):", html)
        # Calendar capture ends Tuesday: 12 full weeks + Sunday/Monday/Tuesday, starting Jul 19.
        assert (len(shown), min(shown), max(shown)) == (87, "2026-07-19", "2026-10-13")
        rendered.append(html)
    assert rendered[0] == rendered[1]
