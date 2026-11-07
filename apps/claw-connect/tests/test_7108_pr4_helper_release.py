"""#7117 PR-4 — the helper EXE release script stays a plan until the CTO runs it.

The dry-run test uses a tiny local file, so it proves the build/upload/deploy
plan and the exact URL/SHA/set_var payload without touching Cloudflare, R2,
GitHub Actions, or a helper binary.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "apps" / "claw-connect" / "release-windows-helper.ps1"
DOC = ROOT / "docs" / "operations" / "PC_USER_HELPER_RELEASE_20261107.md"


def test_release_script_has_the_required_stages() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "build-windows-helper.ps1" in text
    assert "r2 object put" in text
    assert "--remote" in text
    assert "b62-production-code-deploy-gate.yml" in text
    assert "PC_USER_HELPER_INSTALL_URL" in text
    assert "PC_USER_HELPER_SHA256" in text
    assert "set_var" in text
    assert "PC_AGENT_INSTALL_URL" not in text


def test_release_procedure_names_the_worker_and_exact_locations() -> None:
    text = DOC.read_text(encoding="utf-8")
    for needle in (
        "padiem-pc-helper-releases",
        "downloads.padiem.net",
        "PC_USER_HELPER_INSTALL_URL",
        "PC_USER_HELPER_SHA256",
        "apps/padiem-chat/wrangler.toml:207",
        "apps/padiem-chat/worker.py:1695-1700",
        ".github/workflows/b62-production-code-deploy-gate.yml:140-144",
        "apps/padiem-chat/app/local_cpython.py:641-647",
        "HELPER_RELEASE_UPLOAD=NOT_RUN",
    ):
        assert needle in text, needle


def test_dry_run_prints_the_exact_release_plan_without_mutating(tmp_path: Path) -> None:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell is not available")
    artifact = tmp_path / "padiem-user-helper.exe"
    artifact.write_bytes(b"release-plan-only\n")
    sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    done = subprocess.run(
        [
            shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPT),
            "-ArtifactPath", str(artifact),
            "-Version", "0.3.0-rc1",
            "-DryRun",
        ],
        capture_output=True, text=True, errors="replace", timeout=60, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    output = done.stdout
    url = "https://downloads.padiem.net/pc-helper/0.3.0-rc1/padiem-user-helper.exe"
    assert f"HELPER_RELEASE_SHA256={sha}" in output
    assert f"HELPER_RELEASE_URL={url}" in output
    assert "PC_USER_HELPER_INSTALL_URL" in output
    assert "PC_USER_HELPER_SHA256" in output
    assert "PLAN_R2_UPLOAD=" in output
    assert "PLAN_DEPLOY_BODY=" in output
    assert "PRODUCTION_MUTATION=0" in output
