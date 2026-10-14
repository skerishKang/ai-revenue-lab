"""No-secret Windows browser protocol starts only the canonical tray.

The URI is never an account, device or enrollment authority. These tests do
not touch a real Registry key, browser, network, or resident process.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from claw_connect import __main__ as cli
from claw_connect.browser_launch import BROWSER_START_URI, accepts_browser_launch_uri


@pytest.mark.parametrize("invalid", (
    "", None, 3, b"padiem-connector://start",
    "https://chat.padiem.net/", "padiem-connector://START",
    "padiem-connector://start/", "padiem-connector://start?token=fake",
    "padiem-connector://start?pairing_code=fake",
    "padiem-connector://start#session",
    "padiem-connector://start@evil.invalid",
    "padiem-connector://start:443",
    "padiem-connector://start%2f",
    'padiem-connector://start" --extra-argument',
    "padiem-connector://start\n--injected",
))
def test_browser_launch_is_byte_exact_and_contains_no_credentials(invalid):
    assert not accepts_browser_launch_uri(invalid)


def test_protocol_default_is_only_zero_data_start():
    assert BROWSER_START_URI == "padiem-connector://start"
    assert accepts_browser_launch_uri(BROWSER_START_URI)


def test_invalid_uri_rejected_before_creating_machine_state(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ConnectApp", lambda: pytest.fail("created state"))
    assert cli.main(["open-from-web", "padiem-connector://start?token=fake"]) == 2
    assert "untrusted browser launch URI" in capsys.readouterr().out


def test_allowed_link_starts_existing_tray_only_and_never_claims_pairing(monkeypatch):
    events = []
    class ExistingTray:
        def run(self):
            events.append("start_tray")
            return cli.CONNECT_APP_EXIT_ALREADY_RUNNING
    monkeypatch.setattr(cli, "ConnectApp", ExistingTray)
    assert cli.main(["open-from-web", BROWSER_START_URI]) == 0
    assert events == ["start_tray"]


def test_launch_protocol_is_standalone_local_package_entrypoint():
    launcher = (ROOT / "launch_protocol.py").read_text(encoding="utf-8")
    assert "from claw_connect.__main__ import main" in launcher
    assert '"open-from-web"' in launcher
    assert "sys.argv[1:]" in launcher
    assert "subprocess" not in launcher
    assert "shell=True" not in launcher


def test_installer_registers_only_per_user_uri_and_safe_uninstall():
    installer = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "HKCU:\\Software\\Classes\\padiem-connector" in installer
    assert "$ExpectedProtocolCommand" in installer
    assert "(Get-ProtocolCommand) -cne $ExpectedProtocolCommand" in installer
    assert "(Get-ProtocolCommand) -ceq $ExpectedProtocolCommand" in installer
    assert "Copy-Item -Path (Join-Path $SourceRoot 'launch_protocol.py')" in installer
    assert '"%1"' in installer
    assert "HKLM:" not in installer
    assert "New-Service" not in installer


def test_uninstalled_browser_protocol_launcher_from_foreign_working_directory(tmp_path):
    import os
    import shutil
    import subprocess

    installed = tmp_path / "installed" / "ClawConnect"
    installed.mkdir(parents=True)
    for package in ("claw_connect", "padiem_connector"):
        shutil.copytree(ROOT / package, installed / package,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "launch_protocol.py", installed / "launch_protocol.py")
    unrelated = tmp_path / "foreign_cwd"
    unrelated.mkdir()
    state = tmp_path / "state"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["CLAW_CONNECT_STATE_DIR"] = str(state)
    response = subprocess.run(
        [sys.executable, str(installed / "launch_protocol.py"),
         "padiem-connector://start?owner=fake"],
        cwd=unrelated, env=env, capture_output=True, text=True, timeout=15,
    )
    assert response.returncode == 2
    assert "untrusted browser launch URI" in response.stdout
    assert "owner=fake" not in response.stdout
    assert not state.exists()
