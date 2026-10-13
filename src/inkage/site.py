"""The Site: Manifest model, file layout, previous-Site access."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from inkage.encoders import ENCODERS

MANIFEST = "manifest.json"
# Bumped on any Manifest schema change; a previous Site with another version is treated as absent.
MANIFEST_VERSION = 3

# Fetch one Site-relative path from the previous Site; None when absent/unreachable.
type Getter = Callable[[str], bytes | None]


def iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def frame_path(source: str, panel: str, suffix: str = "png") -> str:
    return f"{source}/{panel}.{suffix}"


def sidecar_path(source: str, panel: str) -> str:
    return frame_path(source, panel, "json")


def preview_path(source: str, panel: str) -> str:
    return frame_path(source, panel, "preview.png")


def encoder_path(source: str, panel: str, encoder: str) -> str:
    return frame_path(source, panel, ENCODERS[encoder].ext)


@dataclass(slots=True)
class Entry:
    source: str
    panel: str
    # Site-relative, like every URL in the Manifest: devices join it with the base they fetched the Manifest from,
    # so a mirror of the Site needs no rewriting.
    url: str
    sha256: str | None
    generated_at: str | None
    next_due: str | None
    error: str | None = None
    # Encoder name -> {"url": ..., "sha256": ...}
    encoders: dict[str, dict[str, str]] = field(default_factory=dict)
    # Next attempt after a failure; Frame freshness stays in generated_at/next_due.
    retry_at: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.panel)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        if data["error"] is None:
            del data["error"]
        if data["retry_at"] is None:
            del data["retry_at"]
        return data

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Entry:
        return cls(**raw)


@dataclass(slots=True)
class Manifest:
    generated_at: str
    frames: list[Entry]

    def by_key(self) -> dict[tuple[str, str], Entry]:
        return {e.key: e for e in self.frames}

    def to_bytes(self) -> bytes:
        body = {
            "version": MANIFEST_VERSION,
            "generated_at": self.generated_at,
            "frames": [e.to_json() for e in self.frames],
        }
        return json.dumps(body, ensure_ascii=False, indent=2).encode() + b"\n"

    @classmethod
    def from_bytes(cls, data: bytes) -> Manifest | None:
        """Parse a Manifest; None (with a warning) when it was written by another schema version."""
        raw = json.loads(data)
        if raw.get("version") != MANIFEST_VERSION:
            logger.warning(f"previous Manifest has version {raw.get('version')!r}, expected {MANIFEST_VERSION}")
            return None
        return cls(generated_at=raw["generated_at"], frames=[Entry.from_json(e) for e in raw["frames"]])


def sidecar_bytes(entry: Entry) -> bytes:
    return json.dumps(entry.to_json(), ensure_ascii=False, indent=2).encode() + b"\n"


def http_getter(site_url: str, timeout: float = 20.0) -> Getter:
    """Read the live Site, retrying temporary gateway errors before failing.

    404 and network errors mean "absent"; other statuses fail.
    """
    client = httpx.Client(base_url=site_url.rstrip("/") + "/", timeout=timeout, follow_redirects=True)

    def get(path: str) -> bytes | None:
        try:
            resp = client.get(path, headers={"Cache-Control": "no-cache"})
            for delay in (1, 2):
                if resp.status_code not in (502, 503, 504):
                    break
                logger.warning(f"previous Site returned {resp.status_code} for {path}; retrying")
                time.sleep(delay)
                resp = client.get(path, headers={"Cache-Control": "no-cache"})
        except httpx.TransportError as e:
            logger.warning(f"previous Site unreachable for {path}: {e}")
            return None
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content

    return get
