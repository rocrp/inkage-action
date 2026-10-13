"""Statuspage summary from an anonymous GitHub Status capture, 2026-10-13."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from inkage.config import parse_config
from inkage.run import context_for

FIXTURE = Path(__file__).parent / "fixtures/status/github_summary.json"
NOW = datetime(2026, 10, 13, 3, 15, tzinfo=UTC)


def fetch(monkeypatch, raw):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=raw)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    sc = parse_config({"sources": {"status": {"panels": ["800x480-bwr"]}}}).sources[0]
    return asyncio.run(sc.cls().fetch(context_for(sc, NOW))), requests


def test_public_summary_capture(monkeypatch):
    data, requests = fetch(monkeypatch, json.loads(FIXTURE.read_text()))
    assert (data["label"], data["headline"], data["affected"], data["incidents"]) == ("GitHub", "OPERATIONAL", 0, [])
    assert len(data["components"]) == 11  # Capture has one non-showcase information component.
    assert str(requests[0].url) == "https://www.githubstatus.com/api/v2/summary.json"
    assert "authorization" not in requests[0].headers


def test_outage_has_priority_over_healthy_components(monkeypatch):
    # Statuspage's documented states: the provider rollup is authoritative; affected components go first.
    raw = json.loads(FIXTURE.read_text())
    raw["status"] = {"indicator": "major", "description": "Partial System Outage"}
    raw["components"][6]["status"] = "partial_outage"  # Actions
    raw["incidents"] = [{"name": "Delayed workflow starts", "status": "investigating"}]
    data, _ = fetch(monkeypatch, raw)
    assert (data["headline"], data["alert"], data["affected"]) == ("PARTIAL OUTAGE", True, 1)
    assert data["components"][0] == {"name": "Actions", "state": "Partial outage", "severity": 3}
    assert data["incidents"] == [{"name": "Delayed workflow starts", "state": "investigating"}]


@pytest.mark.parametrize("damage", ["components", "indicator", "component_status"])
def test_incomplete_summary_never_becomes_healthy(monkeypatch, damage):
    raw = json.loads(FIXTURE.read_text())
    if damage == "components":
        del raw["components"]
    elif damage == "indicator":
        raw["status"]["indicator"] = "unknown"
    else:
        raw["components"][0]["status"] = "unknown"
    with pytest.raises(RuntimeError, match="status:"):
        fetch(monkeypatch, raw)
