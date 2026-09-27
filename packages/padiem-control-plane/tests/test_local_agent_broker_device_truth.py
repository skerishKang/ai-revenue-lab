"""#3094 — the canonical broker's narrow device_truth projection.

Unit coverage for the read-only ``device_truth`` runtime method added to the
durable Local Agent broker authority: owner scoping, the bounded
never-online fact vocabulary, secret-free envelope, and read-only behaviour.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sqlite3
import sys
import types

import pytest

from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord


class _FakeResponse:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env


_workers = types.ModuleType("workers")
_workers.Response = _FakeResponse
_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
_workers.DurableObject = _FakeDurableObject
sys.modules.setdefault("workers", _workers)

_WORKER_PATH = Path(__file__).parents[1] / "local_agent_broker_worker.py"
_WORKER_SPEC = importlib.util.spec_from_file_location("padiem_local_agent_broker_device_truth_test", _WORKER_PATH)
assert _WORKER_SPEC is not None and _WORKER_SPEC.loader is not None
worker = importlib.util.module_from_spec(_WORKER_SPEC)
sys.modules[_WORKER_SPEC.name] = worker
_WORKER_SPEC.loader.exec_module(worker)


BASE = datetime(2026, 9, 4, 2, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.device-truth-test.v1"
PEPPER = "cloudflare-do-device-truth-test-pepper"
CREDENTIAL = b"cloudflare-do-device-truth-credential"
ACCOUNT_REF = "acct.device-truth.1"
OTHER_ACCOUNT_REF = "acct.device-truth.other"
WORKSPACE_REF = "ws.device-truth.1"
SESSION_ID = "sess.device-truth.1"
BINDING_REF = "bind.device-truth.1"
DEVICE_ID = "device.truth.1"


class _Cursor:
    def __init__(self, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self):
        return list(self._rows)

    def one(self):
        if len(self._rows) != 1:
            raise RuntimeError("expected exactly one row")
        return self._rows[0]


class _Sql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def exec(self, query: str, *bindings):
        cursor = self.connection.execute(query, bindings)
        rows: list[dict] = []
        if cursor.description is not None:
            names = [item[0] for item in cursor.description]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return _Cursor(rows, rows_written)


class _Storage:
    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self.connection = connection or sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)

    def transactionSync(self, callback):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
            self.connection.execute("COMMIT")
            return value
        except Exception:
            self.connection.execute("ROLLBACK")
            raise


class _Context:
    def __init__(self, storage: _Storage) -> None:
        self.storage = storage


class _Env:
    def __init__(self) -> None:
        self.LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        self.LOCAL_AGENT_BROKER_PEPPER = PEPPER


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _register_payload(*, account_ref: str = ACCOUNT_REF) -> dict:
    return {
        "binding_ref": BINDING_REF,
        "device_id": DEVICE_ID,
        "account_ref": account_ref,
        "workspace_ref": WORKSPACE_REF,
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
        "now": _iso(BASE),
    }


def _session_payload() -> dict:
    return {
        "session_id": SESSION_ID,
        "binding_ref": BINDING_REF,
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
        "account_ref": ACCOUNT_REF,
        "workspace_ref": WORKSPACE_REF,
        "now": _iso(BASE + timedelta(minutes=1)),
        "ttl_seconds": 900,
    }


def _rpc_fixture(*, connection: sqlite3.Connection | None = None):
    storage = _Storage(connection)
    env = _Env()
    durable_object = worker.LocalAgentBrokerDurableObject(_Context(storage), env)
    return storage, env, durable_object


def _provision_live_device(durable_object) -> dict:
    registered = asyncio.run(durable_object.register_binding(_register_payload()))
    assert registered["ok"] is True
    opened = asyncio.run(durable_object.open_session(_session_payload()))
    assert opened["ok"] is True
    session = opened["session"]
    record = DurableLocalAgentSessionRecord(
        session_id=session["session_id"],
        binding_ref=session["binding_ref"],
        device_id=session["device_id"],
        account_ref=session["account_ref"],
        workspace_ref=session["workspace_ref"],
        credential_generation=session["credential_generation"],
        issued_at=datetime.fromisoformat(session["issued_at"]),
        expires_at=datetime.fromisoformat(session["expires_at"]),
    )
    durable_object.http_state.save_session(record)
    durable_object.http_state.record_last_seen(
        SESSION_ID, seen_at=BASE + timedelta(minutes=1, seconds=5)
    )
    return session


def test_device_truth_reports_the_live_device_facts_and_never_online() -> None:
    _storage, _env, durable_object = _rpc_fixture()
    session = _provision_live_device(durable_object)

    result = asyncio.run(durable_object.device_truth({"account_ref": ACCOUNT_REF}))
    assert result["ok"] is True
    assert result["available"] is True
    facts = result["device_truth"]
    # The broker's own vocabulary has no ONLINE fact: the web consumer derives
    # ONLINE through the canonical #3080 projection rule from these facts.
    assert facts["canonical_state"] == "paired_offline"
    assert facts["binding"]["binding_ref"] == BINDING_REF
    assert facts["binding"]["device_id"] == DEVICE_ID
    assert facts["binding"]["account_ref"] == ACCOUNT_REF
    assert facts["binding"]["credential_generation"] == 1
    assert facts["session"]["session_id"] == SESSION_ID
    assert facts["session"]["expires_at"] == session["expires_at"]
    assert facts["heartbeat_last_seen_at"] is not None
    # Secret-free envelope: the digest is only ever referenced by its
    # negative-claim marker, never by its value.
    assert facts["binding"]["credential_digest_exposed"] is False
    assert facts["binding"]["raw_device_credential"] is False
    flat = str(result)
    import re as _re

    assert not _re.search(r"[0-9a-f]{64}", flat)
    assert base64.b64encode(CREDENTIAL).decode("ascii") not in flat


def test_device_truth_is_owner_scoped_and_unknown_owners_get_nothing() -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _provision_live_device(durable_object)

    other = asyncio.run(durable_object.device_truth({"account_ref": OTHER_ACCOUNT_REF}))
    assert other == {"ok": True, "available": False, "reason": "no_device_binding"}

    # The workspace filter narrows further; a wrong workspace sees nothing.
    scoped = asyncio.run(
        durable_object.device_truth(
            {"account_ref": ACCOUNT_REF, "workspace_ref": "ws.other.1"}
        )
    )
    assert scoped == {"ok": True, "available": False, "reason": "no_device_binding"}


def test_device_truth_reports_revoked_from_the_binding_record() -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _provision_live_device(durable_object)
    revoked = asyncio.run(
        durable_object.revoke_binding({"binding_ref": BINDING_REF, "now": _iso(BASE + timedelta(minutes=2))})
    )
    assert revoked["ok"] is True

    result = asyncio.run(durable_object.device_truth({"account_ref": ACCOUNT_REF}))
    assert result["available"] is True
    assert result["device_truth"]["canonical_state"] == "revoked"


def test_device_truth_reports_credential_expiry_from_the_owned_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _provision_live_device(durable_object)

    frozen = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)  # past the 30-day credential TTL
    runtime_module = importlib.import_module("local_agent_broker_durable_runtime")
    real_datetime = runtime_module.datetime

    class _FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr(
        "local_agent_broker_durable_runtime.datetime", _FrozenDatetime, raising=True
    )
    result = asyncio.run(durable_object.device_truth({"account_ref": ACCOUNT_REF}))
    assert result["available"] is True
    assert result["device_truth"]["canonical_state"] == "credential_expired"


def test_device_truth_rejects_malformed_requests_with_a_bounded_error() -> None:
    _storage, _env, durable_object = _rpc_fixture()
    for payload in ({}, {"account_ref": ""}, {"account_ref": "bad ref with spaces!"}, {"nope": 1}):
        result = asyncio.run(durable_object.device_truth(payload))
        assert result["ok"] is False
        assert result["error"] == {
            "code": "invalid_device_truth_request",
            "message": "device truth request was rejected",
        }


def test_device_truth_is_read_only_and_needs_no_transaction() -> None:
    # Provision through the real write paths first, then take transactionSync
    # away: any write inside the projection would explode, so completing proves
    # the projection is read-only. The snapshot must be untouched.
    storage = _Storage()
    _env = _Env()
    durable_object = worker.LocalAgentBrokerDurableObject(_Context(storage), _env)
    _provision_live_device(durable_object)
    before = durable_object._runtime.state_port.load(authority_ref=AUTHORITY_REF)

    storage.transactionSync = None  # type: ignore[method-assign]
    result = asyncio.run(durable_object.device_truth({"account_ref": ACCOUNT_REF}))
    assert result["available"] is True
    after = durable_object._runtime.state_port.load(authority_ref=AUTHORITY_REF)
    assert after.snapshot.bindings == before.snapshot.bindings
    assert after.snapshot.sessions == before.snapshot.sessions
    assert after.snapshot.commands == before.snapshot.commands


def test_worker_entrypoints_expose_the_device_truth_rpc_without_a_public_route() -> None:
    assert callable(getattr(worker.LocalAgentBrokerDurableObject, "device_truth"))
    assert callable(getattr(worker.Default, "device_truth"))
    # The projection is a private Service Binding RPC, never a public fetch.
    assert worker.PUBLIC_ENDPOINT_ADDED is False
    assert worker.NARROW_DEVICE_TRUTH_PROJECTION is True
    assert worker.DEVICE_TRUTH_VOCABULARY_HAS_ONLINE is False
    assert worker.DEVICE_TRUTH_SECOND_ONLINE_AUTHORITY is False
    assert worker.DEVICE_TRUTH_MUTATION is False
    assert worker.PRODUCTION_MUTATION is False
