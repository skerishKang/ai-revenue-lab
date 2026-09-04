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

from padiem_control_plane.local_agent_broker_http import (
    LocalAgentBrokerHttpHandler,
    LocalAgentMaterialResolutionRequest,
    TrustedLocalAgentHttpAuthContext,
)


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
_WORKER_SPEC = importlib.util.spec_from_file_location("padiem_local_agent_material_worker_test", _WORKER_PATH)
assert _WORKER_SPEC is not None and _WORKER_SPEC.loader is not None
worker = importlib.util.module_from_spec(_WORKER_SPEC)
sys.modules[_WORKER_SPEC.name] = worker
_WORKER_SPEC.loader.exec_module(worker)


BASE = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.material-test.v1"
PEPPER = "durable-material-test-pepper"
CREDENTIAL_1 = b"durable-material-device-credential-1"
CREDENTIAL_2 = b"durable-material-device-credential-2"
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
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
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
    LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
    LOCAL_AGENT_BROKER_PEPPER = PEPPER


def _do(storage: _Storage | None = None):
    storage = storage or _Storage()
    env = _Env()
    return storage, env, worker.LocalAgentBrokerDurableObject(_Context(storage), env)


def _prepare_command(
    *,
    command_id: str = "command.material.1",
    fingerprint: str = FINGERPRINT_1,
    ttl_seconds: int = 300,
):
    storage, env, durable = _do()
    registered = asyncio.run(
        durable.register_binding(
            {
                "binding_ref": "binding.material.1",
                "device_id": "device.material.1",
                "account_ref": "account.material.1",
                "workspace_ref": "workspace.material.1",
                "credential_b64": _encoded(CREDENTIAL_1),
                "now": BASE.isoformat(),
            }
        )
    )
    assert registered["ok"] is True
    opened = asyncio.run(
        durable.open_session(
            {
                "session_id": "session.material.1",
                "binding_ref": "binding.material.1",
                "credential_b64": _encoded(CREDENTIAL_1),
                "account_ref": "account.material.1",
                "workspace_ref": "workspace.material.1",
                "now": (BASE + timedelta(seconds=1)).isoformat(),
            }
        )
    )
    assert opened["ok"] is True
    queued = asyncio.run(
        durable.enqueue_command(
            {
                "command_id": command_id,
                "binding_ref": "binding.material.1",
                "run_id": f"run.{command_id}",
                "tool_request_ref": f"tool-request.{command_id}",
                "request_fingerprint": fingerprint,
                "now": (BASE + timedelta(seconds=2)).isoformat(),
                "ttl_seconds": ttl_seconds,
            }
        )
    )
    assert queued["ok"] is True
    return storage, env, durable, queued["command"]


def _wire(command: dict, *, marker: str = "material-argv-marker") -> dict:
    return {
        "contract_version": "claw-local-command-material.v1",
        "command_id": command["command_id"],
        "binding_ref": command["binding_ref"],
        "sequence": command["sequence"],
        "request_fingerprint": command["request_fingerprint"],
        "material": {
            "request_id": f"request.{command['command_id']}",
            "run_id": command["run_id"],
            "device_id": "device.material.1",
            "root_ref": "root.material.1",
            "argv": ["python", "-c", marker],
            "cwd_relative": ".",
            "requested_at": (BASE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "timeout_seconds": 30,
            "shell_authority": False,
            "admin_elevation": False,
            "environment_payload": None,
            "provider_authority": None,
            "p01_approval_payload": None,
        },
    }


def _request(command: dict, *, at: datetime) -> LocalAgentMaterialResolutionRequest:
    return LocalAgentMaterialResolutionRequest(
        request_ref=f"material-request.{command['command_id']}",
        session_id="session.material.1",
        binding_ref=command["binding_ref"],
        command_id=command["command_id"],
        request_fingerprint=command["request_fingerprint"],
        server_requested_at=at,
    )


def _material_count(storage: _Storage) -> int:
    return int(storage.connection.execute("SELECT COUNT(*) FROM local_agent_command_material").fetchone()[0])


def _admit(durable, command: dict, *, at: datetime) -> dict:
    return asyncio.run(
        durable.admit_command(
            {
                "admission_ref": f"admission.{command['command_id']}",
                "evidence_ref": f"evidence.{command['command_id']}",
                "session_id": "session.material.1",
                "binding_ref": command["binding_ref"],
                "credential_b64": _encoded(CREDENTIAL_1),
                "command_id": command["command_id"],
                "request_fingerprint": command["request_fingerprint"],
                "now": at.isoformat(),
            }
        )
    )


def test_exact_material_survives_recreation_without_expanding_broker_metadata() -> None:
    storage, env, first, command = _prepare_command()
    marker = "argv-only-in-material-table-7f4e"
    wire = _wire(command, marker=marker)

    stored = asyncio.run(first.store_command_material(wire))
    assert stored["stored"] is True
    assert stored["raw_argv"] is False
    assert stored["raw_device_credential"] is False
    assert stored["execution_approval"] is False

    wire_text = storage.connection.execute(
        "SELECT wire_text FROM local_agent_command_material WHERE command_id = ?",
        (command["command_id"],),
    ).fetchone()[0]
    assert wire_text == json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    broker_payload = storage.connection.execute(
        "SELECT payload_text FROM local_agent_broker_state WHERE singleton = 1"
    ).fetchone()[0]
    assert marker not in broker_payload
    assert '"raw_argv"' not in broker_payload

    restarted = worker.LocalAgentBrokerDurableObject(_Context(storage), env)
    resolved = restarted.material_store.resolve(_request(command, at=BASE + timedelta(seconds=3)))
    assert resolved == wire

    polled = asyncio.run(
        restarted.poll(
            {
                "session_id": "session.material.1",
                "binding_ref": command["binding_ref"],
                "credential_b64": _encoded(CREDENTIAL_1),
                "after_sequence": 0,
                "now": (BASE + timedelta(seconds=3)).isoformat(),
                "limit": 1,
            }
        )
    )
    assert polled["ok"] is True
    assert polled["commands"][0]["raw_argv"] is False
    assert polled["commands"][0]["raw_file_content"] is False

    dump = "\n".join(storage.connection.iterdump())
    assert CREDENTIAL_1.decode("ascii") not in dump
    assert _encoded(CREDENTIAL_1) not in dump

    with pytest.raises(ValueError):
        restarted.material_store.store(wire)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command_id", "command.material.other"),
        ("binding_ref", "binding.material.other"),
        ("sequence", 2),
        ("request_fingerprint", FINGERPRINT_2),
    ],
)
def test_store_rejects_command_correlation_mismatch(field: str, value) -> None:
    storage, _env, durable, command = _prepare_command()
    wire = _wire(command)
    wire[field] = value
    with pytest.raises(ValueError):
        durable.material_store.store(wire)
    assert _material_count(storage) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("shell_authority", True),
        ("admin_elevation", True),
        ("environment_payload", {"PATH": "tampered"}),
        ("provider_authority", {"provider": "tampered"}),
        ("p01_approval_payload", {"approved": True}),
    ],
)
def test_store_rejects_authority_expansion(field: str, value) -> None:
    storage, _env, durable, command = _prepare_command()
    wire = _wire(command)
    wire["material"][field] = value
    with pytest.raises(ValueError):
        durable.material_store.store(wire)
    assert _material_count(storage) == 0


def test_store_rejects_oversized_material() -> None:
    storage, _env, durable, command = _prepare_command()
    wire = _wire(command, marker="x" * (worker.MAX_DURABLE_COMMAND_MATERIAL_BYTES + 1))
    with pytest.raises(ValueError):
        durable.material_store.store(wire)
    assert _material_count(storage) == 0


def test_new_material_requires_command_to_remain_queued() -> None:
    storage, _env, durable, command = _prepare_command()
    admitted = _admit(durable, command, at=BASE + timedelta(seconds=3))
    assert admitted["ok"] is True
    with pytest.raises(ValueError):
        durable.material_store.store(_wire(command))
    assert _material_count(storage) == 0

    acknowledged = asyncio.run(
        durable.acknowledge(
            {
                "session_id": "session.material.1",
                "binding_ref": command["binding_ref"],
                "credential_b64": _encoded(CREDENTIAL_1),
                "command_id": command["command_id"],
                "admission_ref": f"admission.{command['command_id']}",
                "evidence_ref": f"evidence.{command['command_id']}",
                "now": (BASE + timedelta(seconds=4)).isoformat(),
            }
        )
    )
    assert acknowledged["ok"] is True
    with pytest.raises(ValueError):
        durable.material_store.store(_wire(command))
    assert _material_count(storage) == 0


def test_expired_material_fails_closed_and_is_deleted() -> None:
    storage, _env, durable, command = _prepare_command(ttl_seconds=5)
    durable.material_store.store(_wire(command))
    assert _material_count(storage) == 1

    with pytest.raises(RuntimeError):
        durable.material_store.resolve(_request(command, at=BASE + timedelta(seconds=8)))
    assert _material_count(storage) == 0


def test_acknowledgement_purges_material_in_same_lifecycle() -> None:
    storage, _env, durable, command = _prepare_command()
    durable.material_store.store(_wire(command))
    admitted = _admit(durable, command, at=BASE + timedelta(seconds=3))
    assert admitted["ok"] is True
    assert _material_count(storage) == 1

    acknowledged = asyncio.run(
        durable.acknowledge(
            {
                "session_id": "session.material.1",
                "binding_ref": command["binding_ref"],
                "credential_b64": _encoded(CREDENTIAL_1),
                "command_id": command["command_id"],
                "admission_ref": f"admission.{command['command_id']}",
                "evidence_ref": f"evidence.{command['command_id']}",
                "now": (BASE + timedelta(seconds=4)).isoformat(),
            }
        )
    )
    assert acknowledged["ok"] is True
    assert _material_count(storage) == 0


def test_rotation_and_revocation_purge_outstanding_binding_material() -> None:
    storage, _env, durable, command = _prepare_command()
    durable.material_store.store(_wire(command))
    assert _material_count(storage) == 1

    rotated = asyncio.run(
        durable.rotate_credential(
            {
                "binding_ref": command["binding_ref"],
                "expected_generation": 1,
                "new_credential_b64": _encoded(CREDENTIAL_2),
                "now": (BASE + timedelta(seconds=3)).isoformat(),
            }
        )
    )
    assert rotated["ok"] is True
    assert _material_count(storage) == 0

    second = asyncio.run(
        durable.enqueue_command(
            {
                "command_id": "command.material.2",
                "binding_ref": command["binding_ref"],
                "run_id": "run.command.material.2",
                "tool_request_ref": "tool-request.command.material.2",
                "request_fingerprint": FINGERPRINT_2,
                "now": (BASE + timedelta(seconds=4)).isoformat(),
            }
        )
    )
    assert second["ok"] is True
    durable.material_store.store(_wire(second["command"], marker="second-material"))
    assert _material_count(storage) == 1

    revoked = asyncio.run(
        durable.revoke_binding(
            {
                "binding_ref": command["binding_ref"],
                "now": (BASE + timedelta(seconds=5)).isoformat(),
            }
        )
    )
    assert revoked["ok"] is True
    assert _material_count(storage) == 0


def test_m2e_http_material_handler_accepts_durable_resolver_without_new_authority() -> None:
    storage, _env, durable, command = _prepare_command()
    now = [BASE + timedelta(seconds=3)]
    handler = LocalAgentBrokerHttpHandler(
        rpc=durable._facade(),
        state=durable.http_state,
        material_resolver=durable.material_store,
        clock=lambda: now[0],
    )
    auth = TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.material.1",
        account_ref="account.material.1",
        workspace_ref="workspace.material.1",
        authenticated=True,
        tls_verified=True,
    )

    session_result = durable._facade().open_session(
        {
            "session_id": "session.http.material.1",
            "binding_ref": command["binding_ref"],
            "credential_b64": _encoded(CREDENTIAL_1),
            "account_ref": "account.material.1",
            "workspace_ref": "workspace.material.1",
            "now": (BASE + timedelta(seconds=2)).isoformat(),
        }
    )
    assert session_result["ok"] is True
    session = session_result["session"]
    durable.http_state.save_session(
        worker.DurableLocalAgentSessionRecord(
            session_id=session["session_id"],
            binding_ref=session["binding_ref"],
            device_id=session["device_id"],
            account_ref=session["account_ref"],
            workspace_ref=session["workspace_ref"],
            credential_generation=session["credential_generation"],
            issued_at=datetime.fromisoformat(session["issued_at"].replace("Z", "+00:00")),
            expires_at=datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00")),
        )
    )

    wire = _wire(command, marker="handler-material")
    durable.material_store.store(wire)
    body = json.dumps(
        {
            "request_ref": "material-request.http.1",
            "session_id": "session.http.material.1",
            "binding_ref": command["binding_ref"],
            "credential_b64": _encoded(CREDENTIAL_1),
            "command_id": command["command_id"],
            "request_fingerprint": command["request_fingerprint"],
            "now": now[0].isoformat(),
        }
    ).encode("utf-8")
    response = handler.handle(
        method="POST",
        route="/material",
        content_type="application/json",
        body=body,
        auth=auth,
    )
    assert response.status == 200
    assert response.body == {"ok": True, "material": wire}
    assert _material_count(storage) == 1


def test_m2i_truth_flags_preserve_security_nonclaims() -> None:
    assert worker.DURABLE_COMMAND_MATERIAL_STORE is True
    assert worker.CANONICAL_MATERIAL_WIRE_REUSED is True
    assert worker.SECOND_FINGERPRINT_ALGORITHM is False
    assert worker.BROKER_METADATA_EXPANDED_WITH_ARGV is False
    assert worker.EXACT_COMMAND_CORRELATION_ON_STORE is True
    assert worker.EXACT_RESOLUTION_CORRELATION is True
    assert worker.QUEUED_STATE_REQUIRED_FOR_STORE is True
    assert worker.MATERIAL_EXPIRY_BOUNDED is True
    assert worker.ACK_PURGES_MATERIAL is True
    assert worker.ROTATION_REVOCATION_PURGES_MATERIAL is True
    assert worker.M2E_RESOLVER_PORT_IMPLEMENTED is True
    assert worker.RAW_DEVICE_CREDENTIAL_PERSISTED is False
    assert worker.PRODUCTION_DEPLOYMENT is False
    assert worker.PRODUCTION_ROUTE_CONFIGURED is False
    assert worker.PRODUCTION_SECRET_BOUND is False
    assert worker.PRODUCTION_MUTATION is False
    assert worker.PRODUCTION_READY is False
