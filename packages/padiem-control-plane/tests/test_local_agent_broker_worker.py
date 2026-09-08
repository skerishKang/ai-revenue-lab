from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import types

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord
from padiem_control_plane.local_agent_broker_state import LocalAgentBrokerStateSnapshot
from padiem_control_plane.local_agent_broker_state_wire import LocalAgentBrokerStateJsonCodec


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
_WORKER_SPEC = importlib.util.spec_from_file_location("padiem_local_agent_broker_worker_test", _WORKER_PATH)
assert _WORKER_SPEC is not None and _WORKER_SPEC.loader is not None
worker = importlib.util.module_from_spec(_WORKER_SPEC)
sys.modules[_WORKER_SPEC.name] = worker
_WORKER_SPEC.loader.exec_module(worker)


BASE = datetime(2026, 9, 4, 2, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.do-test.v1"
PEPPER = "cloudflare-do-test-pepper-value"
CREDENTIAL_1 = b"cloudflare-do-device-credential-1"
CREDENTIAL_2 = b"cloudflare-do-device-credential-2"
FINGERPRINT_1 = "a" * 64
FINGERPRINT_2 = "b" * 64


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


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
    def __init__(self, *, namespace=None) -> None:
        self.LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        self.LOCAL_AGENT_BROKER_PEPPER = PEPPER
        self.LOCAL_AGENT_BROKER_STATE = namespace


class _Stub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def register_binding(self, payload):
        self.calls.append(("register_binding", payload))
        return {"ok": True, "routed": True}


class _Namespace:
    def __init__(self, stub: _Stub) -> None:
        self.stub = stub
        self.names: list[str] = []
        self.ids: list[str] = []

    def idFromName(self, name: str):
        self.names.append(name)
        return f"do::{name}"

    def get(self, object_id: str):
        self.ids.append(object_id)
        return self.stub


def _rpc_fixture(storage: _Storage | None = None):
    storage = storage or _Storage()
    env = _Env()
    durable_object = worker.LocalAgentBrokerDurableObject(_Context(storage), env)
    return storage, env, durable_object


def test_deployment_config_declares_private_sqlite_durable_object_without_public_preview() -> None:
    config_path = Path(__file__).parents[1] / ("wrang" + "ler.local-agent-broker.jsonc")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["main"] == "local_agent_broker_worker.py"
    assert config["workers_dev"] is False
    assert config["preview_urls"] is False
    assert config["compatibility_flags"] == ["python_workers", "disable_python_external_sdk"]
    assert config["durable_objects"]["bindings"] == [
        {
            "name": "LOCAL_AGENT_BROKER_STATE",
            "class_name": "LocalAgentBrokerDurableObject",
        }
    ]
    assert config["exports"]["LocalAgentBrokerDurableObject"] == {
        "type": "durable-object",
        "storage": "sqlite",
    }
    assert "routes" not in config


def test_public_fetch_is_404_and_authority_routing_is_server_owned() -> None:
    stub = _Stub()
    namespace = _Namespace(stub)
    entrypoint = worker.Default(_Env(namespace=namespace))

    response = asyncio.run(entrypoint.fetch(object()))
    assert response.status == 404
    assert response.headers["cache-control"] == "no-store"

    result = asyncio.run(
        entrypoint.register_binding(
            {
                "authority_ref": "caller.must.not.route.this",
                "binding_ref": "binding.fake",
            }
        )
    )
    assert result == {"ok": True, "routed": True}
    assert namespace.names == [AUTHORITY_REF]
    assert namespace.ids == [f"do::{AUTHORITY_REF}"]
    assert stub.calls[0][1]["authority_ref"] == "caller.must.not.route.this"


def test_serialized_backend_persists_exact_payload_and_rejects_stale_cas() -> None:
    storage = _Storage()
    first = worker.CloudflareDurableObjectSerializedStateBackend(storage)
    snapshot = LocalAgentBrokerStateSnapshot.empty(authority_ref=AUTHORITY_REF)
    payload = LocalAgentBrokerStateJsonCodec().encode(snapshot)

    created = first.compare_and_swap(
        authority_ref=AUTHORITY_REF,
        expected_version=0,
        payload=payload,
    )
    assert created.version == 1
    assert created.payload == payload

    restarted = worker.CloudflareDurableObjectSerializedStateBackend(storage)
    loaded = restarted.load(authority_ref=AUTHORITY_REF)
    assert loaded is not None
    assert loaded.version == 1
    assert loaded.payload == payload

    second = restarted.compare_and_swap(
        authority_ref=AUTHORITY_REF,
        expected_version=1,
        payload=payload,
    )
    assert second.version == 2
    with pytest.raises(ControlPlaneContractError) as stale:
        first.compare_and_swap(
            authority_ref=AUTHORITY_REF,
            expected_version=1,
            payload=payload,
        )
    assert stale.value.code == "stale_local_agent_broker_state"

    with pytest.raises(ControlPlaneContractError) as mismatch:
        restarted.load(authority_ref="control-plane.local-agent-broker.other")
    assert mismatch.value.code == "invalid_local_agent_broker_state_wire"


def test_canonical_broker_authority_survives_durable_object_recreation() -> None:
    storage, env, first = _rpc_fixture()

    registered = asyncio.run(
        first.register_binding(
            {
                "binding_ref": "binding.do.1",
                "device_id": "device.do.1",
                "account_ref": "account.do.1",
                "workspace_ref": "workspace.do.1",
                "credential_b64": _encoded(CREDENTIAL_1),
                "now": BASE.isoformat(),
            }
        )
    )
    assert registered["ok"] is True

    opened = asyncio.run(
        first.open_session(
            {
                "session_id": "session.do.1",
                "binding_ref": "binding.do.1",
                "credential_b64": _encoded(CREDENTIAL_1),
                "account_ref": "account.do.1",
                "workspace_ref": "workspace.do.1",
                "now": (BASE + timedelta(seconds=1)).isoformat(),
            }
        )
    )
    assert opened["ok"] is True

    queued = asyncio.run(
        first.enqueue_command(
            {
                "command_id": "command.do.1",
                "binding_ref": "binding.do.1",
                "run_id": "run.do.1",
                "tool_request_ref": "tool-request.do.1",
                "request_fingerprint": FINGERPRINT_1,
                "now": (BASE + timedelta(seconds=2)).isoformat(),
            }
        )
    )
    assert queued["ok"] is True
    assert queued["command"]["sequence"] == 1

    admitted = asyncio.run(
        first.admit_command(
            {
                "admission_ref": "admission.do.1",
                "evidence_ref": "evidence.do.1",
                "session_id": "session.do.1",
                "binding_ref": "binding.do.1",
                "credential_b64": _encoded(CREDENTIAL_1),
                "command_id": "command.do.1",
                "request_fingerprint": FINGERPRINT_1,
                "now": (BASE + timedelta(seconds=3)).isoformat(),
            }
        )
    )
    assert admitted["ok"] is True

    acknowledged = asyncio.run(
        first.acknowledge(
            {
                "session_id": "session.do.1",
                "binding_ref": "binding.do.1",
                "credential_b64": _encoded(CREDENTIAL_1),
                "command_id": "command.do.1",
                "admission_ref": "admission.do.1",
                "evidence_ref": "evidence.do.1",
                "now": (BASE + timedelta(seconds=4)).isoformat(),
            }
        )
    )
    assert acknowledged["ok"] is True
    assert acknowledged["command"]["state"] == "acknowledged"

    restarted = worker.LocalAgentBrokerDurableObject(_Context(storage), env)
    second = asyncio.run(
        restarted.enqueue_command(
            {
                "command_id": "command.do.2",
                "binding_ref": "binding.do.1",
                "run_id": "run.do.2",
                "tool_request_ref": "tool-request.do.2",
                "request_fingerprint": FINGERPRINT_2,
                "now": (BASE + timedelta(seconds=5)).isoformat(),
            }
        )
    )
    assert second["ok"] is True
    assert second["command"]["sequence"] == 2

    rotated = asyncio.run(
        restarted.rotate_credential(
            {
                "binding_ref": "binding.do.1",
                "expected_generation": 1,
                "new_credential_b64": _encoded(CREDENTIAL_2),
                "now": (BASE + timedelta(seconds=6)).isoformat(),
            }
        )
    )
    assert rotated["ok"] is True
    assert rotated["binding"]["credential_generation"] == 2

    after_rotation = worker.LocalAgentBrokerDurableObject(_Context(storage), env)
    old_session = asyncio.run(
        after_rotation.poll(
            {
                "session_id": "session.do.1",
                "binding_ref": "binding.do.1",
                "credential_b64": _encoded(CREDENTIAL_2),
                "after_sequence": 0,
                "now": (BASE + timedelta(seconds=7)).isoformat(),
            }
        )
    )
    assert old_session["ok"] is False
    assert old_session["error"]["code"] == "device_session_not_found"

    revoked = asyncio.run(
        after_rotation.revoke_binding(
            {
                "binding_ref": "binding.do.1",
                "now": (BASE + timedelta(seconds=8)).isoformat(),
            }
        )
    )
    assert revoked["ok"] is True

    after_revoke = worker.LocalAgentBrokerDurableObject(_Context(storage), env)
    denied = asyncio.run(
        after_revoke.open_session(
            {
                "session_id": "session.do.2",
                "binding_ref": "binding.do.1",
                "credential_b64": _encoded(CREDENTIAL_2),
                "account_ref": "account.do.1",
                "workspace_ref": "workspace.do.1",
                "now": (BASE + timedelta(seconds=9)).isoformat(),
            }
        )
    )
    assert denied["ok"] is False
    assert denied["error"]["code"] == "device_binding_revoked"

    dump = "\n".join(storage.connection.iterdump())
    assert CREDENTIAL_1.decode("ascii") not in dump
    assert CREDENTIAL_2.decode("ascii") not in dump
    assert _encoded(CREDENTIAL_1) not in dump
    assert _encoded(CREDENTIAL_2) not in dump


def test_http_session_state_survives_recreation_and_enforces_last_seen_monotonicity() -> None:
    storage = _Storage()
    first = worker.CloudflareDurableObjectHttpSessionState(storage)
    record = DurableLocalAgentSessionRecord(
        session_id="session.http.do.1",
        binding_ref="binding.http.do.1",
        device_id="device.http.do.1",
        account_ref="account.http.do.1",
        workspace_ref="workspace.http.do.1",
        credential_generation=1,
        issued_at=BASE,
        expires_at=BASE + timedelta(minutes=15),
    )
    first.save_session(record)

    restarted = worker.CloudflareDurableObjectHttpSessionState(storage)
    loaded = restarted.load_session(record.session_id)
    assert loaded == record

    seen = restarted.record_last_seen(record.session_id, seen_at=BASE + timedelta(seconds=10))
    assert seen.last_seen_at == BASE + timedelta(seconds=10)
    assert worker.CloudflareDurableObjectHttpSessionState(storage).load_session(record.session_id) == seen

    with pytest.raises(ValueError):
        restarted.record_last_seen(record.session_id, seen_at=BASE + timedelta(seconds=9))
    with pytest.raises(ValueError):
        restarted.record_last_seen(record.session_id, seen_at=record.expires_at)
    with pytest.raises(ValueError):
        restarted.save_session(record)


def test_adapter_truth_flags_do_not_claim_public_or_production_activation() -> None:
    assert worker.CLOUDFLARE_DO_ADAPTER is True
    assert worker.FOUNDATION_PACKAGE_SIDE_EFFECT_FREE is True
    assert worker.SQLITE_BACKED_DURABLE_OBJECT is True
    assert worker.SERVER_OWNED_AUTHORITY_ROUTING is True
    assert worker.M2G_SERIALIZED_STATE_REUSED is True
    assert worker.ATOMIC_VERSION_CAS is True
    assert worker.STALE_CAS_FAILS_CLOSED is True
    assert worker.M2E_HTTP_SESSION_STATE_DURABLE is True
    assert worker.LAST_SEEN_MONOTONIC is True
    assert worker.CANONICAL_BROKER_RPC_REUSED is True
    assert worker.SECOND_REPLAY_SEQUENCE_AUTHORITY is False
    assert worker.RAW_DEVICE_CREDENTIAL_PERSISTED is False
    assert worker.PUBLIC_FETCH is False
    assert worker.DURABLE_COMMAND_MATERIAL_STORE is True
    assert worker.PRODUCTION_DEPLOYMENT is False
    assert worker.PRODUCTION_ROUTE_CONFIGURED is False
    assert worker.PRODUCTION_SECRET_BOUND is False
    assert worker.PRODUCTION_MUTATION is False
    assert worker.PRODUCTION_READY is False
