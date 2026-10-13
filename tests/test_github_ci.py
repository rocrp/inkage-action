"""Anonymous Actions response captured 2026-10-13; status vs conclusion semantics."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from inkage.config import parse_config
from inkage.run import context_for

FIXTURE = Path(__file__).parent / "fixtures/github_ci/runs.json"
NOW = datetime(2026, 10, 13, 3, 15, tzinfo=UTC)


def fetch(monkeypatch, raw, **params):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=raw)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    sc = parse_config({"sources": {"github_ci": {"panels": ["800x480-bwr"], **params}}}).sources[0]
    return asyncio.run(sc.cls().fetch(context_for(sc, NOW))), requests


def test_capture_has_running_and_finished_runs(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "unused")  # This Source never depends on workflow authentication.
    data, requests = fetch(monkeypatch, json.loads(FIXTURE.read_text()), branch="main")
    assert [(r["name"], r["state"]) for r in data["runs"]] == [("inkage", "IN PROGRESS")] + [("inkage", "SUCCESS")] * 4
    assert (data["runs"][0]["sha"], data["runs"][0]["updated"]) == ("93f7f58", "10-13 03:11")
    assert dict(requests[0].url.params) == {"per_page": "5", "branch": "main"}
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize(
    ("status", "conclusion", "label", "failed"),
    [
        ("completed", "failure", "FAILURE", True),
        ("completed", "cancelled", "CANCELLED", False),
        ("completed", "timed_out", "TIMED OUT", True),
        ("queued", None, "QUEUED", False),
    ],
)
def test_run_state_is_not_always_the_conclusion(monkeypatch, status, conclusion, label, failed):
    raw = json.loads(FIXTURE.read_text())
    raw["workflow_runs"][0].update(status=status, conclusion=conclusion)
    data, _ = fetch(monkeypatch, raw)
    assert (data["runs"][0]["state"], data["runs"][0]["failed"]) == (label, failed)


def test_completed_run_without_conclusion_raises(monkeypatch):
    raw = json.loads(FIXTURE.read_text())
    raw["workflow_runs"][0]["status"] = "completed"  # Truncated/inconsistent upstream response.
    with pytest.raises(RuntimeError, match="invalid conclusion"):
        fetch(monkeypatch, raw)


def test_no_runs_is_valid(monkeypatch):
    data, _ = fetch(monkeypatch, {"total_count": 0, "workflow_runs": []})
    assert data["runs"] == []


def test_missing_runs_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="malformed workflow run"):
        fetch(monkeypatch, {"total_count": 4})
