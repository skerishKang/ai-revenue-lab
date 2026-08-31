from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .b14_execution import B14ExecutionError, B14ExecutionResult
from .b14_multimodal import B14MultimodalChatRequest, _normalize_messages as _normalize_b14_messages
from .contracts import AgentProfile, ErrorClass, RunStatus
from .execution_runtime import (
    MAX_EXECUTION_MESSAGES,
    ExecutionResult,
    ExecutionRuntime,
    ExecutionRuntimeError,
    _compose_system_instruction,
    _error_class_for_b14,
    _normalize_additional_system_context,
    _normalize_model_policy,
    _safe_identifier,
    _safe_message_for_b14,
)


def _normalize_multimodal_messages(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(messages, (str, bytes)):
        raise ValueError("messages must be a sequence of message objects")
    items = tuple(messages)
    if not 1 <= len(items) <= MAX_EXECUTION_MESSAGES:
        raise ValueError(
            f"messages must contain 1 to {MAX_EXECUTION_MESSAGES} items"
        )

    normalized, _ = _normalize_b14_messages(items)
    image_count = 0
    safe_messages: list[Mapping[str, Any]] = []
    for index, message in enumerate(normalized):
        role = message["role"]
        if role not in {"user", "assistant"}:
            raise ValueError(
                f"messages[{index}].role must be user or assistant"
            )
        content = message["content"]
        if not isinstance(content, str):
            image_count += sum(
                1 for part in content if part["type"] == "image_url"
            )
        safe_messages.append(
            MappingProxyType({"role": role, "content": content})
        )

    if image_count != 1:
        raise ValueError("multimodal execution requires exactly one image")
    return tuple(safe_messages)


@dataclass(frozen=True, slots=True)
class MultimodalExecutionRequest:
    """Product-neutral non-streaming execution request with one image.

    The product owns attachment UX and creates the existing B14-compatible
    multimodal message parts. Core owns system-instruction composition,
    model/routing policy normalization, execution metadata and safe errors.
    """

    agent: AgentProfile
    messages: tuple[Mapping[str, Any], ...]
    session_id: str | None = None
    additional_system_context: str | None = None
    trace_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.agent, AgentProfile):
            raise ValueError("agent must be AgentProfile")
        object.__setattr__(
            self,
            "messages",
            _normalize_multimodal_messages(self.messages),
        )
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


class MultimodalExecutionRuntime(ExecutionRuntime):
    """Higher-level Core facade for the existing bounded B14 image contract."""

    async def run(self, request: MultimodalExecutionRequest) -> ExecutionResult:
        if not isinstance(request, MultimodalExecutionRequest):
            raise ValueError("request must be MultimodalExecutionRequest")

        started_at = self._clock
        # Keep one timestamp source and the exact ExecutionRuntime metadata shape.
        started_value = started_at()
        trace_id = self._trace_id(request)  # type: ignore[arg-type]

        if request.agent.allowed_tools:
            metadata = self._metadata(  # type: ignore[arg-type]
                request=request,
                trace_id=trace_id,
                status=RunStatus.POLICY_BLOCKED,
                duration_ms=self._duration_ms(started_value),
                error_class=ErrorClass.POLICY_BLOCKED,
            )
            raise ExecutionRuntimeError(
                "native_tools_unsupported",
                "Model-native tool execution is not available in the current B14 contract.",
                metadata=metadata,
            )

        try:
            system_instruction = _compose_system_instruction(request)  # type: ignore[arg-type]
            model, temperature, routing = _normalize_model_policy(request.agent)
            b14_request = B14MultimodalChatRequest(
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
            metadata = self._metadata(  # type: ignore[arg-type]
                request=request,
                trace_id=trace_id,
                status=RunStatus.REJECTED,
                duration_ms=self._duration_ms(started_value),
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
            metadata = self._metadata(  # type: ignore[arg-type]
                request=request,
                trace_id=trace_id,
                status=status,
                duration_ms=self._duration_ms(started_value),
                error_class=error_class,
            )
            raise ExecutionRuntimeError(
                exc.code,
                _safe_message_for_b14(exc.code),
                metadata=metadata,
                retryable=exc.retryable,
            ) from None
        except Exception:
            metadata = self._metadata(  # type: ignore[arg-type]
                request=request,
                trace_id=trace_id,
                status=RunStatus.FAILED,
                duration_ms=self._duration_ms(started_value),
                error_class=ErrorClass.INTERNAL_ERROR,
            )
            raise ExecutionRuntimeError(
                "execution_failed",
                "Model execution failed.",
                metadata=metadata,
            ) from None

        if not isinstance(result, B14ExecutionResult):
            metadata = self._metadata(  # type: ignore[arg-type]
                request=request,
                trace_id=trace_id,
                status=RunStatus.FAILED,
                duration_ms=self._duration_ms(started_value),
                error_class=ErrorClass.INTERNAL_ERROR,
            )
            raise ExecutionRuntimeError(
                "invalid_execution_result",
                "Model execution returned an invalid result contract.",
                metadata=metadata,
            )

        metadata = self._metadata(  # type: ignore[arg-type]
            request=request,
            trace_id=trace_id,
            status=RunStatus.COMPLETED,
            duration_ms=self._duration_ms(started_value),
            result=result,
        )
        return ExecutionResult(
            answer=result.answer,
            route=result.route,
            metadata=metadata,
        )
