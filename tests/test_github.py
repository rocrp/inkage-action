"""github Source: real REST captures read by hand through a mock transport, 404 release, auth, E2E."""

import asyncio
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from PIL import Image

from inkage.config import parse_config
from inkage.frame import png_bytes
from inkage.render import Renderer
from inkage.run import context_for, frame_from_data

FIX = Path(__file__).parent / "fixtures" / "github"
NOW = datetime(2026, 10, 12, 11, 10, tzinfo=ZoneInfo("Asia/Shanghai"))  # capture time
REPO = "/repos/rocrp/inkage-action"
# Captured 2026-10-12: inkage-action has no release (real 404 body); uv's latest release stands in for one.
ROUTES = {
    REPO: (200, (FIX / "repo.json").read_bytes()),
    f"{REPO}/commits": (200, (FIX / "commits.json").read_bytes()),
    f"{REPO}/releases/latest": (404, (FIX / "release_404.json").read_bytes()),
}
UV_RELEASE = (200, (FIX / "release_uv.json").read_bytes())


def source_config(panel: str = "800x480-bwr", **params):
    return parse_config({"sources": {"github": {"panels": [panel], "timezone": "Asia/Shanghai", **params}}}).sources[0]


def fetched(monkeypatch, routes: dict[str, tuple[int, bytes]], sc=None) -> tuple[dict, list[httpx.Request]]:
    """Run the real fetch against GitHub answering from fixtures; return data and the requests sent."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        assert request.url.host == "api.github.com"
        status, body = routes[request.url.path]
        return httpx.Response(status, content=body)

    real = httpx.AsyncClient

    def client(**kw):
        return real(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    sc = sc or source_config()
    return asyncio.run(sc.cls().fetch(context_for(sc, NOW))), sent


def test_parse_repo_without_release(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    data, sent = fetched(monkeypatch, ROUTES)
    # Read off repo.json / commits.json; UTC 15:54 is 23:54 in Asia/Shanghai.
    assert data == {
        "repo": "rocrp/inkage-action",
        "description": "",  # null in the capture
        "language": "Python",
        "stars": 0,
        "forks": 0,
        "open_issues": 3,
        "pushed_at": "2026-10-11 23:54",
        "commit_message": "fix: address review — tick-sized tolerance, Manifest version, carry Sidecar bytes, "
        "encoder changes",
        "commit_author": "RoCry",
        "commit_date": "2026-10-11 23:54",
        "commit_sha": "088a1d7",
        "release": "",
        "release_date": "",
    }
    assert sent[1].url.params["per_page"] == "1"
    assert all("authorization" not in r.headers for r in sent)


def test_latest_release_and_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")
    routes = {**ROUTES, f"{REPO}/releases/latest": UV_RELEASE}
    data, sent = fetched(monkeypatch, routes)
    # uv 0.13.0 published 2026-10-09T19:49:55Z = 2026-10-10 03:49 Asia/Shanghai.
    assert (data["release"], data["release_date"]) == ("0.13.0", "2026-10-10 03:49")
    assert {r.headers["authorization"] for r in sent} == {"Bearer ghs_test"}


def test_missing_repo_raises(monkeypatch):
    # A 404 on the repo itself (not the release) is an error.
    routes = {**ROUTES, REPO: ROUTES[f"{REPO}/releases/latest"]}
    with pytest.raises(httpx.HTTPStatusError, match="404"):
        fetched(monkeypatch, routes)


@pytest.mark.parametrize("key", ["stargazers_count", "pushed_at"])
def test_missing_core_field_raises(monkeypatch, key):
    repo = json.loads(ROUTES[REPO][1])
    del repo[key]
    with pytest.raises(RuntimeError, match="missing stargazers_count or pushed_at"):
        fetched(monkeypatch, {**ROUTES, REPO: (200, json.dumps(repo).encode())})


def test_bad_repo_param_raises(monkeypatch):
    with pytest.raises(ValueError, match="owner/name"):
        fetched(monkeypatch, ROUTES, source_config(repo="inkage-action"))


def test_e2e_frame_800x480_bwr(monkeypatch):
    sc = source_config()
    data, _ = fetched(monkeypatch, {**ROUTES, f"{REPO}/releases/latest": UV_RELEASE}, sc)
    src, ctx = sc.cls(), context_for(sc, NOW)

    async def go():
        async with Renderer() as r:
            return await frame_from_data(r, src, ctx, sc.panels[0], sc, src.check_data(data))

    png = Image.open(io.BytesIO(png_bytes(asyncio.run(go()))))
    assert png.size == (800, 480)
    assert len(png.getpalette() or []) == 3 * 3
