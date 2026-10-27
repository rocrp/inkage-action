"""Config loading: the default config resolves; every invalid shape fails naming its key."""

import subprocess
import textwrap
from pathlib import Path

import pytest

from inkage.config import ConfigError, load_config, parse_config

ROOT = Path(__file__).parent.parent


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "inkage.toml"
    p.write_text(textwrap.dedent(text))
    return p


def test_cli_validate_prints_default_pairs():
    out = subprocess.run(
        ["uv", "run", "inkage", "validate", "inkage.toml"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert "calendar" in out and "800x480-bwr" in out and "250x122-bwr" in out and "800x480-spectra6" in out


def test_demo_publishes_native_portrait_for_every_source_instance():
    cfg = load_config(ROOT / "inkage.toml")
    assert {source.id for source in cfg.sources if any(panel.id == "528x792-bw" for panel in source.panels)} == {
        source.id for source in cfg.sources
    }


def test_cli_validate_exits_nonzero_on_error(tmp_path):
    cfg = write(tmp_path, "[sources.calendar]\npanels = ['nope']\n")
    res = subprocess.run(["uv", "run", "inkage", "validate", str(cfg)], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode != 0
    assert "sources.calendar.panels[0]" in res.stderr


@pytest.mark.parametrize(
    ("toml", "key"),
    [
        ("[panels.x]\npreset = 'waveshare-nope'\n[sources.calendar]\npanels = ['x']\n", "panels.x.preset"),
        ("[sources.calendar]\npanels = ['400x300-bwr']\n", "sources.calendar.panels[0]"),
        (
            "[sources.calendar]\npanels = ['800x480-bwr']\nschedule = { every = '5 minutes' }\n",
            "sources.calendar.schedule",
        ),
        (
            "[sources.calendar]\npanels = ['800x480-bwr']\nschedule = { every = '5m', at = ['00:05'] }\n",
            "sources.calendar.schedule: 'every' and 'at' are mutually exclusive",
        ),
        ("[sources.calendar]\npanels = ['800x480-bwr']\nschedule = { at = ['25:00'] }\n", "sources.calendar.schedule"),
        ("[sources.calendar]\npanels = ['800x480-bwr']\ncolour = 'red'\n", "sources.calendar"),
        ("[sources.calendar]\npanels = ['800x480-bwr']\ndither = 'blue-noise'\n", "sources.calendar.dither"),
        ("[defaults]\ntimezone = 'Mars/Olympus'\n[sources.calendar]\npanels = ['800x480-bwr']\n", "defaults.timezone"),
        ("[panels.x]\nwidth = 800\nheight = 480\npalette = 'cmyk'\n", "panels.x"),
        ("[panels.x]\npreset = '800x480-bwr'\nencoders = ['jpeg2000']\n", "panels.x.encoders"),
        ("[sources.aurora]\npanels = ['800x480-bwr']\n", "sources.aurora"),
        ("[sources.calendar\npanels = []\n", "TOML syntax error"),
    ],
)
def test_invalid_config_names_offending_key(tmp_path, toml, key):
    with pytest.raises(ConfigError, match=key.replace("[", r"\[").replace("]", r"\]")):
        load_config(write(tmp_path, toml))


def test_missing_required_secret(tmp_path):
    src = tmp_path / "sources" / "secretive"
    (src / "templates").mkdir(parents=True)
    (src / "templates" / "250x122.html").write_text("<p>x</p>")
    (src / "source.py").write_text(
        "from inkage.source import Source\nfrom inkage.schedule import Schedule\n"
        "class S(Source):\n    requires_secrets = ('API_TOKEN',)\n    schedule = Schedule.parse({'every': '1h'})\n"
    )
    raw = {"sources": {"secretive": {"panels": ["250x122-bwr"]}}}
    with pytest.raises(ConfigError, match=r"sources\.secretive.*API_TOKEN"):
        parse_config(raw, sources_dir=tmp_path / "sources", env={})
    assert parse_config(raw, sources_dir=tmp_path / "sources", env={"API_TOKEN": "x"}).sources[0].id == "secretive"


def test_panel_inline_or_preset(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            """
            [panels.inline]
            width = 250
            height = 122
            palette = "bwr"
            measured = [[20, 20, 20], [255, 255, 255], [200, 30, 30]]
            [panels.byname]
            preset = "800x480-bwr"
            [sources.calendar]
            panels = ["inline", "byname", "250x122-bw"]
            """,
        )
    )
    inline, byname, direct = cfg.sources[0].panels
    assert (inline.width, inline.height, inline.palette, inline.measured[2]) == (250, 122, "bwr", (200, 30, 30))
    assert (byname.width, byname.height, byname.palette) == (800, 480, "bwr")
    assert (direct.width, direct.height, direct.palette) == (250, 122, "bw")


def test_source_instance_with_explicit_source_and_timezone(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            """
            [sources.cal-ny]
            source = "calendar"
            timezone = "America/New_York"
            panels = ["800x480-bwr"]
            """,
        )
    )
    sc = cfg.sources[0]
    assert (sc.id, sc.cls.name, sc.tz.key) == ("cal-ny", "calendar", "America/New_York")
