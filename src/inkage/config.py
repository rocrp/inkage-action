"""Load and fully validate ``inkage.toml`` before anything else runs.

Every error names the offending key (e.g. ``sources.index.panels[1]``).
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from inkage.dither import Dither
from inkage.encoders import ENCODERS
from inkage.panel import PRESETS, Panel, nominal_measured
from inkage.schedule import Schedule, ScheduleError
from inkage.source import Source, load_sources


class ConfigError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class SourceConfig:
    id: str
    cls: type[Source]
    params: dict[str, Any]
    panels: tuple[Panel, ...]
    schedule: Schedule
    tz: ZoneInfo
    dither: Dither


@dataclass(slots=True, frozen=True)
class Config:
    timezone: ZoneInfo
    panels: dict[str, Panel]
    sources: tuple[SourceConfig, ...]

    def pairs(self) -> list[tuple[SourceConfig, Panel]]:
        return [(s, p) for s in self.sources for p in s.panels]


def _table(raw: Any, key: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{key}: expected a table, got {raw!r}")
    return raw


def _check_keys(raw: dict, allowed: set[str], key: str) -> None:
    if unknown := set(raw) - allowed:
        raise ConfigError(f"{key}: unknown keys {sorted(unknown)} (allowed: {sorted(allowed)})")


def _zone(name: Any, key: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ConfigError(f"{key}: unknown timezone {name!r}") from None


def _panel(pid: str, raw: dict) -> Panel:
    key = f"panels.{pid}"
    _check_keys(raw, {"preset", "width", "height", "palette", "measured", "encoders"}, key)
    try:
        if "preset" in raw:
            if spelled := {"width", "height", "palette"} & set(raw):
                raise ConfigError(f"{key}: 'preset' excludes {sorted(spelled)}")
            if (base := PRESETS.get(raw["preset"])) is None:
                raise ConfigError(f"{key}.preset: unknown Preset {raw['preset']!r} (known: {', '.join(PRESETS)})")
            width, height, palette, measured = base.width, base.height, base.palette, base.measured
        else:
            if missing := {"width", "height", "palette"} - set(raw):
                raise ConfigError(f"{key}: needs 'preset' or width/height/palette (missing {sorted(missing)})")
            width, height, palette = raw["width"], raw["height"], raw["palette"]
            measured = nominal_measured(palette)
        if "measured" in raw:
            measured = tuple(tuple(c) for c in raw["measured"])
        encoders = tuple(raw.get("encoders", ()))
        if unknown := [e for e in encoders if e not in ENCODERS]:
            raise ConfigError(f"{key}.encoders: unknown Encoder {unknown} (known: {', '.join(ENCODERS)})")
        return Panel(id=pid, width=width, height=height, palette=palette, measured=measured, encoders=encoders)
    except (ValueError, TypeError) as e:
        if isinstance(e, ConfigError):
            raise
        raise ConfigError(f"{key}: {e}") from None


def _source(
    sid: str,
    raw: dict,
    *,
    registry: dict[str, type[Source]],
    panels: dict[str, Panel],
    default_tz: ZoneInfo,
    env: Mapping[str, str],
) -> SourceConfig:
    key = f"sources.{sid}"
    name = raw.get("source", sid)
    if (cls := registry.get(name)) is None:
        raise ConfigError(f"{key}: unknown Source {name!r} (known: {', '.join(sorted(registry))})")
    _check_keys(raw, {"source", "panels", "schedule", "timezone", "dither", *cls.params}, key)

    if not isinstance(pids := raw.get("panels"), list) or not pids:
        raise ConfigError(f"{key}.panels: expected a non-empty list of Panel ids")
    resolved: list[Panel] = []
    for i, pid in enumerate(pids):
        panel = panels.get(pid) or PRESETS.get(pid)
        if panel is None:
            raise ConfigError(f"{key}.panels[{i}]: unknown Panel {pid!r} (not in [panels] nor a Preset)")
        if panel.size not in cls.sizes:
            sizes = ", ".join(f"{w}x{h}" for w, h in cls.sizes)
            raise ConfigError(
                f"{key}.panels[{i}]: Source {name!r} does not support size "
                f"{panel.width}x{panel.height} (supported: {sizes})"
            )
        resolved.append(panel)

    try:
        schedule = Schedule.parse(_table(raw["schedule"], f"{key}.schedule")) if "schedule" in raw else cls.schedule
    except ScheduleError as e:
        raise ConfigError(f"{key}.schedule: {e}") from None
    if schedule is None:
        raise ConfigError(f"{key}.schedule: Source {name!r} has no default Schedule; set one")

    try:
        dither = Dither.parse(raw.get("dither", cls.dither))
    except (ValueError, TypeError) as e:
        raise ConfigError(f"{key}.dither: {e}") from None

    for secret in cls.requires_secrets:
        if not env.get(secret):
            raise ConfigError(f"{key}: missing required secret {secret!r} (set it as an environment variable)")

    return SourceConfig(
        id=sid,
        cls=cls,
        params={k: raw.get(k, v) for k, v in cls.params.items()},
        panels=tuple(resolved),
        schedule=schedule,
        tz=_zone(raw.get("timezone", cls.timezone), f"{key}.timezone")
        if "timezone" in raw or cls.timezone
        else default_tz,
        dither=dither,
    )


def parse_config(raw: dict, sources_dir: Path | None = None, env: dict[str, str] | None = None) -> Config:
    _check_keys(raw, {"defaults", "panels", "sources"}, "<root>")
    defaults = _table(raw.get("defaults", {}), "defaults")
    _check_keys(defaults, {"timezone"}, "defaults")
    timezone = _zone(defaults.get("timezone", "UTC"), "defaults.timezone")
    panels = _panels(raw)
    try:
        registry = load_sources(sources_dir)
    except ValueError as e:
        raise ConfigError(f"sources: {e}") from None
    sources = _table(raw.get("sources", {}), "sources")
    if not sources:
        raise ConfigError("sources: no Sources configured")
    return Config(
        timezone=timezone,
        panels=panels,
        sources=tuple(
            _source(
                sid,
                _table(s, f"sources.{sid}"),
                registry=registry,
                panels=panels,
                default_tz=timezone,
                env=os.environ if env is None else env,
            )
            for sid, s in sources.items()
        ),
    )


def _read(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: TOML syntax error: {e}") from None
    except OSError as e:
        raise ConfigError(f"{path}: cannot read config: {e}") from None


def _panels(raw: dict[str, Any]) -> dict[str, Panel]:
    return {pid: _panel(pid, _table(p, f"panels.{pid}")) for pid, p in _table(raw.get("panels", {}), "panels").items()}


def load_panels(path: Path) -> dict[str, Panel]:
    """Only the [panels] table of a config, validated."""
    return _panels(_read(path))


def load_config(path: Path, sources_dir: Path | None = None, env: dict[str, str] | None = None) -> Config:
    return parse_config(_read(path), sources_dir=sources_dir, env=env)
