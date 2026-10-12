"""photo Source: real Bing capture parsed by hand, cover-crop geometry, undecodable body, Spectra 6 E2E."""

import asyncio
import io
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data
from inkage.source import load_sources

FIX = Path(__file__).parent / "fixtures" / "photo"
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
PHOTO = load_sources()["photo"]
photo = SimpleNamespace(**PHOTO.fetch.__globals__)  # the loaded source.py's names (it is not in sys.modules)


def source_config(panel: str, **params):
    return parse_config({"sources": {"photo": {"panels": [panel], **params}}}).sources[0]


def fetched(monkeypatch, sc, responses: dict[str, bytes]) -> dict:
    async def fake(url: str) -> bytes:
        return responses[url]

    monkeypatch.setitem(sc.cls.fetch.__globals__, "fetch_bytes", fake)  # each config load re-executes source.py
    return asyncio.run(sc.cls().fetch(context_for(sc, NOW)))


def test_parse_bing_capture():
    # Read off tests/fixtures/photo/bing.json (captured 2026-10-12; Bing served the zh-CN market).
    meta = photo.parse_bing((FIX / "bing.json").read_bytes())
    assert meta == {
        "url": "https://www.bing.com/th?id=OHR.MumblesSwansea2026_ZH-CN5419531039_1920x1080.jpg"
        "&rf=LaDigue_1920x1080.jpg&pid=hp",
        "title": "从铁轨到潮汐",
        "source": "曼布尔斯码头，斯旺西，威尔士 (© Helen Hotson/Shutterstock)",
    }


def test_bing_without_images_raises():
    with pytest.raises(ValueError, match="malformed"):
        photo.parse_bing(b'{"images": []}')


def test_cover_crop_lands_patch_at_hand_computed_box():
    # 1600x900 -> 800x480. Aspect 16:9 is wider than 5:3, so height binds: scale 480/900 = 8/15,
    # the source keeps a 900*5/3 = 1500 wide centre window, cutting 50 px from each side.
    # Source x -> output (x - 50) * 8/15; y -> y * 8/15.
    #   blue  x 0..40      -> entirely cut away
    #   green x 50..110    -> output x 0..32
    #   red   x 800..1100, y 300..600 -> output x 400..560, y 160..320
    img = Image.new("RGB", (1600, 900), (255, 255, 255))
    img.paste((0, 0, 255), (0, 0, 40, 900))
    img.paste((0, 255, 0), (50, 0, 110, 900))
    img.paste((255, 0, 0), (800, 300, 1100, 600))
    out = np.asarray(photo.cover(img, (800, 480))).astype(int)
    assert out.shape == (480, 800, 3)

    def is_(xy, rgb):
        x, y = xy
        return np.abs(out[y, x] - rgb).max() < 40

    red, white, green = (255, 0, 0), (255, 255, 255), (0, 255, 0)
    for xy in [(404, 164), (556, 164), (404, 316), (556, 316), (480, 240)]:
        assert is_(xy, red), xy
    for xy in [(396, 240), (564, 240), (480, 156), (480, 324)]:  # just outside the box
        assert is_(xy, white), xy
    for xy in [(0, 0), (28, 240), (0, 479)]:
        assert is_(xy, green), xy
    assert is_((36, 240), white)
    assert not ((out[..., 2] > 200) & (out[..., 0] < 60) & (out[..., 1] < 60)).any(), "blue strip survived"


def test_undecodable_body_raises(monkeypatch):
    sc = source_config("800x480-spectra6", url="https://example.com/a.jpg")
    with pytest.raises(ValueError, match="not a decodable image"):
        fetched(monkeypatch, sc, {"https://example.com/a.jpg": b"<html>404</html>"})


def test_e2e_bing_photo_on_spectra6(monkeypatch):
    sc = source_config("800x480-spectra6")
    assert sc.dither.method == "atkinson"
    # Six vertical bands in the Spectra 6 inks so the dithered Frame must use every index.
    bands = [(0, 0, 0), (255, 255, 255), (200, 40, 40), (255, 240, 40), (40, 80, 200), (60, 120, 60)]
    img = Image.new("RGB", (1920, 1080))
    for i, c in enumerate(bands):
        img.paste(c, (i * 320, 0, (i + 1) * 320, 1080))
    meta = photo.parse_bing((FIX / "bing.json").read_bytes())
    data = fetched(monkeypatch, sc, {photo.BING_API: (FIX / "bing.json").read_bytes(), meta["url"]: png_bytes(img)})
    data = sc.cls.check_data(data)
    assert data["title"] == "从铁轨到潮汐"

    async def go():
        async with Renderer() as r:
            return await frame_from_data(r, sc.cls(), context_for(sc, NOW), sc.panels[0], sc, data)

    frame = Image.open(io.BytesIO(png_bytes(asyncio.run(go()))))
    assert frame.size == (800, 480)
    assert len(frame.getpalette() or []) == 3 * 6
    assert set(np.unique(np.asarray(frame))) == {0, 1, 2, 3, 4, 5}


def test_every_preset_size_is_supported():
    for pid in ("250x122-bw", "400x600-spectra6", "648x480-bwry"):
        assert source_config(pid).panels[0].id == pid
