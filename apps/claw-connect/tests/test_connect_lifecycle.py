"""Claw Connect S1 lifecycle contracts (#4139 items 6–8).

Offline: no Windows desktop, no real registry, no real broker. The registry
and the single-instance lock are reached through seams so these contracts run
on CI as well as on the developer PC.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claw_connect.autostart import (
    PREFERENCE_OFF,
    PREFERENCE_ON,
    REGISTRATION_ABSENT,
    Autostart,
    MemoryPreferenceStore,
    MemoryRunKeyStore,
)
from claw_connect.connection import (
    BACKOFF_SECONDS,
    ConnectionController,
    ConnectionState,
    InvalidTransition,
    MAX_BACKOFF_SECONDS,
)
from claw_connect.single_instance import AlreadyRunning, FileLockBackend, SingleInstance


# --- single instance (#4139 item 7) ---------------------------------------
def test_second_process_is_refused_while_first_holds_the_lock(tmp_path):
    backend_a = FileLockBackend(str(tmp_path / "connect.lock"))
    backend_b = FileLockBackend(str(tmp_path / "connect.lock"))
    first = SingleInstance("ClawConnectTest", backend=backend_a)
    second = SingleInstance("ClawConnectTest", backend=backend_b)

    assert first.acquire() is True
    assert second.acquire() is False
    with pytest.raises(AlreadyRunning):
        with second:
            pass
    first.release()
    assert second.acquire() is True


def test_lock_is_released_after_release_so_a_restart_can_take_it(tmp_path):
    lock = str(tmp_path / "restart.lock")
    holder = SingleInstance("restart", backend=FileLockBackend(lock))
    assert holder.acquire() is True
    holder.release()
    successor = SingleInstance("restart", backend=FileLockBackend(lock))
    assert successor.acquire() is True
    successor.release()


# --- autostart (#4139 item 6; default-ON since the 2026-10-13 contract) ---
def _autostart() -> tuple[Autostart, MemoryRunKeyStore, MemoryPreferenceStore]:
    store = MemoryRunKeyStore()
    preferences = MemoryPreferenceStore()
    return (
        Autostart("PadiemClawConnect", store, preference_store=preferences),
        store,
        preferences,
    )


def test_a_fresh_pc_is_not_registered_and_has_no_recorded_choice():
    autostart, _, _ = _autostart()
    assert autostart.classify() == REGISTRATION_ABSENT
    assert autostart.is_enabled() is False
    assert autostart.current_command() is None
    assert autostart.preference() is None


def test_autostart_can_be_enabled_and_disabled_by_the_user():
    autostart, store, preferences = _autostart()
    command = r'"C:\Python311\python.exe" -m claw_connect start'

    autostart.enable(command)
    assert autostart.is_enabled() is True
    assert autostart.current_command() == command
    assert autostart.preference() == PREFERENCE_ON

    autostart.disable()
    assert autostart.is_enabled() is False
    assert autostart.current_command() is None
    assert "PadiemClawConnect" not in store.values
    # The opt-out is durable, which is what makes it survive restart/logon.
    assert preferences.values == {"Autostart": PREFERENCE_OFF}
    assert autostart.preference() == PREFERENCE_OFF


def test_autostart_refuses_an_empty_command():
    autostart, _, _ = _autostart()
    with pytest.raises(ValueError):
        autostart.enable("   ")


# --- connection state machine (#4139 item 8) ------------------------------
def test_happy_path_connects_once_and_resets_backoff():
    controller = ConnectionController(lambda: True)
    assert controller.state is ConnectionState.DISCONNECTED
    controller.connect()
    assert controller.state is ConnectionState.CONNECTING
    controller.poll()
    assert controller.state is ConnectionState.CONNECTED
    assert controller.reconnect_delay == 0.0


def test_network_loss_is_observed_and_moves_to_disconnected():
    reachable = {"value": True}
    controller = ConnectionController(lambda: reachable["value"])
    controller.connect()
    controller.poll()
    assert controller.state is ConnectionState.CONNECTED

    reachable["value"] = False
    controller.poll()
    assert controller.state is ConnectionState.DISCONNECTED


def test_pause_stops_reconnecting_until_the_user_resumes():
    controller = ConnectionController(lambda: True)
    controller.connect()
    controller.poll()
    controller.pause()
    assert controller.state is ConnectionState.PAUSED
    # A paused controller never reconnects on its own.
    controller.poll()
    assert controller.state is ConnectionState.PAUSED
    controller.resume()
    assert controller.state is ConnectionState.CONNECTING


def test_reconnect_backoff_is_bounded_and_capped():
    controller = ConnectionController(lambda: False, backoff=BACKOFF_SECONDS)
    delays = []
    for _ in range(len(BACKOFF_SECONDS) + 3):
        controller.connect()
        delays.append(controller.fail())
    assert delays == sorted(delays)
    assert max(delays) <= MAX_BACKOFF_SECONDS
    # The very last step stays at the cap instead of growing without bound.
    assert delays[-1] == min(BACKOFF_SECONDS[-1], MAX_BACKOFF_SECONDS)


def test_invalid_transitions_are_refused():
    controller = ConnectionController(lambda: True)
    with pytest.raises(InvalidTransition):
        controller.pause()
    controller.connect()
    controller.poll()
    with pytest.raises(InvalidTransition):
        controller.succeed()


def test_disconnect_from_every_state_is_allowed():
    for setup in (
        lambda c: None,
        lambda c: c.connect(),
        lambda c: (c.connect(), c.poll()),
        lambda c: (c.connect(), c.poll(), c.pause()),
    ):
        controller = ConnectionController(lambda: True)
        setup(controller)
        controller.disconnect()
        assert controller.state is ConnectionState.DISCONNECTED
