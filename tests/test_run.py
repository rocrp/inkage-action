"""The Run: carry-over, Manifest, failure isolation, gallery. Fixture Sources render with Pillow."""

import asyncio
import json
import re
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from inkage.config import parse_config
from inkage.run import RunResult, run
from inkage.schedule import Schedule

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
    return asyncio.run(run(cfg, get, out, now))


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


def test_forced_release_refresh_preserves_last_good_frame_on_upstream_failure(tmp_path):
    # A release arrives one minute after a successful run, before any Source is due.
    cfg = config()
    before, release, waiting = (tmp_path / name for name in ("before", "release", "waiting"))
    do_run(cfg, lambda _p: None, before, T0)
    cfg.sources[-1].params["fail"] = True
    at = T0 + timedelta(minutes=1)
    result = asyncio.run(run(cfg, site_getter(before), release, at, force=True))
    frames = result.manifest.by_key()
    assert frames[("daily", "250x122-bw")].generated_at == "2026-10-12T00:01:00Z"
    failed = frames[("flaky", "250x122-bwr")]
    assert (failed.generated_at, failed.retry_at) == ("2026-10-12T00:00:00Z", "2026-10-12T00:06:00Z")
    assert (release / "flaky/250x122-bwr.png").read_bytes() == (before / "flaky/250x122-bwr.png").read_bytes()
    # The next ordinary chain run must honor the retry time, even if upstream recovers.
    cfg.sources[-1].params["fail"] = False
    followup = do_run(cfg, site_getter(release), waiting, T0 + timedelta(minutes=2))
    assert followup.manifest.by_key()[("flaky", "250x122-bwr")] == failed


def test_manifest_entry_fields_and_next_due(tmp_path):
    do_run(config(), lambda _p: None, tmp_path, T0)
    frames = {(e["source"], e["panel"]): e for e in json.loads((tmp_path / "manifest.json").read_bytes())["frames"]}
    daily = frames[("daily", "250x122-bwr")]
    assert set(daily) == {"source", "panel", "url", "sha256", "generated_at", "next_due", "encoders"}
    assert daily["url"] == "daily/250x122-bwr.png"  # Site-relative: mirrors need no rewriting
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
    assert frames["tag"]["encoders"]["pcim"]["url"] == "daily/tag.pcim"
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


def test_failed_source_retries_independently_of_frame_freshness(tmp_path):
    # Healthy frame at 08:00, outage at 08:31, another Source wakes at 08:36,
    # retry fails at 09:01, and recovery occurs on the next retry at 09:31.
    cfg = config()
    flaky = next(sc for sc in cfg.sources if sc.id == "flaky")
    cfg = replace(
        cfg,
        sources=tuple(
            replace(sc, schedule=Schedule.parse({"every": "30m"})) if sc is flaky else sc for sc in cfg.sources
        ),
    )
    flaky = next(sc for sc in cfg.sources if sc.id == "flaky")
    sites = [tmp_path / str(i) for i in range(5)]
    key = ("flaky", "250x122-bwr")
    do_run(cfg, lambda _p: None, sites[0], T0)
    original = (sites[0] / "flaky/250x122-bwr.png").read_bytes()
    flaky.params["fail"] = True
    failed = do_run(cfg, site_getter(sites[0]), sites[1], T0 + timedelta(minutes=31)).manifest.by_key()[key]
    assert (failed.generated_at, failed.next_due, failed.retry_at) == (
        "2026-10-12T00:00:00Z",
        "2026-10-12T00:30:00Z",
        "2026-10-12T01:01:00Z",
    )

    # Upstream would now succeed. Waiting must still skip it when the clock wakes.
    flaky.params["fail"] = False
    waiting = do_run(cfg, site_getter(sites[1]), sites[2], T0 + timedelta(minutes=36))
    decision = next(d for d in waiting.decisions if d.source.id == "flaky")
    assert (decision.due, decision.reason, decision.next_due.isoformat()) == (
        False,
        "waiting for retry",
        "2026-10-12T01:01:00+00:00",
    )
    assert waiting.manifest.by_key()[key] == failed
    assert not waiting.ok  # The unresolved upstream error remains visible.

    flaky.params["fail"] = True
    failed_again = do_run(cfg, site_getter(sites[2]), sites[3], T0 + timedelta(minutes=61)).manifest.by_key()[key]
    assert (failed_again.generated_at, failed_again.next_due, failed_again.retry_at) == (
        "2026-10-12T00:00:00Z",
        "2026-10-12T00:30:00Z",
        "2026-10-12T01:31:00Z",
    )
    assert (sites[3] / "flaky/250x122-bwr.png").read_bytes() == original

    flaky.params["fail"] = False
    recovered = do_run(cfg, site_getter(sites[3]), sites[4], T0 + timedelta(minutes=91)).manifest.by_key()[key]
    assert (recovered.generated_at, recovered.next_due, recovered.error, recovered.retry_at) == (
        "2026-10-12T01:31:00Z",
        "2026-10-12T02:01:00Z",
        None,
        None,
    )
    assert "retry_at" not in recovered.to_json()


def test_first_run_failure_has_retry_and_carries_without_a_png(tmp_path):
    cfg = parse_config(
        {"sources": {"flaky": {"panels": ["250x122-bwr"], "fail": True, "schedule": {"every": "30m"}}}},
        sources_dir=FIXTURES,
    )
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    result = do_run(cfg, lambda _p: None, a, T0)
    failed = result.manifest.frames[0]
    assert (failed.generated_at, failed.next_due, failed.retry_at, failed.sha256) == (
        None,
        None,
        "2026-10-12T00:30:00Z",
        None,
    )
    cfg.sources[0].params["fail"] = False
    waiting = do_run(cfg, site_getter(a), b, T0 + timedelta(minutes=5))
    assert not waiting.decisions[0].due
    assert (b / "flaky/250x122-bwr.json").read_bytes() == (a / "flaky/250x122-bwr.json").read_bytes()
    assert not (b / "flaky/250x122-bwr.png").exists()
    recovered = do_run(cfg, site_getter(b), c, T0 + timedelta(minutes=30)).manifest.frames[0]
    assert (recovered.generated_at, recovered.next_due, recovered.error, recovered.retry_at) == (
        "2026-10-12T00:30:00Z",
        "2026-10-12T01:00:00Z",
        None,
        None,
    )
