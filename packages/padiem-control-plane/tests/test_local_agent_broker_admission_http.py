from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_admission_http import (
    CANONICAL_BROKER_ADMISSION_REUSED,
    CLIENT_ADMISSION_AUTHORITY,
    PHYSICAL_ADMISSION_HTTP_BOUNDARY,
    PRODUCTION_MUTATION,
    PRODUCTION_READY,
    RAW_ADMISSION_ARGV,
    RAW_ADMISSION_DEVICE_CREDENTIAL,
    SERVER_ADMISSION_TIME_AUTHORITY,
    SERVER_OWNED_ADMISSION_REFS,
    AdmissionEnabledLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade


BASE = datetime(2026, 9, 4, 2, 20, tzinfo=timezone.utc)
CREDENTIAL = b"admission-http-device-credential"
FINGERPRINT = "a" * 64


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _State:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        return self.records[session_id]

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        changed = self.records[session_id].with_last_seen(seen_at)
        self.records[session_id] = changed
        return changed


class _UnusedMaterialResolver:
    def resolve(self, request):
        raise AssertionError(f"material resolver must not be called during admission: {request!r}")


class _References:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> tuple[str, str]:
        self.calls += 1
        return (f"admission_server_{self.calls}", f"evidence_server_{self.calls}")


def _body(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _fixture():
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=b"admission-http-control-plane-pepper",
        authority_ref="control-plane.local-agent-broker.admission-http.v1",
    )
    authority.register_binding(
        binding_ref="binding.admission.1",
        device_id="device.admission.1",
        account_ref="account.admission.1",
        workspace_ref="workspace.admission.1",
        credential=CREDENTIAL,
        now=BASE,
    )
    authority.enqueue_command(
        command_id="command.admission.1",
        binding_ref="binding.admission.1",
        run_id="run.admission.1",
        tool_request_ref="tool-request.admission.1",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=1),
    )
    clock = _Clock(BASE + timedelta(seconds=2))
    references = _References()
    handler = AdmissionEnabledLocalAgentBrokerHttpHandler(
        rpc=LocalAgentBrokerRpcFacade(authority=authority),
        state=_State(),
        material_resolver=_UnusedMaterialResolver(),
        clock=clock,
        admission_reference_factory=references,
    )
    auth = TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.admission.1",
        account_ref="account.admission.1",
        workspace_ref="workspace.admission.1",
        authenticated=True,
        tls_verified=True,
    )
    session_payload = {
        "session_id": "session.admission.1",
        "binding_ref": "binding.admission.1",
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
        "account_ref": "account.admission.1",
        "workspace_ref": "workspace.admission.1",
        "now": (BASE + timedelta(seconds=2)).isoformat(),
        "ttl_seconds": 900,
    }
    opened = handler.handle(
        method="POST",
        route="/session",
        content_type="application/json",
        body=_body(session_payload),
        auth=auth,
    )
    assert opened.status == 200 and opened.body["ok"] is True
    return authority, handler, auth, clock, references


def _admission_payload() -> dict:
    return {
        "session_id": "session.admission.1",
        "binding_ref": "binding.admission.1",
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
        "command_id": "command.admission.1",
        "request_fingerprint": FINGERPRINT,
        "now": (BASE + timedelta(seconds=3)).isoformat(),
    }


def test_admission_refs_and_time_are_server_owned_and_projection_is_bounded() -> None:
    _authority, handler, auth, clock, references = _fixture()
    clock.now = BASE + timedelta(seconds=5)
    response = handler.handle(
        method="POST",
        route="/admission",
        content_type="application/json; charset=utf-8",
        body=_body(_admission_payload()),
        auth=auth,
    )
    assert response.status == 200
    assert response.body["ok"] is True
    admission = response.body["admission"]
    assert admission["admission_ref"] == "admission_server_1"
    assert admission["evidence_ref"] == "evidence_server_1"
    assert admission["authority_ref"] == "control-plane.local-agent-broker.admission-http.v1"
    assert admission["command_id"] == "command.admission.1"
    assert admission["session_id"] == "session.admission.1"
    assert admission["binding_ref"] == "binding.admission.1"
    assert admission["request_fingerprint"] == FINGERPRINT
    assert datetime.fromisoformat(admission["accepted_at"].replace("Z", "+00:00")) == clock.now
    assert admission["raw_argv"] is False
    assert admission["raw_device_credential"] is False
    assert references.calls == 1


def test_client_cannot_mint_admission_or_evidence_refs() -> None:
    _authority, handler, auth, clock, references = _fixture()
    clock.now = BASE + timedelta(seconds=5)
    payload = _admission_payload()
    payload["admission_ref"] = "client_admission"
    payload["evidence_ref"] = "client_evidence"
    response = handler.handle(
        method="POST",
        route="/admission",
        content_type="application/json",
        body=_body(payload),
        auth=auth,
    )
    assert response.status == 400
    assert response.body["ok"] is False
    assert references.calls == 0


def test_admission_requires_auth_tls_and_exact_fingerprint() -> None:
    _authority, handler, auth, clock, references = _fixture()
    clock.now = BASE + timedelta(seconds=5)
    no_auth = handler.handle(
        method="POST",
        route="/admission",
        content_type="application/json",
        body=_body(_admission_payload()),
        auth=None,
    )
    assert no_auth.status == 401
    assert references.calls == 0

    no_tls = TrustedLocalAgentHttpAuthContext(
        principal_ref=auth.principal_ref,
        account_ref=auth.account_ref,
        workspace_ref=auth.workspace_ref,
        authenticated=True,
        tls_verified=False,
    )
    denied = handler.handle(
        method="POST",
        route="/admission",
        content_type="application/json",
        body=_body(_admission_payload()),
        auth=no_tls,
    )
    assert denied.status == 403
    assert references.calls == 0

    wrong = _admission_payload()
    wrong["request_fingerprint"] = "b" * 64
    mismatch = handler.handle(
        method="POST",
        route="/admission",
        content_type="application/json",
        body=_body(wrong),
        auth=auth,
    )
    assert mismatch.status == 200
    assert mismatch.body["ok"] is False
    assert references.calls == 1


def test_existing_routes_are_delegated_without_semantic_change() -> None:
    _authority, handler, auth, clock, references = _fixture()
    clock.now = BASE + timedelta(seconds=4)
    poll = handler.handle(
        method="POST",
        route="/poll",
        content_type="application/json",
        body=_body(
            {
                "session_id": "session.admission.1",
                "binding_ref": "binding.admission.1",
                "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
                "after_sequence": 0,
                "now": clock.now.isoformat(),
                "limit": 1,
            }
        ),
        auth=auth,
    )
    assert poll.status == 200
    assert poll.body["ok"] is True
    assert poll.body["commands"][0]["state"] == "queued"
    assert references.calls == 0


def test_admission_boundary_truth_flags_keep_production_nonclaims() -> None:
    assert PHYSICAL_ADMISSION_HTTP_BOUNDARY is True
    assert SERVER_OWNED_ADMISSION_REFS is True
    assert CLIENT_ADMISSION_AUTHORITY is False
    assert CANONICAL_BROKER_ADMISSION_REUSED is True
    assert SERVER_ADMISSION_TIME_AUTHORITY is True
    assert RAW_ADMISSION_ARGV is False
    assert RAW_ADMISSION_DEVICE_CREDENTIAL is False
    assert PRODUCTION_MUTATION is False
    assert PRODUCTION_READY is False
