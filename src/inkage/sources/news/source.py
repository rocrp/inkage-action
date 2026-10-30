"""Headlines: Hacker News top stories, or any RSS/Atom feed.

``feed = "hn"`` uses the key-less HN Firebase API: ``topstories.json`` (ids,
ranked) then ``item/<id>.json`` for the first ``count``, fetched concurrently.
A dead or deleted item (``null``, ``dead``/``deleted`` set) is skipped. Any other
``feed`` is an RSS/Atom URL parsed by feedparser. Fewer than one headline raises.
"""

import asyncio
import calendar
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import urlsplit

import feedparser
import httpx

from inkage.schedule import Schedule
from inkage.source import Context, Source

HN_API = "https://hacker-news.firebaseio.com/v0"


class NewsError(RuntimeError):
    pass


async def fetch_hn(path: str) -> Any:
    """GET ``HN_API/<path>`` as JSON (``topstories.json``, ``item/<id>.json``)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{HN_API}/{path}")
        resp.raise_for_status()
        return resp.json()


async def fetch_feed(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def domain(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def _clock(ts: datetime, ctx: Context) -> str:
    return ts.astimezone(ctx.tz).strftime("%m-%d %H:%M")


async def hn_items(count: int, ctx: Context) -> list[dict[str, Any]]:
    ids = await fetch_hn("topstories.json")
    if not isinstance(ids, list):
        raise NewsError(f"HN topstories: expected a list, got {str(ids)[:80]!r}")
    raw = await asyncio.gather(*(fetch_hn(f"item/{i}.json") for i in ids[:count]))
    items = []
    for item in raw:
        if not item or item.get("dead") or item.get("deleted"):
            continue
        if not item.get("title") or not isinstance(item.get("time"), int):
            raise NewsError(f"HN item {item.get('id')}: missing title or time")
        items.append(
            {
                "title": item["title"],
                "source": domain(item["url"]) if item.get("url") else "news.ycombinator.com",
                "score": item.get("score", 0),
                "time": _clock(datetime.fromtimestamp(item["time"], UTC), ctx),
            }
        )
    return items


def feed_items(content: bytes, count: int, ctx: Context) -> tuple[str, list[dict[str, Any]]]:
    """(feed title, headlines) from RSS/Atom bytes; raise when nothing parses."""
    parsed = feedparser.parse(content)
    if not parsed.version:
        raise NewsError(f"not an RSS/Atom feed (parser: {parsed.get('bozo_exception')!r})")
    items = []
    for e in parsed.entries[:count]:
        if not (title := (e.get("title") or "").strip()):
            raise NewsError(f"feed entry without title: {e.get('link')!r}")
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        items.append(
            {
                "title": title,
                "source": domain(e.get("link") or ""),
                "score": None,
                "time": _clock(datetime.fromtimestamp(calendar.timegm(stamp), UTC), ctx) if stamp else "",
            }
        )
    return parsed.feed.get("title", ""), items


class News(Source):
    schedule = Schedule.parse({"every": "30m"})
    dither = "threshold"
    params: ClassVar[dict[str, Any]] = {"feed": "hn", "count": 8, "label": ""}
    fields = ("label", "items")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        feed, count = ctx.params["feed"], ctx.params["count"]
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 30:
            raise ValueError(f"news: count must be an integer 1..30, got {count!r}")
        if not isinstance(feed, str) or not feed:
            raise ValueError(f"news: feed must be 'hn' or an RSS/Atom URL, got {feed!r}")
        if feed == "hn":
            title, items = "Hacker News", await hn_items(count, ctx)
        else:
            title, items = feed_items(await fetch_feed(feed), count, ctx)
        if not items:
            raise NewsError(f"news: feed {feed!r} returned no headlines")
        return {"label": ctx.params["label"] or title or domain(feed), "items": items}
