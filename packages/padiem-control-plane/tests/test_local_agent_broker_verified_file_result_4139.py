"""#4139 — the real Windows TXT result reaches the Claw through the canonical Broker.

Everything under test is real: the private Service Binding bridge, the canonical
device service, the #3129 transactional session open, the M2e HTTP handler, the
durable runtime composition over a genuine SQLite database, the canonical
command lifecycle, and the verified file result store.

Two properties are load-bearing and pinned here:

* the acknowledgement keeps carrying only the bounded outcome and correlation.
  File text is stored through its own canonical route and is gated on the
  canonical command's own successful outcome — never on the ack body, on device
  stdout, or on a fixture;
* the Claw-facing read answers exactly the three shapes #4687 / #4690 / #4693
  accept (full verified receipt, pending text-file result, or ``other``), with
  every correlation value taken from the canonical persisted command record.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
import sqlite3
import sys
import types
from typing import Any

import pytest

from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord

if "workers" not in sys.modules:
    _workers = types.ModuleType("workers")

    class _FakeResponse:
        def __init__(self, body="", *, status=200, headers=None):
            self.body = body
            self.status = status
            self.headers = headers or {}

    class _FakeWorkerEntrypoint:
        def __init__(self, env=None):
            self.env = env

    class _FakeDurableObject:
        def __init__(self, ctx=None, env=None):
            self.ctx = ctx
            self.env = env

    _workers.Response = _FakeResponse
    _workers.WorkerEntrypoint = _FakeWorkerEntrypoint
    _workers.DurableObject = _FakeDurableObject
    sys.modules["workers"] = _workers

import local_agent_broker_device_http as device_http  # noqa: E402
import local_agent_broker_private_http_bridge as private_bridge  # noqa: E402
import local_agent_broker_verified_file_store as verified_store  # noqa: E402
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime  # noqa: E402

BASE = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.verified-file.v1"
PEPPER = "verified-file-result-pepper"
CREDENTIAL = b"verified-file-result-credential"
FINGERPRINT = "a" * 64
BINDING_REF = "binding.verified.1"
DEVICE_ID = "device.verified.1"
ACCOUNT_REF = "account.verified.1"
WORKSPACE_REF = "workspace.verified.1"
SESSION_ID = "session.verified.1"
COMMAND_ID = "command.verified.1"
RUN_ID = "run.command.verified.1"
TOOL_REQUEST_REF = "tool-request.command.verified.1"
ADMISSION_REF = "admission.verified.1"
EVIDENCE_REF = "evidence.verified.1"
REQUEST_ID = "request.verified.1"
CONTENT = "오늘 PC의 실제 테스트 파일입니다.\n"
FILE_RESULT_PATH = "/file-result"


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
    """SQLite-backed Durable Object storage: `transactionSync` is a real transaction."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
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


class _Clock:
    def __init__(self) -> None:
        self.now = BASE

    def __call__(self) -> datetime:
        return self.now


class _PrivateRequest:
    def __init__(self, *, path: str, body: bytes, method: str = "POST") -> None:
        self.url = f"https://broker.internal{path}"
        self.method = method
        self.headers = {"content-type": "application/json"}
        self.body = self._stream(body)

    @staticmethod
    async def _stream(body: bytes):
        yield body


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _post(service, path: str, payload: dict) -> dict:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    response = asyncio.run(
        private_bridge.handle_private_device_fetch(
            _PrivateRequest(path=path, body=body),
            lambda: _Stub(service),
        )
    )
    try:
        decoded = json.loads(response.body)
    except (TypeError, ValueError):
        decoded = {"raw": response.body}
    return {"status": response.status, "body": decoded}


class _Stub:
    """The DO stub the private bridge calls: the canonical service, unchanged."""

    def __init__(self, service) -> None:
        self._service = service

    async def handle_device_http(self, envelope: dict) -> dict:
        return self._service.handle(envelope)


class _HttpSessionState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        return self.records[session_id]

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


def _service(runtime: LocalAgentBrokerDurableRuntime, clock) -> Any:
    """The deployed device-service composition, over the durable runtime."""

    return device_http.LocalAgentBrokerDeviceHttpService(
        state_port=runtime.state_port,
        pepper=PEPPER.encode("utf-8"),
        authority_ref=AUTHORITY_REF,
        rpc_factory=runtime.facade,
        http_state=runtime.http_state,
        material_resolver=runtime.material_store,
        session_open_transaction=runtime._storage.transactionSync,  # noqa: SLF001 - the real seam
        clock=clock,
        verified_file_result_store=runtime.verified_file_store,
    )


def _material_body() -> dict:
    return {
        "request_id": REQUEST_ID,
        "run_id": RUN_ID,
        "device_id": DEVICE_ID,
        "root_ref": "root.verified.1",
        "argv": ["cmd", "/c", "type", "sample.txt"],
        "cwd_relative": ".",
        "requested_at": (BASE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "timeout_seconds": 30,
        "shell_authority": False,
        "admin_elevation": False,
        "environment_payload": None,
        "provider_authority": None,
        "p01_approval_payload": None,
    }


def _submission(
    revision_ref: str,
    *,
    content: str | None = CONTENT,
    kind: str = "file_read_text",
    **overrides: Any,
) -> dict:
    digest = None
    if content is not None:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    payload = {
        "session_id": SESSION_ID,
        "binding_ref": BINDING_REF,
        "credential_b64": _encoded(CREDENTIAL),
        "command_id": COMMAND_ID,
        "revision_ref": revision_ref,
        "request_id": REQUEST_ID,
        "evidence_ref": EVIDENCE_REF,
        "kind": kind,
        "content_utf8": content,
        "content_sha256": digest,
        "now": (BASE + timedelta(seconds=8)).isoformat(),
    }
    payload.update(overrides)
    return payload


def _admitted(*, with_material: bool = True):
    """One registered device, one real session, one admitted command."""

    storage = _Storage()
    runtime = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    clock = _Clock()
    service = _service(runtime, clock)

    registered = runtime.register_binding(
        {
            "binding_ref": BINDING_REF,
            "device_id": DEVICE_ID,
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "now": BASE.isoformat(),
        }
    )
    assert registered["ok"] is True

    opened = _post(
        service,
        "/session",
        {
            "session_id": SESSION_ID,
            "binding_ref": BINDING_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "now": (BASE + timedelta(seconds=1)).isoformat(),
            "ttl_seconds": 3600,
        },
    )
    assert opened["status"] == 200 and opened["body"]["ok"] is True

    enqueue = {
        "command_id": COMMAND_ID,
        "binding_ref": BINDING_REF,
        "run_id": RUN_ID,
        "tool_request_ref": TOOL_REQUEST_REF,
        "request_fingerprint": FINGERPRINT,
        "now": (BASE + timedelta(seconds=2)).isoformat(),
        "ttl_seconds": 300,
    }
    if with_material:
        queued = runtime.enqueue_command_with_material(enqueue, _material_body())
    else:
        queued = runtime.enqueue_command(enqueue)
    assert queued["ok"] is True
    command = queued["command"]

    admitted = runtime.admit_command(
        {
            "admission_ref": ADMISSION_REF,
            "evidence_ref": EVIDENCE_REF,
            "session_id": SESSION_ID,
            "binding_ref": BINDING_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "command_id": COMMAND_ID,
            "request_fingerprint": FINGERPRINT,
            "request_id": REQUEST_ID,
            "now": (BASE + timedelta(seconds=3)).isoformat(),
        }
    )
    assert admitted["ok"] is True
    return runtime, service, command


def _ack(runtime, *, termination: str = "exited", exit_code: int | None = 0, now_offset: int = 9) -> dict:
    return runtime.acknowledge(
        {
            "session_id": SESSION_ID,
            "binding_ref": BINDING_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "command_id": COMMAND_ID,
            "admission_ref": ADMISSION_REF,
            "evidence_ref": EVIDENCE_REF,
            "revision_ref": runtime.state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands[0].revision_ref,
            "termination": termination,
            "request_id": REQUEST_ID,
            "exit_code": exit_code,
            "now": (BASE + timedelta(seconds=now_offset)).isoformat(),
        }
    )


def _read(runtime, **overrides: Any) -> dict:
    payload = {
        "account_ref": ACCOUNT_REF,
        "workspace_ref": WORKSPACE_REF,
        "run_id": RUN_ID,
        "command_id": COMMAND_ID,
    }
    payload.update(overrides)
    return runtime.read_verified_file_text(payload)


def test_verified_windows_text_reaches_the_claw_receipt_shape() -> None:
    runtime, service, command = _admitted()
    submitted = _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))
    assert submitted["status"] == 200, submitted
    stored = submitted["body"]["file_result"]
    assert stored["kind"] == "file_read_text"
    assert stored["content_bytes"] == len(CONTENT.encode("utf-8"))
    assert stored["content_sha256"] == hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
    assert stored["raw_device_credential"] is False

    acknowledged = _ack(runtime)
    assert acknowledged["ok"] is True
    # The acknowledgement itself still carries the bounded outcome only.
    assert acknowledged["command"]["raw_file_content"] is False
    assert CONTENT not in json.dumps(acknowledged, ensure_ascii=False)

    receipt = _read(runtime)
    assert frozenset(receipt) == frozenset(verified_store.RECEIPT_FIELDS)
    assert receipt["ok"] is True and receipt["available"] is True
    assert receipt["kind"] == "file_read_text"
    assert receipt["content_utf8"] == CONTENT
    assert receipt["content_sha256"] == hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
    assert receipt["account_ref"] == ACCOUNT_REF
    assert receipt["workspace_ref"] == WORKSPACE_REF
    assert receipt["run_id"] == RUN_ID
    assert receipt["command_id"] == COMMAND_ID
    assert receipt["tool_request_ref"] == TOOL_REQUEST_REF
    assert receipt["request_id"] == REQUEST_ID
    assert receipt["revision_ref"] == command["revision_ref"]
    assert receipt["evidence_ref"] == EVIDENCE_REF
    assert receipt["request_fingerprint"] == FINGERPRINT


def test_ack_alone_yields_other_and_never_a_fabricated_file_result() -> None:
    runtime, service, command = _admitted()
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False
    assert _ack(runtime)["ok"] is True
    assert _read(runtime) == {"ok": True, "available": False, "kind": "other"}
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False

    # A device that explicitly states the command was not a text-file read gets
    # the same bounded answer, and still no content can be attached.
    declared = _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"], content=None, kind="other"))
    assert declared["status"] == 200
    assert declared["body"]["file_result"]["content_bytes"] is None
    assert _read(runtime) == {"ok": True, "available": False, "kind": "other"}


def test_pending_declaration_then_text_upgrade_keeps_one_receipt() -> None:
    runtime, service, command = _admitted()
    pending = _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"], content=None))
    assert pending["status"] == 200, pending
    assert pending["body"]["file_result"]["content_bytes"] is None
    assert _ack(runtime)["ok"] is True
    assert _read(runtime) == {"ok": True, "available": False, "kind": "file_read_text"}

    upgraded = _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))
    assert upgraded["status"] == 200, upgraded
    assert upgraded["body"]["file_result"]["content_bytes"] == len(CONTENT.encode("utf-8"))
    receipt = _read(runtime)
    assert receipt["available"] is True and receipt["content_utf8"] == CONTENT
    rows = runtime._storage.connection.execute(  # noqa: SLF001 - the storage under test
        "SELECT command_id FROM local_agent_verified_file_results"
    ).fetchall()
    assert rows == [(COMMAND_ID,)]

    # An identical retry is idempotent; a downgrade is refused.
    again = _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))
    assert again["status"] == 200
    assert again["body"]["file_result"]["content_bytes"] == len(CONTENT.encode("utf-8"))
    downgrade = _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"], content=None))
    assert downgrade["status"] == 400


def test_failed_execution_purges_a_stored_result_and_refuses_new_text() -> None:
    runtime, service, command = _admitted()
    assert _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))["status"] == 200
    failed = _ack(runtime, exit_code=1)
    assert failed["ok"] is True and failed["command"]["state"] == "acknowledged"
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False

    late = _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))
    assert late["status"] == 400
    refused = _read(runtime)
    assert refused["ok"] is False
    assert refused["error"]["code"] == "verified_file_result_not_successful"


def test_cancelled_execution_never_serves_text() -> None:
    runtime, service, command = _admitted()
    assert _ack(runtime, termination="cancelled", exit_code=None)["ok"] is True
    assert _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))["status"] == 400
    refused = _read(runtime)
    assert refused["ok"] is False and refused["error"]["code"] == "verified_file_result_not_successful"


@pytest.mark.parametrize(
    "override",
    [
        {"content_utf8": "가" * 300},
        {"content_utf8": "bad\x00data"},
        {"content_sha256": "0" * 64},
        {"content_utf8": "text", "kind": "other"},
        {"content_sha256": None},
        {"kind": "stdout"},
    ],
)
def test_bounded_utf8_hash_and_kind_are_enforced_at_the_route(override) -> None:
    runtime, service, command = _admitted()
    payload = _submission(command["revision_ref"])
    payload.update(override)
    refused = _post(service, FILE_RESULT_PATH, payload)
    assert refused["status"] == 400, (override, refused)
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False


def test_correlation_is_server_owned_and_cross_binding_writes_are_refused() -> None:
    runtime, service, command = _admitted()
    revision_ref = command["revision_ref"]
    for override in (
        {"revision_ref": "revision.other"},
        {"request_id": "request.other"},
        {"evidence_ref": "evidence.other"},
        {"command_id": "command.other"},
    ):
        payload = _submission(revision_ref)
        payload.update(override)
        assert _post(service, FILE_RESULT_PATH, payload)["status"] == 400, override
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False

    # A second, genuinely authenticated device may not write a result for a
    # command that belongs to the first device's binding.
    second = runtime.register_binding(
        {
            "binding_ref": "binding.verified.2",
            "device_id": "device.verified.2",
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "credential_b64": _encoded(CREDENTIAL),
            # Issued no later than the device service's own (fixed) clock: the
            # canonical broker refuses a session that lies outside its
            # binding's credential lifetime.
            "now": BASE.isoformat(),
        }
    )
    assert second["ok"] is True
    opened = _post(
        service,
        "/session",
        {
            "session_id": "session.verified.2",
            "binding_ref": "binding.verified.2",
            "credential_b64": _encoded(CREDENTIAL),
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "now": (BASE + timedelta(seconds=5)).isoformat(),
            "ttl_seconds": 3600,
        },
    )
    assert opened["status"] == 200 and opened["body"]["ok"] is True
    foreign = _submission(revision_ref)
    foreign.update({"session_id": "session.verified.2", "binding_ref": "binding.verified.2"})
    assert _post(service, FILE_RESULT_PATH, foreign)["status"] == 403


def test_read_is_owner_and_workspace_scoped_and_read_only() -> None:
    runtime, service, command = _admitted()
    assert _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))["status"] == 200
    assert _ack(runtime)["ok"] is True
    before = runtime.state_port.load(authority_ref=AUTHORITY_REF).version

    assert _read(runtime)["available"] is True
    for override in (
        {"account_ref": "account.other"},
        {"workspace_ref": "workspace.other"},
        {"run_id": "run.other"},
        {"command_id": "command.other"},
    ):
        refused = _read(runtime, **override)
        assert refused["ok"] is False, override
        assert refused["error"]["code"] == "verified_file_result_not_found"
    assert _read(runtime, account_ref="account.other", workspace_ref="workspace.other")["ok"] is False
    assert runtime.state_port.load(authority_ref=AUTHORITY_REF).version == before


def test_revocation_and_rotation_purge_a_stored_result() -> None:
    runtime, service, command = _admitted()
    assert _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))["status"] == 200
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is True
    rotated = runtime.rotate_credential(
        {
            "binding_ref": BINDING_REF,
            "expected_generation": 1,
            "new_credential_b64": _encoded(b"rotated-verified-file-credential"),
            "now": (BASE + timedelta(seconds=6)).isoformat(),
        }
    )
    assert rotated["ok"] is True
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False
    assert _read(runtime)["ok"] is False

    revoked = runtime.revoke_binding({"binding_ref": BINDING_REF, "now": (BASE + timedelta(seconds=7)).isoformat()})
    assert revoked["ok"] is True
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False


def test_expired_reconciliation_purges_a_stored_result() -> None:
    runtime, service, command = _admitted()
    assert _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))["status"] == 200
    reconciled = runtime.reconcile_expired_command(
        {
            "session_id": SESSION_ID,
            "binding_ref": BINDING_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "command_id": COMMAND_ID,
            "admission_ref": ADMISSION_REF,
            "revision_ref": command["revision_ref"],
            "request_id": REQUEST_ID,
            "request_fingerprint": FINGERPRINT,
            "termination": None,
            "exit_code": None,
            # Past the command's hard deadline: #3121 reconciles an ADMITTED
            # command that provably never reported a result.
            "now": (BASE + timedelta(seconds=400)).isoformat(),
        }
    )
    assert reconciled["ok"] is True and reconciled["command"]["state"] == "expired"
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False
    assert _read(runtime)["ok"] is False


def test_route_is_reachable_only_because_it_is_in_the_canonical_set() -> None:
    assert verified_store.FILE_RESULT_ROUTE in device_http.DEVICE_HTTP_ROUTES
    assert frozenset(device_http.DEVICE_HTTP_ROUTES) == private_bridge._PRIVATE_DEVICE_ROUTE_SET  # noqa: SLF001
    runtime, service, command = _admitted()
    assert _post(service, "/file-result-extra", _submission(command["revision_ref"]))["status"] == 404
    assert _post(service, FILE_RESULT_PATH, _submission(command["revision_ref"]))["status"] == 200


def test_route_fails_closed_when_no_store_is_composed() -> None:
    runtime, _service_with_store, command = _admitted()
    clock = _Clock()
    without_store = device_http.LocalAgentBrokerDeviceHttpService(
        state_port=runtime.state_port,
        pepper=PEPPER.encode("utf-8"),
        authority_ref=AUTHORITY_REF,
        rpc_factory=runtime.facade,
        http_state=runtime.http_state,
        material_resolver=runtime.material_store,
        session_open_transaction=runtime._storage.transactionSync,  # noqa: SLF001 - the real seam
        clock=clock,
    )
    refused = _post(without_store, FILE_RESULT_PATH, _submission(command["revision_ref"]))
    assert refused["status"] == 503
    assert refused["body"]["error"]["code"] == "local_agent_file_result_not_configured"
    assert runtime.verified_file_store.has_stored_result(COMMAND_ID) is False
