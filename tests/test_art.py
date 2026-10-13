"""Museum eligibility, captured metadata, and preservation of the complete artwork."""

import asyncio
import base64
import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.run import context_for
from inkage.source import load_sources

ART = load_sources()["art"]
art = SimpleNamespace(**ART.fetch.__globals__)
FIX = Path(__file__).parent / "fixtures" / "art" / "met_wheat.json"
NOW = datetime(2026, 10, 13, 8, tzinfo=ZoneInfo("Asia/Singapore"))


def test_captured_van_gogh_metadata():
    # Captured from the Met 2026-10-13; values read independently from the museum record.
    data = art.parse_artwork(json.loads(FIX.read_bytes()), 436535)
    assert (data["title"], data["artist"], data["date"], data["image_url"]) == (
        "Wheat Field with Cypresses",
        "Vincent van Gogh",
        "1889",
        "https://images.metmuseum.org/CRDImages/ep/web-large/DP-42549-001.jpg",
    )


@pytest.mark.parametrize("value", [False, None, "true"])
def test_rejects_work_without_public_domain_confirmation(value):
    raw = json.loads(FIX.read_bytes())
    raw["isPublicDomain"] = value
    with pytest.raises(ValueError, match="not marked public domain"):
        art.parse_artwork(raw, 436535)


def test_image_download_error_page_fails():
    with pytest.raises(ValueError, match="undecodable image"):
        art.validated_image(b"<html>Unavailable</html>")


def test_image_normalization_keeps_all_four_corners():
    # A hand-painted corner oracle catches inadvertent cover-cropping or orientation changes.
    image = Image.new("RGB", (80, 50), "white")
    for box, color in (
        ((0, 0, 10, 10), "red"),
        ((70, 0, 80, 10), "blue"),
        ((0, 40, 10, 50), "green"),
        ((70, 40, 80, 50), "black"),
    ):
        image.paste(color, box)
    raw = io.BytesIO()
    image.save(raw, format="PNG")
    normalized = Image.open(io.BytesIO(base64.b64decode(art.validated_image(raw.getvalue()).split(",")[1])))
    assert [normalized.getpixel(point) for point in ((2, 2), (78, 2), (2, 48), (78, 48))] == [
        (255, 0, 0),
        (0, 0, 255),
        (0, 128, 0),
        (0, 0, 0),
    ]


def test_pinned_artwork_downloads_museum_image(monkeypatch):
    sc = parse_config({"sources": {"art": {"panels": ["800x480-spectra6"], "artwork_id": 436535}}}).sources[0]
    requests = []
    image = io.BytesIO()
    Image.new("RGB", (40, 60), "red").save(image, format="PNG")

    async def metadata(url):
        requests.append(url)
        return json.loads(FIX.read_bytes())

    async def download(url):
        requests.append(url)
        return image.getvalue()

    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_json", metadata)
    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_bytes", download)
    data = asyncio.run(sc.cls().fetch(context_for(sc, NOW)))
    assert requests == [
        "https://collectionapi.metmuseum.org/public/collection/v1/objects/436535",
        "https://images.metmuseum.org/CRDImages/ep/web-large/DP-42549-001.jpg",
    ]
    assert data["source"] == "https://www.metmuseum.org/art/collection/search/436535"


@pytest.mark.parametrize("value", [-1, True, "436535"])
def test_invalid_artwork_id_fails_before_network(value):
    sc = parse_config({"sources": {"art": {"panels": ["250x122-bw"], "artwork_id": value}}}).sources[0]
    with pytest.raises(ValueError, match="artwork_id"):
        asyncio.run(sc.cls().fetch(context_for(sc, NOW)))


def test_daily_selection_is_stable_until_local_midnight(monkeypatch):
    sc = parse_config({"sources": {"art": {"panels": ["250x122-bw"], "timezone": "Asia/Singapore"}}}).sources[0]
    requests = []
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(image, format="PNG")

    async def metadata(url):
        requests.append(url)
        raw = json.loads(FIX.read_bytes())
        raw["objectID"] = int(url.rsplit("/", 1)[1])
        return raw

    async def download(url):
        return image.getvalue()

    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_json", metadata)
    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_bytes", download)
    for hour, minute in ((8, 0), (15, 59), (16, 0)):
        now = datetime(2026, 10, 13, hour, minute, tzinfo=ZoneInfo("UTC"))
        asyncio.run(sc.cls().fetch(context_for(sc, now)))
    assert requests == [
        "https://collectionapi.metmuseum.org/public/collection/v1/objects/436532",
        "https://collectionapi.metmuseum.org/public/collection/v1/objects/436532",
        "https://collectionapi.metmuseum.org/public/collection/v1/objects/436121",
    ]
