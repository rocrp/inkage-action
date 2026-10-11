"""The Site: Manifest model, file layout, previous-Site access, and the gallery page."""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from inkage.encoders import ENCODERS

MANIFEST = "manifest.json"
# Bumped on any Manifest schema change; a previous Site with another version is treated as absent.
MANIFEST_VERSION = 1

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
    url: str
    sha256: str | None
    generated_at: str | None
    next_due: str | None
    error: str | None = None
    # Encoder name -> {"url": ..., "sha256": ...}
    encoders: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.panel)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        if data["error"] is None:
            del data["error"]
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
    """Getter over the live Site. 404 and network errors mean "absent"; other statuses fail."""
    client = httpx.Client(base_url=site_url.rstrip("/") + "/", timeout=timeout, follow_redirects=True)

    def get(path: str) -> bytes | None:
        try:
            resp = client.get(path, headers={"Cache-Control": "no-cache"})
        except httpx.TransportError as e:
            logger.warning(f"previous Site unreachable for {path}: {e}")
            return None
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content

    return get


def gallery_html(manifest: Manifest) -> str:
    """Self-contained gallery: every Frame's Preview, URL and times. Only Site-relative requests."""
    cards = []
    for e in manifest.frames:
        preview = preview_path(e.source, e.panel)
        img = f'<img src="{html.escape(preview)}" alt="">' if e.sha256 else "<div class=missing>no frame yet</div>"
        links = [f'<a href="{html.escape(frame_path(e.source, e.panel))}">png</a>']
        links += [
            f'<a href="{html.escape(encoder_path(e.source, e.panel, name))}">{html.escape(name)}</a>'
            for name in e.encoders
        ]
        links.append(f'<a href="{html.escape(sidecar_path(e.source, e.panel))}">json</a>')
        error = f"<p class=error>error: {html.escape(e.error)}</p>" if e.error else ""
        cards.append(
            f"<figure>{img}<figcaption><b>{html.escape(e.source)}</b> · {html.escape(e.panel)}<br>"
            f"<code>{html.escape(e.url)}</code><br>generated {e.generated_at or '—'} · next {e.next_due or '—'}<br>"
            f"{' · '.join(links)}{error}</figcaption></figure>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inkage Frames</title>
<style>
:root{{color-scheme:light dark;--bg:#f6f6f4;--fg:#1d1d1b;--card:#fff;--muted:#6b6b66;--err:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1b1b1a;--fg:#ececea;--card:#262624;--muted:#a3a39e;--err:#f2b8b5}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
main{{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr))}}
figure{{margin:0;padding:12px;background:var(--card);border-radius:8px}}
img{{max-width:100%;image-rendering:pixelated;border:1px solid var(--muted)}}
figcaption{{margin-top:8px;color:var(--muted);word-break:break-all}} b{{color:var(--fg)}}
.error{{color:var(--err);margin:4px 0 0}} .missing{{padding:32px;text-align:center;border:1px dashed var(--muted)}}
</style></head><body>
<h1>Inkage Frames</h1><p>Manifest generated {manifest.generated_at} · <a href="{MANIFEST}">manifest.json</a></p>
<main>{"".join(cards)}</main>
</body></html>
"""
