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
