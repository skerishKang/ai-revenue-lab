"""#5553 — the composer control and the Connectors card show ONE state.

The composer status chip and the Connectors computer card both answer the
same question, so they must not read the state two different ways. These
contracts are pinned here:

- ONE_STATE_AUTHORITY: the shared state module owns the classification, and
  the card no longer opens a connection of its own.
- ONE_VOCABULARY: connected / connecting / disconnected / unavailable /
  preparing, with one colour per state on both surfaces.
- NEVER_FAKE_CONNECTED: a read that did not complete, a read that failed and a
  deployment without the lane never read as connected.
- THE_READER_STAYS_ONE: a re-read only triggers the existing directory
  control, so the device directory module stays the only reader.
"""
from __future__ import annotations

from _support import connection_state_static as state_assets

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

STATE_JS = state_assets.state_js()
COMPOSER_JS = state_assets.composer_js()
HOME_JS = state_assets.home_js()
COMPOSER_CSS_SELECTORS = state_assets.selectors("claw-composer-connection-status.css")
NAV_CSS_SELECTORS = state_assets.selectors("capability-nav.css")
COMPOSER_CSS_VALUES = state_assets.declaration_values("claw-composer-connection-status.css")
NAV_CSS_VALUES = state_assets.declaration_values("capability-nav.css")

STATES = ("connected", "connecting", "disconnected", "unavailable", "preparing")


# ── one authority ──────────────────────────────────────────────────────────


def test_the_shared_state_module_owns_the_classification():
    assert "function classify(snapshot)" in STATE_JS
    assert "PadiemComputerConnectionState" in STATE_JS
    # The composer does not classify on its own any more.
    assert "PadiemComputerConnectionState" in COMPOSER_JS
    assert "device.online === true" not in COMPOSER_JS


def test_the_card_does_not_open_a_connection_of_its_own():
    # The Connectors computer card reads the shared state, so the device
    # directory module stays the only reader of the canonical endpoint.
    assert "/api/claw/local-access/devices" not in HOME_JS
    assert "PadiemComputerConnectionState" in HOME_JS
    assert "padiem:computer-connection" in HOME_JS


def test_a_reread_only_triggers_the_existing_directory_control():
    assert "claw-device-manager-refresh" in STATE_JS
    # The shared module opens no connection itself.
    assert "fetch(" not in STATE_JS
    assert "/api/" not in STATE_JS


# ── the vocabulary ─────────────────────────────────────────────────────────


def test_the_shared_vocabulary_is_the_five_states():
    for state in STATES:
        assert f'"{state}"' in STATE_JS, state


def test_the_composer_label_covers_every_state():
    for state in STATES:
        assert f'"{state}"' in COMPOSER_JS, state
    # The old state names are gone, so a surface cannot speak two languages.
    assert "checkingHint" not in COMPOSER_JS
    assert '"unknown"' not in COMPOSER_JS


def test_the_card_copy_covers_every_state():
    for state in STATES:
        assert f"{state}:" in HOME_JS, state


def test_both_surfaces_use_the_same_state_names():
    for state in STATES:
        assert (any(f'data-state="{state}"' in selector for selector in COMPOSER_CSS_SELECTORS)
                or state in ("disconnected", "preparing")), state
        assert (any(f'data-connector-status="{state}"' in selector for selector in NAV_CSS_SELECTORS)
                or state in ("disconnected", "preparing")), state


def test_each_state_has_one_colour_on_both_surfaces():
    # The composer chip: connected, connecting and unreadable have their own.
    for state in ("connected", "connecting", "unavailable"):
        assert any(f'[data-state="{state}"]' in selector
                   for selector in COMPOSER_CSS_SELECTORS), state
        assert any(f'[data-connector-status="{state}"]' in selector
                   for selector in NAV_CSS_SELECTORS), state
    # The connected/unreadable tones use the same tokens on both surfaces.
    for token in ("--success", "--danger"):
        assert any(token in value for value in COMPOSER_CSS_VALUES), token
        assert any(token in value for value in NAV_CSS_VALUES), token


# ── never fake a connection ────────────────────────────────────────────────


def test_an_unread_or_failed_state_is_never_connected():
    # The classification only reports connected when the server proved a
    # usable device.
    assert 'return STATE.CONNECTING' in STATE_JS
    assert 'return STATE.UNAVAILABLE' in STATE_JS
    assert 'usableDevice(target)) return STATE.CONNECTED' in STATE_JS
    # A revoked or expired device is never connected.
    assert "device.revoked !== true && device.expired !== true" in STATE_JS


def test_a_failed_read_is_not_shown_as_not_connected():
    # The unreadable state is its own state, never the disconnected one.
    assert 'status === "readFailed"' in STATE_JS
    assert 'status === "failed"' in STATE_JS
    assert 'status === "unavailable"' in STATE_JS
    # A deployment without the lane is "preparing", not an error.
    assert 'status === "unconfigured"' in STATE_JS


def test_the_shared_module_is_loaded_before_the_composer_control():
    scripts = state_assets.script_sources()
    assert "./claw-connection-state.js" in scripts
    assert "./claw-composer-connection-status.js" in scripts
    assert scripts.index("./claw-connection-state.js") < scripts.index(
        "./claw-composer-connection-status.js"
    )


# ── the backend stays untouched ────────────────────────────────────────────


def test_no_connector_backend_or_endpoint_changed():
    # The existing endpoints and the existing device directory reader stay.
    assert '"/api/claw/local-access/devices"' in state_assets.device_manager_js()
    assert '"/api/connectors/github/status"' in state_assets.connector_management_js()
