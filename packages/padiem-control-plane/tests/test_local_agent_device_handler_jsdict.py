from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json

from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import (
    InMemoryLocalAgentBrokerStatePort,
    StateBackedLocalAgentBrokerAuthority,
)

from local_agent_broker_device_http import LocalAgentBrokerDeviceHttpService

BASE = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.device-handler-jsdict-test.v1"
PEPPER = b"device-handler-jsdict-test-pepper-value"
CREDENTIAL = b"device-handler-jsdict-test-credential-value"


class _DurableMemoryStatePort(InMemoryLocalAgentBrokerStatePort):
    durable = True


class _DurableHttpState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        if record.session_id in self.records:
            raise RuntimeError("duplicate durable HTTP session")
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        try:
            return self.records[session_id]
        except KeyError as exc:
            raise RuntimeError("durable HTTP session not found") from exc

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _UnusedMaterialResolver:
    def resolve(self, request):
        del request
        raise RuntimeError("material resolver is not used by this test")


class _JsDict(dict):
    """Mirror of the dict-subclass (opik JsDict) the RPC boundary returns."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


def _service_fixture():
    state = _DurableMemoryStatePort()
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state,
    )
    authority.register_binding(
        binding_ref="binding.jsdict.1",
        device_id="device.jsdict.1",
        account_ref="account.jsdict.1",
        workspace_ref="workspace.jsdict.1",
        credential=CREDENTIAL,
        now=BASE,
        credential_ttl_seconds=3600,
    )
    http_state = _DurableHttpState()

    def rpc_factory() -> LocalAgentBrokerRpcFacade:
        return LocalAgentBrokerRpcFacade(
            authority=StateBackedLocalAgentBrokerAuthority(
                pepper=PEPPER,
                authority_ref=AUTHORITY_REF,
                state_port=state,
            )
        )

    service = LocalAgentBrokerDeviceHttpService(
        state_port=state,
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        rpc_factory=rpc_factory,
        http_state=http_state,
        material_resolver=_UnusedMaterialResolver(),
        clock=lambda: BASE + timedelta(seconds=10),
    )
    return state, authority, http_state, service


def _session_body(*, session_id: str) -> bytes:
    return json.dumps(
        {
            "session_id": session_id,
            "binding_ref": "binding.jsdict.1",
            "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
            "account_ref": "account.jsdict.1",
            "workspace_ref": "workspace.jsdict.1",
            "now": BASE.isoformat(),
            "ttl_seconds": 900,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _jsdict_envelope(body: bytes, *, route: str = "/session") -> _JsDict:
    envelope = {
        "method": "POST",
        "route": route,
        "content_type": "application/json",
        "body_b64": base64.b64encode(body).decode("ascii"),
        "tls_verified": True,
    }
    return _JsDict(envelope)


def test_jsdict_envelope_is_accepted_and_auth_path_returns_401_not_400() -> None:
    _, _, http_state, service = _service_fixture()
    envelope = _jsdict_envelope(json.dumps({}).encode("utf-8"))

    result = service.handle(envelope)

    assert type(envelope) is _JsDict
    assert result["status"] == 401
    assert result["body"] == {
        "ok": False,
        "error": {
            "code": "local_agent_http_auth_required",
            "message": "authenticated Local Agent broker access is required",
        },
    }
    assert http_state.records == {}


def test_jsdict_envelope_with_valid_credential_returns_200() -> None:
    _, _, http_state, service = _service_fixture()
    envelope = _jsdict_envelope(_session_body(session_id="session.jsdict.1"))

    result = service.handle(envelope)

    assert result["status"] == 200
    assert result["body"]["ok"] is True
    assert result["body"]["session"]["account_ref"] == "account.jsdict.1"
    assert "session.jsdict.1" in http_state.records


def test_key_set_strictness_is_preserved_for_jsdict_envelopes() -> None:
    _, _, _, service = _service_fixture()
    missing_key = _jsdict_envelope(_session_body(session_id="session.jsdict.2"))
    del missing_key["tls_verified"]

    result = service.handle(missing_key)

    assert result["status"] == 400
    assert result["body"]["ok"] is False
    assert result["body"]["error"]["code"] == "local_agent_edge_invalid_envelope"


def test_extra_key_jsdict_envelope_is_still_rejected() -> None:
    _, _, _, service = _service_fixture()
    extra_key = _jsdict_envelope(_session_body(session_id="session.jsdict.3"))
    extra_key["injected"] = True

    result = service.handle(extra_key)

    assert result["status"] == 400
    assert result["body"]["ok"] is False
    assert result["body"]["error"]["code"] == "local_agent_edge_invalid_envelope"
