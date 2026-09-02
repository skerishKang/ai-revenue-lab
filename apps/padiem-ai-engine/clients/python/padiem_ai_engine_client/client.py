"""Trusted first-party Python client for Padiem AI Engine v1.

This module is Engine-owned transport code. Product/browser layers must not copy
its wire contract or mint approval authority. The caller identity/credential is
server-owned and every request is sent only through an injected internal
transport (normally a Cloudflare Service Binding adapter).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Protocol

ENGINE_INTERNAL_ORIGIN = "https://padiem-ai-engine.internal"
ENGINE_CONTRACT_MAJOR = 1
ENGINE_CONTRACT_VERSION = "1.0"
ENGINE_EXECUTE_PATH = "/internal/v1/execute"
ENGINE_HEALTH_PATH = "/internal/v1/health"
ENGINE_ORCHESTRATE_PATH = "/internal/v1/orchestrate"
ENGINE_ORCHESTRATE_RESUME_PATH = "/internal/v1/orchestrate/resume"
ENGINE_ORCHESTRATE_CANCEL_PATH = "/internal/v1/orchestrate/cancel"

_ENGINE_CALLER_HEADER = "X-Padiem-Engine-Caller"
_ENGINE_CREDENTIAL_HEADER = "X-Padiem-Engine-Credential"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_CONTINUATION_RE = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")

_EXECUTION_ALLOWED = frozenset(
    {
        "agent",
        "messages",
        "session_id",
        "additional_system_context",
        "trace_id",
        "execution_context",
    }
)
_ORCHESTRATION_ALLOWED = _EXECUTION_ALLOWED | frozenset(
    {
        "subject_id",
        "agent_plan",
        "recovery_policy",
        "max_retries",
        "require_evidence",
        "require_verification",
    }
)
_ORCHESTRATION_RESUME_ALLOWED = _EXECUTION_ALLOWED | frozenset(
    {
        "continuation_ref",
        "decision",
        "subject_id",
        "agent_plan",
        "recovery_policy",
        "max_retries",
    }
)
_DEFERRED_AUTHORITY_FIELDS = frozenset(
    {
        "agent_definition",
        "compiled_agent_profile",
        "tool_authorization",
        "tool_runtime",
        "tool_arguments",
        "pause",
    }
)
_DECISION_FIELDS = frozenset(
    {"decision_id", "pause_id", "outcome", "authority_ref", "evidence_ref", "decided_at"}
)
_CANCEL_ALLOWED = frozenset({"continuation_ref", "reason"})

ORCHESTRATION_FIELD_PARITY = MappingProxyType(
    {
        "app_id": "CLIENT_OWNED_AND_INJECTED",
        "agent": "SUPPORTED_AND_MAPPED",
        "messages": "SUPPORTED_AND_MAPPED",
        "session_id": "SUPPORTED_AND_MAPPED",
        "additional_system_context": "SUPPORTED_AND_MAPPED",
        "trace_id": "SUPPORTED_AND_MAPPED",
        "execution_context": "SUPPORTED_AND_MAPPED",
        "subject_id": "SUPPORTED_AND_MAPPED",
        "agent_plan": "SUPPORTED_AND_MAPPED",
        "recovery_policy": "SUPPORTED_AND_MAPPED",
        "max_retries": "SUPPORTED_AND_MAPPED",
        "require_evidence": "SUPPORTED_AND_MAPPED",
        "require_verification": "SUPPORTED_AND_MAPPED",
        "continuation_ref": "RESUME_ONLY_SUPPORTED_AND_MAPPED",
        "decision": "RESUME_ONLY_SUPPORTED_AND_MAPPED",
        "reason": "CANCEL_ONLY_SUPPORTED_AND_MAPPED",
        "agent_definition": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "compiled_agent_profile": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "tool_authorization": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "tool_runtime": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "tool_arguments": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "pause": "UNSUPPORTED_AND_NOT_EXPOSED",
    }
)


class PadiemAiEngineClientError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = bool(retryable)
        self.metadata = dict(metadata) if isinstance(metadata, Mapping) else None


@dataclass(frozen=True, slots=True)
class EngineTransportResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int) or not 100 <= self.status <= 599:
            raise ValueError("status must be an HTTP status integer")
        if not isinstance(self.body, bytes):
            raise ValueError("body must be bytes")
        if not isinstance(self.headers, Mapping):
            raise ValueError("headers must be a mapping")


class EngineTransport(Protocol):
    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> EngineTransportResponse: ...


def _safe_identifier(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise PadiemAiEngineClientError(
            "invalid_client_configuration",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _credential(value: Any) -> str:
    if not isinstance(value, str) or not 32 <= len(value.encode("utf-8")) <= 512:
        raise PadiemAiEngineClientError(
            "invalid_client_configuration",
            "credential must contain 32 to 512 bytes",
        )
    return value


def _transport(value: Any) -> EngineTransport:
    if value is None or not callable(getattr(value, "request", None)):
        raise PadiemAiEngineClientError(
            "invalid_engine_transport",
            "Engine transport must provide async request()",
        )
    return value


def _execution_context(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "execution_context must be an object"
        )
    data = dict(value)
    allowed = {"trace_id", "idempotency_key", "timeout_seconds"}
    if set(data) - allowed:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "execution_context contains unsupported fields"
        )
    if "trace_id" not in data:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "execution_context.trace_id is required"
        )
    normalized: dict[str, Any] = {
        "trace_id": _safe_identifier("execution_context.trace_id", data["trace_id"])
    }
    if "idempotency_key" in data:
        key = data["idempotency_key"]
        if not isinstance(key, str) or not _IDEMPOTENCY_RE.fullmatch(key):
            raise PadiemAiEngineClientError(
                "invalid_engine_request",
                "execution_context.idempotency_key must be a bounded safe identifier",
            )
        normalized["idempotency_key"] = key
    if "timeout_seconds" in data:
        timeout = data["timeout_seconds"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 1 <= float(timeout) <= 60
        ):
            raise PadiemAiEngineClientError(
                "invalid_engine_request",
                "execution_context.timeout_seconds must be between 1 and 60",
            )
        normalized["timeout_seconds"] = timeout
    return normalized


def _decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PadiemAiEngineClientError("invalid_engine_request", "decision must be an object")
    data = dict(value)
    if set(data) != _DECISION_FIELDS:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "decision must contain the exact trusted decision fields"
        )
    for name in ("decision_id", "pause_id", "authority_ref", "evidence_ref"):
        _safe_identifier(f"decision.{name}", data[name])
    if data["outcome"] not in {"approved", "denied"}:
        raise PadiemAiEngineClientError("invalid_engine_request", "decision.outcome is invalid")
    decided_at = data["decided_at"]
    if not isinstance(decided_at, str):
        raise PadiemAiEngineClientError("invalid_engine_request", "decision.decided_at is invalid")
    try:
        parsed = datetime.fromisoformat(decided_at)
    except ValueError:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "decision.decided_at is invalid"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "decision.decided_at must be timezone-aware"
        )
    return data


def _run_payload(app_id: str, request: Any, *, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PadiemAiEngineClientError("invalid_engine_request", "Engine request must be an object")
    data = dict(request)
    if set(data) & _DEFERRED_AUTHORITY_FIELDS:
        raise PadiemAiEngineClientError(
            "unsupported_orchestration_field",
            "Engine authority-bearing fields are not client-supplied in this contract version",
        )
    if set(data) - allowed:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine request contains unsupported fields"
        )
    if "agent" not in data or "messages" not in data:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine request requires agent and messages"
        )
    payload: dict[str, Any] = {"app_id": app_id, "agent": data["agent"], "messages": data["messages"]}
    for name in (
        "session_id",
        "additional_system_context",
        "trace_id",
        "subject_id",
        "agent_plan",
        "recovery_policy",
        "max_retries",
        "require_evidence",
        "require_verification",
        "continuation_ref",
    ):
        if name in data:
            payload[name] = data[name]
    if "execution_context" in data:
        payload["execution_context"] = _execution_context(data["execution_context"])
    if "decision" in data:
        payload["decision"] = _decision(data["decision"])
    return payload


def _cancel_payload(app_id: str, request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PadiemAiEngineClientError("invalid_engine_request", "Engine cancel request must be an object")
    data = dict(request)
    if set(data) - _CANCEL_ALLOWED:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine cancel request contains unsupported fields"
        )
    ref = data.get("continuation_ref")
    if not isinstance(ref, str) or not _CONTINUATION_RE.fullmatch(ref):
        raise PadiemAiEngineClientError("invalid_engine_request", "continuation_ref is required")
    payload = {"app_id": app_id, "continuation_ref": ref}
    if "reason" in data:
        reason = data["reason"]
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise PadiemAiEngineClientError(
                "invalid_engine_request", "cancel reason must be a bounded non-empty string"
            )
        payload["reason"] = reason
    return payload


def _json_body(response: EngineTransportResponse) -> dict[str, Any]:
    try:
        body = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PadiemAiEngineClientError(
            "invalid_engine_response",
            "Engine returned an invalid JSON response",
            status=response.status,
        ) from None
    if not isinstance(body, dict):
        raise PadiemAiEngineClientError(
            "invalid_engine_response", "Engine returned an invalid response object", status=response.status
        )
    if body.get("ok") is False:
        error = body.get("error") if isinstance(body.get("error"), Mapping) else {}
        raise PadiemAiEngineClientError(
            error.get("code") if isinstance(error.get("code"), str) else "engine_request_failed",
            error.get("message") if isinstance(error.get("message"), str) else "Padiem AI Engine request failed",
            status=response.status,
            retryable=error.get("retryable") is True,
            metadata=error.get("metadata") if isinstance(error.get("metadata"), Mapping) else None,
        )
    if not 200 <= response.status < 300:
        raise PadiemAiEngineClientError(
            "engine_http_error", "Padiem AI Engine request failed", status=response.status
        )
    return body


class PadiemAiEngineClient:
    def __init__(self, *, transport: EngineTransport, app_id: str, caller_id: str, credential: str) -> None:
        self._transport = _transport(transport)
        self.app_id = _safe_identifier("app_id", app_id)
        self.caller_id = _safe_identifier("caller_id", caller_id)
        self._credential = _credential(credential)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            _ENGINE_CALLER_HEADER: self.caller_id,
            _ENGINE_CREDENTIAL_HEADER: self._credential,
        }

    async def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = await self._transport.request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{path}",
            headers=self._headers(),
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
        )
        return _json_body(response)

    async def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = await self._post(
            ENGINE_EXECUTE_PATH,
            _run_payload(self.app_id, request, allowed=_EXECUTION_ALLOWED),
        )
        if body.get("ok") is not True or not isinstance(body.get("answer"), str):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine completed-run response is invalid"
            )
        return body

    async def orchestrate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = await self._post(
            ENGINE_ORCHESTRATE_PATH,
            _run_payload(self.app_id, request, allowed=_ORCHESTRATION_ALLOWED),
        )
        orchestration = body.get("orchestration")
        if body.get("ok") is not True or not isinstance(orchestration, Mapping):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine orchestration response is invalid"
            )
        return dict(orchestration)

    async def resume_orchestration(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = await self._post(
            ENGINE_ORCHESTRATE_RESUME_PATH,
            _run_payload(self.app_id, request, allowed=_ORCHESTRATION_RESUME_ALLOWED),
        )
        orchestration = body.get("orchestration")
        if body.get("ok") is not True or not isinstance(orchestration, Mapping):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine orchestration resume response is invalid"
            )
        return dict(orchestration)

    async def cancel_orchestration_pause(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return await self._post(
            ENGINE_ORCHESTRATE_CANCEL_PATH,
            _cancel_payload(self.app_id, request),
        )

    async def health(self) -> dict[str, Any]:
        response = await self._transport.request(
            method="GET",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_HEALTH_PATH}",
            headers={},
            body=None,
        )
        return _json_body(response)
