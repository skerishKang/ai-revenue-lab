"""Language-neutral completed-run contract for the internal Padiem AI Engine."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping, Protocol

from padiem_ai_core import (
    AgentProfile,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntimeError,
    IdempotencyConflictError,
)
from padiem_ai_core.contextual_execution import ContextualExecutionRunner

from app.execution_context_wire import parse_execution_context

EXECUTE_PATH = "/internal/v1/execute"
HEALTH_PATH = "/internal/v1/health"
MAX_REQUEST_BODY_BYTES = 128 * 1024

_TOP_LEVEL_REQUIRED = frozenset({"app_id", "agent", "messages"})
_TOP_LEVEL_ALLOWED = frozenset(
    {"app_id", "agent", "messages", "session_id", "additional_system_context", "trace_id", "execution_context"}
)
_AGENT_REQUIRED = frozenset({"id", "title", "description", "system_instruction", "task_type", "optimize_for", "max_tokens"})
_AGENT_ALLOWED = frozenset({
    "id", "title", "description", "system_instruction", "task_type", "optimize_for", "max_tokens",
    "required_capabilities", "model_policy",
})


class ExecutionRunner(Protocol):
    async def run(self, request: Any) -> ExecutionResult: ...


RuntimeFactory = Callable[[str], ExecutionRunner]


@dataclass(frozen=True, slots=True)
class ServiceResponse:
    status_code: int
    body: Mapping[str, Any]


class ServiceContractError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def _service_error(code: str, message: str, *, status_code: int, retryable: bool = False, metadata: Mapping[str, Any] | None = None) -> ServiceResponse:
    return ServiceResponse(
        status_code=status_code,
        body={
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "retryable": bool(retryable),
                "metadata": dict(metadata) if metadata is not None else None,
            },
        },
    )


def _require_exact_object(value: Any, *, name: str, allowed: frozenset[str], required: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_request", f"{name} must be an object.")
    data = dict(value)
    unknown = set(data) - allowed
    if unknown:
        raise ServiceContractError("invalid_request", f"{name} contains unsupported fields.")
    missing = required - set(data)
    if missing:
        raise ServiceContractError("invalid_request", f"{name} is missing required fields.")
    return data


def _required_capabilities(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ServiceContractError("invalid_request", "agent.required_capabilities must be an array of strings.")
    return tuple(value)


def _model_policy(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_request", "agent.model_policy must be an object.")
    return dict(value)


def _execution_context(value: Any) -> ExecutionContext | None:
    try:
        return parse_execution_context(value)
    except (TypeError, ValueError, OverflowError):
        raise ServiceContractError("invalid_execution_context", "Execution context fields are invalid.") from None


def build_execution_request(payload: Any) -> tuple[str, ExecutionRequest, ExecutionContext | None]:
    data = _require_exact_object(payload, name="request", allowed=_TOP_LEVEL_ALLOWED, required=_TOP_LEVEL_REQUIRED)
    agent_data = _require_exact_object(data["agent"], name="agent", allowed=_AGENT_ALLOWED, required=_AGENT_REQUIRED)

    app_id = data["app_id"]
    context = _execution_context(data.get("execution_context"))
    explicit_trace = data.get("trace_id")
    if context is not None and explicit_trace is not None and explicit_trace != context.trace_id:
        raise ServiceContractError("trace_id_conflict", "trace_id conflicts with execution_context.trace_id.")
    trace_id = context.trace_id if context is not None else explicit_trace

    try:
        agent = AgentProfile(
            id=agent_data["id"],
            title=agent_data["title"],
            description=agent_data["description"],
            system_instruction=agent_data["system_instruction"],
            task_type=agent_data["task_type"],
            optimize_for=agent_data["optimize_for"],
            max_tokens=agent_data["max_tokens"],
            allowed_tools=(),
            required_capabilities=_required_capabilities(agent_data.get("required_capabilities")),
            model_policy=_model_policy(agent_data.get("model_policy")),
            max_steps=1,
        )
        request = ExecutionRequest(
            agent=agent,
            messages=data["messages"],
            session_id=data.get("session_id"),
            additional_system_context=data.get("additional_system_context"),
            trace_id=trace_id,
        )
        AgentProfile(
            id=app_id,
            title="Application",
            description="Application identifier validation.",
            system_instruction="Validation only.",
            task_type="general",
            optimize_for="balanced",
            max_tokens=1,
        )
    except (TypeError, ValueError, OverflowError):
        raise ServiceContractError("invalid_request", "Request fields are invalid for the Padiem AI Core contract.") from None

    return app_id, request, context


def _status_for_runtime_error(exc: ExecutionRuntimeError) -> int:
    if exc.code in {"invalid_execution_request", "invalid_execution_context"}:
        return 400
    if exc.code in {"native_tools_unsupported", "policy_blocked"}:
        return 422
    if exc.code == "execution_timeout":
        return 504
    if exc.code == "upstream_timeout":
        return 504
    if exc.code == "upstream_rate_limited":
        return 503
    return 502


class EngineService:
    """Pure-Python internal request handler over a runtime factory."""

    def __init__(self, *, runtime_factory: RuntimeFactory, b14_service_bound: bool, idempotency_adapter: Any | None = None) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        self._runtime_factory = runtime_factory
        self._b14_service_bound = bool(b14_service_bound)
        self._idempotency_adapter = idempotency_adapter

    def health(self) -> ServiceResponse:
        # Use the single authoritative posture source for health/manifest parity.
        # Local import avoids circular dependency (contract_manifest imports EXECUTE_PATH etc. from this module).
        try:
            from app.contract_manifest import current_engine_contract_manifest, engine_capability_posture  # type: ignore

            posture = engine_capability_posture()
            manifest = current_engine_contract_manifest()
            endpoints = [e.to_public_dict() for e in manifest.endpoints]
        except Exception:
            # Fail-closed: if authoritative posture source is unavailable, do not
            # advertise unproven features as available. Liveness stays ok, but
            # feature readiness must be unavailable/deferred and not expose exception.
            posture = {
                "completed_run": "unavailable",
                "provider_streaming_run": "unavailable",
                "orchestration_run": "unavailable",
                "orchestration_resume": "unavailable",
                "orchestration_cancel": "unavailable",
                "orchestration_stream": "unavailable",
                "idempotency_replay": "unavailable",
                "service_identity_wire_enforcement": "unavailable",
            }
            endpoints = []

        # Backward-compatible booleans derived from bounded posture (do not hide deferred)
        completed_run_bool = posture.get("completed_run") == "available"
        streaming_run_bool = posture.get("provider_streaming_run") == "available"

        body: dict[str, object] = {
            "status": "ok",
            "service": "padiem-ai-engine",
            "core_available": True,
            "b14_service_bound": self._b14_service_bound,
            # backward compat
            "completed_run": completed_run_bool,
            "streaming_run": streaming_run_bool,
            # explicit bounded posture (#1237) — truthful, not boolean-hidden
            "capabilities": posture,
            "service_identity": "required_for_all_non_health_routes",
            "endpoints": endpoints,
        }
        return ServiceResponse(status_code=200, body=body)

    async def execute_payload(self, payload: Any) -> ServiceResponse:
        if not self._b14_service_bound:
            return _service_error("b14_service_unavailable", "Business 14 service binding is unavailable.", status_code=503, retryable=True)

        try:
            app_id, request, context = build_execution_request(payload)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        try:
            runtime = self._runtime_factory(app_id)
            if context is None:
                result = await runtime.run(request)
            else:
                contextual = ContextualExecutionRunner(runtime=runtime, app_id=app_id, idempotency=self._idempotency_adapter)
                result = await contextual.run(request, context=context, request_payload=payload)
        except IdempotencyConflictError:
            return _service_error(
                "idempotency_conflict",
                "Idempotency key is already bound to a different execution request.",
                status_code=409,
            )
        except ValueError:
            return _service_error(
                "execution_context_unavailable",
                "Execution context is unavailable.",
                status_code=422,
            )
        except ExecutionRuntimeError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=_status_for_runtime_error(exc), retryable=exc.retryable, metadata=exc.metadata.to_public_dict())
        except Exception:
            return _service_error("engine_internal_error", "Padiem AI Engine execution failed.", status_code=500)

        if not isinstance(result, ExecutionResult):
            return _service_error("invalid_execution_result", "Padiem AI Engine returned an invalid execution result.", status_code=500)
        return ServiceResponse(status_code=200, body={
            "ok": True,
            "answer": result.answer,
            "route": result.route.to_public_dict(),
            "metadata": result.metadata.to_public_dict(),
        })

    async def handle(self, *, method: str, path: str, content_type: str | None = None, body: bytes = b"") -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path == HEALTH_PATH:
            if normalized_method != "GET":
                return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
            return self.health()
        if path != EXECUTE_PATH:
            return _service_error("not_found", "Internal Engine route not found.", status_code=404)
        if normalized_method != "POST":
            return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
        if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
            return _service_error("unsupported_media_type", "Content-Type must be application/json.", status_code=415)
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error("invalid_request", "Request body is invalid.", status_code=400)
        raw = bytes(body)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            return _service_error("request_too_large", "Request body exceeds the internal Engine safety limit.", status_code=413)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error("invalid_json", "Request body must contain valid UTF-8 JSON.", status_code=400)
        return await self.execute_payload(payload)
