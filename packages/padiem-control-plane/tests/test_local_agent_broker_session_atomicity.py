"""Issue #3129 — POST /session persists broker session CAS + HTTP session row
atomically (both-or-neither).

Every scenario drives the REAL device HTTP service composition:

* `LocalAgentBrokerDeviceHttpService.handle(envelope)` — the production entry;
* the real `StateBackedLocalAgentBindingAuthenticator` credential check;
* the real `LocalAgentBrokerHttpHandler` with the #3129 transaction port;
* the real `SerializedLocalAgentBrokerStatePort` over the real
  `CloudflareDurableObjectSerializedStateBackend` (canonical broker CAS);
* the real `CloudflareDurableObjectHttpSessionState` (HTTP session rows);
* the real `LocalAgentBrokerRpcFacade`.

The only substituted component is the Durable Object storage: a faithful
sqlite3-backed fake with DO semantics (statements outside `transactionSync`
commit immediately; `transactionSync` runs BEGIN/COMMIT/ROLLBACK) that can
inject a crash between the two writes and a crash after the last write but
before the transaction returns. No write is stubbed away — the crash is
injected at the storage seam exactly where a DO crash would land.
"""

from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane import local_agent_broker_state as state_module
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import SerializedLocalAgentBrokerStatePort
from local_agent_broker_device_http import LocalAgentBrokerDeviceHttpService
from local_agent_broker_sql_state import (
    CloudflareDurableObjectHttpSessionState,
    CloudflareDurableObjectSerializedStateBackend,
)

BASE = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
PEPPER = b"session-atomicity-test-pepper-value"
CREDENTIAL = b"session-atomicity-test-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.session-atomicity.v1"


class _Cursor:
    def __init__(self, cur: sqlite3.Cursor) -> None:
        self._cur = cur
        self.rowsWritten = cur.rowcount if isinstance(cur.rowcount, int) and cur.rowcount >= 0 else 0

    def toArray(self) -> list[dict]:
        names = [d[0] for d in self._cur.description or []]
        return [dict(zip(names, row)) for row in self._cur.fetchall()]


class _Sql:
    def __init__(self, storage: "TransactionCapableStorage") -> None:
        self._storage = storage

    def exec(self, statement: str, *params):
        key = " ".join(statement.strip().split()).lower()
        record = (self._storage.in_transaction, key.split("(")[0][:48])
        self._storage.executed_statements.append(record)
        # Crash (a): the Durable Object dies right after the broker CAS write
        # committed inside the transaction, before the HTTP session row.
        if self._storage.crash_before_http_insert and key.startswith(
            "insert or ignore into local_agent_http_session"
        ):
            raise RuntimeError("SIMULATED_CRASH_BETWEEN_SESSION_WRITES")
        if self._storage.interfere_with_broker_cas and key.startswith("update local_agent_broker_state"):
            self._storage.conn.execute(
                "UPDATE local_agent_broker_state SET version = version + 1 WHERE singleton = 1"
            )
        cur = self._storage.conn.execute(statement, params)
        return _Cursor(cur)


class TransactionCapableStorage:
    """Durable-Object-shaped storage: per-statement autocommit plus a real
    BEGIN/COMMIT/ROLLBACK transactionSync with crash injection at the seam."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.in_transaction = False
        self.crash_before_http_insert = False
        self.crash_before_commit = False
        self.interfere_with_broker_cas = False
        self.executed_statements: list[tuple[bool, str]] = []
        self.sql = _Sql(self)

    def transactionSync(self, operation):
        if self.in_transaction:
            raise RuntimeError("nested transactionSync is not supported")
        self.in_transaction = True
        try:
            self.conn.execute("BEGIN")
            result = operation()
            # Crash (b): the isolate dies after the last statement executed
            # but before the transaction returns/commits — DO rolls back.
            if self.crash_before_commit:
                raise RuntimeError("SIMULATED_CRASH_BEFORE_TRANSACTION_RETURN")
            self.conn.execute("COMMIT")
            return result
        except BaseException:
            try:
                self.conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            self.in_transaction = False


class _UnusedMaterialResolver:
    def resolve(self, request):
        del request
        raise RuntimeError("material resolver is not used by this test")


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _build(storage: TransactionCapableStorage, *, now: datetime = BASE):
    backend = CloudflareDurableObjectSerializedStateBackend(storage)
    state_port = SerializedLocalAgentBrokerStatePort(backend=backend)
    bootstrap_authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state_port,
    )
    try:
        bootstrap_authority.register_binding(
            binding_ref="binding.atomic.1",
            device_id="device.atomic.1",
            account_ref="account.1",
            workspace_ref="workspace.1",
            credential=CREDENTIAL,
            now=now,
            credential_ttl_seconds=3600,
        )
    except ControlPlaneContractError as exc:
        # Rebuilding over the same durable storage (restart scenarios) finds
        # the binding already durable — persistence working, not a failure.
        if exc.code != "duplicate_device_binding":
            raise
    http_state = CloudflareDurableObjectHttpSessionState(storage)
    service = LocalAgentBrokerDeviceHttpService(
        state_port=state_port,
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        rpc_factory=lambda: LocalAgentBrokerRpcFacade(
            authority=StateBackedLocalAgentBrokerAuthority(
                pepper=PEPPER,
                authority_ref=AUTHORITY_REF,
                state_port=state_port,
            )
        ),
        http_state=http_state,
        material_resolver=_UnusedMaterialResolver(),
        session_open_transaction=storage.transactionSync,
        clock=lambda: now,
    )
    return state_port, http_state, service


def _session_envelope(session_id: str) -> dict:
    body = (
        '{"session_id":"%s","binding_ref":"binding.atomic.1","credential_b64":"%s",'
        '"account_ref":"account.1","workspace_ref":"workspace.1","now":"%s","ttl_seconds":900}'
        % (session_id, _encoded(CREDENTIAL), BASE.isoformat())
    ).encode("utf-8")
    return {
        "method": "POST",
        "route": "/session",
        "content_type": "application/json",
        "body_b64": _encoded(body),
        "tls_verified": True,
    }


def _heartbeat_envelope(session_id: str, now: datetime) -> dict:
    body = (
        '{"session_id":"%s","binding_ref":"binding.atomic.1","credential_b64":"%s","now":"%s"}'
        % (session_id, _encoded(CREDENTIAL), now.isoformat())
    ).encode("utf-8")
    return {
        "method": "POST",
        "route": "/heartbeat",
        "content_type": "application/json",
        "body_b64": _encoded(body),
        "tls_verified": True,
    }


def _poll_envelope(session_id: str, now: datetime) -> dict:
    body = (
        '{"session_id":"%s","binding_ref":"binding.atomic.1","credential_b64":"%s",'
        '"after_sequence":0,"now":"%s","limit":32}'
        % (session_id, _encoded(CREDENTIAL), now.isoformat())
    ).encode("utf-8")
    return {
        "method": "POST",
        "route": "/poll",
        "content_type": "application/json",
        "body_b64": _encoded(body),
        "tls_verified": True,
    }


def _broker_sessions(storage: TransactionCapableStorage) -> list[str]:
    payload = storage.conn.execute(
        "SELECT payload_text FROM local_agent_broker_state WHERE singleton = 1"
    ).fetchone()
    if payload is None:
        return []
    # Sessions live inside the serialized canonical snapshot; decode via the
    # real codec surface by reusing the wire module is overkill here — the
    # session_id string is bounded safe text and appears verbatim.
    import json

    return [item["session_id"] for item in json.loads(payload[0])["sessions"]]


def _http_rows(storage: TransactionCapableStorage) -> list[str]:
    return [row[0] for row in storage.conn.execute("SELECT session_id FROM local_agent_http_session").fetchall()]


def _canonical_payload(storage: TransactionCapableStorage) -> str | None:
    row = storage.conn.execute(
        "SELECT payload_text FROM local_agent_broker_state WHERE singleton = 1"
    ).fetchone()
    return None if row is None else row[0]


def test_session_open_persists_both_sides_in_one_transaction_and_survives_restart():
    storage = TransactionCapableStorage()
    state_port, _, service = _build(storage)
    response = service.handle(_session_envelope("sess.ok"))
    assert response["status"] == 200 and response["body"]["ok"] is True

    # Both-or-neither by construction: the canonical CAS and the HTTP row were
    # written inside the SAME transactionSync, and exactly one of each ran.
    broker_cas_in_tx = any(
        in_tx and key.startswith("update local_agent_broker_state") for in_tx, key in storage.executed_statements
    )
    http_insert_in_tx = any(
        in_tx and key.startswith("insert or ignore into local_agent_http_session")
        for in_tx, key in storage.executed_statements
    )
    assert broker_cas_in_tx and http_insert_in_tx
    assert _broker_sessions(storage) == ["sess.ok"]
    assert _http_rows(storage) == ["sess.ok"]

    # Success + restart: fresh composition over the same durable storage.
    state_port2, _, service2 = _build(storage, now=BASE + timedelta(seconds=120))
    assert _broker_sessions(storage) == ["sess.ok"]
    assert _http_rows(storage) == ["sess.ok"]
    poll = service2.handle(_poll_envelope("sess.ok", BASE + timedelta(seconds=130)))
    assert poll["status"] == 200 and poll["body"]["ok"] is True
    assert poll["body"]["commands"] == []
    del state_port, state_port2


def test_crash_between_broker_write_and_http_write_leaves_neither():
    storage = TransactionCapableStorage()
    _, _, service = _build(storage)
    storage.crash_before_http_insert = True
    response = service.handle(_session_envelope("sess.torn"))
    storage.crash_before_http_insert = False

    # The transaction rolled back before the handler mapped the failure to a
    # dependency-unavailable response: the client sees 503, the durable state
    # saw both-or-neither.
    assert response["status"] == 503
    assert response["body"]["error"]["code"] == "local_agent_http_dependency_unavailable"
    assert _broker_sessions(storage) == []
    assert _http_rows(storage) == []
    assert _canonical_payload(storage) is None or "sess.torn" not in _canonical_payload(storage)


def test_crash_after_http_insert_before_transaction_return_leaves_neither():
    storage = TransactionCapableStorage()
    _, _, service = _build(storage)
    storage.crash_before_commit = True
    response = service.handle(_session_envelope("sess.torn2"))
    storage.crash_before_commit = False

    # The row executed inside the transaction, but the transaction never
    # returned, so the storage seam rolled the whole pair back.
    assert response["status"] == 503
    assert response["body"]["error"]["code"] == "local_agent_http_dependency_unavailable"
    assert _broker_sessions(storage) == []
    assert _http_rows(storage) == []


def test_stale_cas_writes_no_http_row_and_leaves_canonical_payload_unchanged():
    storage = TransactionCapableStorage()
    _, _, service = _build(storage)
    # Seed one durable session so the canonical payload exists and is non-empty.
    first = service.handle(_session_envelope("sess.first"))
    assert first["status"] == 200 and first["body"]["ok"] is True
    payload_before = _canonical_payload(storage)

    storage.interfere_with_broker_cas = True
    second = service.handle(_session_envelope("sess.second"))
    storage.interfere_with_broker_cas = False

    assert second["status"] == 200
    assert second["body"]["ok"] is False
    assert second["body"]["error"]["code"] == "stale_local_agent_broker_state"
    assert "sess.second" not in _http_rows(storage)
    assert _canonical_payload(storage) == payload_before


def test_device_http_is_unusable_for_a_session_that_never_fully_opened():
    storage = TransactionCapableStorage()
    _, _, service = _build(storage)
    storage.crash_before_http_insert = True
    torn = service.handle(_session_envelope("sess.torn"))
    storage.crash_before_http_insert = False
    assert torn["status"] == 503

    # No partial session exists, so there is nothing usable and nothing stale:
    # a fresh open of a new session id works and the torn one leaves no row.
    recovered = service.handle(_session_envelope("sess.next"))
    assert recovered["status"] == 200 and recovered["body"]["ok"] is True
    assert sorted(_broker_sessions(storage)) == ["sess.next"]
    assert _http_rows(storage) == ["sess.next"]


def test_heartbeat_behavior_is_unchanged_by_the_session_open_transaction():
    storage = TransactionCapableStorage()
    _, _, service = _build(storage)
    opened = service.handle(_session_envelope("sess.hb"))
    assert opened["status"] == 200 and opened["body"]["ok"] is True
    statements_before = len(storage.executed_statements)

    # The injected server clock is the only time authority for last-seen; the
    # envelope's client `now` stays request evidence, exactly as before.
    heartbeat = service.handle(_heartbeat_envelope("sess.hb", BASE))
    assert heartbeat["status"] == 200 and heartbeat["body"]["ok"] is True
    heartbeat_body = heartbeat["body"]["heartbeat"]
    assert heartbeat_body["session_id"] == "sess.hb"
    assert heartbeat_body["last_seen_at"] == BASE.isoformat().replace("+00:00", "Z")
    assert heartbeat_body["session_expires_at"].endswith("Z")
    assert heartbeat_body["raw_device_credential"] is False

    # The heartbeat still persists last-seen through its own record_last_seen
    # transaction, outside the session-open write pair.
    heartbeat_update_in_own_tx = any(
        in_tx and key.startswith("update local_agent_http_session")
        for in_tx, key in storage.executed_statements[statements_before:]
    )
    assert heartbeat_update_in_own_tx
    last_seen = storage.conn.execute(
        "SELECT last_seen_at FROM local_agent_http_session WHERE session_id = 'sess.hb'"
    ).fetchone()[0]
    assert last_seen == BASE.isoformat().replace("+00:00", "Z")


def _acknowledge_envelope(session_id: str, command: dict) -> dict:
    body = (
        '{"session_id":"%s","binding_ref":"binding.atomic.1","credential_b64":"%s",'
        '"command_id":"%s","admission_ref":"%s","evidence_ref":"%s","revision_ref":"%s",'
        '"termination":"exited","request_id":"%s","exit_code":0,"now":"%s"}'
        % (
            session_id,
            _encoded(CREDENTIAL),
            command["command_id"],
            command["admission_ref"],
            command["evidence_ref"],
            command["revision_ref"],
            command["request_id"],
            (BASE + timedelta(seconds=30)).isoformat(),
        )
    ).encode("utf-8")
    return {
        "method": "POST",
        "route": "/acknowledge",
        "content_type": "application/json",
        "body_b64": _encoded(body),
        "tls_verified": True,
    }


def test_acknowledge_runs_inside_the_session_open_transaction():
    # #3123: the acknowledge state mutation - including any terminal-history
    # compaction it triggers, which moves used-command-id ledger rows - must
    # be crash-atomic with its ledger writes, so it runs inside the same
    # deployable mutation transaction the #3129 session-open double write
    # uses.
    storage = TransactionCapableStorage()
    entered = []
    real = storage.transactionSync

    def recording(callback):
        entered.append(True)
        return real(callback)

    state_port, _, service = _build(storage)

    # Open the HTTP session first: the canonical admit below correlates with it.
    opened = service.handle(_session_envelope("sess.ack"))
    assert opened["status"] == 200 and opened["body"]["ok"] is True

    # Drive a command to ADMITTED through the canonical authority, then
    # acknowledge it through the device HTTP surface.
    bootstrap = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state_port,
    )
    command = bootstrap.enqueue_command(
        command_id="command.atomic.ack",
        binding_ref="binding.atomic.1",
        run_id="run.atomic.ack",
        tool_request_ref="tool-request.atomic.ack",
        request_fingerprint="a" * 64,
        now=BASE + timedelta(seconds=2),
    )
    bootstrap.admit_command(
        admission_ref="admission.atomic.ack",
        evidence_ref="evidence.atomic.ack",
        session_id="sess.ack",
        binding_ref="binding.atomic.1",
        credential=CREDENTIAL,
        command_id=command.command_id,
        request_fingerprint=command.request_fingerprint,
        request_id="request.atomic.ack",
        now=BASE + timedelta(seconds=6),
    )

    service._session_open_transaction = recording
    acknowledged = service.handle(
        _acknowledge_envelope(
            "sess.ack",
            {
                "command_id": command.command_id,
                "admission_ref": "admission.atomic.ack",
                "evidence_ref": "evidence.atomic.ack",
                "revision_ref": command.revision_ref,
                "request_id": "request.atomic.ack",
            },
        )
    )
    assert acknowledged["status"] == 200 and acknowledged["body"]["ok"] is True
    assert entered, "acknowledge must execute inside the mutation transaction"
    assert acknowledged["body"]["command"]["state"] == "acknowledged"


def test_reconcile_runs_inside_the_mutation_transaction_and_compacts_atomically(monkeypatch):
    # #3123 fourth review: /reconcile is a direct-facade broker mutation that
    # can also trigger terminal-history compaction (which moves
    # used-command-id ledger rows), so it must run inside the same deployable
    # storage transaction as session-open and acknowledge. Proven three ways:
    # the reconcile enters the deployable seam exactly once and never nests,
    # its blob CAS and compaction ledger backfill execute with the storage
    # transaction open, and the #3128 expired outcome stays terminal.
    monkeypatch.setattr(state_module, "COMPACTION_PROACTIVE_TRIGGER_COMMANDS", 1)
    storage = TransactionCapableStorage()
    backend = CloudflareDurableObjectSerializedStateBackend(storage)
    state_port = SerializedLocalAgentBrokerStatePort(backend=backend)
    NOW = BASE + timedelta(days=2)
    binding_issued = NOW - timedelta(seconds=80_000)

    bootstrap = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER, authority_ref=AUTHORITY_REF, state_port=state_port,
    )
    bootstrap.register_binding(
        binding_ref="binding.recon.1",
        device_id="device.recon.1",
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential=CREDENTIAL,
        now=binding_issued,
        credential_ttl_seconds=2_592_000,
    )
    # A terminal command old enough to be compaction-eligible at NOW: its
    # ledger row was recorded at mint, so the compaction backfill inside the
    # reconcile transaction is an INSERT OR IGNORE that must still run in the
    # transaction.
    old_command = bootstrap.enqueue_command(
        command_id="command.recon.old",
        binding_ref="binding.recon.1",
        run_id="run.recon.old",
        tool_request_ref="tool-request.recon.old",
        request_fingerprint="a" * 64,
        now=NOW - timedelta(seconds=4_310),
        ttl_seconds=300,
    )
    bootstrap.open_session(
        session_id="sess.recon.old",
        binding_ref="binding.recon.1",
        credential=CREDENTIAL,
        account_ref="account.1",
        workspace_ref="workspace.1",
        now=NOW - timedelta(seconds=4_305),
    )
    bootstrap.admit_command(
        admission_ref="admission.recon.old",
        evidence_ref="evidence.recon.old",
        session_id="sess.recon.old",
        binding_ref="binding.recon.1",
        credential=CREDENTIAL,
        command_id=old_command.command_id,
        request_fingerprint=old_command.request_fingerprint,
        request_id="request.recon.old",
        now=NOW - timedelta(seconds=4_302),
    )
    bootstrap.acknowledge(
        session_id="sess.recon.old",
        binding_ref="binding.recon.1",
        credential=CREDENTIAL,
        command_id=old_command.command_id,
        admission_ref="admission.recon.old",
        evidence_ref="evidence.recon.old",
        revision_ref=old_command.revision_ref,
        termination="exited",
        request_id="request.recon.old",
        exit_code=0,
        now=NOW - timedelta(seconds=4_015),
    )

    # The reconcile target: ADMITTED with its hard deadline in the past.
    target = bootstrap.enqueue_command(
        command_id="command.recon.target",
        binding_ref="binding.recon.1",
        run_id="run.recon.target",
        tool_request_ref="tool-request.recon.target",
        request_fingerprint="a" * 64,
        now=NOW - timedelta(seconds=800),
        ttl_seconds=60,
    )

    clock = {"now": NOW}
    seam = {"entries": 0, "depth": 0, "max_depth": 0}

    def recording_mutation_transaction(callback):
        seam["entries"] += 1
        seam["depth"] += 1
        seam["max_depth"] = max(seam["max_depth"], seam["depth"])
        try:
            return storage.transactionSync(callback)
        finally:
            seam["depth"] -= 1

    service = LocalAgentBrokerDeviceHttpService(
        state_port=state_port,
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        rpc_factory=lambda: LocalAgentBrokerRpcFacade(
            authority=StateBackedLocalAgentBrokerAuthority(
                pepper=PEPPER,
                authority_ref=AUTHORITY_REF,
                state_port=state_port,
            )
        ),
        http_state=CloudflareDurableObjectHttpSessionState(storage),
        material_resolver=_UnusedMaterialResolver(),
        session_open_transaction=recording_mutation_transaction,
        clock=lambda: clock["now"],
    )

    def reconcile_envelope():
        body = (
            '{"session_id":"sess.recon","binding_ref":"binding.recon.1","credential_b64":"%s",'
            '"command_id":"%s","admission_ref":"admission.recon.target","evidence_ref":"evidence.recon.target",'
            '"revision_ref":"%s","request_id":"request.recon.target","request_fingerprint":"%s",'
            '"termination":null,"exit_code":null,"now":"%s"}'
            % (
                _encoded(CREDENTIAL),
                target.command_id,
                target.revision_ref,
                "a" * 64,
                clock["now"].isoformat(),
            )
        ).encode("utf-8")
        return {
            "method": "POST",
            "route": "/reconcile",
            "content_type": "application/json",
            "body_b64": _encoded(body),
            "tls_verified": True,
        }

    # The device HTTP session must exist for the reconcile's session scoping.
    session_body = (
        '{"session_id":"sess.recon","binding_ref":"binding.recon.1","credential_b64":"%s",'
        '"account_ref":"account.1","workspace_ref":"workspace.1","now":"%s","ttl_seconds":900}'
        % (_encoded(CREDENTIAL), clock["now"].isoformat())
    ).encode("utf-8")
    clock["now"] = NOW - timedelta(seconds=800)
    opened = service.handle({
        "method": "POST",
        "route": "/session",
        "content_type": "application/json",
        "body_b64": _encoded(session_body),
        "tls_verified": True,
    })
    assert opened["status"] == 200 and opened["body"]["ok"] is True, opened["body"]
    bootstrap.admit_command(
        admission_ref="admission.recon.target",
        evidence_ref="evidence.recon.target",
        session_id="sess.recon",
        binding_ref="binding.recon.1",
        credential=CREDENTIAL,
        command_id=target.command_id,
        request_fingerprint=target.request_fingerprint,
        request_id="request.recon.target",
        now=NOW - timedelta(seconds=795),
    )

    seam_entries_before = seam["entries"]
    statements_before = len(storage.executed_statements)
    clock["now"] = NOW
    reconciled = service.handle(reconcile_envelope())
    assert reconciled["status"] == 200 and reconciled["body"]["ok"] is True, reconciled["body"]

    # RECONCILE_MUTATION_INSIDE_TRANSACTION: the handler entered the deployable
    # seam exactly once for this request and never nested.
    assert seam["entries"] - seam_entries_before == 1
    assert seam["max_depth"] == 1

    window = storage.executed_statements[statements_before:]
    # The reconcile's broker-state CAS ran with the storage transaction open.
    broker_updates = [flag for flag, head in window if head.startswith("update local_agent_broker_state")]
    assert broker_updates and all(broker_updates)
    # The compaction this reconcile triggered moved the old terminal record and
    # its used-command-id backfill ran inside the same open transaction.
    ledger_writes = [
        flag for flag, head in window
        if head.startswith("insert or ignore into local_agent_broker_used_co")
    ]
    assert ledger_writes and all(ledger_writes)
    assert storage.in_transaction is False, "the mutation transaction must commit"

    # LEDGER_AND_BLOB_ATOMIC: the compaction removed the old terminal record
    # and its used-command-id row is durable - identity outlives the record.
    state = state_port.load(authority_ref=AUTHORITY_REF).snapshot
    assert "command.recon.old" not in {item.command_id for item in state.commands}
    assert backend.has_used_command_id(authority_ref=AUTHORITY_REF, command_id="command.recon.old") is True

    # #3128_RECONCILIATION_RESULT_PRESERVED: the EXPIRED outcome fabricates no
    # execution fact and keeps every correlation verbatim.
    reconciled_command = reconciled["body"]["command"]
    assert reconciled_command["state"] == "expired"
    assert reconciled_command["acknowledged_at"] is None
    assert reconciled_command["termination"] is None
    assert reconciled_command["exit_code"] is None
    assert reconciled_command["revision_ref"] == target.revision_ref
    assert reconciled_command["admission_ref"] == "admission.recon.target"
    assert reconciled_command["request_id"] == "request.recon.target"

    # TERMINAL_REPLAY = 0: a second reconciliation is refused and mints nothing.
    watermark = dict(state.last_sequence_by_binding)["binding.recon.1"]
    replay = service.handle(reconcile_envelope())
    assert replay["status"] == 200 and replay["body"]["ok"] is False
    assert replay["body"]["error"]["code"] == "broker_command_not_reconcilable"
    state_after = state_port.load(authority_ref=AUTHORITY_REF).snapshot
    assert dict(state_after.last_sequence_by_binding)["binding.recon.1"] == watermark
