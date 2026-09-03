from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Callable

from .contracts import ControlPlaneContractError
from .local_agent_broker import InMemoryLocalAgentBrokerAuthority


def _dt(value: str) -> datetime:
    if not isinstance(value, str):
        raise ControlPlaneContractError("invalid_local_agent_broker_rpc_payload", "timestamp must be ISO-8601 text")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlPlaneContractError("invalid_local_agent_broker_rpc_payload", "timestamp must be valid ISO-8601 text") from exc


def _credential(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ControlPlaneContractError("invalid_local_agent_broker_rpc_payload", "credential_b64 must be non-empty text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ControlPlaneContractError("invalid_local_agent_broker_rpc_payload", "credential_b64 is invalid") from exc
    if not decoded:
        raise ControlPlaneContractError("invalid_local_agent_broker_rpc_payload", "credential_b64 must decode to non-empty bytes")
    return decoded


class LocalAgentBrokerRpcFacade:
    """Structured-clone-safe facade over the Control Plane Local Agent broker core.

    The facade does not authenticate a public HTTP caller and does not own
    persistence. A future deployed adapter must provide a durable authority
    instance and its own network authentication before invoking this facade.
    Numeric values are passed through unchanged so the canonical core, rather
    than RPC coercion, remains the sole type/range validator.
    """

    def __init__(self, *, authority: InMemoryLocalAgentBrokerAuthority) -> None:
        if not isinstance(authority, InMemoryLocalAgentBrokerAuthority):
            raise ValueError("authority must be InMemoryLocalAgentBrokerAuthority")
        self._authority = authority

    def _call(self, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": exc.safe_message}}
        except (KeyError, TypeError, ValueError):
            return {
                "ok": False,
                "error": {
                    "code": "invalid_local_agent_broker_rpc_payload",
                    "message": "Local Agent broker RPC payload is invalid",
                },
            }

    def register_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            binding = self._authority.register_binding(
                binding_ref=payload["binding_ref"],
                device_id=payload["device_id"],
                account_ref=payload["account_ref"],
                workspace_ref=payload["workspace_ref"],
                credential=_credential(payload["credential_b64"]),
                now=_dt(payload["now"]),
                credential_ttl_seconds=payload.get("credential_ttl_seconds", 2_592_000),
            )
            return {"ok": True, "binding": binding.safe_dict()}

        return self._call(operation)

    def rotate_credential(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            binding = self._authority.rotate_credential(
                payload["binding_ref"],
                expected_generation=payload["expected_generation"],
                new_credential=_credential(payload["new_credential_b64"]),
                now=_dt(payload["now"]),
                credential_ttl_seconds=payload.get("credential_ttl_seconds", 2_592_000),
            )
            return {"ok": True, "binding": binding.safe_dict()}

        return self._call(operation)

    def revoke_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            binding = self._authority.revoke_binding(payload["binding_ref"], now=_dt(payload["now"]))
            return {"ok": True, "binding": binding.safe_dict()}

        return self._call(operation)

    def open_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            session = self._authority.open_session(
                session_id=payload["session_id"],
                binding_ref=payload["binding_ref"],
                credential=_credential(payload["credential_b64"]),
                account_ref=payload["account_ref"],
                workspace_ref=payload["workspace_ref"],
                now=_dt(payload["now"]),
                ttl_seconds=payload.get("ttl_seconds", 900),
            )
            return {"ok": True, "session": session.safe_dict()}

        return self._call(operation)

    def enqueue_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            command = self._authority.enqueue_command(
                command_id=payload["command_id"],
                binding_ref=payload["binding_ref"],
                run_id=payload["run_id"],
                tool_request_ref=payload["tool_request_ref"],
                request_fingerprint=payload["request_fingerprint"],
                now=_dt(payload["now"]),
                ttl_seconds=payload.get("ttl_seconds", 300),
            )
            return {"ok": True, "command": command.safe_dict()}

        return self._call(operation)

    def poll(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            commands = self._authority.poll(
                session_id=payload["session_id"],
                binding_ref=payload["binding_ref"],
                credential=_credential(payload["credential_b64"]),
                after_sequence=payload.get("after_sequence", 0),
                now=_dt(payload["now"]),
                limit=payload.get("limit", 32),
            )
            return {"ok": True, "commands": [item.safe_dict() for item in commands]}

        return self._call(operation)

    def admit_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            admission = self._authority.admit_command(
                admission_ref=payload["admission_ref"],
                evidence_ref=payload["evidence_ref"],
                session_id=payload["session_id"],
                binding_ref=payload["binding_ref"],
                credential=_credential(payload["credential_b64"]),
                command_id=payload["command_id"],
                request_fingerprint=payload["request_fingerprint"],
                now=_dt(payload["now"]),
            )
            return {"ok": True, "admission": admission.to_public_dict()}

        return self._call(operation)

    def acknowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            command = self._authority.acknowledge(
                session_id=payload["session_id"],
                binding_ref=payload["binding_ref"],
                credential=_credential(payload["credential_b64"]),
                command_id=payload["command_id"],
                admission_ref=payload["admission_ref"],
                evidence_ref=payload["evidence_ref"],
                now=_dt(payload["now"]),
            )
            return {"ok": True, "command": command.safe_dict()}

        return self._call(operation)


STRUCTURED_CLONE_SAFE_LOCAL_AGENT_BROKER_RPC = True
RPC_NUMERIC_COERCION = False
PUBLIC_HTTP_AUTHENTICATION_IMPLEMENTED = False
DURABLE_BROKER_PERSISTENCE_CONFIGURED = False
RAW_DEVICE_CREDENTIAL_RETURNED = False
