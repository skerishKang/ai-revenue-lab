from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_http import (
    ACK_ADMISSION_EVIDENCE_EXACT,
    BOUNDED_JSON,
    CLIENT_TIME_AUTHORITY,
    CLOSED_SCHEMA,
    CONTROL_PLANE_BROKER_AUTHORITY_REUSED,
    DEPLOYABLE_HTTP_HANDLER_BOUNDARY,
    DURABLE_STORE_PORT_DEFINED,
    HEARTBEAT_SERVER_LAST_SEEN,
    IN_MEMORY_COUNTS_AS_DURABLE,
    MATERIAL_FINGERPRINT_EXACT,
    POLL_REQUEST_FINGERPRINT_PRESERVED,
    PRODUCTION_ENDPOINT_CONFIGURED,
    PRODUCTION_MUTATION,
    PRODUCTION_READY,
    PUBLIC_UNAUTHENTICATED_ACCESS,
    RAW_DEVICE_CREDENTIAL_LOGGED,
    REPLAY_SEQUENCE_AUTHORITY_DUPLICATED,
    REQUEST_CONTENT_TYPE_JSON_REQUIRED,
    DurableLocalAgentSessionRecord,
    LocalAgentBrokerHttpHandler,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

BASE = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
CREDENTIAL = b"http-handler-device-credential"
FINGERPRINT = "a" * 64


def _encoded(value: bytes = CREDENTIAL) -> str:
    return base64.b64encode(value).decode("ascii")


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _DurableState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        try:
            return self.records[session_id]
        except KeyError as exc:
            raise RuntimeError("session is not present in durable test state") from exc

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _MaterialResolver:
    def __init__(self, *, sequence: int = 1, fingerprint: str = FINGERPRINT) -> None:
        self.sequence = sequence
        self.fingerprint = fingerprint
        self.requests = []

    def resolve(self, request):
        self.requests.append(request)
        return {
            "contract_version": "claw-local-command-material.v1",
            "command_id": request.command_id,
            "binding_ref": request.binding_ref,
            "sequence": self.sequence,
            "request_fingerprint": self.fingerprint,
            "material": {"kind": "deterministic-test-material"},
        }


def _fixture(*, resolver: _MaterialResolver | None = None):
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=b"http-handler-deterministic-pepper",
        authority_ref="control-plane.local-agent-broker.http-test.v1",
    )
    rpc = LocalAgentBrokerRpcFacade(authority=authority)
    registered = rpc.register_binding(
        {
            "binding_ref": "binding.http.1",
            "device_id": "device.http.1",
            "account_ref": "account.http.1",
            "workspace_ref": "workspace.http.1",
            "credential_b64": _encoded(),
            "now": BASE.isoformat(),
        }
    )
    assert registered["ok"] is True
    clock = _Clock(BASE + timedelta(seconds=1))
    state = _DurableState()
    resolver = resolver or _MaterialResolver()
    handler = LocalAgentBrokerHttpHandler(rpc=rpc, state=state, material_resolver=resolver, clock=clock)
    auth = TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.http.1",
        account_ref="account.http.1",
        workspace_ref="workspace.http.1",
        authenticated=True,
        tls_verified=True,
    )
    return authority, rpc, clock, state, resolver, handler, auth


def _request(handler, *, route: str, payload: dict, auth, content_type: str = "application/json"):
    return handler.handle(
        method="POST",
        route=route,
        content_type=content_type,
        body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        auth=auth,
    )


def _session_payload(*, client_now: datetime = BASE + timedelta(hours=4)) -> dict:
    return {
        "session_id": "session.http.1",
        "binding_ref": "binding.http.1",
        "credential_b64": _encoded(),
        "account_ref": "account.http.1",
        "workspace_ref": "workspace.http.1",
        "now": client_now.isoformat(),
        "ttl_seconds": 900,
    }


def test_http_boundary_rejects_missing_auth_tls_and_wrong_content_type() -> None:
    _, _, _, _, _, handler, auth = _fixture()
    payload = _session_payload()

    unauthenticated = _request(handler, route="/session", payload=payload, auth=None)
    assert unauthenticated.status == 401
    assert unauthenticated.body["error"]["code"] == "local_agent_http_auth_required"

    tls_denied = _request(
        handler,
        route="/session",
        payload=payload,
        auth=TrustedLocalAgentHttpAuthContext(
            principal_ref="principal.http.1",
            account_ref="account.http.1",
            workspace_ref="workspace.http.1",
            authenticated=True,
            tls_verified=False,
        ),
    )
    assert tls_denied.status == 403
    assert tls_denied.body["error"]["code"] == "local_agent_http_tls_required"

    wrong_type = _request(handler, route="/session", payload=payload, auth=auth, content_type="text/plain")
    assert wrong_type.status == 415
    assert wrong_type.body["error"]["code"] == "local_agent_http_json_required"

    parameterized_json = _request(
        handler,
        route="/session",
        payload=payload,
        auth=auth,
        content_type="Application/JSON; charset=utf-8",
    )
    assert parameterized_json.status == 200
    assert parameterized_json.body["ok"] is True


def test_http_boundary_rejects_non_json_closed_schema_and_scope_tampering() -> None:
    _, _, _, _, _, handler, auth = _fixture()

    malformed = handler.handle(
        method="POST",
        route="/session",
        content_type="application/json",
        body=b"{not-json",
        auth=auth,
    )
    assert malformed.status == 400

    extra = _session_payload()
    extra["unexpected"] = True
    closed = _request(handler, route="/session", payload=extra, auth=auth)
    assert closed.status == 400
    assert closed.body["error"]["code"] == "local_agent_http_invalid_request"

    wrong_scope = TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.other",
        account_ref="account.other",
        workspace_ref="workspace.http.1",
        authenticated=True,
        tls_verified=True,
    )
    scoped = _request(handler, route="/session", payload=_session_payload(), auth=wrong_scope)
    assert scoped.status == 403
    assert scoped.body["error"]["code"] == "local_agent_http_scope_mismatch"


def test_server_clock_owns_session_heartbeat_and_ack_timestamps() -> None:
    authority, rpc, clock, state, _, handler, auth = _fixture()

    opened = _request(handler, route="/session", payload=_session_payload(client_now=BASE + timedelta(days=2)), auth=auth)
    assert opened.status == 200 and opened.body["ok"] is True
    assert opened.body["session"]["issued_at"] == (BASE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")

    queued = rpc.enqueue_command(
        {
            "command_id": "command.http.1",
            "binding_ref": "binding.http.1",
            "run_id": "run.http.1",
            "tool_request_ref": "tool-request.http.1",
            "request_fingerprint": FINGERPRINT,
            "now": (BASE + timedelta(seconds=2)).isoformat(),
        }
    )
    assert queued["ok"] is True

    clock.now = BASE + timedelta(seconds=3)
    polled = _request(
        handler,
        route="/poll",
        payload={
            "session_id": "session.http.1",
            "binding_ref": "binding.http.1",
            "credential_b64": _encoded(),
            "after_sequence": 0,
            "now": (BASE + timedelta(days=3)).isoformat(),
            "limit": 32,
        },
        auth=auth,
    )
    assert polled.status == 200 and polled.body["ok"] is True
    assert polled.body["commands"][0]["request_fingerprint"] == FINGERPRINT

    clock.now = BASE + timedelta(seconds=4)
    heartbeat = _request(
        handler,
        route="/heartbeat",
        payload={
            "session_id": "session.http.1",
            "binding_ref": "binding.http.1",
            "credential_b64": _encoded(),
            "now": (BASE + timedelta(days=4)).isoformat(),
        },
        auth=auth,
    )
    expected_heartbeat = (BASE + timedelta(seconds=4)).isoformat().replace("+00:00", "Z")
    assert heartbeat.body["heartbeat"]["last_seen_at"] == expected_heartbeat
    assert state.load_session("session.http.1").last_seen_at == clock.now

    admitted = authority.admit_command(
        admission_ref="admission.http.1",
        evidence_ref="evidence.http.1",
        session_id="session.http.1",
        binding_ref="binding.http.1",
        credential=CREDENTIAL,
        command_id="command.http.1",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=5),
    )
    assert admitted.admission_ref == "admission.http.1"

    clock.now = BASE + timedelta(seconds=7)
    acknowledged = _request(
        handler,
        route="/acknowledge",
        payload={
            "session_id": "session.http.1",
            "binding_ref": "binding.http.1",
            "credential_b64": _encoded(),
            "command_id": "command.http.1",
            "admission_ref": "admission.http.1",
            "evidence_ref": "evidence.http.1",
            "now": (BASE + timedelta(days=5)).isoformat(),
        },
        auth=auth,
    )
    assert acknowledged.status == 200 and acknowledged.body["ok"] is True
    assert acknowledged.body["command"]["acknowledged_at"] == (
        BASE + timedelta(seconds=7)
    ).isoformat().replace("+00:00", "Z")


def test_material_resolution_is_bound_to_exact_canonical_fingerprint_and_sequence() -> None:
    for resolver, expected_code in (
        (_MaterialResolver(sequence=1, fingerprint="b" * 64), "local_agent_http_invalid_request"),
        (_MaterialResolver(sequence=2, fingerprint=FINGERPRINT), "local_agent_material_command_not_current"),
    ):
        with __import__("contextlib").nullcontext():
            _, rpc, clock, _, _, handler, auth = _fixture(resolver=resolver)
            opened = _request(handler, route="/session", payload=_session_payload(), auth=auth)
            assert opened.body["ok"] is True
            queued = rpc.enqueue_command(
                {
                    "command_id": "command.http.1",
                    "binding_ref": "binding.http.1",
                    "run_id": "run.http.1",
                    "tool_request_ref": "tool-request.http.1",
                    "request_fingerprint": FINGERPRINT,
                    "now": (BASE + timedelta(seconds=2)).isoformat(),
                }
            )
            assert queued["ok"] is True
            clock.now = BASE + timedelta(seconds=3)
            result = _request(
                handler,
                route="/material",
                payload={
                    "request_ref": "material.http.1",
                    "session_id": "session.http.1",
                    "binding_ref": "binding.http.1",
                    "credential_b64": _encoded(),
                    "command_id": "command.http.1",
                    "request_fingerprint": FINGERPRINT,
                    "now": (BASE + timedelta(hours=3)).isoformat(),
                },
                auth=auth,
            )
            assert result.body["error"]["code"] == expected_code


def test_http_boundary_source_truth_keeps_production_unclaimed() -> None:
    _, _, _, _, _, handler, _ = _fixture()
    safe = handler.safe_dict()
    assert safe["request_content_type"] == "application/json"
    assert DEPLOYABLE_HTTP_HANDLER_BOUNDARY is True
    assert PUBLIC_UNAUTHENTICATED_ACCESS is False
    assert CONTROL_PLANE_BROKER_AUTHORITY_REUSED is True
    assert REPLAY_SEQUENCE_AUTHORITY_DUPLICATED is False
    assert BOUNDED_JSON is True
    assert CLOSED_SCHEMA is True
    assert REQUEST_CONTENT_TYPE_JSON_REQUIRED is True
    assert HEARTBEAT_SERVER_LAST_SEEN is True
    assert POLL_REQUEST_FINGERPRINT_PRESERVED is True
    assert MATERIAL_FINGERPRINT_EXACT is True
    assert ACK_ADMISSION_EVIDENCE_EXACT is True
    assert DURABLE_STORE_PORT_DEFINED is True
    assert IN_MEMORY_COUNTS_AS_DURABLE is False
    assert RAW_DEVICE_CREDENTIAL_LOGGED is False
    assert CLIENT_TIME_AUTHORITY is False
    assert PRODUCTION_ENDPOINT_CONFIGURED is False
    assert PRODUCTION_MUTATION is False
    assert PRODUCTION_READY is False
