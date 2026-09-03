from __future__ import annotations

import base64
from datetime import datetime, timezone

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade, RPC_NUMERIC_COERCION

NOW = datetime(2026, 9, 3, 14, 30, tzinfo=timezone.utc)
CREDENTIAL = base64.b64encode(b"fail-closed-device-credential").decode("ascii")


def rpc() -> LocalAgentBrokerRpcFacade:
    return LocalAgentBrokerRpcFacade(
        authority=InMemoryLocalAgentBrokerAuthority(
            pepper=b"padiem-broker-rpc-fail-closed-pepper",
            authority_ref="control-plane.local-agent-broker.v1",
        )
    )


def register(service: LocalAgentBrokerRpcFacade) -> None:
    result = service.register_binding({
        "binding_ref": "binding.1",
        "device_id": "device.1",
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "credential_b64": CREDENTIAL,
        "now": NOW.isoformat(),
    })
    assert result["ok"] is True


def test_rpc_does_not_coerce_boolean_or_numeric_text_into_ttl():
    service = rpc()

    boolean_ttl = service.register_binding({
        "binding_ref": "binding.bool",
        "device_id": "device.bool",
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "credential_b64": CREDENTIAL,
        "now": NOW.isoformat(),
        "credential_ttl_seconds": True,
    })
    assert boolean_ttl["ok"] is False
    assert boolean_ttl["error"]["code"] == "invalid_local_agent_broker_ttl"

    numeric_text = service.register_binding({
        "binding_ref": "binding.text",
        "device_id": "device.text",
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "credential_b64": CREDENTIAL,
        "now": NOW.isoformat(),
        "credential_ttl_seconds": "300",
    })
    assert numeric_text["ok"] is False
    assert numeric_text["error"]["code"] == "invalid_local_agent_broker_ttl"


def test_rpc_does_not_coerce_boolean_poll_cursor_or_limit():
    service = rpc()
    register(service)
    opened = service.open_session({
        "session_id": "session.1",
        "binding_ref": "binding.1",
        "credential_b64": CREDENTIAL,
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "now": NOW.isoformat(),
    })
    assert opened["ok"] is True

    bad_cursor = service.poll({
        "session_id": "session.1",
        "binding_ref": "binding.1",
        "credential_b64": CREDENTIAL,
        "after_sequence": True,
        "now": NOW.isoformat(),
    })
    assert bad_cursor["ok"] is False
    assert bad_cursor["error"]["code"] == "invalid_poll_cursor"

    bad_limit = service.poll({
        "session_id": "session.1",
        "binding_ref": "binding.1",
        "credential_b64": CREDENTIAL,
        "after_sequence": 0,
        "limit": "1",
        "now": NOW.isoformat(),
    })
    assert bad_limit["ok"] is False
    assert bad_limit["error"]["code"] == "invalid_poll_limit"


def test_rpc_numeric_coercion_source_truth_is_disabled():
    assert RPC_NUMERIC_COERCION is False
