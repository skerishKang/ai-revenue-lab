"""Hermetic Broker->Python Resident fixture for Windows Node cross-process tests.

Synthetic pre-admitted P01 only. Broker SQLite is constructed ON the actual
Resident responder thread, preserving sqlite3 check_same_thread=True (default).
No product Worker, network call, credentials from users, or browser execution.
"""
from __future__ import annotations

import sys

from kagent.local_agent_desktop_material import ResidentDesktopMaterialResponder
from test_local_agent_broker_browser_authenticated_take_3782 import (
    DEVICE_CREDENTIAL,
    NOW,
)
from test_local_agent_broker_browser_registration_3782 import empty_fixture, register

_resident_thread_state: dict[str, object] = {}


def broker_take(command_ref: str) -> dict:
    if not _resident_thread_state:
        # SQLite connection belongs to THIS responder thread, not the setup
        # thread that reads the Resident's command protocol from stdin.
        storage, broker, scope, material = empty_fixture()
        assert register(broker, scope, material)["stored"] is True
        _resident_thread_state.update(storage=storage, broker=broker, scope=scope)
    broker = _resident_thread_state["broker"]
    scope = _resident_thread_state["scope"]
    if command_ref != scope.command_ref:
        raise ValueError("wrong canonical Broker command reference")
    return broker._take_authenticated_browser_control_command(
        scope=scope, credential=DEVICE_CREDENTIAL, now=NOW,
    )


def emit(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main() -> None:
    responder = ResidentDesktopMaterialResponder(
        material_projection=lambda: {"ok": False},
        approved_command_take=broker_take, emit=emit,
    )
    responder.start()
    assert responder._thread is not None
    responder._thread.join()


if __name__ == "__main__":
    main()
