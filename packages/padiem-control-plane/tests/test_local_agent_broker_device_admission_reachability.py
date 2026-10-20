"""#5080 — a real device can obtain its server-owned admission references.

The Android 1.0.1 report was concrete: the phone could poll, resolve material and
build the exact acknowledgement, but had nowhere to read ``admission_ref`` and
``evidence_ref`` from, while ``/acknowledge`` refuses any acknowledgement that
does not echo the references the Broker stored. Those two references are minted by
the server-owned admission transition, which existed only on the inner handler and
was therefore refused by the outer private edge before it ever ran.

This test starts at the outermost deployed boundary — ``handle_private_device_fetch``
— and walks one canonical command through the exact order the contract pins:
session, poll, material, admission, acknowledge. Everything under test is the real
composition: the private bridge, the canonical device service, the server-owned
reference factory, the M2e handler, the state-backed serialized broker.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import (
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

BASE = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
PEPPER = b"device-admission-reachability-pepper"
CREDENTIAL = b"device-admission-reachability-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.5080.admission.v1"
BINDING_REF = "binding.android.5080"
DEVICE_ID = "device.android.5080"
ACCOUNT_REF = "account.android.5080"
WORKSPACE_REF = "workspace.android.5080"
SESSION_ID = "session.android.5080"
COMMAND_TTL_SECONDS = 300
REQUEST_ID = "andreq-5080"


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


if "workers" not in sys.modules:
    _fake_workers = types.ModuleType("workers")
    _fake_workers.Response = _FakeResponse
    _fake_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
    _fake_workers.DurableObject = _FakeDurableObject
    sys.modules["workers"] = _fake_workers

import local_agent_broker_device_http as device_http  # noqa: E402
import local_agent_broker_private_http_bridge as private_bridge  # noqa: E402
from padiem_control_plane.local_agent_broker_admission_http import (  # noqa: E402
    ADMISSION_DEVICE_ROUTE,
    server_owned_admission_references,
)


class _Clock:
    def __init__(self) -> None:
        self.now = BASE

    def __call__(self) -> datetime:
        return self.now


class _SerializedStatePort(SerializedLocalAgentBrokerStatePort):
    def __init__(self) -> None:
        super().__init__(backend=InMemorySerializedLocalAgentBrokerStateBackend())


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


class _MaterialResolver:
    """The durable command-material port, keyed exactly like the real store."""

    def __init__(self) -> None:
        self._wires: dict[str, dict] = {}
        self.calls: list[str] = []

    def register(self, wire: dict) -> None:
        self._wires[wire["command_id"]] = wire

    def resolve(self, request: Any) -> dict:
        self.calls.append(request.command_id)
        wire = self._wires.get(request.command_id)
        if wire is None:
            raise AssertionError("material may only be resolved for a registered command")
        return wire


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class _PrivateRequest:
    def __init__(self, *, path: str, body: bytes) -> None:
        self.url = f"https://broker.internal{path}"
        self.method = "POST"
        self.headers = {"content-type": "application/json"}
        self.body = self._stream(body)

    @staticmethod
    async def _stream(body: bytes):
        yield body


class _Stub:
    def __init__(self, service) -> None:
        self._service = service
        self.routes: list[str] = []

    async def handle_device_http(self, envelope: dict) -> dict:
        self.routes.append(envelope["route"])
        return self._service.handle(envelope)


def _fixture(**service_kwargs: Any):
    clock = _Clock()
    http_state = _HttpSessionState()
    state_port = _SerializedStatePort()
    material = _MaterialResolver()
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER, authority_ref=AUTHORITY_REF, state_port=state_port
    )
    authority.register_binding(
        binding_ref=BINDING_REF,
        device_id=DEVICE_ID,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        credential=CREDENTIAL,
        now=BASE,
        credential_ttl_seconds=3600,
    )

    def rpc_factory() -> LocalAgentBrokerRpcFacade:
        return LocalAgentBrokerRpcFacade(
            authority=StateBackedLocalAgentBrokerAuthority(
                pepper=PEPPER, authority_ref=AUTHORITY_REF, state_port=state_port
            )
        )

    service = device_http.LocalAgentBrokerDeviceHttpService(
        state_port=state_port,
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        rpc_factory=rpc_factory,
        http_state=http_state,
        material_resolver=material,
        session_open_transaction=lambda operation: operation(),
        clock=clock,
        **service_kwargs,
    )
    return clock, authority, state_port, material, _Stub(service)


def _post(stub, path: str, payload: dict) -> dict:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    response = asyncio.run(
        private_bridge.handle_private_device_fetch(_PrivateRequest(path=path, body=body), lambda: stub)
    )
    try:
        decoded = json.loads(response.body)
    except (TypeError, ValueError):
        decoded = {"raw": response.body}
    return {"status": response.status, "body": decoded}


def _device_body(**fields: Any) -> dict:
    body = {
        "session_id": SESSION_ID,
        "binding_ref": BINDING_REF,
        "credential_b64": _encoded(CREDENTIAL),
        "now": BASE.isoformat(),
    }
    body.update(fields)
    return body


def _open_session(stub, clock) -> None:
    clock.now = BASE + timedelta(seconds=5)
    opened = _post(stub, "/session", _device_body(
        account_ref=ACCOUNT_REF, workspace_ref=WORKSPACE_REF, ttl_seconds=900,
    ))
    assert opened["status"] == 200, opened
    assert opened["body"]["ok"] is True


def _enqueue(authority, material, clock, *, command_id: str, fingerprint: str) -> None:
    command = authority.enqueue_command(
        command_id=command_id,
        binding_ref=BINDING_REF,
        run_id=f"run.{command_id}",
        tool_request_ref=f"tool.{command_id}",
        request_fingerprint=fingerprint,
        now=clock.now + timedelta(seconds=1),
        ttl_seconds=COMMAND_TTL_SECONDS,
    )
    material.register({
        "contract_version": "claw-local-command-material.v2",
        "command_id": command.command_id,
        "binding_ref": BINDING_REF,
        "sequence": command.sequence,
        "request_fingerprint": fingerprint,
        "revision_ref": command.revision_ref,
        "material": {
            "request_id": REQUEST_ID,
            "run_id": command.run_id,
            "device_id": DEVICE_ID,
            "root_ref": "safroot-documents",
            "argv": [],
        },
    })


def test_admission_is_reachable_and_delivers_the_references_acknowledge_requires() -> None:
    fingerprint = "b" * 64
    clock, authority, state_port, material, stub = _fixture()
    _open_session(stub, clock)
    _enqueue(authority, material, clock, command_id="andcmd-5080-1", fingerprint=fingerprint)

    clock.now = BASE + timedelta(seconds=10)
    polled = _post(stub, "/poll", _device_body(after_sequence=0, limit=8))
    assert polled["status"] == 200 and polled["body"]["ok"] is True
    command = polled["body"]["commands"][0]
    assert command["state"] == "queued"
    # The queued projection carries no admission evidence: that is precisely the
    # reference a device cannot invent.
    assert command["admission_ref"] is None and command["evidence_ref"] is None

    materialled = _post(stub, "/material", _device_body(
        request_ref="andmat-5080-1",
        command_id=command["command_id"],
        request_fingerprint=fingerprint,
    ))
    assert materialled["status"] == 200 and materialled["body"]["ok"] is True
    assert materialled["body"]["material"]["material"]["request_id"] == REQUEST_ID

    admitted = _post(stub, ADMISSION_DEVICE_ROUTE, _device_body(
        command_id=command["command_id"],
        request_fingerprint=fingerprint,
        request_id=REQUEST_ID,
    ))
    assert admitted["status"] == 200, admitted
    assert admitted["body"]["ok"] is True, admitted["body"]
    admission = admitted["body"]["admission"]
    assert admission["command_id"] == command["command_id"]
    assert admission["request_id"] == REQUEST_ID
    assert admission["sequence"] == command["sequence"]
    assert admission["revision_ref"] == command["revision_ref"]
    assert admission["authority_ref"] == AUTHORITY_REF
    assert admission["raw_argv"] is False and admission["raw_device_credential"] is False
    assert admission["admission_ref"] != admission["evidence_ref"]
    for value in (admission["admission_ref"], admission["evidence_ref"]):
        assert isinstance(value, str) and value and len(value) <= 256

    acknowledged = _post(stub, "/acknowledge", _device_body(
        command_id=command["command_id"],
        admission_ref=admission["admission_ref"],
        evidence_ref=admission["evidence_ref"],
        revision_ref=admission["revision_ref"],
        request_id=admission["request_id"],
        termination="exited",
        exit_code=0,
    ))
    assert acknowledged["status"] == 200, acknowledged
    assert acknowledged["body"]["ok"] is True, acknowledged["body"]
    assert acknowledged["body"]["command"]["state"] == "acknowledged"

    stored = state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands[0]
    assert stored.state.value == "acknowledged"
    assert stored.admission_ref == admission["admission_ref"]
    assert stored.evidence_ref == admission["evidence_ref"]
    # The route list is the single source of reachability for both edges.
    assert stub.routes == ["/session", "/poll", "/material", ADMISSION_DEVICE_ROUTE, "/acknowledge"]
    assert ADMISSION_DEVICE_ROUTE in device_http.DEVICE_HTTP_ROUTES
    assert ADMISSION_DEVICE_ROUTE in private_bridge._PRIVATE_DEVICE_ROUTE_SET


def test_admission_request_cannot_supply_its_own_references() -> None:
    fingerprint = "c" * 64
    clock, authority, state_port, material, stub = _fixture()
    _open_session(stub, clock)
    _enqueue(authority, material, clock, command_id="andcmd-5080-2", fingerprint=fingerprint)
    clock.now = BASE + timedelta(seconds=10)
    polled = _post(stub, "/poll", _device_body(after_sequence=0, limit=8))
    command = polled["body"]["commands"][0]

    forged = _post(stub, ADMISSION_DEVICE_ROUTE, _device_body(
        command_id=command["command_id"],
        request_fingerprint=fingerprint,
        request_id=REQUEST_ID,
        admission_ref="admission.device.chosen",
        evidence_ref="evidence.device.chosen",
    ))
    assert forged["status"] == 400, forged
    assert forged["body"]["error"]["code"] == "local_agent_http_invalid_request"
    # A refused forged admission leaves the canonical command untouched: the
    # closed request schema is the guard, not a later correction.
    stored = state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands[0]
    assert stored.state.value == "queued"
    assert stored.admission_ref is None and stored.evidence_ref is None
    assert stub.routes == ["/session", "/poll", ADMISSION_DEVICE_ROUTE]


def test_admission_references_are_distinct_per_command() -> None:
    clock, authority, _, material, stub = _fixture(
        admission_reference_factory=server_owned_admission_references
    )
    _open_session(stub, clock)
    first = "d" * 64
    second = "e" * 64
    _enqueue(authority, material, clock, command_id="andcmd-5080-3", fingerprint=first)
    _enqueue(authority, material, clock, command_id="andcmd-5080-4", fingerprint=second)

    clock.now = BASE + timedelta(seconds=20)
    references = []
    for command_id, fingerprint in (("andcmd-5080-3", first), ("andcmd-5080-4", second)):
        admitted = _post(stub, ADMISSION_DEVICE_ROUTE, _device_body(
            command_id=command_id, request_fingerprint=fingerprint, request_id=REQUEST_ID,
        ))
        assert admitted["status"] == 200 and admitted["body"]["ok"] is True, admitted
        references.append((
            admitted["body"]["admission"]["admission_ref"],
            admitted["body"]["admission"]["evidence_ref"],
        ))
    assert len(set(references[0] + references[1])) == 4


if __name__ == "__main__":
    pytest.main([__file__])
