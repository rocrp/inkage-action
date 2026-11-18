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


@pytest.mark.parametrize(("fail_times", "expected_code", "expected_calls"), [(2, 0, 3), (3, 1, 3)])
def test_chain_next_retries_transient_dispatch_errors(tmp_path, fail_times, expected_code, expected_calls):
    # Captured from production run 44240630436: POST .../dispatches returned HTTP 500.
    calls = tmp_path / "calls"
    stub = tmp_path / "gh"
    stub.write_text(
        f'#!/usr/bin/env bash\nn=$(cat "{calls}" 2>/dev/null || echo 0)\n'
        f'n=$((n + 1))\necho "$n" > "{calls}"\n'
        f'(( n <= {fail_times} )) && {{ echo "HTTP 500" >&2; exit 1; }}\n'
        'echo "$*"\n'
    )
    stub.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GITHUB_TOKEN": "tok",
        "GITHUB_REPOSITORY": "rocrp/inkage-action",
        "GITHUB_WORKFLOW_REF": "rocrp/inkage-action/.github/workflows/inkage.yml@refs/heads/main",
        "GITHUB_REF_NAME": "main",
        "MAX_SLEEP_SECONDS": "0",
        "RETRY_DELAYS": "0 0",
    }
    res = subprocess.run(
        ["bash", str(ROOT / "scripts/chain-next.sh"), ""],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == expected_code
    assert int(calls.read_text().strip()) == expected_calls
    if expected_code == 0:
        assert "workflow run inkage.yml -R rocrp/inkage-action --ref main" in res.stdout
