"""Network-free tests for the generic served-version CLI adapter (#3656)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"
ACTIVE = "11111111-1111-1111-1111-111111111111"


def _run(tmp_path: Path, payload: object) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "deployments.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "resolve-active",
            "--deployments",
            str(path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _envelope(versions: list[object]) -> dict:
    return {
        "success": True,
        "result": {
            "deployments": [
                {
                    "versions": versions,
                }
            ]
        },
    }


def test_cli_success_prints_only_safe_version_id(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _envelope([{"version_id": ACTIVE, "percentage": 100}]),
    )
    assert result.returncode == 0
    assert result.stdout == f"{ACTIVE}\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            [{"versions": [{"version_id": ACTIVE, "percentage": 100}]}],
            "envelope",
        ),
        (
            {"success": True, "result": {"versions": [{"version_id": ACTIVE, "percentage": 100}]}},
            "deployment-records",
        ),
        (
            _envelope(
                [
                    {"version_id": ACTIVE, "percentage": 50},
                    {"version_id": "22222222-2222-2222-2222-222222222222", "percentage": 50},
                ]
            ),
            "version-count",
        ),
        (
            _envelope([{"version_id": ACTIVE, "percentage": 99}]),
            "traffic",
        ),
        (
            _envelope([{"version_id": "bad version;echo secret", "percentage": 100}]),
            "version-id",
        ),
    ],
)
def test_cli_fails_closed_with_bounded_reason(
    tmp_path: Path,
    payload: object,
    reason: str,
) -> None:
    result = _run(tmp_path, payload)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"SERVED_VERSION_RESOLUTION=FAIL\nREASON={reason}\n"
    assert ACTIVE not in result.stderr
    assert "bad version" not in result.stderr


def test_cli_unreadable_or_invalid_json_is_input_error_without_payload_echo(
    tmp_path: Path,
) -> None:
    path = tmp_path / "deployments.json"
    path.write_text("{this-is-not-json-and-must-not-be-echoed", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "resolve-active",
            "--deployments",
            str(path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == (
        "SERVED_VERSION_RESOLUTION=INPUT_ERROR\n"
        "REASON=deployments-payload-unreadable\n"
    )
    assert "this-is-not-json" not in result.stderr


def test_cli_is_thin_and_contains_no_network_or_mutation_authority() -> None:
    source = CLI.read_text(encoding="utf-8")
    assert "from cloudflare_served_version import" in source
    assert "resolve_served_version_id(payload)" in source
    for forbidden in (
        "urllib",
        "requests",
        "httpx",
        "subprocess.run",
        "curl ",
        "wrangler ",
        "os.environ",
        "CLOUDFLARE_API_TOKEN",
    ):
        assert forbidden not in source
