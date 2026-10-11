"""``inkage`` command line: validate, plan, convert, render, run."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger
from PIL import Image

from inkage.config import Config, ConfigError, SourceConfig, load_config, load_panels, parse_config
from inkage.dither import Dither
from inkage.frame import Framing, make_frame, png_bytes, preview
from inkage.panel import PRESETS
from inkage.render import Renderer
from inkage.run import RunResult, context_for, frame_from_data, plan, run
from inkage.site import Manifest, http_getter, iso

# Exit code when a Source failed at runtime but the Site was still written (config errors exit 2).
SOURCE_FAILED = 3

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)

ConfigOpt = Annotated[Path, typer.Option("--config", "-c", help="Path to inkage.toml")]
SourcesOpt = Annotated[Path | None, typer.Option(help="Directory of custom Sources")]
FontsOpt = Annotated[Path | None, typer.Option(help="Directory of fonts available to templates")]
NowOpt = Annotated[str | None, typer.Option(help="Override 'now' (ISO 8601 with offset)")]


def _now(text: str | None) -> datetime:
    if text is None:
        return datetime.now(UTC)
    t = datetime.fromisoformat(text)
    if t.tzinfo is None:
        raise typer.BadParameter(f"--now needs a UTC offset, got {text!r}")
    return t


@contextmanager
def _config_errors() -> Iterator[None]:
    """Config errors exit 2 with the message naming the offending key."""
    try:
        yield
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2) from None


def _load(config: Path, sources_dir: Path | None) -> Config:
    with _config_errors():
        return load_config(config, sources_dir=sources_dir)


@app.command()
def validate(config: Annotated[Path, typer.Argument()], sources_dir: SourcesOpt = None) -> None:
    """Validate a config and print every resolved (Source, Panel) pair."""
    cfg = _load(config, sources_dir)
    for sc, p in cfg.pairs():
        typer.echo(
            f"{sc.id:<12} {p.id:<18} {p.width}x{p.height} {p.palette}({p.ink_count}) "
            f"{sc.schedule.describe()} [{sc.tz.key}] dither={sc.dither.method}"
            + (f" encoders={','.join(p.encoders)}" if p.encoders else "")
        )


@app.command("plan")
def plan_cmd(
    config: ConfigOpt = Path("inkage.toml"),
    manifest: Annotated[Path | None, typer.Option(help="Previous manifest.json (omit = none)")] = None,
    sources_dir: SourcesOpt = None,
    now: NowOpt = None,
) -> None:
    """Print due / not-due per Frame with the reason and next_due."""
    cfg = _load(config, sources_dir)
    previous = Manifest.from_bytes(manifest.read_bytes()) if manifest else None
    for d in plan(cfg, previous, _now(now)):
        state = "DUE " if d.due else "skip"
        typer.echo(f"{state} {d.source.id:<12} {d.panel.id:<18} next_due={iso(d.next_due)}  ({d.reason})")


@app.command()
def convert(
    image: Annotated[Path, typer.Argument()],
    panel: Annotated[str, typer.Option(help="Preset id, or a [panels] id from --config")],
    dither: Annotated[str, typer.Option(help="Dither method")] = "floyd-steinberg",
    framing: Annotated[Framing, typer.Option(help="fill (crop) or fit (letterbox)")] = "fill",
    config: Annotated[Path | None, typer.Option("--config", "-c", help="inkage.toml defining Panels")] = None,
    out_dir: Annotated[Path, typer.Option()] = Path("."),
) -> None:
    """Convert an RGB image into a Frame (indexed PNG) plus Preview."""
    panels = dict(PRESETS)
    if config is not None:
        with _config_errors():
            panels |= load_panels(config)
    if (p := panels.get(panel)) is None:
        raise typer.BadParameter(f"unknown Panel {panel!r} (known: {', '.join(panels)})")
    frame = make_frame(Image.open(image), p, Dither.parse(dither), framing)
    _write(out_dir, f"{image.stem}.{p.id}", frame)


@app.command()
def render(
    source: Annotated[str, typer.Argument()],
    panel: Annotated[str, typer.Option(help="Preset id")],
    out_dir: Annotated[Path, typer.Option()] = Path("."),
    timezone: Annotated[str, typer.Option()] = "Asia/Shanghai",
    sources_dir: SourcesOpt = None,
    fonts_dir: FontsOpt = None,
    now: NowOpt = None,
) -> None:
    """Render one Source for one Preset with its default settings."""
    raw = {"defaults": {"timezone": timezone}, "sources": {source: {"panels": [panel]}}}
    with _config_errors():
        sc = parse_config(raw, sources_dir=sources_dir).sources[0]
    frame = asyncio.run(_render_one(sc, _now(now), fonts_dir))
    _write(out_dir, f"{source}.{panel}", frame)


async def _render_one(sc: SourceConfig, now: datetime, fonts_dir: Path | None) -> Image.Image:
    ctx = context_for(sc, now)
    src = sc.cls()
    data = src.check_data(await src.fetch(ctx))
    async with Renderer(fonts_dir) as renderer:
        return await frame_from_data(renderer, src, ctx, sc.panels[0], sc, data)


def _write(out_dir: Path, stem: str, frame: Image.Image) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.png").write_bytes(png_bytes(frame))
    (out_dir / f"{stem}.preview.png").write_bytes(png_bytes(preview(frame)))
    typer.echo(f"wrote {out_dir / stem}.png and .preview.png")


@app.command("run")
def run_cmd(
    config: ConfigOpt = Path("inkage.toml"),
    site_url: Annotated[str, typer.Option(help="Live Site URL holding the previous Manifest ('' = none)")] = "",
    out: Annotated[Path, typer.Option(help="Output directory for the Site")] = Path("dist"),
    sources_dir: SourcesOpt = None,
    fonts_dir: FontsOpt = None,
    now: NowOpt = None,
) -> None:
    """Regenerate due Frames, carry the rest over, write the full Site."""
    cfg = _load(config, sources_dir)
    get = http_getter(site_url) if site_url else (lambda _path: None)
    result = asyncio.run(run(cfg, get, out, _now(now), site_url=site_url, fonts_dir=fonts_dir))
    _summary(result)
    if not result.ok:
        typer.echo(f"{len(result.errors)} Frame(s) failed; Site written with previous Frames kept", err=True)
        raise typer.Exit(SOURCE_FAILED)


def _summary(result: RunResult) -> None:
    lines = ["| Source | Panel | Status | Generated | Next due |", "|---|---|---|---|---|"]
    entries = result.manifest.by_key()
    for d in result.decisions:
        e = entries[(d.source.id, d.panel.id)]
        status = f"❌ {e.error}" if e.error else ("regenerated" if d.due else "carried over")
        lines.append(f"| {e.source} | {e.panel} | {status} | {e.generated_at or '—'} | {e.next_due or '—'} |")
    text = "\n".join(lines) + "\n"
    typer.echo(text)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write("## Inkage Run\n\n" + text)


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, format="{level: <7} {message}", level="INFO")
    app()
