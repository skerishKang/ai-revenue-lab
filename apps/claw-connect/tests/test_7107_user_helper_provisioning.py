"""#7107 PR-B — the Connector self-provisions the helper after enrollment."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from claw_connect import user_helper_provisioning as provisioning
from claw_connect import user_helper_registration as registration

DEVICE = "abcdefghijklmnopqrstuvwx1234567890ABCDEFGHIJKLMNOPQRSTfi$D62t1"
USER = r"PC\padiem"


def _state(tmp_path: Path) -> Path:
    root = tmp_path / "ClawConnect"
    (root / "claw_connect").mkdir(parents=True)
    return root


def _runner(calls: list[list[str]], fail=None):
    def run(argv, **kwargs):
        calls.append(list(argv))
        if fail is not None and fail(argv):
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


def _runtime_class(runtime):
    return next(
        obj for obj in vars(runtime).values()
        if isinstance(obj, type) and hasattr(obj, "_provision_user_helper")
    )


def test_enrollment_provisioning_creates_secret_and_registers_a_started_task(tmp_path):
    root = _state(tmp_path)
    secret_dir = tmp_path / "ProgramData"
    calls: list[list[str]] = []
    result = provisioning.provision_user_helper(
        device_id=DEVICE, state_dir=root, secret_dir=secret_dir, user=USER,
        run=_runner(calls), platform="win32", python_executable=sys.executable,
    )
    assert result["status"] == "installed"
    secret = (secret_dir / "helper.secret").read_text(encoding="ascii").strip()
    assert len(secret) == 64
    assert len(bytes.fromhex(secret)) == 32
    status = (root / "helper-status.json").read_text(encoding="utf-8")
    assert secret not in status
    script = next(call[-1] for call in calls if call[0] == "powershell.exe")
    assert DEVICE in script
    assert "-WorkingDirectory" in script
    assert "Start-ScheduledTask" in script
    assert secret not in script


def test_the_task_definition_carries_the_install_root_and_raw_id(tmp_path):
    root = _state(tmp_path)
    launch = registration.build_launch(
        python_executable=sys.executable, device_id=DEVICE,
        secret_file=r"C:\ProgramData\Padiem\helper.secret",
        working_directory=str(root),
    )
    definition = registration.task_definition(launch=launch, user=USER)
    assert definition["Action"]["WorkingDirectory"] == str(root)
    assert DEVICE in definition["Action"]["Argument"]
    script = registration.register_script(definition)
    assert "-WorkingDirectory" in script
    assert "Start-ScheduledTask" in script
    assert DEVICE in script


def test_a_task_registration_failure_is_reported_not_raised(tmp_path):
    root = _state(tmp_path)
    result = provisioning.provision_user_helper(
        device_id=DEVICE, state_dir=root, secret_dir=tmp_path / "ProgramData",
        user=USER, run=_runner([], fail=lambda argv: argv[0] == "powershell.exe"),
        platform="win32", python_executable=sys.executable,
    )
    assert result["status"] == "not_installed"
    assert result["reason"] == "task_registration_failed"
    assert (root / "helper-status.json").is_file()


def test_missing_claw_connect_skips_without_creating_a_secret(tmp_path):
    root = tmp_path / "ClawConnect"
    root.mkdir()
    secret_dir = tmp_path / "ProgramData"
    result = provisioning.provision_user_helper(
        device_id=DEVICE, state_dir=root, secret_dir=secret_dir, user=USER,
        run=_runner([]), platform="win32", python_executable=sys.executable,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "claw_connect_missing"
    assert not (secret_dir / "helper.secret").exists()


def test_the_runtime_provisions_after_enrollment(monkeypatch, tmp_path):
    runtime = pytest.importorskip("claw_connect.runtime")
    called: dict = {}

    def fake_provision(**kwargs):
        called.update(kwargs)
        return {"status": "installed"}

    monkeypatch.setattr(provisioning, "provision_user_helper", fake_provision)

    class Enrollment:
        def committed_record(self):
            return SimpleNamespace(device_id=DEVICE, is_enrolled=lambda: True)

    fake = SimpleNamespace(_enrollment=Enrollment(), _state_dir=tmp_path)
    _runtime_class(runtime)._provision_user_helper(fake)
    assert called == {"device_id": DEVICE, "state_dir": tmp_path}


def test_a_missing_record_does_not_provision(monkeypatch, tmp_path):
    runtime = pytest.importorskip("claw_connect.runtime")
    called = []
    monkeypatch.setattr(provisioning, "provision_user_helper",
                        lambda **kwargs: called.append(kwargs) or {"status": "installed"})

    class Enrollment:
        def committed_record(self):
            return None

    fake = SimpleNamespace(_enrollment=Enrollment(), _state_dir=tmp_path)
    _runtime_class(runtime)._provision_user_helper(fake)
    assert called == []
