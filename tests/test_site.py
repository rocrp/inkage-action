"""Regression: Pages returned 503 for a carried preview and broke the Chain."""

import httpx
import pytest

from inkage import site


def getter_with_responses(monkeypatch, statuses):
    responses = iter(statuses)

    def respond(request):
        return httpx.Response(next(responses), content=b"previous frame", request=request)

    client_type = httpx.Client
    monkeypatch.setattr(
        site.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs)
    )
    monkeypatch.setattr(site.time, "sleep", lambda _: None)
    return site.http_getter("https://rocrp.github.io/inkage-action/")


def test_pages_503_recovery_retains_the_previous_frame(monkeypatch):
    # Observed 2026-10-13, run 38350026567, github_ci/800x480-bwr.preview.png.
    get = getter_with_responses(monkeypatch, [503, 503, 200])
    assert get("github_ci/800x480-bwr.preview.png") == b"previous frame"


def test_persistent_gateway_error_fails_after_bounded_retries(monkeypatch):
    get = getter_with_responses(monkeypatch, [503, 503, 503])
    with pytest.raises(httpx.HTTPStatusError, match="503"):
        get("github_ci/800x480-bwr.preview.png")


def test_missing_previous_frame_is_absent(monkeypatch):
    assert getter_with_responses(monkeypatch, [404])("missing.png") is None


def test_nontransient_status_fails_without_retry(monkeypatch):
    get = getter_with_responses(monkeypatch, [403])
    with pytest.raises(httpx.HTTPStatusError, match="403"):
        get("manifest.json")
