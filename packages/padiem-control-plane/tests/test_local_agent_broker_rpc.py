from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_rpc import (
    DURABLE_BROKER_PERSISTENCE_CONFIGURED,
    PUBLIC_HTTP_AUTHENTICATION_IMPLEMENTED,
    RAW_DEVICE_CREDENTIAL_RETURNED,
    STRUCTURED_CLONE_SAFE_LOCAL_AGENT_BROKER_RPC,
    LocalAgentBrokerRpcFacade,
)

NOW = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
PEPPER = b"padiem-local-agent-broker-rpc-test-pepper"
CREDENTIAL = b"rpc-device-credential"
FINGERPRINT = "a" * 64


def encoded(value: bytes = CREDENTIAL) -> str:
    return base64.b64encode(value).decode("ascii")


def facade() -> LocalAgentBrokerRpcFacade:
    return LocalAgentBrokerRpcFacade(
        authority=InMemoryLocalAgentBrokerAuthority(
            pepper=PEPPER,
            authority_ref="control-plane.local-agent-broker.v1",
        )
    )


def register_payload() -> dict:
    return {
        "binding_ref": "binding.1",
        "device_id": "device.1",
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "credential_b64": encoded(),
        "now": NOW.isoformat(),
    }


def test_rpc_full_broker_lifecycle_never_returns_raw_credential():
    rpc = facade()
    registered = rpc.register_binding(register_payload())
    assert registered["ok"] is True
    assert registered["binding"]["raw_device_credential"] is False
    assert CREDENTIAL.decode() not in repr(registered)

    opened = rpc.open_session({
        "session_id": "session.1",
        "binding_ref": "binding.1",
        "credential_b64": encoded(),
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "now": (NOW + timedelta(seconds=1)).isoformat(),
    })
    assert opened["ok"] is True
    assert opened["session"]["credential_generation"] == 1
    assert CREDENTIAL.decode() not in repr(opened)

    queued = rpc.enqueue_command({
        "command_id": "command.1",
        "binding_ref": "binding.1",
        "run_id": "run.1",
        "tool_request_ref": "tool-request.1",
        "request_fingerprint": FINGERPRINT,
        "now": (NOW + timedelta(seconds=2)).isoformat(),
    })
    assert queued["ok"] is True
    assert queued["command"]["sequence"] == 1
    assert queued["command"]["credential_generation"] == 1
    assert queued["command"]["raw_argv"] is False

    polled = rpc.poll({
        "session_id": "session.1",
        "binding_ref": "binding.1",
        "credential_b64": encoded(),
        "after_sequence": 0,
        "now": (NOW + timedelta(seconds=3)).isoformat(),
    })
    assert polled["ok"] is True
    assert [item["command_id"] for item in polled["commands"]] == ["command.1"]
    assert CREDENTIAL.decode() not in repr(polled)

    admitted = rpc.admit_command({
        "admission_ref": "admission.1",
        "evidence_ref": "evidence.1",
        "session_id": "session.1",
        "binding_ref": "binding.1",
        "credential_b64": encoded(),
        "command_id": "command.1",
        "request_fingerprint": FINGERPRINT,
        "now": (NOW + timedelta(seconds=4)).isoformat(),
    })
    assert admitted["ok"] is True
    assert admitted["admission"]["authority_ref"] == "control-plane.local-agent-broker.v1"
    assert admitted["admission"]["request_fingerprint"] == FINGERPRINT
    assert admitted["admission"]["raw_argv"] is False

    acknowledged = rpc.acknowledge({
        "session_id": "session.1",
        "binding_ref": "binding.1",
        "credential_b64": encoded(),
        "command_id": "command.1",
        "admission_ref": "admission.1",
        "evidence_ref": "evidence.1",
        "now": (NOW + timedelta(seconds=5)).isoformat(),
    })
    assert acknowledged["ok"] is True
    assert acknowledged["command"]["state"] == "acknowledged"
    assert CREDENTIAL.decode() not in repr(acknowledged)


def test_rpc_malformed_credential_is_bounded_error_and_not_echoed():
    rpc = facade()
    payload = register_payload()
    payload["credential_b64"] = "%%%not-base64%%%"

    result = rpc.register_binding(payload)
    assert result == {
        "ok": False,
        "error": {
            "code": "invalid_local_agent_broker_rpc_payload",
            "message": "credential_b64 is invalid",
        },
    }
    assert "%%%not-base64%%%" not in repr(result)


def test_rpc_wrong_credential_returns_safe_core_error():
    rpc = facade()
    assert rpc.register_binding(register_payload())["ok"] is True

    result = rpc.open_session({
        "session_id": "session.bad",
        "binding_ref": "binding.1",
        "credential_b64": encoded(b"wrong-device-credential"),
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "now": (NOW + timedelta(seconds=1)).isoformat(),
    })
    assert result == {
        "ok": False,
        "error": {
            "code": "invalid_device_credential",
            "message": "device credential is invalid",
        },
    }


def test_rpc_rotation_invalidates_old_generation_delivery():
    rpc = facade()
    assert rpc.register_binding(register_payload())["ok"] is True
    assert rpc.open_session({
        "session_id": "session.1",
        "binding_ref": "binding.1",
        "credential_b64": encoded(),
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "now": (NOW + timedelta(seconds=1)).isoformat(),
    })["ok"] is True
    assert rpc.enqueue_command({
        "command_id": "command.old",
        "binding_ref": "binding.1",
        "run_id": "run.1",
        "tool_request_ref": "tool-request.old",
        "request_fingerprint": FINGERPRINT,
        "now": (NOW + timedelta(seconds=2)).isoformat(),
    })["ok"] is True

    new_credential = b"rotated-rpc-device-credential"
    rotated = rpc.rotate_credential({
        "binding_ref": "binding.1",
        "expected_generation": 1,
        "new_credential_b64": encoded(new_credential),
        "now": (NOW + timedelta(seconds=10)).isoformat(),
    })
    assert rotated["ok"] is True
    assert rotated["binding"]["credential_generation"] == 2

    assert rpc.open_session({
        "session_id": "session.2",
        "binding_ref": "binding.1",
        "credential_b64": encoded(new_credential),
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "now": (NOW + timedelta(seconds=11)).isoformat(),
    })["ok"] is True

    polled = rpc.poll({
        "session_id": "session.2",
        "binding_ref": "binding.1",
        "credential_b64": encoded(new_credential),
        "after_sequence": 0,
        "now": (NOW + timedelta(seconds=12)).isoformat(),
    })
    assert polled == {"ok": True, "commands": []}

    stale = rpc.admit_command({
        "admission_ref": "admission.old",
        "evidence_ref": "evidence.old",
        "session_id": "session.2",
        "binding_ref": "binding.1",
        "credential_b64": encoded(new_credential),
        "command_id": "command.old",
        "request_fingerprint": FINGERPRINT,
        "now": (NOW + timedelta(seconds=12)).isoformat(),
    })
    assert stale["ok"] is False
    assert stale["error"]["code"] == "stale_broker_command_generation"


def test_rpc_source_truth_constants_keep_live_network_and_persistence_unconfigured():
    assert STRUCTURED_CLONE_SAFE_LOCAL_AGENT_BROKER_RPC is True
    assert PUBLIC_HTTP_AUTHENTICATION_IMPLEMENTED is False
    assert DURABLE_BROKER_PERSISTENCE_CONFIGURED is False
    assert RAW_DEVICE_CREDENTIAL_RETURNED is False
