"""#4139 reversible owner OFF is durable and blocks Broker dispatch.

These exercise the real Broker runtime against SQLite-backed Durable Object
adapters; no client flag is ever an authority for ON or OFF.
"""
from __future__ import annotations
from datetime import timedelta

from test_local_agent_broker_enqueue_material_atomicity import (
    _runtime, _register_and_open, _enqueue_payload, _material_body,
    _poll_payload, _admit_payload, _persisted_commands, BASE,
)

OWNER = {"account_ref": "account.atomic.1", "workspace_ref": "workspace.atomic.1"}
BINDING = "binding.atomic.1"


def test_off_prevents_enqueue_poll_and_admit_and_survives_runtime_restart(tmp_path):
    path = tmp_path / "usage.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    queued = runtime.enqueue_command_with_material(
        _enqueue_payload("command.before.off", now=BASE+timedelta(seconds=2)),
        _material_body("command.before.off"),
    )
    assert queued["ok"] is True

    paused = runtime.set_owner_usage({**OWNER, "paused": True})
    assert paused == {"ok": True, "paused": True, "dispatch_authorized": False}
    assert runtime.device_directory(OWNER)["usage_paused"] is True
    blocked = runtime.enqueue_command_with_material(
        _enqueue_payload("command.during.off", now=BASE+timedelta(seconds=3)),
        _material_body("command.during.off"),
    )
    assert blocked["ok"] is False and blocked["error"]["code"] == "owner_pc_paused"
    assert "command.during.off" not in _persisted_commands(path)
    poll = runtime.poll(_poll_payload(at=BASE+timedelta(seconds=4)))
    assert poll["ok"] is True and poll["commands"] == []
    admitted = runtime.admit_command(_admit_payload(queued["command"], at=BASE+timedelta(seconds=5)))
    assert admitted["ok"] is False and admitted["error"]["code"] == "owner_pc_paused"

    # Simulate a Durable Object eviction: preference is persisted in SQLite,
    # not held in browser storage or ephemeral runtime memory.
    restarted = _runtime(path)
    assert restarted.device_directory(OWNER)["usage_paused"] is True
    assert restarted.poll(_poll_payload(at=BASE+timedelta(seconds=6)))["commands"] == []
    resumed = restarted.set_owner_usage({**OWNER, "paused": False})
    assert resumed == {"ok": True, "paused": False, "dispatch_authorized": True}
    assert restarted.device_directory(OWNER)["usage_paused"] is False
    poll_after = restarted.poll(_poll_payload(at=BASE+timedelta(seconds=7)))
    assert [row["command_id"] for row in poll_after["commands"]] == ["command.before.off"]
    admitted_after = restarted.admit_command(
        _admit_payload(queued["command"], at=BASE+timedelta(seconds=8))
    )
    assert admitted_after["ok"] is True


def test_cross_owner_and_malformed_pause_cannot_mutate(tmp_path):
    runtime = _runtime(tmp_path / "usage.sqlite3")
    _register_and_open(runtime)
    invalid = [
        {"account_ref": "other", "workspace_ref": OWNER["workspace_ref"], "paused": True},
        {"account_ref": OWNER["account_ref"], "workspace_ref": "other", "paused": True},
        {**OWNER, "paused": "true"},
        {**OWNER, "paused": True, "device_id": "device.atomic.1"},
        {"paused": True},
    ]
    for attempt in invalid:
        assert runtime.set_owner_usage(attempt)["ok"] is False
    assert runtime.device_directory(OWNER)["usage_paused"] is False
