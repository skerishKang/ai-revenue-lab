"""#3123 - bounded terminal history without losing sequence *or* identity.

Every test here drives the real state path: `StateBackedLocalAgentBrokerAuthority`
over the real serialized CAS port, so compaction, the sequence watermark and
the exact used-command-id ledger are exercised through the same encode -> CAS
-> decode round trip a durable object performs. The only patched values are
module-level trigger thresholds, so small-scale tests can reach the same code
paths the 10,000-record pressure test reaches at full scale.

The CENTRAL blocker on the first cut of this change was that folded/evicted
tombstones let a used command_id become fresh again. That cannot happen any
more: command-id identity lives in an exact, durable, append-only
used-command-id ledger in the same canonical broker storage, which is a
superset of every id the bounded snapshot has ever carried.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

from padiem_control_plane import local_agent_broker as broker_module
from padiem_control_plane import local_agent_broker_state as state_module
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    TERMINAL_RETENTION_SECONDS,
    BrokerCommandRecord,
    BrokerCommandState,
    InMemoryLocalAgentBrokerAuthority,
)
from padiem_control_plane.local_agent_broker_state import (
    LocalAgentBrokerStateSnapshot,
    StateBackedLocalAgentBrokerAuthority,
)
from padiem_control_plane.local_agent_broker_state_wire import (
    MAX_BROKER_STATE_COLLECTION_ITEMS,
    InMemorySerializedLocalAgentBrokerStateBackend,
    LocalAgentBrokerStateJsonCodec,
    SerializedLocalAgentBrokerStatePort,
)

# The durable-object serialized backend lives one level above the package
# because it is the Cloudflare-side wiring module; load it the same way the
# worker tests do.
_SQL_STATE_PATH = Path(__file__).parents[1] / "local_agent_broker_sql_state.py"
_sql_state_spec = importlib.util.spec_from_file_location(
    "padiem_local_agent_broker_sql_state_compaction_test", _SQL_STATE_PATH
)
assert _sql_state_spec is not None and _sql_state_spec.loader is not None
sql_state = importlib.util.module_from_spec(_sql_state_spec)
sys.modules[_sql_state_spec.name] = sql_state
_sql_state_spec.loader.exec_module(sql_state)


class _SqlCursor:
    def __init__(self, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self) -> list[dict]:
        return self._rows


class _Sql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def exec(self, query: str, *bindings):
        cursor = self.connection.execute(query, bindings)
        rows: list[dict] = []
        if cursor.description is not None:
            names = [item[0] for item in cursor.description]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        return _SqlCursor(rows, cursor.rowcount if cursor.rowcount >= 0 else 0)


class _Storage:
    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self.connection = connection or sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)

BASE = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
PEPPER = b"compaction-test-pepper-0123456789abcdef"
CREDENTIAL_1 = b"compaction-device-credential-1"
FINGERPRINT = "d" * 64
FINGERPRINT_2 = "e" * 64
AUTHORITY_REF = "control-plane.local-agent-broker.compaction-test.v1"
BINDING = "binding.compaction.1"
RETRY_HORIZON = timedelta(seconds=TERMINAL_RETENTION_SECONDS)


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


def _backend(port: SerializedLocalAgentBrokerStatePort) -> InMemorySerializedLocalAgentBrokerStateBackend:
    return port._backend  # the durable storage under test


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
# Retention: terminal records compact, live and unresolved records never do
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
    retained = _enqueue(
        authority,
        "command.c.keep",
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON - timedelta(seconds=1),
    )
    state = _live_state(port)
    assert state.commands[0].command_id == "command.c.1"
    assert state.commands[0].state is BrokerCommandState.ACKNOWLEDGED

    # Past the horizon, the next mutation compacts the terminal record.
    _enqueue(
        authority,
        "command.c.2",
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=1),
    )
    state = _live_state(port)
    assert [item.command_id for item in state.commands] == ["command.c.keep", "command.c.2"]
    # The id stays consumed in the exact ledger even though the record is gone.
    assert _backend(port).has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.c.1") is True
    # The watermark never moves down and no sequence is ever reused.
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
    # Active work survives days of pressure; only the terminal record goes.
    assert by_id["command.c.2"].state is BrokerCommandState.ADMITTED
    assert by_id["command.c.3"].state is BrokerCommandState.QUEUED
    assert by_id["command.c.4"].state is BrokerCommandState.QUEUED
    assert "command.c.1" not in by_id
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
    # stays ADMITTED - unresolved evidence - until the device reconciles it.
    far_future = BASE + timedelta(days=2)
    _enqueue(authority, "command.c.2", now=far_future)
    state = _live_state(port)
    assert state.commands[0].state is BrokerCommandState.ADMITTED

    # A restarted device reconciles on a fresh session; the removed expired
    # one is exactly the state the compaction is allowed to reclaim.
    fresh_session = _session(
        authority,
        session_id="session.compaction.2",
        now=far_future + timedelta(seconds=1),
    )
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

    _enqueue(
        authority,
        "command.c.3",
        now=far_future + timedelta(seconds=1) + RETRY_HORIZON + timedelta(seconds=1),
    )
    state = _live_state(port)
    # The reconciled EXPIRED record is terminal evidence whose retention
    # window has passed: removed from the snapshot, id still consumed.
    assert [item.command_id for item in state.commands] == ["command.c.2", "command.c.3"]
    assert _backend(port).has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.c.1") is True


# ---------------------------------------------------------------------------
# Duplicate rejection across compaction - exact, durable, not probabilistic
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
    _enqueue(
        authority,
        "command.c.trigger",
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=1),
    )
    assert "command.c.1" not in {item.command_id for item in _live_state(port).commands}

    # An exact retry of the compacted id cannot be served from the record
    # anymore, and it must not silently become a fresh command either.
    with pytest.raises(ControlPlaneContractError) as exact:
        _enqueue(
            authority,
            "command.c.1",
            now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=2),
        )
    assert exact.value.code == "broker_command_history_compacted"
    with pytest.raises(ControlPlaneContractError) as conflicting:
        _enqueue(
            authority,
            "command.c.1",
            now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=2),
            fingerprint=FINGERPRINT_2,
        )
    assert conflicting.value.code == "broker_command_history_compacted"

    # The live #3118 contract is untouched for records that still exist.
    live = _enqueue(
        authority,
        "command.c.trigger",
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=2),
    )
    assert live.state is BrokerCommandState.QUEUED
    fresh = _enqueue(
        authority,
        "command.c.9",
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=3),
    )
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
    _enqueue(
        authority,
        "command.c.trigger",
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=1),
    )
    late_session = _session(
        authority,
        session_id="session.compaction.2",
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=1),
    )
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
            now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=2),
        )
    assert retry.value.code == "broker_command_history_compacted"


# ---------------------------------------------------------------------------
# Restart recovery: the ledger and the watermark are durable
# ---------------------------------------------------------------------------


def test_ledger_and_watermark_survive_restart_and_keep_rejecting(monkeypatch):
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    port = _port()
    first = _authority(port)
    _register(first)
    session = _session(first)
    command = _enqueue(first, "command.c.1", now=BASE + timedelta(seconds=2))
    _admit(first, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=5))
    _ack(first, command, index="c.1", session_id=session.session_id, now=BASE + timedelta(seconds=10))
    _enqueue(
        first,
        "command.c.trigger",
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=1),
    )
    before = _live_state(port)

    # A fresh process over the same durable storage: identity and watermark
    # survive the restart, because they live in the same durable storage.
    restarted = _authority(port)
    assert _backend(port).has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.c.1") is True
    fresh = restarted.enqueue_command(
        command_id="command.c.9",
        binding_ref=BINDING,
        run_id="run.command.c.9",
        tool_request_ref="tool-request.command.c.9",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=2),
    )
    assert fresh.sequence == dict(before.last_sequence_by_binding)[BINDING] + 1
    assert dict(_live_state(port).last_sequence_by_binding)[BINDING] == fresh.sequence
    with pytest.raises(ControlPlaneContractError) as rejected:
        _enqueue(restarted, "command.c.1", now=BASE + timedelta(seconds=10) + RETRY_HORIZON + timedelta(seconds=3))
    assert rejected.value.code == "broker_command_history_compacted"


def test_refused_cas_records_no_ledger_id():
    # A stale CAS must not mark the attempted id as used: the caller's
    # legitimate retry against the winning state must still be able to mint.
    port = _port()
    authority = _authority(port)
    _register(authority)
    _session(authority)
    other = _enqueue(authority, "command.c.other", now=BASE + timedelta(seconds=2))

    backend = _backend(port)
    seed = InMemoryLocalAgentBrokerAuthority(pepper=PEPPER, authority_ref=AUTHORITY_REF)
    seed.register_binding(
        binding_ref=BINDING,
        device_id="device.compaction.1",
        account_ref="account.compaction.1",
        workspace_ref="workspace.compaction.1",
        credential=CREDENTIAL_1,
        now=BASE,
    )
    stale_snapshot = LocalAgentBrokerStateSnapshot.capture(seed)
    with pytest.raises(ControlPlaneContractError):
        port.compare_and_swap(
            authority_ref=AUTHORITY_REF,
            expected_version=0,
            snapshot=stale_snapshot,
            new_command_ids=("command.c.stale",),
        )
    assert backend.has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.c.stale") is False
    assert other.sequence == 1


# ---------------------------------------------------------------------------
# The real 10,000-record pressure path - and CENTRAL's required regression:
# after far more compaction pressure than any forgetting budget had, the
# OLDEST used command_id must still be rejected, with no second mint.
# ---------------------------------------------------------------------------


def _persist_bulk_acked_state(
    port: SerializedLocalAgentBrokerStatePort,
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
    port.compare_and_swap(
        authority_ref=AUTHORITY_REF,
        expected_version=0,
        snapshot=LocalAgentBrokerStateSnapshot.capture(seed),
    )


def test_pressure_over_the_real_wire_bound_compacts_and_keeps_authority():
    port = SerializedLocalAgentBrokerStatePort(backend=InMemorySerializedLocalAgentBrokerStateBackend())
    record_count = MAX_BROKER_STATE_COLLECTION_ITEMS
    _persist_bulk_acked_state(port, record_count)
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
    assert result.state is BrokerCommandState.QUEUED
    assert "command.bulk.new" in {item.command_id for item in state.commands}
    assert len(state.commands) < MAX_BROKER_STATE_COLLECTION_ITEMS

    # CENTRAL's required regression, at the largest pressure the bound allows:
    # every one of the 10,000 compacted ids - including the oldest, which the
    # first cut's forgetting budgets would have dropped - stays exactly
    # rejected, and the refusals mint nothing at all.
    oldest = "command.bulk.1"
    assert _backend(port).has_used_command_id(authority_ref=AUTHORITY_REF, command_id=oldest) is True
    with pytest.raises(ControlPlaneContractError) as reused:
        authority.enqueue_command(
            command_id=oldest,
            binding_ref=BINDING,
            run_id=f"run.{oldest}",
            tool_request_ref=f"tool-request.{oldest}",
            request_fingerprint=FINGERPRINT,
            now=now + timedelta(seconds=1),
        )
    assert reused.value.code == "broker_command_history_compacted"
    with pytest.raises(ControlPlaneContractError) as reused_conflict:
        authority.enqueue_command(
            command_id=oldest,
            binding_ref=BINDING,
            run_id="run.conflict",
            tool_request_ref="tool-request.conflict",
            request_fingerprint=FINGERPRINT_2,
            now=now + timedelta(seconds=1),
        )
    assert reused_conflict.value.code == "broker_command_history_compacted"
    # The refusals minted nothing: the watermark is untouched by them.
    assert dict(_live_state(port).last_sequence_by_binding)[BINDING] == record_count + 1

    # A live record's #3118 exact retry is still idempotent, and the next mint
    # continues the watermark without reuse.
    retried = authority.enqueue_command(
        command_id="command.bulk.new",
        binding_ref=BINDING,
        run_id="run.bulk.new",
        tool_request_ref="tool-request.bulk.new",
        request_fingerprint=FINGERPRINT,
        now=now + timedelta(seconds=2),
    )
    assert retried == result
    follow_up = authority.enqueue_command(
        command_id="command.bulk.new2",
        binding_ref=BINDING,
        run_id="run.bulk.new2",
        tool_request_ref="tool-request.bulk.new2",
        request_fingerprint=FINGERPRINT,
        now=now + timedelta(seconds=3),
    )
    assert follow_up.sequence == result.sequence + 1


def test_pressure_recovers_through_the_reactive_path_when_proactive_misses(monkeypatch):
    # The proactive trigger is a threshold on command count; a state can still
    # cross the wire bound without reaching it (byte-heavy records, a lowered
    # bound, a threshold tuned for a different shape). When that happens the
    # reactive escape - real wire failure, one real compaction, one retry - is
    # the only thing standing between the mutation and a permanent wedge.
    monkeypatch.setattr(
        state_module,
        "COMPACTION_PROACTIVE_TRIGGER_COMMANDS",
        MAX_BROKER_STATE_COLLECTION_ITEMS * 2,
    )
    port = SerializedLocalAgentBrokerStatePort(backend=InMemorySerializedLocalAgentBrokerStateBackend())
    record_count = MAX_BROKER_STATE_COLLECTION_ITEMS
    _persist_bulk_acked_state(port, record_count)

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
    # The reactive path records the compaction-removed ids in the ledger too.
    assert _backend(port).has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.bulk.1") is True


def test_pressure_that_retention_cannot_relieve_fails_closed(monkeypatch):
    # Freshly acknowledged records are inside their retention window: with no
    # eligible record, pressure that retention cannot relieve fails closed
    # with the wire code - it does not corrupt state, drop records silently,
    # or loop forever.
    port = SerializedLocalAgentBrokerStatePort(backend=InMemorySerializedLocalAgentBrokerStateBackend())
    record_count = MAX_BROKER_STATE_COLLECTION_ITEMS
    _persist_bulk_acked_state(port, record_count)

    authority = _authority(port)
    with pytest.raises(ControlPlaneContractError) as refused:
        authority.enqueue_command(
            command_id="command.bulk.new",
            binding_ref=BINDING,
            run_id="run.bulk.new",
            tool_request_ref="tool-request.bulk.new",
            request_fingerprint=FINGERPRINT,
            now=BASE + timedelta(seconds=20),
        )
    # The bulk records are acknowledged 10 seconds in: retention cannot touch
    # them yet, so the wire bound failure must surface explicitly.
    assert refused.value.code == "local_agent_broker_state_wire_too_large"
    assert len(_live_state(port).commands) == record_count


def test_durable_object_ledger_records_mints_and_rolls_back_refused_cas():
    # The exact used-command-id ledger is implemented in the real durable
    # backend over the same attached SQLite storage as the state blob. A
    # committed CAS must record its minted ids; a refused CAS must record
    # nothing, or the caller's legitimate retry would be refused afterwards.
    storage = _Storage()
    backend = sql_state.CloudflareDurableObjectSerializedStateBackend(storage)
    codec = LocalAgentBrokerStateJsonCodec()
    payload = codec.encode(LocalAgentBrokerStateSnapshot.empty(authority_ref=AUTHORITY_REF))

    backend.compare_and_swap(
        authority_ref=AUTHORITY_REF, expected_version=0, payload=payload
    )
    backend.compare_and_swap(
        authority_ref=AUTHORITY_REF,
        expected_version=1,
        payload=payload,
        new_command_ids=("command.do.1", "command.do.2"),
    )
    assert backend.has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.do.1") is True
    assert backend.has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.do.2") is True

    with pytest.raises(ControlPlaneContractError):
        backend.compare_and_swap(
            authority_ref=AUTHORITY_REF,
            expected_version=99,
            payload=payload,
            new_command_ids=("command.do.stale",),
        )
    assert backend.has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.do.stale") is False

    # And a committed id keeps surviving a backend re-open (restart).
    reopened = sql_state.CloudflareDurableObjectSerializedStateBackend(_Storage(storage.connection))
    assert reopened.has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.do.1") is True
