"""Photo: a full-bleed photograph (a given image URL, or Bing's daily wallpaper), cover-cropped to the Panel."""

import io
import json
from typing import Any

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from inkage.panel import PRESETS, Panel
from inkage.schedule import Schedule
from inkage.source import Context, Source

BING_BASE = "https://www.bing.com"
BING_API = f"{BING_BASE}/HPImageArchive.aspx?format=js&idx=0&n=1&mkt=en-US"


async def fetch_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def parse_bing(raw: bytes) -> dict[str, str]:
    """Image URL, title and credit of today's wallpaper from the HPImageArchive JSON."""
    try:
        image = json.loads(raw)["images"][0]
        path, title, credit = image["url"], image["title"], image["copyright"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ValueError(f"Bing HPImageArchive: malformed response ({type(e).__name__}: {e})") from None
    if not (isinstance(path, str) and path.startswith("/")):
        raise ValueError(f"Bing HPImageArchive: expected a site-relative image url, got {path!r}")
    return {"url": BING_BASE + path, "title": title, "source": credit}


def decode_image(raw: bytes, url: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"{url}: body is not a decodable image ({len(raw)} bytes): {e}") from None
    return img


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale to cover ``size`` and centre-crop the overflow: no letterbox, no distortion."""
    return ImageOps.fit(img.convert("RGB"), size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))


class Photo(Source):
    sizes = tuple(sorted({p.size for p in PRESETS.values()}))
    schedule = Schedule.parse({"at": ["00:10"]})
    dither = "atkinson"
    params = {"url": ""}
    fields = ("image", "url", "source")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        if url := ctx.params["url"]:
            meta = {"url": url, "title": "", "source": url}
        else:
            meta = parse_bing(await fetch_bytes(BING_API))
        raw = await fetch_bytes(meta["url"])
        decode_image(raw, meta["url"])
        return {**meta, "image": raw}

    def render(self, ctx: Context, panel: Panel, data: dict[str, Any]) -> Image.Image:
        return cover(decode_image(data["image"], data["url"]), panel.size)
