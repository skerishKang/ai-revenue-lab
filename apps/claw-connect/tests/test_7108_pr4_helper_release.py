"""#7117 PR-4 - the helper EXE release script stays a plan until the CTO runs it.

The dry-run test uses a tiny local file, so it proves the build/upload/COM2
EnvironmentFile plan and the exact URL/SHA values without touching Cloudflare,
R2, GitHub Actions, SSH, the COM2 host, or a helper binary.
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


def test_release_script_targets_com2_env_not_the_worker_gate() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for needle in (
        "build-windows-helper.ps1",
        "r2 object put",
        "--remote",
        "/opt/padiem/chat-com2/.env",
        "padiem-chat-com2.service",
        "wsl.exe",
        "scp",
        "ssh",
        "COM2_ENV_BACKUP",
        "os.replace",
        "/proc/",
        "PAIRING_RESPONSE_VERIFY=REQUIRED_SIGNED_IN_OWNER",
        "PC_USER_HELPER_INSTALL_URL",
        "PC_USER_HELPER_SHA256",
    ):
        assert needle in text, needle
    assert "b62-production-code-deploy-gate.yml" not in text
    assert "set_var" not in text
    assert "PC_AGENT_INSTALL_URL" not in text


def test_release_procedure_names_com2_as_authority_and_exact_locations() -> None:
    text = DOC.read_text(encoding="utf-8")
    for needle in (
        "padiem-pc-helper-releases",
        "downloads.padiem.net",
        "9be14bb7b8974e65d0afba647ab16932",
        "wrangler r2 bucket create",
        "wrangler r2 bucket domain add",
        "PC_USER_HELPER_INSTALL_URL",
        "PC_USER_HELPER_SHA256",
        "deploy/host-com2/chat/padiem-chat-com2.service:15",
        "apps/padiem-chat/app/local_cpython.py:642-647",
        "apps/padiem-chat-front/wrangler.toml:24",
        "apps/padiem-chat-front/worker.mjs:335-351",
        "COM2_CANONICAL=writes",
        "PAIRING_RESPONSE_VERIFY=REQUIRED_SIGNED_IN_OWNER",
        "HELPER_RELEASE_UPLOAD=NOT_RUN",
        "HELPER_RELEASE_ENV_SET=NOT_RUN",
        "PRODUCTION_MUTATION=0",
    ):
        assert needle in text, needle
    assert "not the production authority" not in text
    assert "B62 set_var" not in text


def test_dry_run_prints_the_exact_com2_plan_without_mutating(tmp_path: Path) -> None:
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
    assert "PLAN_COM2_ENV=" in output
    assert "/opt/padiem/chat-com2/.env" in output
    assert "PLAN_COM2_TRANSPORT=" in output
    assert "scp" in output
    assert "wsl.exe" in output
    assert "PLAN_COM2_RESTART=" in output
    assert "padiem-chat-com2.service" in output
    assert "PLAN_COM2_ENV_READBACK=" in output
    assert "PLAN_PAIRING_RESPONSE=" in output
    assert "/api/pc/pairings/install-file" in output
    assert "PADIEMHELPERURL" in output
    assert "PADIEMHELPERSHA" in output
    assert "PLAN_WORKER_FALLBACK=NOT_UPDATED" in output
    assert "PRODUCTION_MUTATION=0" in output
    assert "PLAN_DEPLOY_BODY" not in output
    assert "set_var" not in output


def test_dry_run_survives_a_work_folder_without_the_builder(tmp_path: Path) -> None:
    """The 2026-11-08 real condition: the script is run alone from a work
    folder that sits on another branch without apps/claw-connect. The dry-run
    must print the topology plan instead of dying on the missing builder."""
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell is not available")
    script = Path(__file__).resolve().parents[1] / "release-windows-helper.ps1"
    solo_dir = tmp_path / "solo"
    solo_dir.mkdir()
    shutil.copyfile(script, solo_dir / "release-windows-helper.ps1")
    done = subprocess.run(
        [
            shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(solo_dir / "release-windows-helper.ps1"), "-DryRun",
        ],
        capture_output=True, text=True, errors="replace", timeout=120, check=False,
        cwd=str(solo_dir),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PLAN_BUILD=SKIPPED_BUILDER_ABSENT_IN_THIS_WORK_FOLDER" in done.stdout
    assert "PLAN_R2_UPLOAD=" in done.stdout
    assert "PLAN_COM2_TRANSPORT=" in done.stdout
    assert "PRODUCTION_MUTATION=0" in done.stdout


def test_wrangler_resolution_prefers_the_cmd_shim() -> None:
    """npm's .ps1 shims re-parse arguments through Invoke-Expression and mangle
    values with spaces/quotes (the R2 cache-control header). The release must
    pin the .cmd shim before falling back."""
    text = (Path(__file__).resolve().parents[1] / "release-windows-helper.ps1").read_text(encoding="utf-8")
    assert '"wrangler.cmd"' in text
    assert text.index('"wrangler.cmd"') < text.index('"wrangler")')
