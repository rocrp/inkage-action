"""The Run: carry-over, Manifest, failure isolation, gallery. Fixture Sources render with Pillow."""

import asyncio
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from inkage.config import parse_config
from inkage.run import RunResult, run

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
ROOT = Path(__file__).parent.parent
SH = ZoneInfo("Asia/Shanghai")
T0 = datetime(2026, 10, 12, 8, 0, tzinfo=SH)
T1 = datetime(2026, 10, 12, 8, 6, tzinfo=SH)


def config(fail: bool = False):
    return parse_config(
        {
            "defaults": {"timezone": "Asia/Shanghai"},
            "sources": {
                "clock": {"panels": ["250x122-bw"]},
                "daily": {"panels": ["250x122-bw", "250x122-bwr"]},
                "flaky": {"panels": ["250x122-bwr"], "fail": fail},
            },
        },
        sources_dir=FIXTURES,
    )


def site_getter(site: Path):
    def get(path: str) -> bytes | None:
        p = site / path
        return p.read_bytes() if p.is_file() else None

    return get


def tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def do_run(cfg, get, out: Path, now: datetime) -> RunResult:
    return asyncio.run(run(cfg, get, out, now, site_url="https://example.test/site"))


def test_no_previous_site_generates_everything(tmp_path):
    result = do_run(config(), lambda _p: None, tmp_path, T0)
    assert result.ok
    assert all(d.due for d in result.decisions)
    for f in ("clock/250x122-bw", "daily/250x122-bw", "daily/250x122-bwr", "flaky/250x122-bwr"):
        for suffix in (".png", ".preview.png", ".json"):
            assert (tmp_path / f"{f}{suffix}").is_file()


def test_only_due_frame_changes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    do_run(config(), lambda _p: None, a, T0)
    # 6 minutes later: clock and flaky (every 5m) are due, daily (at 00:05) is not.
    cfg = parse_config(
        {
            "defaults": {"timezone": "Asia/Shanghai"},
            "sources": {"clock": {"panels": ["250x122-bw"]}, "daily": {"panels": ["250x122-bw", "250x122-bwr"]}},
        },
        sources_dir=FIXTURES,
    )
    result = do_run(cfg, site_getter(a), b, T1)
    assert [d.source.id for d in result.decisions if d.due] == ["clock"]
    before, after = tree(a), tree(b)
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed == {
        "clock/250x122-bw.png",
        "clock/250x122-bw.preview.png",
        "clock/250x122-bw.json",
        "manifest.json",
        "index.html",
    }
    for k in ("daily/250x122-bw.png", "daily/250x122-bwr.png", "daily/250x122-bw.json"):
        assert after[k] == before[k]


def test_manifest_entry_fields_and_next_due(tmp_path):
    do_run(config(), lambda _p: None, tmp_path, T0)
    frames = {(e["source"], e["panel"]): e for e in json.loads((tmp_path / "manifest.json").read_bytes())["frames"]}
    daily = frames[("daily", "250x122-bwr")]
    assert set(daily) == {"source", "panel", "url", "sha256", "generated_at", "next_due", "encoders"}
    assert daily["url"] == "https://example.test/site/daily/250x122-bwr.png"
    assert daily["generated_at"] == "2026-10-12T00:00:00Z"  # 08:00 Shanghai
    assert daily["next_due"] == "2026-10-12T16:05:00Z"  # next 00:05 Shanghai
    assert frames[("clock", "250x122-bw")]["next_due"] == "2026-10-12T00:05:00Z"
    sidecar = json.loads((tmp_path / "daily/250x122-bwr.json").read_bytes())
    assert sidecar == daily


def test_fetch_failure_keeps_old_frame_and_marks_error(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    do_run(config(), lambda _p: None, a, T0)
    result = do_run(config(fail=True), site_getter(a), b, T1)
    assert not result.ok
    assert (b / "flaky/250x122-bwr.png").read_bytes() == (a / "flaky/250x122-bwr.png").read_bytes()
    entry = next(e for e in json.loads((b / "manifest.json").read_bytes())["frames"] if e["source"] == "flaky")
    assert "upstream down" in entry["error"]
    assert entry["generated_at"] == "2026-10-12T00:00:00Z"  # still the old Frame's time
    # Everything else was still written.
    assert (b / "clock/250x122-bw.png").read_bytes() != (a / "clock/250x122-bw.png").read_bytes()


def test_cli_run_exits_nonzero_on_source_failure(tmp_path):
    cfg = tmp_path / "inkage.toml"
    cfg.write_text("[sources.flaky]\npanels = ['250x122-bwr']\nfail = true\n[sources.daily]\npanels = ['250x122-bw']\n")
    res = subprocess.run(
        ["uv", "run", "inkage", "run", "-c", str(cfg), "--sources-dir", str(FIXTURES), "--out", str(tmp_path / "out")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 3  # Source failure: Site written, distinct from crashes (1) and config errors (2)
    assert (tmp_path / "out/daily/250x122-bw.png").is_file()
    assert (tmp_path / "out/manifest.json").is_file()


def test_gallery_lists_every_frame_with_only_relative_urls(tmp_path):
    do_run(config(), lambda _p: None, tmp_path, T0)
    page = (tmp_path / "index.html").read_text()
    for f in ("clock/250x122-bw", "daily/250x122-bw", "daily/250x122-bwr", "flaky/250x122-bwr"):
        assert f'src="{f}.preview.png"' in page
    refs = re.findall(r'(?:src|href)="([^"]*)"', page)
    assert refs and all("://" not in r and not r.startswith("//") for r in refs)
    assert "@import" not in page and "url(" not in page


def test_encoder_outputs_only_where_configured(tmp_path):
    cfg = parse_config(
        {
            "panels": {"tag": {"preset": "250x122-bwr", "encoders": ["pcim"]}},
            "sources": {"daily": {"panels": ["tag", "250x122-bw"]}},
        },
        sources_dir=FIXTURES,
    )
    do_run(cfg, lambda _p: None, tmp_path, T0)
    pcim = (tmp_path / "daily/tag.pcim").read_bytes()
    assert pcim[:4] == b"PCIM" and len(pcim) == 16 + 125 * 122
    assert not (tmp_path / "daily/250x122-bw.pcim").exists()
    frames = {e["panel"]: e for e in json.loads((tmp_path / "manifest.json").read_bytes())["frames"]}
    assert frames["tag"]["encoders"]["pcim"]["url"] == "https://example.test/site/daily/tag.pcim"
    assert frames["250x122-bw"]["encoders"] == {}


def test_unreachable_previous_frame_regenerates_with_fresh_next_due(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    do_run(config(), lambda _p: None, a, T0)
    (a / "daily/250x122-bw.png").unlink()  # previous Site lost one file
    result = do_run(config(), site_getter(a), b, T1)
    d = next(d for d in result.decisions if (d.source.id, d.panel.id) == ("daily", "250x122-bw"))
    assert (d.due, d.reason) == (True, "previous Frame unavailable")
    entry = result.manifest.by_key()[("daily", "250x122-bw")]
    assert entry.generated_at == "2026-10-12T00:06:00Z"
    assert entry.next_due == "2026-10-12T16:05:00Z"  # next 00:05 Shanghai after the new generation


def test_manifest_of_other_version_means_full_regenerate(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    do_run(config(), lambda _p: None, a, T0)
    manifest = json.loads((a / "manifest.json").read_bytes())
    (a / "manifest.json").write_text(json.dumps({**manifest, "version": 0}))
    result = do_run(config(), site_getter(a), b, T1)
    assert all(d.due and d.reason == "never generated" for d in result.decisions)


def test_adding_an_encoder_regenerates_a_carried_frame(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    sh = {"timezone": "Asia/Shanghai"}
    plain = parse_config({"defaults": sh, "sources": {"daily": {"panels": ["250x122-bwr"]}}}, sources_dir=FIXTURES)
    do_run(plain, lambda _p: None, a, T0)
    with_pcim = parse_config(
        {
            "defaults": sh,
            "panels": {"250x122-bwr": {"preset": "250x122-bwr", "encoders": ["pcim"]}},
            "sources": {"daily": {"panels": ["250x122-bwr"]}},
        },
        sources_dir=FIXTURES,
    )
    result = do_run(with_pcim, site_getter(a), b, T1)
    assert result.decisions[0].reason == "encoders changed"
    assert (b / "daily/250x122-bwr.pcim").is_file()
