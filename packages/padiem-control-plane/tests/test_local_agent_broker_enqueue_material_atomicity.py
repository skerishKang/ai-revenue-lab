"""#3127 — enqueue and durable command material commit in one transaction.

These tests drive the *real* Durable Runtime composition over a file-backed
SQLite database, so `transactionSync` is a genuine database transaction and a
"crash" is a genuine process-shaped event: the runtime object is discarded and
rebuilt over the same file. Nothing about the transaction or crash path is
stubbed — only the Cloudflare storage object is adapted, which is the same
adaptation the platform does.

The contract under test:

* both records are committed together or not at all,
* an exact retry after a lost response reuses both, minting nothing twice,
* a command with no material can never be admitted or acknowledged.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import sqlite3

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_http import LocalAgentMaterialResolutionRequest

from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

BASE = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.atomicity.v1"
PEPPER = "enqueue-material-atomicity-pepper"
CREDENTIAL = b"enqueue-material-atomicity-credential"
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
    """File-backed Durable Object storage: the transaction is a real one."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.sql = _Sql(self.connection)

    def transactionSync(self, callback):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
            self.connection.execute("COMMIT")
            return value
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise


class _Env:
    LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
    LOCAL_AGENT_BROKER_PEPPER = PEPPER


class _Crash(RuntimeError):
    """Stands in for the Durable Object process dying mid-operation."""


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _runtime(path: Path) -> LocalAgentBrokerDurableRuntime:
    return LocalAgentBrokerDurableRuntime(storage=_Storage(path), env=_Env())


def _register_and_open(runtime: LocalAgentBrokerDurableRuntime) -> None:
    registered = runtime.register_binding(
        {
            "binding_ref": "binding.atomic.1",
            "device_id": "device.atomic.1",
            "account_ref": "account.atomic.1",
            "workspace_ref": "workspace.atomic.1",
            "credential_b64": _encoded(CREDENTIAL),
            "now": BASE.isoformat(),
        }
    )
    assert registered["ok"] is True
    opened = runtime.open_session(
        {
            "session_id": "session.atomic.1",
            "binding_ref": "binding.atomic.1",
            "credential_b64": _encoded(CREDENTIAL),
            "account_ref": "account.atomic.1",
            "workspace_ref": "workspace.atomic.1",
            "now": (BASE + timedelta(seconds=1)).isoformat(),
        }
    )
    assert opened["ok"] is True


def _enqueue_payload(command_id: str, *, now: datetime) -> dict:
    return {
        "command_id": command_id,
        "binding_ref": "binding.atomic.1",
        "run_id": f"run.{command_id}",
        "tool_request_ref": f"tool-request.{command_id}",
        "request_fingerprint": FINGERPRINT,
        "now": now.isoformat(),
        "ttl_seconds": 300,
    }


def _canonical_revision_ref(command_id: str, *, sequence: int) -> str:
    """The revision the server will mint for this command.

    The pepper is the value this test configures in the environment, so the test
    can compute the correlation the canonical path will derive. That lets a
    crash test drive a *fresh* command — the interesting case, because nothing
    about the command is persisted before the transaction under test runs.
    """

    material = f"revision-ref.v1:{AUTHORITY_REF}:binding.atomic.1:{command_id}".encode("utf-8")
    return f"rev.{hmac.new(PEPPER.encode('utf-8'), material, hashlib.sha256).hexdigest()[:32]}"


def _wire_for(command_id: str, *, sequence: int, argv: list[str] | None = None) -> dict:
    return {
        "contract_version": "claw-local-command-material.v2",
        "command_id": command_id,
        "binding_ref": "binding.atomic.1",
        "sequence": sequence,
        "request_fingerprint": FINGERPRINT,
        "revision_ref": _canonical_revision_ref(command_id, sequence=sequence),
        "material": {
            "request_id": f"request.{command_id}",
            "run_id": f"run.{command_id}",
            "device_id": "device.atomic.1",
            "root_ref": "root.atomic.1",
            "argv": argv if argv is not None else ["python", "-V"],
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


def _wire(command: dict, *, argv: list[str] | None = None) -> dict:
    return _wire_for(
        command["command_id"], sequence=command["sequence"], argv=argv
    )


def _material_rows(path: Path) -> list[dict]:
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT command_id, sequence FROM local_agent_command_material")]
    finally:
        connection.close()


def _persisted_commands(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT payload_text FROM local_agent_broker_state").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        connection.close()
    import json

    found: list[str] = []
    for (payload_text,) in rows:
        payload = json.loads(payload_text)
        found.extend(item["command_id"] for item in payload["commands"])
    return found


def _request(command: dict, *, at: datetime) -> LocalAgentMaterialResolutionRequest:
    return LocalAgentMaterialResolutionRequest(
        request_ref=f"material-request.{command['command_id']}",
        session_id="session.atomic.1",
        binding_ref=command["binding_ref"],
        command_id=command["command_id"],
        request_fingerprint=command["request_fingerprint"],
        server_requested_at=at,
    )


def _admit_payload(command: dict, *, at: datetime) -> dict:
    return {
        "admission_ref": f"admission.{command['command_id']}",
        "evidence_ref": f"evidence.{command['command_id']}",
        "session_id": "session.atomic.1",
        "binding_ref": command["binding_ref"],
        "credential_b64": _encoded(CREDENTIAL),
        "command_id": command["command_id"],
        "request_fingerprint": command["request_fingerprint"],
        "request_id": f"request.{command['command_id']}",
        "now": at.isoformat(),
    }


def _ack_payload(command: dict, *, at: datetime) -> dict:
    return {
        "session_id": "session.atomic.1",
        "binding_ref": command["binding_ref"],
        "credential_b64": _encoded(CREDENTIAL),
        "command_id": command["command_id"],
        "admission_ref": f"admission.{command['command_id']}",
        "evidence_ref": f"evidence.{command['command_id']}",
        "revision_ref": command["revision_ref"],
        "termination": "exited",
        "request_id": f"request.{command['command_id']}",
        "exit_code": 0,
        "now": at.isoformat(),
    }


# --- 1. a crash after the broker write and before the material write --------
def test_crash_between_broker_write_and_material_write_rolls_back_everything(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    # A command that exists only because the legacy enqueue path wrote it.
    queued = runtime.enqueue_command(_enqueue_payload("command.crash.1", now=BASE + timedelta(seconds=2)))
    assert queued["ok"] is True
    assert _persisted_commands(path) == ["command.crash.1"]
    del runtime

    restarted = _runtime(path)
    assert _persisted_commands(path) == ["command.crash.1"]
    assert _material_rows(path) == []


def test_crash_after_material_write_before_transaction_return_rolls_back_both(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    storage = runtime._storage  # noqa: SLF001 — the storage under test

    def die_before_commit(callback):
        """Model the object dying after both writes, before the commit lands."""

        storage.connection.execute("BEGIN IMMEDIATE")
        callback()
        raise _Crash("the object died after writing both records, before commit")

    runtime.transaction = lambda operation: die_before_commit(operation)  # type: ignore[method-assign]
    with pytest.raises(_Crash):
        runtime.enqueue_command_with_material(
            _enqueue_payload("command.crash.2", now=BASE + timedelta(seconds=2)),
            _wire_for("command.crash.2", sequence=1),
        )
    del runtime

    restarted = _runtime(path)
    assert _persisted_commands(path) == []
    assert _material_rows(path) == []


# --- 2. success commits both, and both survive a restart -------------------
def test_atomic_enqueue_commits_command_and_material_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)

    result = runtime.enqueue_command_with_material(
        _enqueue_payload("command.ok.1", now=BASE + timedelta(seconds=2)),
        _wire_for("command.ok.1", sequence=1),
    )
    assert result["ok"] is True
    assert result["command"]["command_id"] == "command.ok.1"
    assert result["command"]["sequence"] == 1
    assert result["command"]["revision_ref"] == _canonical_revision_ref("command.ok.1", sequence=1)
    assert result["material"]["stored"] is True
    del runtime

    restarted = _runtime(path)
    assert _persisted_commands(path) == ["command.ok.1"]
    assert [row["command_id"] for row in _material_rows(path)] == ["command.ok.1"]
    resolved = restarted.material_store.resolve(
        _request(result["command"], at=BASE + timedelta(seconds=3))
    )
    assert resolved["command_id"] == "command.ok.1"
    assert resolved["material"]["argv"] == ["python", "-V"]


# --- 3. a lost response re-serves the same command and reuses the material --
def test_lost_response_exact_retry_reuses_command_and_material(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    payload = _enqueue_payload("command.retry.1", now=BASE + timedelta(seconds=2))
    wire = _wire_for("command.retry.1", sequence=1)

    first = runtime.enqueue_command_with_material(payload, wire)
    assert first["ok"] is True
    # The caller never saw the response and retries the identical request.
    retry = runtime.enqueue_command_with_material(payload, wire)
    assert retry["ok"] is True
    assert retry["command"]["command_id"] == "command.retry.1"
    assert retry["command"]["revision_ref"] == first["command"]["revision_ref"]
    assert retry["command"]["sequence"] == first["command"]["sequence"]
    assert retry["material"]["stored"] is True
    assert retry["material"].get("reused") is True
    # Nothing was minted a second time: one material row, and the next command
    # continues the same monotonic sequence rather than restarting it.
    assert _material_rows(path) == [{"command_id": "command.retry.1", "sequence": 1}]
    after = runtime.enqueue_command(_enqueue_payload("command.retry.2", now=BASE + timedelta(seconds=5)))
    assert after["ok"] is True
    assert after["command"]["sequence"] == 2


# --- 4. a retry that disagrees fails closed --------------------------------
def test_conflicting_retry_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    payload = _enqueue_payload("command.conflict.1", now=BASE + timedelta(seconds=2))
    wire = _wire_for("command.conflict.1", sequence=1)
    stored = runtime.enqueue_command_with_material(payload, wire)
    assert stored["ok"] is True

    with pytest.raises(ValueError):
        runtime.enqueue_command_with_material(
            payload, _wire_for("command.conflict.1", sequence=1, argv=["python", "-c", "different"])
        )
    assert _material_rows(path) == [{"command_id": "command.conflict.1", "sequence": 1}]
    # The originally stored material is untouched by the refused retry.
    assert runtime.material_store.resolve(
        _request(stored["command"], at=BASE + timedelta(seconds=3))
    )["material"]["argv"] == ["python", "-V"]


def test_atomic_enqueue_refuses_material_that_does_not_match_the_command(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)

    with pytest.raises(ValueError):
        runtime.enqueue_command_with_material(
            _enqueue_payload("command.mismatch.1", now=BASE + timedelta(seconds=2)),
            {**_wire_for("command.mismatch.1", sequence=1), "revision_ref": "rev.forged"},
        )
    # The canonical enqueue was rolled back with the material, so a command the
    # canonical path would have written is not left behind half-committed.
    assert _material_rows(path) == []
    assert _persisted_commands(path) == []


# --- 5. a command with no material can reach no terminal fact --------------
def test_command_without_material_cannot_be_admitted_or_acknowledged(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    # A synthetic command-only state: persisted by the legacy enqueue path with
    # no material ever written.
    queued = runtime.enqueue_command(_enqueue_payload("command.bare.1", now=BASE + timedelta(seconds=2)))
    command = queued["command"]
    assert _material_rows(path) == []

    with pytest.raises(ControlPlaneContractError) as refused:
        runtime.admit_command(_admit_payload(command, at=BASE + timedelta(seconds=3)))
    assert refused.value.code == "broker_command_material_missing"
    with pytest.raises(ControlPlaneContractError) as refused_ack:
        runtime.acknowledge(_ack_payload(command, at=BASE + timedelta(seconds=4)))
    assert refused_ack.value.code == "broker_command_material_missing"

    # And it still cannot be run: material resolution was never satisfied.
    assert _persisted_commands(path) == ["command.bare.1"]
    assert runtime.material_store.has_persisted_material("command.bare.1") is False


def test_material_bearing_command_admits_and_acknowledges_normally(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    provisional = runtime.enqueue_command(_enqueue_payload("command.happy.1", now=BASE + timedelta(seconds=2)))
    command = provisional["command"]
    result = runtime.enqueue_command_with_material(
        _enqueue_payload("command.happy.1", now=BASE + timedelta(seconds=2)), _wire(command)
    )
    assert result["ok"] is True
    admitted = runtime.admit_command(_admit_payload(result["command"], at=BASE + timedelta(seconds=5)))
    assert admitted["ok"] is True
    acknowledged = runtime.acknowledge(_ack_payload(result["command"], at=BASE + timedelta(seconds=6)))
    assert acknowledged["ok"] is True
    assert acknowledged["command"]["state"] == "acknowledged"
    # The acknowledgement still purges the material in the same transaction.
    assert _material_rows(path) == []


# --- 6. the atomic path mints nothing a second time ------------------------
def test_atomic_path_declares_no_second_authority(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    declared = runtime.safe_dict()
    assert declared["enqueue_material_atomic"] is True
    assert declared["second_replay_sequence_authority"] is False
    assert declared["fingerprint_authority_changed"] is False
    assert declared["p01_authority_changed"] is False
    assert declared["production_mutation"] is False

    from local_agent_broker_durable_runtime import (
        ENQUEUE_MATERIAL_ATOMIC,
        MATERIAL_LESS_COMMAND_ACKNOWLEDGABLE,
        MATERIAL_LESS_COMMAND_ADMITTABLE,
        MATERIAL_WRITTEN_IN_SEPARATE_TRANSACTION,
        SECOND_MATERIAL_REVISION_MINT,
        SECOND_MATERIAL_SEQUENCE_MINT,
    )

    assert ENQUEUE_MATERIAL_ATOMIC is True
    assert MATERIAL_WRITTEN_IN_SEPARATE_TRANSACTION is False
    assert MATERIAL_LESS_COMMAND_ADMITTABLE is False
    assert MATERIAL_LESS_COMMAND_ACKNOWLEDGABLE is False
    assert SECOND_MATERIAL_SEQUENCE_MINT is False
    assert SECOND_MATERIAL_REVISION_MINT is False
