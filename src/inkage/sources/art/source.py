"""Daily public-domain museum art, retaining the entire work inside a white mat.

Stable local-date rotation over four verified Metropolitan Museum works;
``artwork_id`` pins another work. Eligibility is checked against the live API,
including for pinned works. API: https://metmuseum.github.io/
"""

import base64
import io
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from inkage.panel import Panel
from inkage.schedule import Schedule
from inkage.source import Context, Source

API = "https://collectionapi.metmuseum.org/public/collection/v1/objects"
DAILY_IDS = (436535, 436528, 436532, 436121)
HEADERS = {"User-Agent": "inkage/0.1 (public-domain art display)"}


async def fetch_json(url: str) -> Any:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()


async def fetch_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.content


def parse_artwork(raw: Any, expected_id: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("art: Met response must be an artwork object")
    item = raw
    if item.get("objectID") != expected_id:
        raise ValueError(f"art: Met returned a different artwork than {expected_id}")
    if item.get("isPublicDomain") is not True:
        raise ValueError(f"art: artwork {expected_id} is not marked public domain by the Met")
    for field in ("title", "artistDisplayName", "objectDate", "primaryImageSmall"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"art: artwork {expected_id} has no {field}")
    image_url = item["primaryImageSmall"]
    if not image_url.startswith("https://images.metmuseum.org/"):
        raise ValueError(f"art: artwork {expected_id} has an invalid museum image URL")
    return {
        "artwork_id": expected_id,
        "title": item["title"],
        "artist": item["artistDisplayName"],
        "date": item["objectDate"],
        "credit": "The Metropolitan Museum of Art · Public domain",
        "source": f"https://www.metmuseum.org/art/collection/search/{expected_id}",
        "image_url": image_url,
    }


def validated_image(raw: bytes) -> str:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            # Normalize to PNG so the data URL's media type is always correct.
            output = io.BytesIO()
            image.convert("RGB").save(output, format="PNG")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"art: museum returned an undecodable image: {exc}") from None
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


class Art(Source):
    schedule = Schedule.parse({"at": ["00:10"]})
    dither = "atkinson"
    params = {"artwork_id": 0}
    fields = ("title", "artist", "date", "credit", "source", "image")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        artwork_id = ctx.params["artwork_id"]
        if isinstance(artwork_id, bool) or not isinstance(artwork_id, int) or artwork_id < 0:
            raise ValueError("art: artwork_id must be a positive integer, or 0 for daily rotation")
        if artwork_id == 0:
            artwork_id = DAILY_IDS[ctx.local_now.date().toordinal() % len(DAILY_IDS)]
        data = parse_artwork(await fetch_json(f"{API}/{artwork_id}"), artwork_id)
        image = await fetch_bytes(data["image_url"])
        validated_image(image)
        return {**data, "image": image}

    def render(self, ctx: Context, panel: Panel, data: dict[str, Any]) -> str:
        return self.render_template(ctx, panel, {**data, "image_uri": validated_image(data["image"])})
