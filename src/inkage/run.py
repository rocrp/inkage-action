"""The Run: decide what is due, regenerate it, carry the rest over, write the whole Site."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from loguru import logger
from PIL import Image

from inkage.config import Config, SourceConfig
from inkage.encoders import ENCODERS
from inkage.frame import check_frame, frame_to_panel, make_frame, png_bytes, preview
from inkage.gallery import gallery_html
from inkage.panel import Panel
from inkage.render import Renderer
from inkage.site import (
    MANIFEST,
    Entry,
    Getter,
    Manifest,
    encoder_path,
    frame_path,
    iso,
    parse_iso,
    preview_path,
    sidecar_bytes,
    sidecar_path,
)
from inkage.source import Context, Source


@dataclass(slots=True)
class Decision:
    source: SourceConfig
    panel: Panel
    due: bool
    reason: str
    previous: Entry | None
    next_due: datetime | None


@dataclass(slots=True)
class RunResult:
    manifest: Manifest
    decisions: list[Decision]
    errors: dict[tuple[str, str], str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def plan(config: Config, previous: Manifest | None, now: datetime) -> list[Decision]:
    """Due decision for every configured (Source, Panel); ``next_due`` assumes generation at ``now`` if due."""
    prev = previous.by_key() if previous else {}
    decisions = []
    for sc, panel in config.pairs():
        entry = prev.get((sc.id, panel.id))
        last = parse_iso(entry.generated_at) if entry else None
        due, reason = sc.schedule.is_due(now, last, sc.tz)
        if not due and entry and set(entry.encoders) != set(panel.encoders):
            due, reason = True, "encoders changed"
        basis = now if due else last
        assert basis is not None
        decisions.append(Decision(sc, panel, due, reason, entry, sc.schedule.next_due(basis, sc.tz)))
    return decisions


def _files(entry: Entry) -> list[str]:
    s, p = entry.source, entry.panel
    return [frame_path(s, p), preview_path(s, p), sidecar_path(s, p), *(encoder_path(s, p, n) for n in entry.encoders)]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def frame_from_data(
    renderer: Renderer, src: Source, ctx: Context, panel: Panel, sc: SourceConfig, data: dict
) -> Image.Image:
    out = src.render(ctx, panel, data)
    if isinstance(out, str):
        out = await renderer.html_to_image(
            out, panel.width, panel.height, base_dir=src.template_dir, scale=src.supersample
        )
    frame = make_frame(frame_to_panel(out, panel), panel, sc.dither)
    check_frame(frame, panel)
    return frame


def context_for(sc: SourceConfig, now: datetime) -> Context:
    return Context(
        now=now, tz=sc.tz, params=dict(sc.params), secrets={k: os.environ[k] for k in sc.cls.requires_secrets}
    )


async def run(config: Config, get: Getter, out: Path, now: datetime, fonts_dir: Path | None = None) -> RunResult:
    previous = Manifest.from_bytes(raw) if (raw := get(MANIFEST)) is not None else None
    if previous is None:
        logger.warning("no previous Manifest reachable; regenerating every Frame")
    decisions = plan(config, previous, now)
    files: dict[str, bytes] = {}
    entries: dict[tuple[str, str], Entry] = {}

    def carry(entry: Entry) -> bool:
        """Copy a previous Frame's files unchanged; False if any is missing."""
        got = {path: get(path) for path in _files(entry)}
        if any(v is None for v in got.values()):
            return False
        files.update(got)  # type: ignore[arg-type]
        return True

    due: list[Decision] = []
    for d in decisions:
        if not d.due and d.previous and d.previous.sha256 and carry(d.previous):
            entries[d.previous.key] = d.previous
        else:
            if not d.due:
                d.due, d.reason = True, "previous Frame unavailable"
                d.next_due = d.source.schedule.next_due(now, d.source.tz)
            due.append(d)

    errors: dict[tuple[str, str], str] = {}

    def fail(sc: SourceConfig, d: Decision, error: str) -> None:
        """Keep the previous Frame (if any) and record the error in its entry."""
        key = (sc.id, d.panel.id)
        errors[key] = error
        logger.error(f"{sc.id}/{d.panel.id}: {error}")
        old = d.previous
        kept = old if old and old.sha256 and carry(old) else None
        entries[key] = replace(kept, error=error) if kept else _failed_entry(sc, d.panel, error)
        files[sidecar_path(*key)] = sidecar_bytes(entries[key])

    async with Renderer(fonts_dir) as renderer:
        for sc in {d.source.id: d.source for d in due}.values():
            ctx = context_for(sc, now)
            src = sc.cls()
            mine = [d for d in due if d.source is sc]
            try:
                data = src.check_data(await src.fetch(ctx))
            except Exception as e:  # noqa: BLE001 - one Source's runtime failure must not stop the Run
                for d in mine:
                    fail(sc, d, _describe(e))
                continue
            for d in mine:
                try:
                    frame = await frame_from_data(renderer, src, ctx, d.panel, sc, data)
                except Exception as e:  # noqa: BLE001
                    fail(sc, d, _describe(e))
                    continue
                entries[(sc.id, d.panel.id)] = _write_frame(files, frame, sc, d, now)
                logger.info(f"{sc.id}/{d.panel.id}: generated ({d.reason})")

    manifest = Manifest(generated_at=iso(now) or "", frames=[entries[(d.source.id, d.panel.id)] for d in decisions])
    files[MANIFEST] = manifest.to_bytes()
    files["index.html"] = gallery_html(manifest).encode()
    files[".nojekyll"] = b""
    for path, data in files.items():
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(data)
    return RunResult(manifest=manifest, decisions=decisions, errors=errors)


def _describe(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


def _failed_entry(sc: SourceConfig, panel: Panel, error: str) -> Entry:
    return Entry(
        source=sc.id,
        panel=panel.id,
        url=frame_path(sc.id, panel.id),
        sha256=None,
        generated_at=None,
        next_due=None,
        error=error,
    )


def _write_frame(files: dict[str, bytes], frame: Image.Image, sc: SourceConfig, d: Decision, now: datetime) -> Entry:
    s, p = sc.id, d.panel.id
    png = png_bytes(frame)
    files[frame_path(s, p)] = png
    files[preview_path(s, p)] = png_bytes(preview(frame))
    encoders = {}
    for name in d.panel.encoders:
        blob = ENCODERS[name].encode(frame, d.panel.ink_count)
        files[encoder_path(s, p, name)] = blob
        encoders[name] = {"url": encoder_path(s, p, name), "sha256": _sha(blob)}
    entry = Entry(
        source=s,
        panel=p,
        url=frame_path(s, p),
        sha256=_sha(png),
        generated_at=iso(now),
        next_due=iso(d.next_due),
        encoders=encoders,
    )
    files[sidecar_path(s, p)] = sidecar_bytes(entry)
    return entry
