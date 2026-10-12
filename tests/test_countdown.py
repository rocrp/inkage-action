"""countdown Source: hand-counted day differences, yearly rollover, past events, bad input, E2E."""

import asyncio
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data

SH = ZoneInfo("Asia/Shanghai")
# 2026-10-12 00:30 in Shanghai is still 2026-10-11 in UTC: the local date must win.
NOW = datetime(2026, 10, 12, 0, 30, tzinfo=SH)


def source_config(panel: str = "800x480-bwr", **params):
    return parse_config(
        {"defaults": {"timezone": "Asia/Shanghai"}, "sources": {"countdown": {"panels": [panel], **params}}}
    ).sources[0]


def events(evs) -> list[dict]:
    sc = source_config(events=evs)
    return asyncio.run(sc.cls().fetch(context_for(sc, NOW)))["events"]


def test_default_new_year_is_81_days_away():
    # Oct 12 -> Oct 31: 19, Nov: 30, Dec: 31, -> Jan 1: 1  => 81 (82 if the UTC date, Oct 11, were used)
    (ev,) = asyncio.run(source_config().cls().fetch(context_for(source_config(), NOW)))["events"]
    assert (ev["title"], ev["date"], ev["days"], ev["label"]) == ("New Year", "2027-01-01", 81, "81 days")


def test_yearly_rollover_past_and_sorting():
    out = events(
        [
            {"title": "Women's Day", "date": "2000-03-08", "repeat": "yearly"},  # passed this year
            {"title": "Launch", "date": "2026-10-01", "repeat": "none"},  # past, not repeating
            {"title": "Christmas", "date": "2020-12-25", "repeat": "yearly"},  # still ahead this year
            {"title": "Birthday", "date": "1990-10-12", "repeat": "yearly"},  # today
            {"title": "Leap", "date": "2024-02-29", "repeat": "yearly"},  # 2027 is common: Feb 28
            {"title": "Tomorrow", "date": "2026-10-13"},  # repeat defaults to none
        ]
    )
    got = [(e["title"], e["date"], e["days"], e["label"]) for e in out]
    assert got == [
        ("Birthday", "2026-10-12", 0, "TODAY"),
        ("Tomorrow", "2026-10-13", 1, "1 day"),
        # Oct 12 -> Oct 31: 19, Nov 30, -> Dec 25: 25  => 74
        ("Christmas", "2026-12-25", 74, "74 days"),
        # 19 + 30 + 31 + Jan 31 + -> Feb 28: 28  => 139
        ("Leap", "2027-02-28", 139, "139 days"),
        # 139 + Feb 28 -> Mar 8: 8  => 147
        ("Women's Day", "2027-03-08", 147, "147 days"),
        # Oct 1 -> Oct 12 is 11 days back
        ("Launch", "2026-10-01", -11, "11 days ago"),
    ]


@pytest.mark.parametrize(
    ("evs", "match"),
    [
        ([], "non-empty list"),
        ([{"title": "X", "date": "2026-13-01"}], r"events\[0\]: 'date'"),
        ([{"title": "X", "date": "next friday"}], r"events\[0\]: 'date'"),
        ([{"title": "X"}], r"events\[0\]: 'date'"),
        ([{"title": "", "date": "2026-12-01"}], "title"),
        ([{"title": "X", "date": "2026-12-01", "repeat": "monthly"}], "repeat"),
        ([{"title": "X", "date": "2026-12-01", "when": 1}], "unknown keys"),
    ],
)
def test_bad_events_raise(evs, match):
    with pytest.raises(ValueError, match=match):
        events(evs)


MANY = [
    {"title": "New Year", "date": "2027-01-01", "repeat": "yearly"},
    {"title": "Spring Festival 春节", "date": "2027-02-06", "repeat": "none"},
    {"title": "A very long event title that must not overflow the list column", "date": "2026-11-11"},
    {"title": "Launch", "date": "2026-10-01", "repeat": "none"},
]


@pytest.mark.parametrize(("panel", "size"), [("800x480-bwr", (800, 480)), ("250x122-bwr", (250, 122))])
def test_e2e_frame_size_and_palette_count(panel, size):
    sc = source_config(panel, events=MANY)

    async def go():
        ctx = context_for(sc, NOW)
        src = sc.cls()
        data = src.check_data(await src.fetch(ctx))
        async with Renderer() as r:
            raw = await r.html_to_image(
                src.render_template(ctx, sc.panels[0], data), size[0], size[1], src.template_dir
            )
            return raw, await frame_from_data(r, src, ctx, sc.panels[0], sc, data)

    raw, frame = asyncio.run(go())
    png = Image.open(io.BytesIO(png_bytes(frame)))
    assert png.size == size
    assert len(png.getpalette() or []) == 3 * 3
    colors = {tuple(c) for c in np.asarray(raw).reshape(-1, 3)}
    assert colors <= {(0, 0, 0), (255, 255, 255), (255, 0, 0)}, f"{len(colors)} distinct colors"
    assert (np.asarray(frame) == 2).sum() > 100  # the day count is in red ink
