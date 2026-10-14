"""Supervised Resident lifecycle for Claw Connect (#4139 §2/§5, item 8).

The supervisor starts and stops the one existing Resident process. These
tests use a short-lived stand-in command so they never launch the real
Resident, never reach a Broker and never touch a user file.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claw_connect.resident_supervisor import (
    RESIDENT_ENTRY_MODULE,
    ResidentSupervisor,
    default_resident_command,
)

#: A stand-in that behaves like a long-lived resident: it ignores a graceful
#: terminate on Windows and must be reaped by the supervisor's kill path.
SLEEP_FOREVER = [sys.executable, "-c", "import time; time.sleep(60)"]


def test_supervisor_refuses_an_empty_command():
    with pytest.raises(ValueError):
        ResidentSupervisor([])


def test_start_stop_leaves_no_running_child():
    supervisor = ResidentSupervisor(SLEEP_FOREVER)
    resident = supervisor.start()
    assert supervisor.is_running() is True
    assert resident.pid is not None

    supervisor.stop()
    assert supervisor.is_running() is False
    assert resident.running is False
    assert resident.returncode is not None
    supervisor.wait_idle(timeout=5.0) is True


def test_second_start_does_not_create_a_second_resident():
    supervisor = ResidentSupervisor(SLEEP_FOREVER)
    first = supervisor.start()
    second = supervisor.start()
    assert second is first
    assert supervisor.is_running() is True
    supervisor.stop()


def test_stop_is_idempotent_and_safe_when_nothing_is_running():
    supervisor = ResidentSupervisor(SLEEP_FOREVER)
    assert supervisor.stop() is None
    supervisor.start()
    supervisor.stop()
    assert supervisor.stop() is None


def test_restart_replaces_the_child_process():
    supervisor = ResidentSupervisor(SLEEP_FOREVER)
    first = supervisor.start()
    first_pid = first.pid
    time.sleep(0.05)
    second = supervisor.restart()
    assert second is not first
    assert second.pid != first_pid
    assert first.running is False
    supervisor.stop()


def test_forced_kill_when_the_child_ignores_terminate():
    # A child that cannot be terminated gracefully must still be reaped.
    stubborn = [sys.executable, "-c",
                "import time,signal,sys;signal.signal(signal.SIGTERM,lambda *a: None);time.sleep(60)"]
    if sys.platform == "win32":
        # Windows terminate() is already forceful; the graceful path suffices.
        stubborn = SLEEP_FOREVER
    supervisor = ResidentSupervisor(stubborn)
    resident = supervisor.start()
    supervisor.stop(grace=0.2)
    assert resident.running is False
    assert resident.returncode is not None


def test_default_command_targets_the_one_existing_resident_module():
    command = default_resident_command(python="C:/Python311/python.exe")
    assert command[0] == "C:/Python311/python.exe"
    assert RESIDENT_ENTRY_MODULE in command
    assert "-m" in command
    # No second runner, no alternative executor is introduced.
    assert command.count(RESIDENT_ENTRY_MODULE) == 1
