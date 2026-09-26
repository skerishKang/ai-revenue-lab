"""#3128 — the `/reconcile` recovery route is reachable through the real private edge.

CENTRAL blocked #3131 because the route existed only on the inner HTTP handler:
a genuine private Service Binding request to `/reconcile` was rejected by the
outer device service before it ever reached that handler. This test starts at the
outermost boundary — `handle_private_device_fetch` — and drives the whole
reconciliation through it, so reachability is proven where the deployed path
actually is rather than asserted as a constant.

Everything under test is real: the private bridge, the canonical device service,
the #3129 transactional session open, the M2e HTTP handler, the state-backed
canonical broker over its serialized wire state, and the #3121 reconciliation.
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

from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    LocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import (
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

BASE = datetime(2026, 9, 27, 6, 0, tzinfo=timezone.utc)
PEPPER = b"device-route-reachability-pepper"
CREDENTIAL = b"device-route-reachability-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.3128.routes.v1"
BINDING_REF = "binding.routes.1"
DEVICE_ID = "device.routes.1"
ACCOUNT_REF = "account.routes.1"
WORKSPACE_REF = "workspace.routes.1"
COMMAND_TTL_SECONDS = 300
FINGERPRINT = "a" * 64
ADMISSION_REF = "admission.routes.1"
EVIDENCE_REF = "evidence.routes.1"


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


# The private bridge is deployed worker code, so `workers` exists in production
# but not under pytest. Installing the shim before the import is what lets this
# test exercise the bridge itself rather than a copy of its logic.
if "workers" not in sys.modules:
    _fake_workers = types.ModuleType("workers")
    _fake_workers.Response = _FakeResponse
    _fake_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
    _fake_workers.DurableObject = _FakeDurableObject
    sys.modules["workers"] = _fake_workers

import local_agent_broker_device_http as device_http  # noqa: E402
import local_agent_broker_private_http_bridge as private_bridge  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.now = BASE

    def __call__(self) -> datetime:
        return self.now


class _SerializedStatePort(SerializedLocalAgentBrokerStatePort):
    """The deployable durable state port over the serialized wire codec."""

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


class _UnusedMaterialResolver:
    def resolve(self, request: Any) -> dict:
        raise AssertionError("reconciliation must not resolve command material")


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class _PrivateRequest:
    """One real private Service Binding request shape."""

    def __init__(self, *, path: str, body: bytes, method: str = "POST", scheme: str = "https") -> None:
        self.url = f"{scheme}://broker.internal{path}"
        self.method = method
        self.headers = {"content-type": "application/json"}
        self.body = self._stream(body)

    @staticmethod
    async def _stream(body: bytes):
        yield body


class _Stub:
    """The DO stub the private bridge calls, delegating to the canonical service."""

    def __init__(self, service) -> None:
        self._service = service
        self.envelopes: list[dict] = []

    async def handle_device_http(self, envelope: dict) -> dict:
        self.envelopes.append(envelope)
        return self._service.handle(envelope)


def _service(state_port, clock, http_state) -> Any:
    def rpc_factory() -> LocalAgentBrokerRpcFacade:
        return LocalAgentBrokerRpcFacade(
            authority=StateBackedLocalAgentBrokerAuthority(
                pepper=PEPPER,
                authority_ref=AUTHORITY_REF,
                state_port=state_port,
            )
        )

    return device_http.LocalAgentBrokerDeviceHttpService(
        state_port=state_port,
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        rpc_factory=rpc_factory,
        http_state=http_state,
        material_resolver=_UnusedMaterialResolver(),
        session_open_transaction=lambda operation: operation(),
        clock=clock,
    )


def _post(stub, path: str, payload: dict) -> dict:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    response = asyncio.run(
        private_bridge.handle_private_device_fetch(
            _PrivateRequest(path=path, body=body),
            lambda: stub,
        )
    )
    try:
        body = json.loads(response.body)
    except (TypeError, ValueError):
        # The outer edge answers an unrouted path with a plain-text 404.
        body = {"raw": response.body}
    return {"status": response.status, "body": body}


def test_reconcile_route_reaches_canonical_reconciliation_through_the_private_edge() -> None:
    clock = _Clock()
    http_state = _HttpSessionState()
    state_port = _SerializedStatePort()
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
    service = _service(state_port, clock, http_state)
    stub = _Stub(service)

    # 1) A real device session, opened through the private edge.
    clock.now = BASE + timedelta(seconds=5)
    opened = _post(
        stub,
        "/session",
        {
            "session_id": "session.routes.1",
            "binding_ref": BINDING_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "now": BASE.isoformat(),
            "ttl_seconds": 900,
        },
    )
    assert opened["status"] == 200
    assert opened["body"]["ok"] is True
    session_id = opened["body"]["session"]["session_id"]

    # 2) A canonical admitted command that was never acknowledged.
    authority.enqueue_command(
        command_id="command.routes.1",
        binding_ref=BINDING_REF,
        run_id="run.routes.1",
        tool_request_ref="tool.routes.1",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=6),
        ttl_seconds=COMMAND_TTL_SECONDS,
    )
    admission = authority.admit_command(
        admission_ref=ADMISSION_REF,
        evidence_ref=EVIDENCE_REF,
        session_id=session_id,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id="command.routes.1",
        request_fingerprint=FINGERPRINT,
        request_id="request.routes.1",
        now=BASE + timedelta(seconds=7),
    )
    assert admission.admission_ref == ADMISSION_REF

    # 3) The hard deadline passes: the acknowledgement path is closed, so the
    #    reconciliation is the only remaining exit.
    clock.now = BASE + timedelta(seconds=COMMAND_TTL_SECONDS + 10)
    reconciled = _post(
        stub,
        "/reconcile",
        {
            "session_id": session_id,
            "binding_ref": BINDING_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "command_id": "command.routes.1",
            "admission_ref": ADMISSION_REF,
            "evidence_ref": EVIDENCE_REF,
            "revision_ref": admission.revision_ref,
            "request_id": admission.request_id,
            "request_fingerprint": FINGERPRINT,
            "termination": "exited",
            "exit_code": 0,
            "now": BASE.isoformat(),
        },
    )

    assert reconciled["status"] == 200
    assert reconciled["body"]["ok"] is True
    command = reconciled["body"]["command"]
    assert command["state"] == "acknowledged"
    assert command["termination"] == "exited"
    assert command["exit_code"] == 0
    assert command["evidence_ref"] == EVIDENCE_REF
    assert [envelope["route"] for envelope in stub.envelopes] == ["/session", "/reconcile"]

    # The canonical broker, not the edge, owns the state change.
    stored = state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands[0]
    assert stored.state.value == "acknowledged"
    assert stored.termination == "exited"
    assert stored.exit_code == 0

    # 4) The route is reachable because it is in the one canonical list, not
    #    because a second list was added: the bridge derives from the service.
    assert frozenset(device_http.DEVICE_HTTP_ROUTES) == private_bridge._PRIVATE_DEVICE_ROUTE_SET
    assert private_bridge._PRIVATE_DEVICE_ROUTE_SET == frozenset(
        {
            "/session",
            "/poll",
            "/material",
            "/heartbeat",
            "/acknowledge",
            "/reconcile",
        }
    )
    assert len(set(device_http.DEVICE_HTTP_ROUTES)) == len(device_http.DEVICE_HTTP_ROUTES)


def test_unknown_routes_stay_fail_closed_at_the_private_edge() -> None:
    clock = _Clock()
    http_state = _HttpSessionState()
    state_port = _SerializedStatePort()
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
    stub = _Stub(_service(state_port, clock, http_state))

    for path in ("/reconcile_all", "/replay", "/execute", "/register_binding"):
        refused = _post(stub, path, {})
        assert refused["status"] == 404, path
    assert stub.envelopes == []

    # Non-POST and non-HTTPS stay closed too.
    get = asyncio.run(
        private_bridge.handle_private_device_fetch(
            _PrivateRequest(path="/reconcile", body=b"{}", method="GET"), lambda: stub
        )
    )
    assert get.status == 405

    plain = asyncio.run(
        private_bridge.handle_private_device_fetch(
            _PrivateRequest(path="/reconcile", body=b"{}", scheme="http"),
            lambda: stub,
        )
    )
    assert plain.status == 403
    assert stub.envelopes == []


def test_reconcile_before_the_deadline_still_refuses_at_the_private_edge() -> None:
    clock = _Clock()
    http_state = _HttpSessionState()
    state_port = _SerializedStatePort()
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
    service = _service(state_port, clock, http_state)
    stub = _Stub(service)

    clock.now = BASE + timedelta(seconds=5)
    opened = _post(
        stub,
        "/session",
        {
            "session_id": "session.routes.early",
            "binding_ref": BINDING_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "now": BASE.isoformat(),
            "ttl_seconds": 900,
        },
    )
    session_id = opened["body"]["session"]["session_id"]
    authority.enqueue_command(
        command_id="command.routes.early",
        binding_ref=BINDING_REF,
        run_id="run.routes.1",
        tool_request_ref="tool.routes.early",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=6),
        ttl_seconds=COMMAND_TTL_SECONDS,
    )
    admission = authority.admit_command(
        admission_ref="admission.routes.early",
        evidence_ref="evidence.routes.early",
        session_id=session_id,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id="command.routes.early",
        request_fingerprint=FINGERPRINT,
        request_id="request.routes.early",
        now=BASE + timedelta(seconds=7),
    )

    clock.now = BASE + timedelta(seconds=20)
    refused = _post(
        stub,
        "/reconcile",
        {
            "session_id": session_id,
            "binding_ref": BINDING_REF,
            "credential_b64": _encoded(CREDENTIAL),
            "command_id": "command.routes.early",
            "admission_ref": "admission.routes.early",
            "evidence_ref": "evidence.routes.early",
            "revision_ref": admission.revision_ref,
            "request_id": admission.request_id,
            "request_fingerprint": FINGERPRINT,
            "termination": "exited",
            "exit_code": 0,
            "now": BASE.isoformat(),
        },
    )
    assert refused["status"] == 200
    assert refused["body"]["ok"] is False
    assert refused["body"]["error"]["code"] == "broker_command_not_expired"
    # Still admitted: an early reconciliation never invents a terminal fact.
    assert state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands[0].state.value == "admitted"


if __name__ == "__main__":
    pytest.main([__file__])
