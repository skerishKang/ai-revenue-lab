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
BAD_ID_SENTINEL = "bad id;echo STUB-CREDENTIAL-SENTINEL"


def _load_primitive():
    """The canonical resolver the adapter delegates to, loaded the way guards do."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cloudflare_served_version",
        CLI.parent / "cloudflare_served_version.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


primitive = _load_primitive()


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


# --- validate-version-id (#3704) -------------------------------------------
#
# A rollback target is typed by a dispatcher, so it is untrusted input. This
# subcommand exists so a gate can apply the canonical safe-id contract without
# either borrowing another lane's branded adapter or inlining its own rule.


def _validate(version_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "validate-version-id", "--version-id", version_id],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("version_id", [ACTIVE, "a", "ver-A", "ver_A.1", "9" * 64])
def test_validate_version_id_accepts_exactly_the_canonical_charset(version_id: str) -> None:
    result = _validate(version_id)
    assert result.returncode == 0
    assert result.stdout == "VERSION_ID_SAFE=YES\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "version_id",
    [
        "",
        "ver A",
        "9" * 65,
        BAD_ID_SENTINEL,
        "../../ETC-PASSWD-SENTINEL",
        "lead\ttab",
    ],
)
def test_validate_version_id_refuses_with_the_bounded_reason(version_id: str) -> None:
    result = _validate(version_id)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "VERSION_ID_SAFE=NO\nREASON=version-id\n"


def test_validate_version_id_never_echoes_the_candidate() -> None:
    """The rejected string must not be reflected into CI output (#2752 blocker 3)."""
    result = _validate(BAD_ID_SENTINEL)
    assert result.returncode == 1
    assert BAD_ID_SENTINEL not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "version_id",
    [ACTIVE, "a", "9" * 64, "", "ver A", "9" * 65, "../x", "id\nMUTATION_CLASS=ROLLBACK"],
)
def test_validate_version_id_delegates_to_the_canonical_predicate(version_id: str) -> None:
    """Reuse, not a second contract: the adapter must agree with the primitive."""
    assert (_validate(version_id).returncode == 0) is primitive.is_safe_version_id(version_id)


def test_validate_version_id_adds_no_second_charset_rule() -> None:
    source = CLI.read_text(encoding="utf-8")
    assert "is_safe_version_id" in source
    for forbidden in ("re.compile", "A-Za-z0-9", "^\\", "{1,64}"):
        assert forbidden not in source, f"the adapter grew its own charset rule: {forbidden}"

