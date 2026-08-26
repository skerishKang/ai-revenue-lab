from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
import time
from types import MappingProxyType
from typing import Any, Protocol
import uuid

from .b14_execution import (
    B14ChatRequest,
    B14ExecutionError,
    B14ExecutionResult,
    B14RouteMetadata,
    B14RoutingOptions,
)
from .contracts import (
    AgentProfile,
    ErrorClass,
    RunMetadata,
    RunStatus,
    UsageMetadata,
)

MAX_EXECUTION_MESSAGES = 99
MAX_EXECUTION_MESSAGE_CHARS = 32_000
MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS = 16_000
MAX_COMPOSED_SYSTEM_CHARS = 32_000

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MESSAGE_ROLES = frozenset({"user", "assistant"})
_MODEL_POLICY_FIELDS = frozenset(
    {
        "model",
        "temperature",
        "allow_external_fallback",
        "provider_order",
        "max_attempts",
    }
)


class B14Executor(Protocol):
    async def execute(self, request: B14ChatRequest) -> B14ExecutionResult: ...


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty safe identifier")
    return value


def _normalize_messages(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, str], ...]:
    if isinstance(messages, (str, bytes)):
        raise ValueError("messages must be a sequence of message objects")
    items = tuple(messages)
    if not 1 <= len(items) <= MAX_EXECUTION_MESSAGES:
        raise ValueError(
            f"messages must contain 1 to {MAX_EXECUTION_MESSAGES} items"
        )

    normalized: list[Mapping[str, str]] = []
    for index, message in enumerate(items):
        if not isinstance(message, Mapping):
            raise ValueError(f"messages[{index}] must be a mapping")
        if set(message) != {"role", "content"}:
            raise ValueError(
                f"messages[{index}] must contain only role and content"
            )
        role = message.get("role")
        if role not in _MESSAGE_ROLES:
            raise ValueError(
                f"messages[{index}].role must be user or assistant"
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(
                f"messages[{index}].content must be a non-empty string"
            )
        text = content.strip()
        if len(text) > MAX_EXECUTION_MESSAGE_CHARS:
            raise ValueError(
                f"messages[{index}].content must not exceed "
                f"{MAX_EXECUTION_MESSAGE_CHARS} characters"
            )
        normalized.append(MappingProxyType({"role": role, "content": text}))
    return tuple(normalized)


def _normalize_additional_system_context(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("additional_system_context must be a string or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS:
        raise ValueError(
            "additional_system_context exceeds the bounded context limit"
        )
    return text


def _compose_system_instruction(request: "ExecutionRequest") -> str:
    parts = [request.agent.system_instruction]
    if request.additional_system_context is not None:
        parts.append(request.additional_system_context)
    content = "\n\n".join(parts)
    if len(content) > MAX_COMPOSED_SYSTEM_CHARS:
        raise ValueError("composed system instruction exceeds B14 message limit")
    return content


def _normalize_model_policy(
    agent: AgentProfile,
) -> tuple[str, float, B14RoutingOptions]:
    policy = agent.model_policy
    unknown = set(policy) - _MODEL_POLICY_FIELDS
    if unknown:
        raise ValueError(
            "unsupported model_policy fields: " + ", ".join(sorted(unknown))
        )

    model = policy.get("model", "b14/auto")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model_policy.model must be a non-empty string")

    temperature = policy.get("temperature", 0.2)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise ValueError("model_policy.temperature must be numeric")

    provider_order_value = policy.get("provider_order")
    if provider_order_value is None:
        provider_order = None
    elif isinstance(provider_order_value, (tuple, list)):
        provider_order = tuple(provider_order_value)
    else:
        raise ValueError("model_policy.provider_order must be a sequence")

    allow_external_fallback = policy.get("allow_external_fallback")
    max_attempts = policy.get("max_attempts")

    routing = B14RoutingOptions(
        task_type=agent.task_type,
        required_capabilities=(
            agent.required_capabilities if agent.required_capabilities else None
        ),
        optimize_for=agent.optimize_for,
        allow_external_fallback=allow_external_fallback,
        provider_order=provider_order,
        max_attempts=max_attempts,
    )
    return model.strip(), float(temperature), routing


def _error_class_for_b14(code: str) -> ErrorClass:
    if code == "upstream_timeout":
        return ErrorClass.PROVIDER_TIMEOUT
    if code == "upstream_rate_limited":
        return ErrorClass.PROVIDER_RATE_LIMIT
    if code == "upstream_auth_error":
        return ErrorClass.AUTH_ERROR
    if code in {
        "malformed_upstream",
        "empty_upstream_answer",
        "upstream_response_too_large",
    }:
        return ErrorClass.PROVIDER_BAD_RESPONSE
    if code == "upstream_request_error":
        return ErrorClass.INPUT_ERROR
    return ErrorClass.INTERNAL_ERROR


def _safe_message_for_b14(code: str) -> str:
    messages = {
        "upstream_timeout": "Model execution timed out.",
        "upstream_rate_limited": "Model execution is temporarily rate limited.",
        "upstream_auth_error": "Model execution authorization failed.",
        "upstream_request_error": "Model execution request was rejected.",
        "upstream_server_error": "Model execution service failed.",
        "upstream_unavailable": "Model execution service is unavailable.",
        "upstream_response_too_large": "Model execution response exceeded the safety limit.",
        "malformed_upstream": "Model execution returned an invalid response.",
        "empty_upstream_answer": "Model execution returned no usable answer.",
    }
    return messages.get(code, "Model execution failed.")


def _selected_model(route: B14RouteMetadata) -> str | None:
    return route.actual_response_model or route.selected_model


def _selected_provider(route: B14RouteMetadata) -> str | None:
    provider = route.selected_provider
    if provider is None or not _IDENTIFIER_RE.fullmatch(provider):
        return None
    return provider


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    agent: AgentProfile
    messages: tuple[Mapping[str, str], ...]
    session_id: str | None = None
    additional_system_context: str | None = None
    trace_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.agent, AgentProfile):
            raise ValueError("agent must be AgentProfile")
        object.__setattr__(self, "messages", _normalize_messages(self.messages))
        if self.session_id is not None:
            object.__setattr__(
                self,
                "session_id",
                _safe_identifier("session_id", self.session_id),
            )
        object.__setattr__(
            self,
            "additional_system_context",
            _normalize_additional_system_context(self.additional_system_context),
        )
        if self.trace_id is not None:
            object.__setattr__(
                self,
                "trace_id",
                _safe_identifier("trace_id", self.trace_id),
            )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    answer: str
    route: B14RouteMetadata
    metadata: RunMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.answer, str) or not self.answer.strip():
            raise ValueError("answer must be a non-empty string")
        object.__setattr__(self, "answer", self.answer.strip())
        if not isinstance(self.route, B14RouteMetadata):
            raise ValueError("route must be B14RouteMetadata")
        if not isinstance(self.metadata, RunMetadata):
            raise ValueError("metadata must be RunMetadata")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "route": self.route.to_public_dict(),
            "metadata": self.metadata.to_public_dict(),
        }


class ExecutionRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        metadata: RunMetadata,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.code = _safe_identifier("error code", code)
        self.safe_message = safe_message
        self.metadata = metadata
        self.retryable = bool(retryable)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.safe_message,
            "retryable": self.retryable,
            "metadata": self.metadata.to_public_dict(),
        }


class ExecutionRuntime:
    def __init__(
        self,
        *,
        app_id: str,
        b14_client: B14Executor,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._app_id = _safe_identifier("app_id", app_id)
        execute = getattr(b14_client, "execute", None)
        if not callable(execute):
            raise ValueError("b14_client must expose async execute(request)")
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._b14_client = b14_client
        self._clock = clock

    @property
    def app_id(self) -> str:
        return self._app_id

    def _trace_id(self, request: ExecutionRequest) -> str:
        return request.trace_id or f"run_{uuid.uuid4().hex[:24]}"

    def _duration_ms(self, started_at: float) -> int:
        elapsed = self._clock() - started_at
        return max(0, int(round(elapsed * 1000)))

    def _metadata(
        self,
        *,
        request: ExecutionRequest,
        trace_id: str,
        status: RunStatus,
        duration_ms: int,
        result: B14ExecutionResult | None = None,
        error_class: ErrorClass | None = None,
    ) -> RunMetadata:
        route = result.route if result is not None else B14RouteMetadata()
        return RunMetadata(
            trace_id=trace_id,
            app_id=self._app_id,
            agent_id=request.agent.id,
            session_id=request.session_id,
            status=status,
            provider=_selected_provider(route),
            model=_selected_model(route),
            duration_ms=duration_ms,
            usage=result.usage if result is not None else UsageMetadata(),
            error_class=error_class,
        )

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        if not isinstance(request, ExecutionRequest):
            raise ValueError("request must be ExecutionRequest")

        started_at = self._clock()
        trace_id = self._trace_id(request)

        if request.agent.allowed_tools:
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.POLICY_BLOCKED,
                duration_ms=self._duration_ms(started_at),
                error_class=ErrorClass.POLICY_BLOCKED,
            )
            raise ExecutionRuntimeError(
                "native_tools_unsupported",
                "Model-native tool execution is not available in the current B14 contract.",
                metadata=metadata,
            )

        try:
            system_instruction = _compose_system_instruction(request)
            model, temperature, routing = _normalize_model_policy(request.agent)
            b14_request = B14ChatRequest(
                messages=(
                    {"role": "system", "content": system_instruction},
                    *request.messages,
                ),
                model=model,
                temperature=temperature,
                max_tokens=request.agent.max_tokens,
                routing=routing,
            )
        except ValueError:
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.REJECTED,
                duration_ms=self._duration_ms(started_at),
                error_class=ErrorClass.INPUT_ERROR,
            )
            raise ExecutionRuntimeError(
                "invalid_execution_request",
                "Execution request or agent model policy is invalid.",
                metadata=metadata,
            ) from None

        try:
            result = await self._b14_client.execute(b14_request)
        except B14ExecutionError as exc:
            error_class = _error_class_for_b14(exc.code)
            status = (
                RunStatus.TIMEOUT
                if error_class is ErrorClass.PROVIDER_TIMEOUT
                else RunStatus.FAILED
            )
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=status,
                duration_ms=self._duration_ms(started_at),
                error_class=error_class,
            )
            raise ExecutionRuntimeError(
                exc.code,
                _safe_message_for_b14(exc.code),
                metadata=metadata,
                retryable=exc.retryable,
            ) from None
        except Exception:
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.FAILED,
                duration_ms=self._duration_ms(started_at),
                error_class=ErrorClass.INTERNAL_ERROR,
            )
            raise ExecutionRuntimeError(
                "execution_failed",
                "Model execution failed.",
                metadata=metadata,
            ) from None

        if not isinstance(result, B14ExecutionResult):
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.FAILED,
                duration_ms=self._duration_ms(started_at),
                error_class=ErrorClass.INTERNAL_ERROR,
            )
            raise ExecutionRuntimeError(
                "invalid_execution_result",
                "Model execution returned an invalid result contract.",
                metadata=metadata,
            )

        metadata = self._metadata(
            request=request,
            trace_id=trace_id,
            status=RunStatus.COMPLETED,
            duration_ms=self._duration_ms(started_at),
            result=result,
        )
        return ExecutionResult(
            answer=result.answer,
            route=result.route,
            metadata=metadata,
        )
