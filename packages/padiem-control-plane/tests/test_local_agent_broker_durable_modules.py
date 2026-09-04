from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord, LocalAgentMaterialResolutionRequest
from padiem_control_plane.local_agent_broker_state import LocalAgentBrokerStateSnapshot
from padiem_control_plane.local_agent_broker_state_wire import LocalAgentBrokerStateJsonCodec

from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_material_store import CloudflareDurableObjectCommandMaterialStore
from local_agent_broker_sql_state import (
    CloudflareDurableObjectHttpSessionState,
    CloudflareDurableObjectSerializedStateBackend,
)

BASE = datetime(2026, 9, 4, 4, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.refactor-test.v1"
PEPPER = "durable-runtime-refactor-pepper"
CREDENTIAL = b"durable-runtime-refactor-credential"
FINGERPRINT = "a" * 64


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
        found: list[dict] = []
        if cursor.description is not None:
            names = [item[0] for item in cursor.description]
            found = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return _Cursor(found, rows_written)


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


class _Env:
    LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
    LOCAL_AGENT_BROKER_PEPPER = PEPPER


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _runtime() -> tuple[_Storage, LocalAgentBrokerDurableRuntime]:
    storage = _Storage()
    return storage, LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())


def _prepare(runtime: LocalAgentBrokerDurableRuntime) -> tuple[dict, dict]:
    registered = runtime.register_binding(
        {
            "binding_ref": "binding.refactor.1",
            "device_id": "device.refactor.1",
            "account_ref": "account.refactor.1",
            "workspace_ref": "workspace.refactor.1",
            "credential_b64": _encoded(CREDENTIAL),
            "now": BASE.isoformat(),
        }
    )
    assert registered["ok"] is True
    opened = runtime.open_session(
        {
            "session_id": "session.refactor.1",
            "binding_ref": "binding.refactor.1",
            "credential_b64": _encoded(CREDENTIAL),
            "account_ref": "account.refactor.1",
            "workspace_ref": "workspace.refactor.1",
            "now": (BASE + timedelta(seconds=1)).isoformat(),
        }
    )
    assert opened["ok"] is True
    queued = runtime.enqueue_command(
        {
            "command_id": "command.refactor.1",
            "binding_ref": "binding.refactor.1",
            "run_id": "run.refactor.1",
            "tool_request_ref": "tool-request.refactor.1",
            "request_fingerprint": FINGERPRINT,
            "now": (BASE + timedelta(seconds=2)).isoformat(),
            "ttl_seconds": 300,
        }
    )
    assert queued["ok"] is True
    return opened["session"], queued["command"]


def _wire(command: dict) -> dict:
    return {
        "contract_version": "claw-local-command-material.v1",
        "command_id": command["command_id"],
        "binding_ref": command["binding_ref"],
        "sequence": command["sequence"],
        "request_fingerprint": command["request_fingerprint"],
        "material": {
            "request_id": "request.refactor.1",
            "run_id": command["run_id"],
            "device_id": "device.refactor.1",
            "root_ref": "root.refactor.1",
            "argv": ["python", "-V"],
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


def test_sql_state_backend_runs_under_plain_cpython_and_preserves_exact_cas() -> None:
    storage = _Storage()
    backend = CloudflareDurableObjectSerializedStateBackend(storage)
    payload = LocalAgentBrokerStateJsonCodec().encode(LocalAgentBrokerStateSnapshot.empty(authority_ref=AUTHORITY_REF))
    created = backend.compare_and_swap(authority_ref=AUTHORITY_REF, expected_version=0, payload=payload)
    assert created.version == 1
    assert CloudflareDurableObjectSerializedStateBackend(storage).load(authority_ref=AUTHORITY_REF) == created
    updated = backend.compare_and_swap(authority_ref=AUTHORITY_REF, expected_version=1, payload=payload)
    assert updated.version == 2
    with pytest.raises(ControlPlaneContractError) as stale:
        backend.compare_and_swap(authority_ref=AUTHORITY_REF, expected_version=1, payload=payload)
    assert stale.value.code == "stale_local_agent_broker_state"


def test_http_session_store_runs_under_plain_cpython_and_keeps_monotonic_last_seen() -> None:
    storage = _Storage()
    store = CloudflareDurableObjectHttpSessionState(storage)
    record = DurableLocalAgentSessionRecord(
        session_id="session.refactor.direct",
        binding_ref="binding.refactor.direct",
        device_id="device.refactor.direct",
        account_ref="account.refactor.direct",
        workspace_ref="workspace.refactor.direct",
        credential_generation=1,
        issued_at=BASE,
        expires_at=BASE + timedelta(minutes=15),
    )
    store.save_session(record)
    changed = store.record_last_seen(record.session_id, seen_at=BASE + timedelta(seconds=10))
    assert changed.last_seen_at == BASE + timedelta(seconds=10)
    assert CloudflareDurableObjectHttpSessionState(storage).load_session(record.session_id) == changed
    with pytest.raises(ValueError):
        store.record_last_seen(record.session_id, seen_at=BASE + timedelta(seconds=9))


def test_material_store_and_lifecycle_runtime_run_without_platform_module() -> None:
    storage, runtime = _runtime()
    _session, command = _prepare(runtime)
    wire = _wire(command)
    stored = runtime.store_command_material(wire)
    assert stored["stored"] is True
    assert isinstance(runtime.material_store, CloudflareDurableObjectCommandMaterialStore)
    request = LocalAgentMaterialResolutionRequest(
        request_ref="material-request.refactor.1",
        session_id="session.refactor.1",
        binding_ref=command["binding_ref"],
        command_id=command["command_id"],
        request_fingerprint=command["request_fingerprint"],
        server_requested_at=BASE + timedelta(seconds=3),
    )
    assert runtime.material_store.resolve(request) == wire
    admitted = runtime.admit_command(
        {
            "admission_ref": "admission.refactor.1",
            "evidence_ref": "evidence.refactor.1",
            "session_id": "session.refactor.1",
            "binding_ref": command["binding_ref"],
            "credential_b64": _encoded(CREDENTIAL),
            "command_id": command["command_id"],
            "request_fingerprint": command["request_fingerprint"],
            "now": (BASE + timedelta(seconds=4)).isoformat(),
        }
    )
    assert admitted["ok"] is True
    acknowledged = runtime.acknowledge(
        {
            "session_id": "session.refactor.1",
            "binding_ref": command["binding_ref"],
            "credential_b64": _encoded(CREDENTIAL),
            "command_id": command["command_id"],
            "admission_ref": "admission.refactor.1",
            "evidence_ref": "evidence.refactor.1",
            "now": (BASE + timedelta(seconds=5)).isoformat(),
        }
    )
    assert acknowledged["ok"] is True
    count = storage.connection.execute("SELECT COUNT(*) FROM local_agent_command_material").fetchone()[0]
    assert count == 0
    assert runtime.safe_dict()["lifecycle_coordinator"] is True
    assert runtime.safe_dict()["production_mutation"] is False


def test_worker_file_is_thin_and_storage_schemas_live_outside_entrypoint() -> None:
    worker_path = Path(__file__).parents[1] / "local_agent_broker_worker.py"
    source = worker_path.read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source
    assert "class CloudflareDurableObjectSerializedStateBackend" not in source
    assert "class CloudflareDurableObjectHttpSessionState" not in source
    assert "class CloudflareDurableObjectCommandMaterialStore" not in source
    assert "class LocalAgentBrokerDurableRuntime" not in source
    assert "from workers import" in source
    assert len(source.splitlines()) < 190
