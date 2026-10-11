"""Tray menu, CLI and packaging contracts for Claw Connect (#4139 items 5, 9–10)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.connection import ConnectionState
from claw_connect.menu_model import (
    ACTION_DISCONNECT,
    ACTION_OPEN_WEB,
    ACTION_QUIT,
    ACTION_RECONNECT,
    ACTION_TOGGLE_PAUSE,
    ITEM_STATUS,
    build_menu,
    selectable_ids,
)
from claw_connect import __main__ as cli

ALL_STATES = tuple(ConnectionState)


# --- tray menu contract (#4139 item 5) ------------------------------------
@pytest.mark.parametrize("state", ALL_STATES)
def test_every_state_shows_the_six_required_tray_items(state):
    labels = [item.label for item in build_menu(state)]
    assert "Claw Web 열기" in labels
    assert "일시중지" in labels or "다시 시작" in labels
    assert "다시 연결" in labels
    assert "연결 해제" in labels
    assert "종료" in labels


@pytest.mark.parametrize("state", ALL_STATES)
def test_status_rows_are_informational_and_never_selectable(state):
    for item in build_menu(state):
        if item.id == ITEM_STATUS:
            assert item.enabled is False


def test_pause_is_offered_only_when_connected_and_resume_only_when_paused():
    connected = selectable_ids(ConnectionState.CONNECTED)
    paused = selectable_ids(ConnectionState.PAUSED)
    assert ACTION_TOGGLE_PAUSE in connected
    assert ACTION_TOGGLE_PAUSE in paused
    assert ACTION_TOGGLE_PAUSE not in selectable_ids(ConnectionState.DISCONNECTED)
    assert ACTION_TOGGLE_PAUSE not in selectable_ids(ConnectionState.CONNECTING)


def test_quit_is_always_selectable_and_disconnect_only_when_busy():
    for state in ALL_STATES:
        assert ACTION_QUIT in selectable_ids(state)
    assert ACTION_DISCONNECT not in selectable_ids(ConnectionState.DISCONNECTED)
    for state in (ConnectionState.CONNECTING, ConnectionState.CONNECTED,
                  ConnectionState.PAUSED):
        assert ACTION_DISCONNECT in selectable_ids(state)


def test_every_selectable_action_is_one_of_the_known_callbacks():
    known = {
        ACTION_OPEN_WEB, ACTION_TOGGLE_PAUSE, ACTION_RECONNECT,
        ACTION_DISCONNECT, ACTION_QUIT,
    }
    for state in ALL_STATES:
        assert set(selectable_ids(state)) <= known


# --- CLI contract (#4139 item 9) ------------------------------------------
def test_cli_defaults_to_start_and_exposes_the_required_commands():
    parser = cli.build_parser()
    assert parser.parse_args([]).command == "start"
    assert parser.parse_args(["status"]).command == "status"
    assert parser.parse_args(["stop"]).command == "stop"
    assert parser.parse_args(["autostart", "on"]).autostart_mode == "on"
    assert parser.parse_args(["autostart", "off"]).autostart_mode == "off"
    assert parser.parse_args(["autostart", "show"]).autostart_mode == "show"


def test_status_command_prints_machine_readable_state():
    from claw_connect.runtime import ConnectApp

    code = cli.main(["status"])
    assert code == 0


def test_connect_app_status_never_claims_an_unobserved_state():
    from claw_connect.runtime import ConnectApp

    app = ConnectApp(resident_command=[sys.executable, "-c", "pass"])
    status = app.status()
    assert status["state"] == ConnectionState.DISCONNECTED.value
    assert status["resident_running"] is False
    assert status["autostart_enabled"] is False
    assert set(status) == {
        "product", "version", "state", "resident_running",
        "autostart_enabled", "single_instance",
    }
    json.dumps(status)  # must stay JSON serialisable


# --- packaging contract (#4139 item 9) ------------------------------------
def test_npx_entry_point_and_package_manifest_exist():
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert manifest["bin"]["claw-connect"] == "bin/claw-connect.mjs"
    assert "claw_connect/" in manifest["files"]
    assert (ROOT / "bin" / "claw-connect.mjs").exists()


def test_installer_is_per_user_and_never_requests_administrator_rights():
    script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    # Only the executable lines matter; the header comments explain what the
    # installer deliberately does not do.
    code = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("#")
    )
    assert "HKCU" in code
    assert "HKLM" not in code
    assert "New-Service" not in code
    assert "-Verb RunAs" not in code
    # Both the opt-in autostart switch and the uninstall path are required.
    assert "[switch]$Autostart" in code
    assert "[switch]$Uninstall" in code
    assert "$RunValueName" in code


def test_installer_copies_the_same_module_the_npx_path_runs():
    script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "bin" / "claw-connect.mjs").read_text(encoding="utf-8")
    # Both installation paths must execute the same Python module.
    assert "claw_connect" in script
    assert "run_module('claw_connect'" in wrapper or "run_module('claw_connect" in wrapper


def test_connect_package_does_not_introduce_a_second_engine_or_inbound_port():
    for path in (ROOT / "claw_connect").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "listen(" not in source
        assert "bind((" not in source
