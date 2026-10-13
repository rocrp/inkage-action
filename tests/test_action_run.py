"""Action boundary: failed-source retries must outrank expired Frame freshness."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize(
    ("frames", "expected"),
    [
        # Kept Frame's expired deadline must not cause an immediate redispatch.
        (
            [
                {"next_due": "2026-10-12T00:05:00Z", "retry_at": "2026-10-12T00:30:00Z"},
                {"next_due": "2026-10-12T00:45:00Z"},
            ],
            "2026-10-12T00:30:00Z",
        ),
        # A first-attempt failure has no Frame deadline, but still needs a retry.
        ([{"next_due": None, "retry_at": "2026-10-12T00:30:00Z"}], "2026-10-12T00:30:00Z"),
        # Healthy work earlier than a retry still wakes the chain first.
        (
            [
                {"next_due": "2026-10-12T00:05:00Z", "retry_at": "2026-10-12T00:30:00Z"},
                {"next_due": "2026-10-12T00:15:00Z"},
            ],
            "2026-10-12T00:15:00Z",
        ),
    ],
)
def test_chain_output_selects_next_attempt_without_rewriting_freshness(tmp_path, frames, expected):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"frames": frames}))
    output = tmp_path / "outputs"
    env = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(ROOT),
        "GITHUB_OUTPUT": str(output),
        "INKAGE_CONFIG": "unused.toml",
        "INKAGE_SITE_URL": "",
        "INKAGE_OUT": str(tmp_path),
        "INKAGE_SOURCES_DIR": "",
        "INKAGE_FONTS_DIR": "",
    }
    # The CLI boundary already wrote the hand-authored Manifest and exits 3.
    # Run the real action adapter, including its jq selection and output writing.
    subprocess.run(
        ["bash", "-c", 'uv() { return 3; }; export -f uv; exec bash "$1"', "bash", str(ROOT / "scripts/action-run.sh")],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.read_text().splitlines() == [f"dist={tmp_path}", "failed=true", f"next_due={expected}"]
