"""#3123 — bounded terminal history without losing sequence authority.

Every test here drives the real state path: `StateBackedLocalAgentBrokerAuthority`
over `SerializedLocalAgentBrokerStatePort`, so compaction, tombstones, the
watermark and the wire bounds are exercised through the same encode → CAS →
decode round trip a durable object performs. The only patched values are the
module-level trigger thresholds, so small-scale tests can reach the same code
paths the 10,000-record pressure test reaches at full scale.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane import local_agent_broker as broker_module
from padiem_control_plane import local_agent_broker_state as state_module
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    MAX_COMPACTION_TOMBSTONES,
    BrokerCommandRecord,
    BrokerCommandState,
    TERMINAL_RETENTION_SECONDS,
    InMemoryLocalAgentBrokerAuthority,
)
from padiem_control_plane.local_agent_broker_state import (
    LocalAgentBrokerStateSnapshot,
    StateBackedLocalAgentBrokerAuthority,
)
from padiem_control_plane.local_agent_broker_state_wire import (
    BROKER_STATE_WIRE_VERSION,
    MAX_BROKER_STATE_COLLECTION_ITEMS,
    InMemorySerializedLocalAgentBrokerStateBackend,
    LocalAgentBrokerStateJsonCodec,
    SerializedLocalAgentBrokerStatePort,
    SerializedLocalAgentBrokerStateRecord,
)

BASE = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
PEPPER = b"compaction-test-pepper-0123456789abcdef"
CREDENTIAL_1 = b"compaction-device-credential-1"
FINGERPRINT = "d" * 64
FINGERPRINT_2 = "e" * 64
AUTHORITY_REF = "control-plane.local-agent-broker.compaction-test.v1"
BINDING = "binding.compaction.1"


def _port() -> SerializedLocalAgentBrokerStatePort:
    return SerializedLocalAgentBrokerStatePort(
        backend=InMemorySerializedLocalAgentBrokerStateBackend(),
    )


def _authority(port: SerializedLocalAgentBrokerStatePort) -> StateBackedLocalAgentBrokerAuthority:
    return StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=port,
    )


def _register(authority: StateBackedLocalAgentBrokerAuthority, *, now: datetime = BASE):
    return authority.register_binding(
        binding_ref=BINDING,
        device_id="device.compaction.1",
        account_ref="account.compaction.1",
        workspace_ref="workspace.compaction.1",
        credential=CREDENTIAL_1,
        now=now,
    )


def _session(
    authority: StateBackedLocalAgentBrokerAuthority,
    *,
    session_id: str = "session.compaction.1",
    now: datetime = BASE + timedelta(seconds=1),
):
    return authority.open_session(
        session_id=session_id,
        binding_ref=BINDING,
        credential=CREDENTIAL_1,
        account_ref="account.compaction.1",
        workspace_ref="workspace.compaction.1",
        now=now,
    )


def _enqueue(
    authority: StateBackedLocalAgentBrokerAuthority,
    command_id: str,
    *,
    now: datetime,
    fingerprint: str = FINGERPRINT,
) -> BrokerCommandRecord:
    return authority.enqueue_command(
        command_id=command_id,
        binding_ref=BINDING,
        run_id=f"run.{command_id}",
        tool_request_ref=f"tool-request.{command_id}",
        request_fingerprint=fingerprint,
        now=now,
    )


def _admit(
    authority: StateBackedLocalAgentBrokerAuthority,
    command: BrokerCommandRecord,
    *,
    index: str,
    session_id: str,
    now: datetime,
):
    return authority.admit_command(
        admission_ref=f"admission.{index}",
        evidence_ref=f"evidence.{index}",
        session_id=session_id,
        binding_ref=BINDING,
        credential=CREDENTIAL_1,
        command_id=command.command_id,
        request_fingerprint=command.request_fingerprint,
        request_id=f"request.{index}",
        now=now,
    )


def _ack(
    authority: StateBackedLocalAgentBrokerAuthority,
    command: BrokerCommandRecord,
    *,
    index: str,
    session_id: str,
    now: datetime,
    exit_code: int | None = 0,
) -> BrokerCommandRecord:
    return authority.acknowledge(
        session_id=session_id,
        binding_ref=BINDING,
        credential=CREDENTIAL_1,
        command_id=command.command_id,
        admission_ref=f"admission.{index}",
        evidence_ref=f"evidence.{index}",
        revision_ref=command.revision_ref,
        termination="exited",
        request_id=f"request.{index}",
        exit_code=exit_code,
        now=now,
    )


def _live_state(port: SerializedLocalAgentBrokerStatePort) -> LocalAgentBrokerStateSnapshot:
    return port.load(authority_ref=AUTHORITY_REF).snapshot


# ---------------------------------------------------------------------------
# Retention: terminal records compact to tombstones, nothing else ever does
# ---------------------------------------------------------------------------


def test_acknowledged_command_compacts_after_retention_keeping_watermark(monkeypatch):
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    port = _port()
    authority = _authority(port)
    _register(authority)
    session = _session(authority)
    command = _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(authority, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    _ack(authority, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=10))

    # One second inside the horizon: still retained in full.
    retained = _enqueue(authority, "command.c.keep", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS - 1))
    state = _live_state(port)
    assert state.commands[0].command_id == "command.c.1"
    assert state.commands[0].state is BrokerCommandState.ACKNOWLEDGED
    assert state.compacted_commands == ()

    # Past the horizon, the next mutation compacts the terminal record.
    _enqueue(authority, "command.c.2", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 1))
    state = _live_state(port)
    assert [item.command_id for item in state.commands] == ["command.c.keep", "command.c.2"]
    # The tombstone keeps the id rejected; the sequence stays visible.
    assert [tombstone.command_id for tombstone in state.compacted_commands] == ["command.c.1"]
    assert state.compacted_through_by_binding == ()
    # The watermark never moves down and the new command never reuses a sequence.
    assert dict(state.last_sequence_by_binding)[BINDING] == 3
    assert retained.sequence == 2
    assert [item.sequence for item in state.commands] == [2, 3]


def test_queued_and_admitted_commands_are_never_evicted(monkeypatch):
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    port = _port()
    authority = _authority(port)
    _register(authority)
    session = _session(authority)
    acked = _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(authority, acked, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    _ack(authority, acked, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=10))
    admitted = _enqueue(authority, "command.c.2", now=BASE + timedelta(seconds=11))
    _admit(authority, admitted, index="c.2", session_id=session.session_id, now=BASE + timedelta(seconds=12))
    queued = _enqueue(authority, "command.c.3", now=BASE + timedelta(seconds=13))

    far_future = BASE + timedelta(days=2)
    _enqueue(authority, "command.c.4", now=far_future)

    state = _live_state(port)
    by_id = {item.command_id: item for item in state.commands}
    # Active work survives 30 days of pressure; only the terminal record goes.
    assert by_id["command.c.2"].state is BrokerCommandState.ADMITTED
    assert by_id["command.c.3"].state is BrokerCommandState.QUEUED
    assert by_id["command.c.4"].state is BrokerCommandState.QUEUED
    assert "command.c.1" not in by_id
    assert [tombstone.command_id for tombstone in state.compacted_commands] == ["command.c.1"]
    assert queued.sequence == 3 and admitted.sequence == 2


def test_expired_admitted_is_unresolved_until_reconciled_then_compactable(monkeypatch):
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    port = _port()
    authority = _authority(port)
    _register(authority)
    session = _session(authority)
    command = _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(authority, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    # The #3121 reconciliation contract: an admitted command past its deadline
    # stays ADMITTED — unresolved evidence — until the device reconciles it.
    far_future = BASE + timedelta(days=2)
    _enqueue(authority, "command.c.2", now=far_future)
    state = _live_state(port)
    assert state.commands[0].state is BrokerCommandState.ADMITTED
    assert state.compacted_commands == ()

    # A restarted device reconciles on a fresh session; the deleted expired
    # one is exactly the state the compaction is allowed to reclaim.
    fresh_session = _session(authority, session_id="session.compaction.2", now=far_future + timedelta(seconds=1))
    reconciled = authority.reconcile_expired_command(
        session_id=fresh_session.session_id,
        binding_ref=BINDING,
        credential=CREDENTIAL_1,
        command_id=command.command_id,
        admission_ref="admission.c.1",
        revision_ref=command.revision_ref,
        request_id="request.c.1",
        request_fingerprint=command.request_fingerprint,
        termination=None,
        exit_code=None,
        now=far_future + timedelta(seconds=1),
    )
    assert reconciled.state is BrokerCommandState.EXPIRED

    _enqueue(authority, "command.c.3", now=far_future + timedelta(seconds=1) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 1))
    state = _live_state(port)
    # The reconciled EXPIRED record is terminal evidence whose retention window
    # has passed: compacted to a tombstone, correlation kept, nothing fabricated.
    assert [item.command_id for item in state.commands] == ["command.c.2", "command.c.3"]
    assert [tombstone.command_id for tombstone in state.compacted_commands] == ["command.c.1"]


# ---------------------------------------------------------------------------
# Duplicate rejection across compaction
# ---------------------------------------------------------------------------


def test_compacted_command_id_is_rejected_and_sequence_is_never_reused(monkeypatch):
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    port = _port()
    authority = _authority(port)
    _register(authority)
    session = _session(authority)
    command = _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(authority, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    _ack(authority, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=10))
    _enqueue(authority, "command.c.trigger", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 1))
    assert [tombstone.command_id for tombstone in _live_state(port).compacted_commands] == ["command.c.1"]

    # An exact retry of the compacted id cannot be served from the record
    # anymore, and it must not silently become a fresh command either.
    with pytest.raises(ControlPlaneContractError) as exact:
        _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 2))
    assert exact.value.code == "broker_command_history_compacted"
    with pytest.raises(ControlPlaneContractError) as conflicting:
        _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 2), fingerprint=FINGERPRINT_2)
    assert conflicting.value.code == "broker_command_history_compacted"

    # The live #3118 contract is untouched for records that still exist.
    live = _enqueue(authority, "command.c.trigger", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 2))
    assert live.state is BrokerCommandState.QUEUED
    fresh = _enqueue(authority, "command.c.9", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 3))
    assert fresh.sequence == live.sequence + 1


def test_ack_of_compacted_command_refuses_explicitly(monkeypatch):
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    port = _port()
    authority = _authority(port)
    _register(authority)
    session = _session(authority)
    command = _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(authority, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    _ack(authority, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=10))
    _enqueue(authority, "command.c.trigger", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 1))
    late_session = _session(authority, session_id="session.compaction.2", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 1))
    with pytest.raises(ControlPlaneContractError) as retry:
        authority.acknowledge(
            session_id=late_session.session_id,
            binding_ref=BINDING,
            credential=CREDENTIAL_1,
            command_id="command.c.1",
            admission_ref="admission.c.1",
            evidence_ref="evidence.c.1",
            revision_ref=command.revision_ref,
            termination="exited",
            request_id="request.c.1",
            exit_code=0,
            now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 2),
        )
    assert retry.value.code == "broker_command_history_compacted"


# ---------------------------------------------------------------------------
# Folding: contiguous terminal prefixes become watermark state
# ---------------------------------------------------------------------------


def test_contiguous_prefix_folds_under_tombstone_budget_pressure(monkeypatch):
    # Folding is budget relief, not routine cleanup: with a one-slot budget,
    # the next compaction must fold the contiguous prefix to make room, which
    # is exactly the pressure path the 10k test exercises at full scale.
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    monkeypatch.setattr(broker_module, "MAX_COMPACTION_TOMBSTONES", 1)
    port = _port()
    authority = _authority(port)
    _register(authority)
    session = _session(authority)
    first = _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(authority, first, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    _ack(authority, first, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=10))
    _enqueue(authority, "command.c.trigger", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 1))

    # Room existed (empty budget), so the tombstone persisted without folding.
    retained = _live_state(port)
    assert [tombstone.command_id for tombstone in retained.compacted_commands] == ["command.c.1"]
    assert retained.compacted_through_by_binding == ()
    assert dict(retained.last_sequence_by_binding)[BINDING] == 2

    # The next terminal record fills the budget: the contiguous prefix folds
    # through both consumed sequences and the window slides forward. Both
    # records are acknowledged inside the first hour; the late mutation is
    # what drives the retention pass.
    second = _enqueue(authority, "command.c.2", now=BASE + timedelta(seconds=11))
    _admit(authority, second, index="c.2", session_id=session.session_id, now=BASE + timedelta(seconds=12))
    _ack(authority, second, index="c.2", session_id=session.session_id, now=BASE + timedelta(seconds=13))
    _enqueue(authority, "command.c.trigger2", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 5))
    state = _live_state(port)
    # The fold fired when the budget was full — before the new tombstone was
    # placed — so the prefix reached sequence 1 and the newest tombstone stayed.
    assert dict(state.compacted_through_by_binding)[BINDING] == 1
    assert [tombstone.command_id for tombstone in state.compacted_commands] == ["command.c.2"]
    assert dict(state.last_sequence_by_binding)[BINDING] == 4

    # Sustained pressure must not overreach: sequence 2 belongs to the still
    # live `trigger` command, so the fold stays at 1 no matter how often it
    # runs. The prefix only ever claims fully terminal, fully compacted runs.
    _enqueue(authority, "command.c.trigger3", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 6))
    drained = _live_state(port)
    assert dict(drained.compacted_through_by_binding)[BINDING] == 1
    assert [tombstone.sequence for tombstone in drained.compacted_commands] == [3]
    assert dict(drained.last_sequence_by_binding)[BINDING] == 5


def test_fold_stops_at_a_live_command_and_tombstone_window_survives(monkeypatch):
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    monkeypatch.setattr(broker_module, "MAX_COMPACTION_TOMBSTONES", 2)
    port = _port()
    authority = _authority(port)
    _register(authority)
    session = _session(authority)
    first = _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(authority, first, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    _ack(authority, first, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=10))
    # sequence 2 stays QUEUED forever: the prefix can never fold past it.
    _enqueue(authority, "command.c.2", now=BASE + timedelta(seconds=11))

    third = _enqueue(authority, "command.c.3", now=BASE + timedelta(seconds=12))
    _admit(authority, third, index="c.3", session_id=session.session_id, now=BASE + timedelta(seconds=13))
    _ack(authority, third, index="c.3", session_id=session.session_id, now=BASE + timedelta(seconds=14))
    fourth = _enqueue(authority, "command.c.4", now=BASE + timedelta(seconds=15))
    _admit(authority, fourth, index="c.4", session_id=session.session_id, now=BASE + timedelta(seconds=16))
    _ack(authority, fourth, index="c.4", session_id=session.session_id, now=BASE + timedelta(seconds=17))
    later = BASE + timedelta(seconds=30) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 1)
    _enqueue(authority, "command.c.5", now=later)

    state = _live_state(port)
    tombstone_ids = [tombstone.command_id for tombstone in state.compacted_commands]
    # The prefix folded through sequence 1 and stopped at the live sequence 2.
    assert dict(state.compacted_through_by_binding)[BINDING] == 1
    # The budget forced the deepest tombstone out only after the fold freed
    # what the contiguous prefix could; the recent window survived.
    assert tombstone_ids == ["command.c.3", "command.c.4"]
    assert dict(state.last_sequence_by_binding)[BINDING] == 5
    with pytest.raises(ControlPlaneContractError) as rejected:
        _enqueue(authority, "command.c.4", now=later + timedelta(seconds=7))
    assert rejected.value.code == "broker_command_history_compacted"
    fresh = _enqueue(authority, "command.c.6", now=later + timedelta(seconds=7))
    assert fresh.sequence == 6


# ---------------------------------------------------------------------------
# Restart recovery over the real serialized wire
# ---------------------------------------------------------------------------


def test_tombstones_and_prefix_survive_restart_and_keep_rejecting(monkeypatch):
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    port = _port()
    first = _authority(port)
    _register(first)
    session = _session(first)
    command = _enqueue(first, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(first, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    _ack(first, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=10))
    _enqueue(first, "command.c.trigger", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 1))
    before = _live_state(port)
    assert [tombstone.command_id for tombstone in before.compacted_commands] == ["command.c.1"]
    assert before.compacted_through_by_binding == ()

    # A fresh process over the same durable backend: everything the watermark
    # and the tombstone state prove survives the restart.
    restarted = _authority(port)
    fresh = restarted.enqueue_command(
        command_id="command.c.9",
        binding_ref=BINDING,
        run_id="run.command.c.9",
        tool_request_ref="tool-request.command.c.9",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 2),
    )
    assert fresh.sequence == dict(before.last_sequence_by_binding)[BINDING] + 1
    after = _live_state(port)
    assert after.compacted_through_by_binding == before.compacted_through_by_binding
    assert after.compacted_commands == before.compacted_commands
    assert dict(after.last_sequence_by_binding)[BINDING] == fresh.sequence
    with pytest.raises(ControlPlaneContractError) as rejected:
        _enqueue(restarted, "command.c.1", now=BASE + timedelta(seconds=10) + timedelta(seconds=TERMINAL_RETENTION_SECONDS + 3))
    assert rejected.value.code == "broker_command_history_compacted"


def test_legacy_v2_state_survives_restart_and_upgrades_on_next_write():
    port = _port()
    authority = _authority(port)
    _register(authority)
    _session(authority)
    _enqueue(authority, "command.c.1", now=BASE + timedelta(seconds=2))
    v3_payload = json.loads(LocalAgentBrokerStateJsonCodec().encode(_live_state(port)).decode("utf-8"))
    assert v3_payload["wire_version"] == BROKER_STATE_WIRE_VERSION

    # A durable object written before #3123 holds exactly this shape.
    legacy = {key: value for key, value in v3_payload.items() if key not in {"compacted_commands", "compacted_through_by_binding"}}
    legacy["wire_version"] = "padiem.local-agent-broker-state-wire.v2"
    legacy_payload = json.dumps(legacy, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    decoded = LocalAgentBrokerStateJsonCodec().decode(legacy_payload)
    assert decoded.compacted_commands == ()
    assert decoded.compacted_through_by_binding == ()
    assert decoded == _live_state(port)

    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    backend._rows[AUTHORITY_REF] = SerializedLocalAgentBrokerStateRecord(version=1, payload=legacy_payload)
    restarted = _authority(SerializedLocalAgentBrokerStatePort(backend=backend))
    upgraded = restarted.enqueue_command(
        command_id="command.c.2",
        binding_ref=BINDING,
        run_id="run.command.c.2",
        tool_request_ref="tool-request.command.c.2",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=3),
    )
    assert upgraded.sequence == 2
    stored = backend._rows[AUTHORITY_REF]
    assert json.loads(stored.payload.decode("utf-8"))["wire_version"] == BROKER_STATE_WIRE_VERSION


# ---------------------------------------------------------------------------
# The real 10,000-record pressure path
# ---------------------------------------------------------------------------


def _persist_bulk_acked_state(
    port: SerializedLocalAgentBrokerStatePort,
    backend: InMemorySerializedLocalAgentBrokerStateBackend,
    record_count: int,
) -> None:
    """Persist a fully-acknowledged bulk history through the real serialized CAS.

    Fixture-only construction: the point under test is the wire/CAS/compaction
    path at real scale, not enqueue throughput. Every record is a fully
    validated `BrokerCommandRecord` and the snapshot passes the closed snapshot
    validation exactly as a real captured state would.
    """
    seed = InMemoryLocalAgentBrokerAuthority(pepper=PEPPER, authority_ref=AUTHORITY_REF)
    seed.register_binding(
        binding_ref=BINDING,
        device_id="device.compaction.1",
        account_ref="account.compaction.1",
        workspace_ref="workspace.compaction.1",
        credential=CREDENTIAL_1,
        now=BASE,
    )
    for index in range(1, record_count + 1):
        seed._commands[f"command.bulk.{index}"] = BrokerCommandRecord(
            command_id=f"command.bulk.{index}",
            run_id=f"run.bulk.{index}",
            tool_request_ref=f"tool-request.bulk.{index}",
            binding_ref=BINDING,
            credential_generation=1,
            sequence=index,
            request_fingerprint=FINGERPRINT,
            issued_at=BASE + timedelta(seconds=2),
            expires_at=BASE + timedelta(seconds=302),
            state=BrokerCommandState.ACKNOWLEDGED,
            admission_ref=f"admission.bulk.{index}",
            evidence_ref=f"evidence.bulk.{index}",
            admitted_session_id="session.bulk.1",
            admitted_at=BASE + timedelta(seconds=5),
            acknowledged_at=BASE + timedelta(seconds=10),
            revision_ref=f"rev.{index:032x}",
            termination="exited",
            request_id=f"request.bulk.{index}",
            exit_code=0,
        )
    seed._last_sequence_by_binding[BINDING] = record_count
    port.compare_and_swap(authority_ref=AUTHORITY_REF, expected_version=0, snapshot=LocalAgentBrokerStateSnapshot.capture(seed))


def test_pressure_over_the_real_wire_bound_compacts_and_keeps_authority():
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    port = SerializedLocalAgentBrokerStatePort(backend=backend)
    record_count = MAX_BROKER_STATE_COLLECTION_ITEMS
    _persist_bulk_acked_state(port, backend, record_count)
    now = BASE + timedelta(days=2)

    # One more enqueue: the captured state has 10,001 commands, the real codec
    # refuses to encode it, and the mutation must recover through real
    # compaction - not by raising, not by dropping live state.
    authority = _authority(port)
    result = authority.enqueue_command(
        command_id="command.bulk.new",
        binding_ref=BINDING,
        run_id="run.bulk.new",
        tool_request_ref="tool-request.bulk.new",
        request_fingerprint=FINGERPRINT,
        now=now,
    )
    # The watermark owns the sequence: no reuse, no second mint.
    assert result.sequence == record_count + 1

    state = _live_state(port)
    assert dict(state.last_sequence_by_binding)[BINDING] == record_count + 1
    # Every compacted record was terminal; the fresh queued command survived.
    assert result.state is BrokerCommandState.QUEUED
    assert "command.bulk.new" in {item.command_id for item in state.commands}
    # The contiguous terminal prefix folded into the watermark, and the
    # retained tombstone window covers the rest: between them they prove every
    # sequence 1..10,000 was consumed and terminal, in bounded state.
    folded_through = dict(state.compacted_through_by_binding)[BINDING]
    assert folded_through >= record_count - MAX_COMPACTION_TOMBSTONES
    assert len(state.compacted_commands) <= MAX_COMPACTION_TOMBSTONES
    assert all(tombstone.sequence > folded_through for tombstone in state.compacted_commands)
    assert all(item.sequence > dict(state.compacted_through_by_binding)[BINDING] for item in state.commands)
    encoded = LocalAgentBrokerStateJsonCodec().encode(state)
    assert len(encoded) <= 8 * 1024 * 1024
    assert len(state.commands) < MAX_BROKER_STATE_COLLECTION_ITEMS

    # The authority keeps working after compaction: a live record's #3118
    # exact retry is still idempotent, and the next mint continues the
    # watermark without reuse.
    retried = authority.enqueue_command(
        command_id="command.bulk.new",
        binding_ref=BINDING,
        run_id="run.bulk.new",
        tool_request_ref="tool-request.bulk.new",
        request_fingerprint=FINGERPRINT,
        now=now + timedelta(seconds=1),
    )
    assert retried == result
    follow_up = authority.enqueue_command(
        command_id="command.bulk.new2",
        binding_ref=BINDING,
        run_id="run.bulk.new2",
        tool_request_ref="tool-request.bulk.new2",
        request_fingerprint=FINGERPRINT,
        now=now + timedelta(seconds=2),
    )
    assert follow_up.sequence == result.sequence + 1


def test_pressure_that_retention_cannot_relieve_fails_closed(monkeypatch):
    monkeypatch.setattr(broker_module, "MAX_COMPACTION_TOMBSTONES", 0)
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    port = SerializedLocalAgentBrokerStatePort(backend=backend)
    record_count = MAX_BROKER_STATE_COLLECTION_ITEMS
    _persist_bulk_acked_state(port, backend, record_count)

    authority = _authority(port)
    with pytest.raises(ControlPlaneContractError) as refused:
        authority.enqueue_command(
            command_id="command.bulk.new",
            binding_ref=BINDING,
            run_id="run.bulk.new",
            tool_request_ref="tool-request.bulk.new",
            request_fingerprint=FINGERPRINT,
            now=BASE + timedelta(days=2),
        )
    # Pressure that retention cannot relieve fails closed with the wire code —
    # it does not corrupt state, drop records silently, or loop forever.
    assert refused.value.code == "local_agent_broker_state_wire_too_large"
    assert len(_live_state(port).commands) == record_count


def test_pressure_recovers_through_the_reactive_path_when_proactive_misses(monkeypatch):
    # The proactive trigger is a threshold on command count; a state can still
    # cross the wire bound without reaching it (byte-heavy records, a lowered
    # bound, a threshold tuned for a different shape). When that happens the
    # reactive escape - real wire failure, one real compaction, one retry - is
    # the only thing standing between the mutation and a permanent wedge.
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", MAX_BROKER_STATE_COLLECTION_ITEMS * 2)
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    port = SerializedLocalAgentBrokerStatePort(backend=backend)
    record_count = MAX_BROKER_STATE_COLLECTION_ITEMS
    _persist_bulk_acked_state(port, backend, record_count)

    authority = _authority(port)
    result = authority.enqueue_command(
        command_id="command.bulk.new",
        binding_ref=BINDING,
        run_id="run.bulk.new",
        tool_request_ref="tool-request.bulk.new",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(days=2),
    )
    assert result.sequence == record_count + 1
    state = _live_state(port)
    assert result.state is BrokerCommandState.QUEUED
    assert "command.bulk.new" in {item.command_id for item in state.commands}
    assert len(state.commands) < MAX_BROKER_STATE_COLLECTION_ITEMS
    assert len(LocalAgentBrokerStateJsonCodec().encode(state)) <= 8 * 1024 * 1024
