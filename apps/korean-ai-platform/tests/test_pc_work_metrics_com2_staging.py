"""Run an installer copy against temporary paths and inert command shims only."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
INSTALL = ROOT / "deploy/host-com2/b14/install.sh"


@pytest.fixture
def staged_installer(tmp_path):
    if os.name != "posix":
        pytest.skip("the COM2 installer runs on Linux")
    repo = tmp_path / "repo"
    bundle = repo / "deploy/host-com2/b14"
    shutil.copytree(INSTALL.parent, bundle)
    source = repo / "packages/padiem-ai-core/padiem_ai_core/pc_work_metrics.py"
    source.parent.mkdir(parents=True)
    source.write_text((ROOT / "packages/padiem-ai-core/padiem_ai_core/pc_work_metrics.py").read_text())
    app_root = tmp_path / "b14"
    (app_root / "app").mkdir(parents=True)
    (app_root / "app/asgi.py").write_text("# inert app fixture\n")
    (app_root / "venv/bin").mkdir(parents=True)
    python = app_root / "venv/bin/python"
    python.write_text('#!/bin/sh\nexec "' + sys.executable + '" "$@"\n')
    python.chmod(0o755)
    for path in (tmp_path / "systemd", tmp_path / "logrotate", tmp_path / "cloudflared"):
        path.mkdir()
    script = bundle / "install.sh"
    text = script.read_text().replace("APP_ROOT=/opt/padiem/b14", 'APP_ROOT="' + str(app_root) + '"')
    text = text.replace("/etc/systemd/system/", str(tmp_path / "systemd") + "/")
    text = text.replace("/etc/logrotate.d/padiem-b14", str(tmp_path / "logrotate/b14"))
    text = text.replace("/opt/padiem/cloudflared/config.yml", str(tmp_path / "cloudflared/config.yml"))
    text = text.replace("/var/lib/padiem-b14/", str(tmp_path / "state") + "/")
    script.write_text(text)
    shim = tmp_path / "bin"
    shim.mkdir()
    for name, body in {
        "id": "printf '0\\n'", "uname": "printf 'Linux\\n'",
        "systemctl": "printf 'inactive\\n'; exit 0",
    }.items():
        command = shim / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)
    # Strip ownership arguments only in this test: install still copies real
    # files, but neither a host account nor root privilege is a prerequisite.
    real_install = shutil.which("install")
    install_shim = shim / "install"
    install_shim.write_text("#!/usr/bin/env python3\nimport os,sys\n"
                            "args=[]; it=iter(sys.argv[1:])\n"
                            "for arg in it:\n"
                            " if arg in ('-o','-g'): next(it)\n"
                            " else: args.append(arg)\n"
                            f"os.execv({real_install!r},[{real_install!r}]+args)\n")
    install_shim.chmod(0o755)
    env = {**os.environ, "PATH": str(shim) + os.pathsep + os.environ["PATH"],
           "PADIEM_B14_SERVICE_PROOF_SECRET": "synthetic_staging_value_never_logged"}
    def run(*args):
        return subprocess.run(["bash", str(script), *args], env=env,
                              capture_output=True, text=True, timeout=15)
    return run, app_root, source, tmp_path


def test_dry_run_does_not_stage_module_or_package(staged_installer):
    run, app_root, _, _ = staged_installer
    result = run("--dry-run")
    assert result.returncode == 0, result.stderr
    assert "would_stage:pc_work_metrics" in result.stdout
    assert not (app_root / "app/padiem_ai_core").exists()


def test_missing_canonical_source_fails_before_config_mutation(staged_installer):
    run, app_root, source, tmp_path = staged_installer
    source.unlink()
    result = run()
    assert result.returncode == 2
    assert "pc_metrics_source_missing" in result.stderr
    assert not (app_root / "app/padiem_ai_core").exists()
    assert not (tmp_path / "systemd/padiem-b14.service").exists()


def test_temp_install_copies_only_validator_and_keeps_existing_package_initializer(staged_installer):
    run, app_root, source, _ = staged_installer
    package = app_root / "app/padiem_ai_core"
    package.mkdir()
    marker = '"""Existing package initializer fixture."""\n'
    (package / "__init__.py").write_text(marker)
    result = run()
    assert result.returncode == 0, result.stderr
    assert (package / "pc_work_metrics.py").read_text() == source.read_text()
    assert (package / "__init__.py").read_text() == marker
    assert {path.name for path in package.glob("*.py")} == {"pc_work_metrics.py", "__init__.py"}
    assert "staged:pc_work_metrics" in result.stdout
    assert "NO_SERVICE_STARTED=YES" in result.stdout
    assert "NO_CREDENTIAL_WRITTEN=YES" in result.stdout
    assert "synthetic_staging_value_never_logged" not in result.stdout + result.stderr


def test_staging_does_not_overwrite_existing_service_config(staged_installer):
    run, _, _, tmp_path = staged_installer
    target = tmp_path / "systemd/padiem-b14.service"
    target.write_text("operator fixture configuration\n")
    result = run()
    assert result.returncode == 2
    assert "foreign_target:unit" in result.stderr
    assert target.read_text() == "operator fixture configuration\n"
