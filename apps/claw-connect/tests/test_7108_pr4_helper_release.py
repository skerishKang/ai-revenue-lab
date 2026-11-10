"""#7117 PR-4 - the helper EXE release script stays a plan until the CTO runs it.

The dry-run test uses a tiny local file, so it proves the build/upload/COM2
EnvironmentFile plan and the exact URL/SHA values without touching Cloudflare,
R2, GitHub Actions, SSH, the COM2 host, or a helper binary.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "apps" / "claw-connect" / "release-windows-helper.ps1"


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


def test_release_script_names_com2_as_authority_and_exact_locations() -> None:
    # #7404: the step-by-step procedure moved to the private operations records.
    # The script itself must still name the authority (COM2 env + service), the
    # public bucket/host and the signed pairing guard.
    text = SCRIPT.read_text(encoding="utf-8")
    for needle in (
        "padiem-pc-helper-releases",
        "downloads.padiem.net",
        "9be14bb7b8974e65d0afba647ab16932",
        "PC_USER_HELPER_INSTALL_URL",
        "PC_USER_HELPER_SHA256",
        "COM2_CANONICAL=writes",
        "PAIRING_RESPONSE_VERIFY=REQUIRED_SIGNED_IN_OWNER",
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


REMOTE_SCRIPT_START = "$remoteScriptText = @'"


def _remote_script_text() -> str:
    """The bash updater embedded in the release script, exactly as it is run."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index(REMOTE_SCRIPT_START)
    start = text.index("\n", start) + 1
    end = text.index("\n'@", start)
    return text[start:end].replace("\r\n", "\n")


def _posix_bash() -> str | None:
    """A bash that can parse a Windows temp file: Git Bash, not the WSL shim
    in System32 (WSL may be absent and only understands /mnt paths)."""
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if not git:
        return None
    root = Path(git).resolve().parent.parent
    for candidate in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


def test_remote_health_probe_retries_like_the_deploy_readiness_ladder() -> None:
    """2026-11-08 real run: the first probe a few seconds after the restart
    printed CHAT_COM2_HEALTH=FAIL STATUS=0 and the release aborted, while the
    service answered 200 moments later. The remote script must wait like
    wait_for_health in deploy/host-com2/deploy_from_main.sh: probe
    immediately, retry every 2 s, bound the whole wait at 60 s, and report the
    attempt count."""
    remote = _remote_script_text()
    assert "health_interval=2" in remote
    assert "health_timeout=60" in remote
    assert "health_deadline=$((SECONDS + health_timeout))" in remote
    # printed once on success and once with the last output on timeout
    assert remote.count("COM2_HEALTH_ATTEMPTS=$health_attempt") == 2
    probe = remote.index("health.py --url")
    assert remote.count("health.py --url") == 1
    assert remote.index("while :; do") < probe
    assert probe < remote.index('sleep "$health_pause"')
    assert probe < remote.index('echo "COM2_HEALTH=PASS"')
    assert "fail HEALTH_FAILED" in remote
    # The env readback and the unauthenticated pairing gate still follow the
    # health wait in the same order as before.
    assert probe < remote.index("/proc/$main_pid/environ")
    assert probe < remote.index("/api/pc/pairings/install-file")


def test_remote_script_parses_with_bash_n(tmp_path: Path) -> None:
    bash = _posix_bash()
    if not bash:
        pytest.skip("no POSIX bash available to parse the remote updater")
    updater = tmp_path / "padiem-helper-release-contract.sh"
    updater.write_text(_remote_script_text(), encoding="utf-8", newline="\n")
    done = subprocess.run(
        [bash, "-n", str(updater)],
        capture_output=True, text=True, errors="replace", timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr


def test_source_sha_argument_feeds_a_gitless_run(tmp_path: Path) -> None:
    """A `git archive` snapshot has no .git: -SourceSha must carry the release
    evidence, and an invalid value must fail instead of printing UNKNOWN."""
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell is not available")
    artifact = tmp_path / "padiem-user-helper.exe"
    artifact.write_bytes(b"release-plan-only\n")
    sha = "0123456789abcdef0123456789abcdef01234567"
    done = subprocess.run(
        [
            shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPT),
            "-ArtifactPath", str(artifact),
            "-Version", "0.3.0-rc1",
            "-SourceSha", sha,
            "-DryRun",
        ],
        capture_output=True, text=True, errors="replace", timeout=60, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"HELPER_RELEASE_SOURCE_SHA={sha}" in done.stdout

    bad = subprocess.run(
        [
            shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPT),
            "-ArtifactPath", str(artifact),
            "-Version", "0.3.0-rc1",
            "-SourceSha", "not-a-sha",
            "-DryRun",
        ],
        capture_output=True, text=True, errors="replace", timeout=60, check=False,
    )
    assert bad.returncode != 0
    assert "-SourceSha must be an exact 40-hex commit SHA" in (bad.stdout + bad.stderr)


def test_source_sha_falls_back_to_unknown_in_a_gitless_folder(tmp_path: Path) -> None:
    """The 2026-11-08 `git archive` condition: no .git next to the extracted
    snapshot and no -SourceSha. The run must stay honest and print UNKNOWN
    rather than a wrong revision."""
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell is not available")
    script = Path(__file__).resolve().parents[1] / "release-windows-helper.ps1"
    solo_dir = tmp_path / "solo"
    solo_dir.mkdir()
    shutil.copyfile(script, solo_dir / "release-windows-helper.ps1")
    artifact = solo_dir / "padiem-user-helper.exe"
    artifact.write_bytes(b"release-plan-only\n")
    done = subprocess.run(
        [
            shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(solo_dir / "release-windows-helper.ps1"),
            "-ArtifactPath", str(artifact),
            "-Version", "0.3.0-rc1",
            "-DryRun",
        ],
        capture_output=True, text=True, errors="replace", timeout=120, check=False,
        cwd=str(solo_dir),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "HELPER_RELEASE_SOURCE_SHA=UNKNOWN" in done.stdout


def test_release_script_documents_the_archive_and_retry_paths() -> None:
    # #7404: the procedure document moved to the private operations records;
    # the archive/retry anchors the script itself carries stay asserted here.
    text = SCRIPT.read_text(encoding="utf-8")
    assert "git archive" in text
    assert "-SourceSha" in text
    assert "wait_for_health" in text
    assert "COM2_HEALTH_ATTEMPTS" in text


def test_script_keeps_the_source_sha_fallbacks_in_order() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '[string]$SourceSha = ""' in text
    assert "if (-not $SourceSha) { $SourceSha = [string]$build.source_sha }" in text
    assert "if (-not $SourceSha) {" in text
    assert 'if (-not $SourceSha) { $SourceSha = "UNKNOWN" }' in text
