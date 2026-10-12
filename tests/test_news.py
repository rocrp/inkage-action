"""news Source: real HN API and RSS captures read by hand, dead items, empty feeds, E2E."""

import asyncio
import io
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data

FIX = Path(__file__).parent / "fixtures" / "news"
NOW = datetime(2026, 10, 12, 11, 10, tzinfo=ZoneInfo("Asia/Shanghai"))  # capture time
RSS_URL = "https://news.ycombinator.com/rss"
RSS = (FIX / "hn_rss.xml").read_bytes()
HN = {
    "topstories.json": json.loads((FIX / "hn_topstories.json").read_text()),
    "item/50049411.json": json.loads((FIX / "hn_item_50049411.json").read_text()),
    "item/50045984.json": json.loads((FIX / "hn_item_50045984.json").read_text()),
}


def source_config(panel: str = "800x480-bwr", **params):
    return parse_config({"sources": {"news": {"panels": [panel], "timezone": "Asia/Shanghai", **params}}}).sources[0]


def fetched(monkeypatch, sc, hn: dict | None = None, feed: bytes = RSS) -> tuple[dict, list[str]]:
    """Fetch with HN / the feed answering from captures; return data and the HN paths requested."""
    paths: list[str] = []

    async def fake_hn(path: str):
        paths.append(path)
        return (hn or HN)[path]

    async def fake_feed(url: str) -> bytes:
        assert url == sc.params["feed"]
        return feed

    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_hn", fake_hn)
    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_feed", fake_feed)
    return asyncio.run(sc.cls().fetch(context_for(sc, NOW))), paths


def test_hn_top_stories(monkeypatch):
    data, paths = fetched(monkeypatch, source_config(count=2))
    assert paths[0] == "topstories.json"
    assert sorted(paths[1:]) == ["item/50045984.json", "item/50049411.json"]  # first two ids of the capture
    # Item times cross-checked against the RSS capture's pubDate for the same ids:
    # 50049411 = Sun, 11 Oct 2026 23:50:34 +0000, 50045984 = 18:04:47 +0000 (Asia/Shanghai +8).
    assert data == {
        "label": "Hacker News",
        "items": [
            {
                "title": "Whatever became of holography? (2011)",
                "source": "americanscientist.org",
                "score": 81,
                "time": "10-12 07:50",
            },
            {
                "title": "Total Annihilation, rebuilt for modern computers",
                "source": "nanolathe.gg",
                "score": 391,
                "time": "10-12 02:04",
            },
        ],
    }


def test_hn_dead_or_missing_items_are_skipped(monkeypatch):
    # The API answers null for a nonexistent id and sets dead/deleted on removed stories.
    hn = {
        **HN,
        "item/50045984.json": {"id": 50045984, "deleted": True, "time": 1791741887, "type": "story"},
        "item/50048642.json": None,
    }
    data, _ = fetched(monkeypatch, source_config(count=3), hn)
    assert [i["title"] for i in data["items"]] == ["Whatever became of holography? (2011)"]


def test_hn_no_live_items_raises(monkeypatch):
    hn = {"topstories.json": [50049411], "item/50049411.json": None}
    with pytest.raises(RuntimeError, match="no headlines"):
        fetched(monkeypatch, source_config(count=1), hn)


def test_rss_capture(monkeypatch):
    data, paths = fetched(monkeypatch, source_config(feed=RSS_URL))
    assert paths == []
    assert data["label"] == "Hacker News"  # <channel><title>
    assert len(data["items"]) == 8  # count default; the capture holds 30
    # Third <item>: "Fingerprints are the new cookies", royfish.dev, Sun, 11 Oct 2026 22:33:39 +0000.
    assert data["items"][2] == {
        "title": "Fingerprints are the new cookies",
        "source": "royfish.dev",
        "score": None,
        "time": "10-12 06:33",
    }


def test_label_overrides_feed_title(monkeypatch):
    data, _ = fetched(monkeypatch, source_config(feed=RSS_URL, label="HN front page"))
    assert data["label"] == "HN front page"


def test_empty_feed_raises(monkeypatch):
    empty = re.sub(rb"<item>.*?</item>", b"", RSS)
    with pytest.raises(RuntimeError, match="no headlines"):
        fetched(monkeypatch, source_config(feed=RSS_URL), feed=empty)


def test_non_feed_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="not an RSS/Atom feed"):
        fetched(monkeypatch, source_config(feed=RSS_URL), feed=b"<html><body>502 Bad Gateway</body></html>")


def test_bad_count_raises(monkeypatch):
    with pytest.raises(ValueError, match="count"):
        fetched(monkeypatch, source_config(count=0))


def test_e2e_frame_800x480_bwr(monkeypatch):
    sc = source_config(feed=RSS_URL)
    data, _ = fetched(monkeypatch, sc)
    src, ctx = sc.cls(), context_for(sc, NOW)

    async def go():
        async with Renderer() as r:
            return await frame_from_data(r, src, ctx, sc.panels[0], sc, src.check_data(data))

    png = Image.open(io.BytesIO(png_bytes(asyncio.run(go()))))
    assert png.size == (800, 480)
    assert len(png.getpalette() or []) == 3 * 3
