"""Source API and the Source registry (built-in + consumer ``sources_dir``).

A Source lives in ``<dir>/<name>/``: an optional ``source.py`` defining one
``Source`` subclass, and ``templates/<w>x<h>.html`` Jinja2 layouts. A Source
with templates but no Python is template-only: its sizes come from its
template file names and its Schedule must be given in the config.
"""

import importlib.util
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import jinja2
from PIL import Image

from inkage.dither import Dither
from inkage.panel import NOMINAL, Panel
from inkage.schedule import Schedule

BUILTIN_DIR = Path(__file__).parent / "sources"
_TEMPLATE_NAME = re.compile(r"^(\d+)x(\d+)\.html$")


class IncompleteData(RuntimeError):
    pass


@dataclass(slots=True)
class Context:
    now: datetime
    tz: ZoneInfo
    params: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)

    @property
    def local_now(self) -> datetime:
        return self.now.astimezone(self.tz)


class Source:
    # Declared by subclasses.
    sizes: ClassVar[tuple[tuple[int, int], ...]] = ()
    schedule: ClassVar[Schedule | None] = None
    dither: ClassVar[str | dict | Dither] = "threshold"
    requires_secrets: ClassVar[tuple[str, ...]] = ()
    params: ClassVar[dict[str, Any]] = {}
    # Keys ``fetch`` must return with a non-empty value; checked before render.
    fields: ClassVar[tuple[str, ...]] = ()
    # IANA zone the Schedule and display use, unless the config sets one; None = config default.
    timezone: ClassVar[str | None] = None
    # Render at N× the Panel size, then downsample (photo-like Sources).
    supersample: ClassVar[int] = 1
    # Set by the loader.
    name: ClassVar[str] = ""
    root: ClassVar[Path] = Path()

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        return {}

    @property
    def template_dir(self) -> Path:
        return self.root / "templates"

    def render(self, ctx: Context, panel: Panel, data: dict[str, Any]) -> str | Image.Image:
        """Default: the Jinja2 template ``<template_dir>/<w>x<h>.html``."""
        return self.render_template(ctx, panel, data)

    def render_template(self, ctx: Context, panel: Panel, data: dict[str, Any]) -> str:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.template_dir),
            undefined=jinja2.StrictUndefined,
            autoescape=True,
        )
        template = env.get_template(f"{panel.width}x{panel.height}.html")
        return template.render(
            data=data,
            now=ctx.local_now,
            params=ctx.params,
            panel=panel,
            ink={name: "#{:02x}{:02x}{:02x}".format(*NOMINAL[name]) for name in panel.inks},
        )

    @classmethod
    def check_data(cls, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise IncompleteData(f"source {cls.name!r}: fetch returned {type(data).__name__}, expected dict")
        if missing := [k for k in cls.fields if data.get(k) in (None, "")]:
            raise IncompleteData(f"source {cls.name!r}: fetch returned no value for {missing}")
        return data


def _template_sizes(root: Path) -> tuple[tuple[int, int], ...]:
    tdir = root / "templates"
    found = (_TEMPLATE_NAME.match(p.name) for p in tdir.iterdir()) if tdir.is_dir() else ()
    return tuple(sorted((int(m.group(1)), int(m.group(2))) for m in found if m))


def _load_one(root: Path) -> type[Source]:
    name = root.name
    if (py := root / "source.py").is_file():
        spec = importlib.util.spec_from_file_location(f"inkage_source_{name}", py)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        classes = [
            c
            for c in vars(module).values()
            if isinstance(c, type) and issubclass(c, Source) and c is not Source and c.__module__ == module.__name__
        ]
        if len(classes) != 1:
            raise ValueError(f"{py}: expected exactly one Source subclass, found {len(classes)}")
        cls = classes[0]
    else:
        cls = type(f"TemplateSource_{name}", (Source,), {})
    cls.name, cls.root = name, root
    if not cls.sizes:
        cls.sizes = _template_sizes(root)
    if not cls.sizes:
        raise ValueError(f"source {name!r} ({root}): no sizes declared and no templates/<w>x<h>.html found")
    return cls


def load_sources(extra_dir: Path | None = None) -> dict[str, type[Source]]:
    """Discover built-in Sources and those in ``extra_dir``; a name collision fails."""
    registry: dict[str, type[Source]] = {}
    for base in (BUILTIN_DIR, extra_dir):
        if base is None:
            continue
        if not base.is_dir():
            raise ValueError(f"sources dir {base} does not exist")
        for root in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
            if root.name in registry:
                raise ValueError(
                    f"source {root.name!r} in {root} collides with {registry[root.name].root}; rename the custom Source"
                )
            registry[root.name] = _load_one(root)
    return registry
