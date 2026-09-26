"""#3127 — enqueue and durable command material commit in one transaction.

These tests drive the *real* Durable Runtime composition over a file-backed
SQLite database, so `transactionSync` is a genuine database transaction and a
"crash" is a genuine process-shaped event: the runtime object is discarded and
rebuilt over the same file. Nothing about the transaction or crash path is
stubbed — only the Cloudflare storage object is adapted, which is the same
adaptation the platform does.

Two properties of the API are load-bearing and are pinned here:

* the caller supplies the material *body* only. The command id, binding,
  sequence, request fingerprint and revision are the canonical path's to decide,
  and the test never predicts them — a caller that guessed a sequence or a
  revision would be guessing a server-owned value.
* the fail-closed material guard is scoped to the state in which a transition
  still creates a fact, so a lost-response acknowledgement retry is not refused
  for a material row that the acknowledgement itself purged.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import sqlite3
import sys
import types

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


class _FakeResponse:
    def __init__(self, body: str = "", *, status: int = 200, headers=None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None) -> None:
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx, env) -> None:
        self.ctx = ctx
        self.env = env


# The platform entrypoint module imports the Cloudflare runtime. The structural
# gateway proof below is about *which methods the entrypoint exposes*, so the
# platform object is replaced rather than the behaviour under test.
_workers = types.ModuleType("workers")
_workers.Response = _FakeResponse
_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
_workers.DurableObject = _FakeDurableObject
sys.modules.setdefault("workers", _workers)


class _Context:
    """The Durable Object context: the storage and nothing else."""

    def __init__(self, storage: "_Storage") -> None:
        self.storage = storage


class _GatewayStub:
    """A service-binding stub whose calls land on the real Durable Object."""

    def __init__(self, durable_object) -> None:
        self._durable_object = durable_object

    def __getattr__(self, name):
        target = getattr(self._durable_object, name)

        async def call(*args, **kwargs):
            return await target(*args, **kwargs)

        return call


class _GatewayNamespace:
    def __init__(self, stub: _GatewayStub) -> None:
        self.stub = stub
        self.names: list[str] = []
        self.ids: list[str] = []

    def idFromName(self, name: str) -> str:  # noqa: N802 — platform surface
        self.names.append(name)
        return f"do::{name}"

    def get(self, object_id: str) -> _GatewayStub:
        self.ids.append(object_id)
        return self.stub


class _GatewayEnv:
    LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
    LOCAL_AGENT_BROKER_PEPPER = PEPPER

    def __init__(self, namespace) -> None:
        self.LOCAL_AGENT_BROKER_STATE = namespace


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _runtime(path: Path) -> LocalAgentBrokerDurableRuntime:
    return LocalAgentBrokerDurableRuntime(storage=_Storage(path), env=_Env())


def _register_and_open(runtime: LocalAgentBrokerDurableRuntime) -> None:
    asyncio.run(_register_and_open_async(runtime))


async def _register_and_open_async(entrypoint) -> None:
    """Register a binding and open a session on a runtime or a Durable Object.

    The Durable Object entrypoints are async while the runtime composition is
    not, so the setup is written once against either.
    """

    async def call(method_name: str, payload: dict) -> dict:
        result = getattr(entrypoint, method_name)(payload)
        if inspect.isawaitable(result):
            result = await result
        return result

    registered = await call(
        "register_binding",
        {
            "binding_ref": "binding.atomic.1",
            "device_id": "device.atomic.1",
            "account_ref": "account.atomic.1",
            "workspace_ref": "workspace.atomic.1",
            "credential_b64": _encoded(CREDENTIAL),
            "now": BASE.isoformat(),
        },
    )
    assert registered["ok"] is True
    opened = await call(
        "open_session",
        {
            "session_id": "session.atomic.1",
            "binding_ref": "binding.atomic.1",
            "credential_b64": _encoded(CREDENTIAL),
            "account_ref": "account.atomic.1",
            "workspace_ref": "workspace.atomic.1",
            "now": (BASE + timedelta(seconds=1)).isoformat(),
        },
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


def _material_body(command_id: str, *, argv: list[str] | None = None) -> dict:
    """The caller-supplied material body: no server-owned correlation."""

    return {
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
    }


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
    found: list[str] = []
    for (payload_text,) in rows:
        found.extend(item["command_id"] for item in json.loads(payload_text)["commands"])
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


def _ack_payload(command: dict, *, at: datetime, exit_code: int = 0) -> dict:
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
        "exit_code": exit_code,
        "now": at.isoformat(),
    }


# --- 1. the legacy split path still leaves a command with no material -------
def test_legacy_split_enqueue_still_leaves_a_command_without_material(tmp_path: Path) -> None:
    """The residual risk the atomic path exists to remove.

    This is *not* a rollback test: the legacy enqueue commits on its own, so the
    command survives with no material. That is precisely why the atomic path is
    the product path and why the material-less guards below exist.
    """

    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    queued = runtime.enqueue_command(_enqueue_payload("command.legacy.1", now=BASE + timedelta(seconds=2)))
    assert queued["ok"] is True
    del runtime

    restarted = _runtime(path)
    assert _persisted_commands(path) == ["command.legacy.1"]
    assert _material_rows(path) == []
    assert restarted.material_store.has_persisted_material("command.legacy.1") is False


# --- 2. crash inside the atomic transaction rolls both writes back ---------
def test_crash_between_broker_write_and_material_write_rolls_back_everything(tmp_path: Path) -> None:
    """Crash after the broker write, before the material write lands.

    Nothing is committed, so neither the command nor the material exists after
    the restart — the exact window the audit found, closed.
    """

    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    original_store = runtime.material_store.store

    def store_then_die(wire: dict) -> dict:
        raise _Crash("the object died after the broker write, before the material write")

    runtime.material_store.store = store_then_die  # type: ignore[method-assign]
    with pytest.raises(_Crash):
        runtime.enqueue_command_with_material(
            _enqueue_payload("command.crash.1", now=BASE + timedelta(seconds=2)),
            _material_body("command.crash.1"),
        )
    runtime.material_store.store = original_store  # type: ignore[method-assign]
    del runtime

    restarted = _runtime(path)
    assert _persisted_commands(path) == []
    assert _material_rows(path) == []


def test_crash_after_both_writes_before_commit_rolls_back_everything(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    storage = runtime._storage  # noqa: SLF001 — the storage under test
    original_transaction = runtime.transaction
    observed: dict[str, int] = {}

    def die_before_commit(callback):
        """Run the real transaction body, then die instead of committing."""

        storage.connection.execute("BEGIN IMMEDIATE")
        callback()
        observed["material_rows"] = len(
            storage.connection.execute("SELECT command_id FROM local_agent_command_material").fetchall()
        )
        raise _Crash("the object died after writing both records, before commit")

    runtime.transaction = die_before_commit  # type: ignore[method-assign]
    with pytest.raises(_Crash):
        runtime.enqueue_command_with_material(
            _enqueue_payload("command.crash.2", now=BASE + timedelta(seconds=2)),
            _material_body("command.crash.2"),
        )
    runtime.transaction = original_transaction  # type: ignore[method-assign]
    # Both writes really did reach the database before the crash...
    assert observed["material_rows"] == 1
    # ...and the uncommitted transaction left nothing behind.
    del runtime
    restarted = _runtime(path)
    assert _persisted_commands(path) == []
    assert _material_rows(path) == []


# --- 3. success commits both, and both survive a restart -------------------
def test_atomic_enqueue_commits_command_and_material_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)

    result = runtime.enqueue_command_with_material(
        _enqueue_payload("command.ok.1", now=BASE + timedelta(seconds=2)),
        _material_body("command.ok.1"),
    )
    assert result["ok"] is True
    command = result["command"]
    assert command["command_id"] == "command.ok.1"
    # The caller never supplied these: the canonical path decided them inside
    # the transaction, and the material row was assembled to match.
    assert command["sequence"] == 1
    assert command["revision_ref"].startswith("rev.")
    del runtime

    restarted = _runtime(path)
    assert _persisted_commands(path) == ["command.ok.1"]
    assert _material_rows(path) == [{"command_id": "command.ok.1", "sequence": 1}]
    resolved = restarted.material_store.resolve(_request(command, at=BASE + timedelta(seconds=3)))
    assert resolved["command_id"] == "command.ok.1"
    assert resolved["sequence"] == command["sequence"]
    assert resolved["revision_ref"] == command["revision_ref"]
    assert resolved["material"]["argv"] == ["python", "-V"]


# --- 4. a lost response re-serves the same command and reuses the material --
def test_lost_response_exact_retry_reuses_command_and_material(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    payload = _enqueue_payload("command.retry.1", now=BASE + timedelta(seconds=2))
    body = _material_body("command.retry.1")

    first = runtime.enqueue_command_with_material(payload, body)
    assert first["ok"] is True
    # The caller never saw the response and retries the identical request.
    retry = runtime.enqueue_command_with_material(payload, body)
    assert retry["ok"] is True
    assert retry["command"]["command_id"] == first["command"]["command_id"]
    assert retry["command"]["revision_ref"] == first["command"]["revision_ref"]
    assert retry["command"]["sequence"] == first["command"]["sequence"]
    assert retry["material"]["stored"] is True
    assert retry["material"].get("reused") is True
    # Nothing was minted a second time: one material row, and the next command
    # continues the monotonic sequence rather than restarting it.
    assert _material_rows(path) == [{"command_id": "command.retry.1", "sequence": 1}]
    after = runtime.enqueue_command(_enqueue_payload("command.retry.2", now=BASE + timedelta(seconds=5)))
    assert after["ok"] is True
    assert after["command"]["sequence"] == 2


# --- 5. a retry that disagrees fails closed --------------------------------
def test_conflicting_retry_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    payload = _enqueue_payload("command.conflict.1", now=BASE + timedelta(seconds=2))
    stored = runtime.enqueue_command_with_material(payload, _material_body("command.conflict.1"))
    assert stored["ok"] is True

    with pytest.raises(ValueError):
        runtime.enqueue_command_with_material(
            payload, _material_body("command.conflict.1", argv=["python", "-c", "different"])
        )
    assert _material_rows(path) == [{"command_id": "command.conflict.1", "sequence": 1}]
    # The originally stored material is untouched by the refused retry.
    assert runtime.material_store.resolve(
        _request(stored["command"], at=BASE + timedelta(seconds=3))
    )["material"]["argv"] == ["python", "-V"]


def test_atomic_enqueue_refuses_a_material_body_that_violates_the_wire_contract(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)

    for broken in (
        {**_material_body("command.mismatch.1"), "shell_authority": True},
        {**_material_body("command.mismatch.1"), "environment_payload": {"A": "1"}},
        {**_material_body("command.mismatch.1"), "argv": "not-a-list"},
    ):
        with pytest.raises(ValueError):
            runtime.enqueue_command_with_material(
                _enqueue_payload("command.mismatch.1", now=BASE + timedelta(seconds=2)), broken
            )
        # The canonical enqueue was rolled back with the material, so no
        # half-committed command is left behind.
        assert _material_rows(path) == []
        assert _persisted_commands(path) == []


# --- 6. a command with no material can reach no terminal fact --------------
def test_command_without_material_cannot_be_admitted_or_acknowledged(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    queued = runtime.enqueue_command(_enqueue_payload("command.bare.1", now=BASE + timedelta(seconds=2)))
    command = queued["command"]
    assert _material_rows(path) == []

    with pytest.raises(ControlPlaneContractError) as refused:
        runtime.admit_command(_admit_payload(command, at=BASE + timedelta(seconds=3)))
    assert refused.value.code == "broker_command_material_missing"
    # Acknowledgement is refused by the canonical authority here: the command
    # is still QUEUED, so there is no admission to acknowledge. The guard is
    # scoped to ADMITTED, which is where acknowledging would create a fact.
    refused_ack = runtime.acknowledge(_ack_payload(command, at=BASE + timedelta(seconds=4)))
    assert refused_ack["ok"] is False
    assert refused_ack["error"]["code"] == "broker_ack_without_admission"
    assert _persisted_commands(path) == ["command.bare.1"]


def test_material_bearing_command_admits_and_acknowledges_normally(tmp_path: Path) -> None:
    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    result = runtime.enqueue_command_with_material(
        _enqueue_payload("command.happy.1", now=BASE + timedelta(seconds=2)),
        _material_body("command.happy.1"),
    )
    assert result["ok"] is True
    admitted = runtime.admit_command(_admit_payload(result["command"], at=BASE + timedelta(seconds=5)))
    assert admitted["ok"] is True
    acknowledged = runtime.acknowledge(_ack_payload(result["command"], at=BASE + timedelta(seconds=6)))
    assert acknowledged["ok"] is True
    assert acknowledged["command"]["state"] == "acknowledged"
    # The acknowledgement still purges the material in the same transaction.
    assert _material_rows(path) == []


# --- 7. the #3118 lost-response acknowledgement retry still works ----------
def test_ack_exact_retry_after_material_purge_is_still_idempotent(tmp_path: Path) -> None:
    """The acknowledgement itself purges the material.

    An exact retry of a *lost* acknowledgement response therefore arrives when
    the material row is already gone. Refusing that retry for a missing material
    row would break the recovery #3118 added, so the guard is scoped to the
    state where a transition still creates a fact.
    """

    path = tmp_path / "do.sqlite3"
    runtime = _runtime(path)
    _register_and_open(runtime)
    result = runtime.enqueue_command_with_material(
        _enqueue_payload("command.ackretry.1", now=BASE + timedelta(seconds=2)),
        _material_body("command.ackretry.1"),
    )
    command = result["command"]
    assert runtime.admit_command(_admit_payload(command, at=BASE + timedelta(seconds=4)))["ok"] is True

    first = runtime.acknowledge(_ack_payload(command, at=BASE + timedelta(seconds=5)))
    assert first["ok"] is True
    assert _material_rows(path) == []

    # The response was lost; the caller retries the identical acknowledgement.
    retry = runtime.acknowledge(_ack_payload(command, at=BASE + timedelta(seconds=6)))
    assert retry["ok"] is True
    assert retry["command"]["state"] == "acknowledged"
    assert retry["command"]["acknowledged_at"] == first["command"]["acknowledged_at"]
    assert retry["command"]["exit_code"] == first["command"]["exit_code"]

    # A retry that *disagrees* still fails closed, and the terminal record is
    # not reopened or rewritten.
    conflict = runtime.acknowledge(_ack_payload(command, at=BASE + timedelta(seconds=7), exit_code=9))
    assert conflict["ok"] is False
    assert conflict["error"]["code"] == "broker_ack_conflict"

    # The same must hold across a restart: a retry after the object came back
    # is still served, not refused for the purged material.
    del runtime
    restarted = _runtime(path)
    after_restart = restarted.acknowledge(_ack_payload(command, at=BASE + timedelta(seconds=8)))
    assert after_restart["ok"] is True
    assert after_restart["command"]["acknowledged_at"] == first["command"]["acknowledged_at"]


# --- 8. the atomic path mints nothing a second time ------------------------
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


# --- 9. the product gateway cannot create a command by the split pair -------
def test_product_gateway_exposes_no_split_write_surface() -> None:
    """The canonical server gateway must not offer the split pair at all.

    #3127 removes `enqueue_command` and `store_command_material` from the
    `Default` service-binding entrypoint, so a product caller has exactly one
    way to create a command: the atomic one. The Durable Object keeps both as
    internal composition, which is where the tests and the runtime itself live.
    """

    from local_agent_broker_worker import Default, LocalAgentBrokerDurableObject

    assert hasattr(Default, "enqueue_command_with_material")
    assert not hasattr(Default, "enqueue_command")
    assert not hasattr(Default, "store_command_material")

    # Present on the object, so the absence on the gateway is a boundary and
    # not a capability that was never implemented.
    assert hasattr(LocalAgentBrokerDurableObject, "enqueue_command")
    assert hasattr(LocalAgentBrokerDurableObject, "store_command_material")

    source = (Path(__file__).parents[1] / "local_agent_broker_worker.py").read_text(encoding="utf-8")
    gateway_source = source.split("class Default(WorkerEntrypoint)", 1)[1]
    for forbidden in ("async def enqueue_command(", "async def store_command_material("):
        assert forbidden not in gateway_source


def test_gateway_cannot_produce_an_executable_command_without_the_atomic_path(tmp_path: Path) -> None:
    """A command written the split way reaches no executable state.

    Even where the internal split methods still exist — on the Durable Object —
    a command with no material cannot be admitted, resolved or acknowledged.
    That is the structural proof behind removing the pair from the gateway: the
    split path cannot manufacture a runnable command even if it is reached.
    """

    from local_agent_broker_worker import Default, LocalAgentBrokerDurableObject

    path = tmp_path / "do.sqlite3"
    storage = _Storage(path)
    env = _Env()
    durable_object = LocalAgentBrokerDurableObject(_Context(storage), env)
    asyncio.run(_register_and_open_async(durable_object))

    # The internal split write: durable command, no material.
    queued = asyncio.run(
        durable_object.enqueue_command(_enqueue_payload("command.split.1", now=BASE + timedelta(seconds=2)))
    )
    assert queued["ok"] is True
    command = queued["command"]
    assert _material_rows(path) == []

    with pytest.raises(ControlPlaneContractError) as refused:
        asyncio.run(durable_object.admit_command(_admit_payload(command, at=BASE + timedelta(seconds=3))))
    assert refused.value.code == "broker_command_material_missing"
    refused_ack = asyncio.run(
        durable_object.acknowledge(_ack_payload(command, at=BASE + timedelta(seconds=4)))
    )
    assert refused_ack["ok"] is False
    with pytest.raises(RuntimeError):
        durable_object.material_store.resolve(_request(command, at=BASE + timedelta(seconds=5)))

    # And the gateway that product callers actually hold routes to the same
    # object, offers no split method to try, and its one command path is the
    # atomic one: the command it produces carries its material.
    gateway = Default(_GatewayEnv(_GatewayNamespace(_GatewayStub(durable_object))))
    for name in ("enqueue_command", "store_command_material"):
        assert getattr(gateway, name, None) is None
    through_gateway = asyncio.run(
        gateway.enqueue_command_with_material(
            _enqueue_payload("command.gateway.1", now=BASE + timedelta(seconds=6)),
            _material_body("command.gateway.1"),
        )
    )
    assert through_gateway["ok"] is True
    assert through_gateway["material"]["stored"] is True
    assert [row["command_id"] for row in _material_rows(path)] == ["command.gateway.1"]
    assert durable_object.material_store.resolve(
        _request(through_gateway["command"], at=BASE + timedelta(seconds=7))
    )["command_id"] == "command.gateway.1"


def test_atomic_api_does_not_accept_server_owned_correlation(tmp_path: Path) -> None:
    """The atomic call takes a material body, not a pre-assembled wire.

    A caller that supplied the wire would have to predict the canonical
    sequence and revision, which are the server's to decide.
    """

    import inspect

    signature = inspect.signature(LocalAgentBrokerDurableRuntime.enqueue_command_with_material)
    assert list(signature.parameters) == ["self", "payload", "material"]
    source = inspect.getsource(LocalAgentBrokerDurableRuntime.enqueue_command_with_material)
    assert '"contract_version": "claw-local-command-material.v2"' in source
    # The wire is built from the enqueue result, not from the caller's values.
    assert 'command["sequence"]' in source
    assert 'command["revision_ref"]' in source
