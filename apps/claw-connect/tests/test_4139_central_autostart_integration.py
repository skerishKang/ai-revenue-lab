"""CENTRAL #4139: guarded installer, S2 tray and real startup reconciliation.

Synthetic tests only: never modify the user's HKCU keys or contact a Broker.
"""
from __future__ import annotations

import base64
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect import __main__ as cli
from claw_connect.autostart import (
    Autostart, AutostartOutcome, MemoryPreferenceStore, MemoryRunKeyStore,
    PREFERENCE_OFF, start_command,
)
from claw_connect.enrollment import EnrollmentRecord, LIFECYCLE_PAIRED_OFFLINE
from claw_connect.runtime import ConnectApp


class Committed:
    def __init__(self, record):
        self.value = record
        self.state_dir = ROOT
    def committed_record(self):
        return self.value


def _harness(record):
    runs, prefs = MemoryRunKeyStore(), MemoryPreferenceStore()
    auto = Autostart("PadiemClawConnect", runs, preference_store=prefs)
    app = ConnectApp(
        resident_command=[sys.executable, "-c", "pass"],
        autostart=auto,
        enrollment=Committed(record),
    )
    return app, runs, prefs


def test_install_script_has_no_direct_run_write_bypass():
    code = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "Set-ItemProperty -Path $RunKey" not in code
    assert "& $PythonExePath -m padiem_connector autostart on" in code
    assert "if ($LASTEXITCODE -ne 0)" in code
    assert "Push-Location $InstallRoot" in code
    assert "Pop-Location" in code
    assert "-Verb RunAs" not in code
    assert "New-Service" not in code
    assert "HKLM:" not in code


def test_unenrolled_startup_never_writes_run_and_refused_cli_creates_no_identity():
    app, runs, prefs = _harness(None)
    assert app.reconcile_autostart() is None
    assert runs.values == {} and prefs.values == {}
    assert cli.build_parser().parse_args(["autostart", "on"]).autostart_mode == "on"


def test_valid_committed_record_enables_logon_once_and_preserves_off():
    record = EnrollmentRecord(
        device_id="device.synthetic", binding_ref="binding.synthetic",
        device_lifecycle=LIFECYCLE_PAIRED_OFFLINE,
    )
    app, runs, prefs = _harness(record)
    assert app.reconcile_autostart() is AutostartOutcome.REGISTERED
    assert len(runs.writes) == 1
    assert app.reconcile_autostart() is AutostartOutcome.ALREADY_REGISTERED
    assert len(runs.writes) == 1
    app.autostart.disable()
    assert app.reconcile_autostart() is AutostartOutcome.SUPPRESSED_BY_OWNER
    assert runs.values == {} and app.autostart.preference() == PREFERENCE_OFF


def test_after_crash_off_marker_removes_orphan_even_without_credential():
    app, runs, prefs = _harness(None)
    prefs.write("Autostart", PREFERENCE_OFF)
    runs.write("PadiemClawConnect", start_command())
    assert app.reconcile_autostart() is AutostartOutcome.OPT_OUT_RECONCILED
    assert app.reconcile_autostart() is AutostartOutcome.SUPPRESSED_BY_OWNER
    assert runs.values == {}


def test_logon_command_is_importable_without_assuming_current_working_directory():
    command = start_command()
    assert command == cli._autostart_command()
    assert command.startswith(f'"{sys.executable}" -c "')
    marker = "base64.b64decode('"
    assert marker in command
    encoded = command.split(marker, 1)[1].split("'", 1)[0]
    path = base64.b64decode(encoded).decode("utf-8")
    assert Path(path).resolve() == ROOT.resolve()
    assert "runpy.run_module('claw_connect',run_name='__main__')" in command


def test_programmatic_unpair_suspends_registration_but_keeps_owner_off():
    app, runs, _ = _harness(None)
    app.autostart.disable()
    app.autostart.apply_lifecycle("unpair")
    assert runs.values == {}
    assert app.autostart.preference() == PREFERENCE_OFF


def test_foreign_nonsecret_run_entry_cannot_be_deleted_on_off_or_unpair():
    from claw_connect.autostart import AutostartRefused, REGISTRATION_CORRUPT
    app, runs, prefs = _harness(None)
    foreign = r'"C:\Windows\System32\notepad.exe" /s'
    runs.values["PadiemClawConnect"] = foreign
    assert app.autostart.classify() == REGISTRATION_CORRUPT
    assert not app.autostart.is_enabled()
    # Startup exposes a bounded unavailable result rather than surfacing an
    # exception to the tray; the Run value remains byte-identical.
    assert app.reconcile_autostart() is None
    with pytest.raises(AutostartRefused):
        app.autostart.disable()
    assert prefs.values["Autostart"] == PREFERENCE_OFF
    with pytest.raises(AutostartRefused):
        app.autostart.apply_lifecycle("unpair")
    assert runs.values["PadiemClawConnect"] == foreign


def test_installer_uninstall_uses_shared_ownership_gate_instead_of_raw_delete():
    src = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "& $PythonExePath -m $UninstallModule autostart off" in src
    assert "'padiem_connector'" in src and "'claw_connect'" in src
    assert "Remove-ItemProperty -Path $RunKey" not in src
    assert "Could not be safely disabled" not in src or "Autostart could not be safely disabled" in src


def test_cli_show_never_echoes_a_foreign_secret_bearing_registry_command(
    monkeypatch, capsys,
):
    app, runs, _ = _harness(None)
    secret = 'python.exe --token=do-not-log'
    runs.values["PadiemClawConnect"] = secret
    monkeypatch.setattr(cli, "Autostart", lambda _name: app.autostart)
    monkeypatch.setattr(cli, "ConnectApp", lambda: object())
    assert cli.main(["autostart", "show"]) == 0
    output = capsys.readouterr().out
    assert secret not in output
    assert "--token" not in output
    import json
    parsed = json.loads(output)
    assert parsed["enabled"] is False
    assert parsed["command"] is None


def test_expired_committed_credential_refuses_autostart():
    from claw_connect.autostart import AutostartRefused
    record = EnrollmentRecord(
        device_id="device.synthetic", binding_ref="binding.synthetic",
        device_lifecycle=LIFECYCLE_PAIRED_OFFLINE,
        credential_expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    app, runs, prefs = _harness(record)
    assert app.reconcile_autostart() is None
    with pytest.raises(AutostartRefused):
        app.autostart.enable(start_command(), record)
    assert runs.values == {} and prefs.values == {}


def test_future_committed_credential_can_register_autostart():
    record = EnrollmentRecord(
        device_id="device.synthetic", binding_ref="binding.synthetic",
        device_lifecycle=LIFECYCLE_PAIRED_OFFLINE,
        credential_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    app, runs, _ = _harness(record)
    assert app.reconcile_autostart() is AutostartOutcome.REGISTERED
    assert len(runs.writes) == 1
