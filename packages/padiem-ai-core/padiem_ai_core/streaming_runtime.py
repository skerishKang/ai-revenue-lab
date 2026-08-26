from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
import time
from typing import Any, Protocol
import uuid

from .b14_execution import (
    B14ChatRequest,
    B14ExecutionError,
    B14RouteMetadata,
)
from .b14_streaming import B14StreamEvent
from .contracts import ErrorClass, RunMetadata, RunStatus, UsageMetadata
from .execution_runtime import (
    ExecutionRequest,
    ExecutionRuntimeError,
    _compose_system_instruction,
    _error_class_for_b14,
    _normalize_model_policy,
    _safe_identifier,
    _safe_message_for_b14,
    _selected_model,
    _selected_provider,
)


class B14StreamExecutor(Protocol):
    def stream(self, request: B14ChatRequest) -> AsyncIterator[B14StreamEvent]: ...

    def stream_auto(self, request: B14ChatRequest) -> AsyncIterator[B14StreamEvent]: ...


def _has_usage(usage: UsageMetadata) -> bool:
    return any(
        value is not None
        for value in (usage.input_tokens, usage.output_tokens, usage.total_tokens)
    )


def _observed_model(route: B14RouteMetadata, chunk_model: str | None) -> str | None:
    return _selected_model(route) or chunk_model


@dataclass(frozen=True, slots=True)
class StreamingExecutionEvent:
    delta_content: str | None
    answer: str | None
    finish_reason: str | None
    route: B14RouteMetadata
    metadata: RunMetadata
    done: bool = False

    def __post_init__(self) -> None:
        if self.delta_content is not None and not isinstance(self.delta_content, str):
            raise ValueError("delta_content must be a string or None")
        if self.answer is not None and not isinstance(self.answer, str):
            raise ValueError("answer must be a string or None")
        if self.finish_reason is not None and not isinstance(self.finish_reason, str):
            raise ValueError("finish_reason must be a string or None")
        if not isinstance(self.route, B14RouteMetadata):
            raise ValueError("route must be B14RouteMetadata")
        if not isinstance(self.metadata, RunMetadata):
            raise ValueError("metadata must be RunMetadata")
        if not isinstance(self.done, bool):
            raise ValueError("done must be a boolean")

        if self.done:
            if self.delta_content is not None:
                raise ValueError("terminal event must not contain delta_content")
            if self.answer is None or not self.answer.strip():
                raise ValueError("terminal event must contain a non-empty answer")
            if self.metadata.status is not RunStatus.COMPLETED:
                raise ValueError("terminal event metadata must be completed")
        else:
            if self.answer is not None:
                raise ValueError("progress event must not contain final answer")
            if self.delta_content is None or not self.delta_content:
                raise ValueError("progress event must contain a non-empty delta")
            if self.metadata.status is not RunStatus.MODEL_RUNNING:
                raise ValueError("progress event metadata must be model_running")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "delta_content": self.delta_content,
            "answer": self.answer,
            "finish_reason": self.finish_reason,
            "route": self.route.to_public_dict(),
            "metadata": self.metadata.to_public_dict(),
            "done": self.done,
        }


class StreamingExecutionRuntime:
    def __init__(
        self,
        *,
        app_id: str,
        b14_stream_client: B14StreamExecutor,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._app_id = _safe_identifier("app_id", app_id)
        if not callable(getattr(b14_stream_client, "stream", None)):
            raise ValueError("b14_stream_client must expose stream(request)")
        if not callable(getattr(b14_stream_client, "stream_auto", None)):
            raise ValueError("b14_stream_client must expose stream_auto(request)")
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._b14_stream_client = b14_stream_client
        self._clock = clock

    @property
    def app_id(self) -> str:
        return self._app_id

    def _duration_ms(self, started_at: float) -> int:
        elapsed = self._clock() - started_at
        return max(0, int(round(elapsed * 1000)))

    def _metadata(
        self,
        *,
        request: ExecutionRequest,
        trace_id: str,
        status: RunStatus,
        started_at: float,
        route: B14RouteMetadata | None = None,
        usage: UsageMetadata | None = None,
        chunk_model: str | None = None,
        error_class: ErrorClass | None = None,
    ) -> RunMetadata:
        observed_route = route or B14RouteMetadata()
        return RunMetadata(
            trace_id=trace_id,
            app_id=self._app_id,
            agent_id=request.agent.id,
            session_id=request.session_id,
            status=status,
            provider=_selected_provider(observed_route),
            model=_observed_model(observed_route, chunk_model),
            duration_ms=self._duration_ms(started_at),
            usage=usage or UsageMetadata(),
            error_class=error_class,
        )

    def _runtime_error(
        self,
        *,
        request: ExecutionRequest,
        trace_id: str,
        started_at: float,
        code: str,
        safe_message: str,
        error_class: ErrorClass,
        retryable: bool = False,
        route: B14RouteMetadata | None = None,
        usage: UsageMetadata | None = None,
        chunk_model: str | None = None,
    ) -> ExecutionRuntimeError:
        status = (
            RunStatus.TIMEOUT
            if error_class is ErrorClass.PROVIDER_TIMEOUT
            else RunStatus.FAILED
        )
        return ExecutionRuntimeError(
            code,
            safe_message,
            metadata=self._metadata(
                request=request,
                trace_id=trace_id,
                status=status,
                started_at=started_at,
                route=route,
                usage=usage,
                chunk_model=chunk_model,
                error_class=error_class,
            ),
            retryable=retryable,
        )

    async def stream(
        self, request: ExecutionRequest
    ) -> AsyncIterator[StreamingExecutionEvent]:
        if not isinstance(request, ExecutionRequest):
            raise ValueError("request must be ExecutionRequest")

        started_at = self._clock()
        trace_id = request.trace_id or f"run_{uuid.uuid4().hex[:24]}"

        if request.agent.allowed_tools:
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.POLICY_BLOCKED,
                started_at=started_at,
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
                started_at=started_at,
                error_class=ErrorClass.INPUT_ERROR,
            )
            raise ExecutionRuntimeError(
                "invalid_execution_request",
                "Execution request or agent model policy is invalid.",
                metadata=metadata,
            ) from None

        try:
            iterator = (
                self._b14_stream_client.stream_auto(b14_request)
                if b14_request.model == "b14/auto"
                else self._b14_stream_client.stream(b14_request)
            )
        except Exception:
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.FAILED,
                started_at=started_at,
                error_class=ErrorClass.INTERNAL_ERROR,
            )
            raise ExecutionRuntimeError(
                "execution_failed",
                "Model streaming execution failed.",
                metadata=metadata,
            ) from None

        answer_parts: list[str] = []
        last_route = B14RouteMetadata()
        last_usage = UsageMetadata()
        last_model: str | None = None
        last_finish_reason: str | None = None
        saw_done = False

        try:
            async for event in iterator:
                if not isinstance(event, B14StreamEvent):
                    raise self._runtime_error(
                        request=request,
                        trace_id=trace_id,
                        started_at=started_at,
                        code="invalid_stream_event",
                        safe_message="Model streaming execution returned an invalid event contract.",
                        error_class=ErrorClass.PROVIDER_BAD_RESPONSE,
                        route=last_route,
                        usage=last_usage,
                        chunk_model=last_model,
                    )

                if event.route != B14RouteMetadata():
                    last_route = event.route
                if _has_usage(event.usage):
                    last_usage = event.usage
                if event.model is not None:
                    last_model = event.model
                if event.finish_reason is not None:
                    last_finish_reason = event.finish_reason

                if event.done:
                    if saw_done:
                        raise self._runtime_error(
                            request=request,
                            trace_id=trace_id,
                            started_at=started_at,
                            code="invalid_stream_event",
                            safe_message="Model streaming execution returned duplicate completion.",
                            error_class=ErrorClass.PROVIDER_BAD_RESPONSE,
                            route=last_route,
                            usage=last_usage,
                            chunk_model=last_model,
                        )
                    saw_done = True
                    answer = "".join(answer_parts).strip()
                    if not answer:
                        raise self._runtime_error(
                            request=request,
                            trace_id=trace_id,
                            started_at=started_at,
                            code="empty_upstream_answer",
                            safe_message=_safe_message_for_b14("empty_upstream_answer"),
                            error_class=ErrorClass.PROVIDER_BAD_RESPONSE,
                            route=last_route,
                            usage=last_usage,
                            chunk_model=last_model,
                        )
                    yield StreamingExecutionEvent(
                        delta_content=None,
                        answer=answer,
                        finish_reason=last_finish_reason,
                        route=last_route,
                        metadata=self._metadata(
                            request=request,
                            trace_id=trace_id,
                            status=RunStatus.COMPLETED,
                            started_at=started_at,
                            route=last_route,
                            usage=last_usage,
                            chunk_model=last_model,
                        ),
                        done=True,
                    )
                    return

                if event.delta_content:
                    answer_parts.append(event.delta_content)
                    yield StreamingExecutionEvent(
                        delta_content=event.delta_content,
                        answer=None,
                        finish_reason=event.finish_reason,
                        route=last_route,
                        metadata=self._metadata(
                            request=request,
                            trace_id=trace_id,
                            status=RunStatus.MODEL_RUNNING,
                            started_at=started_at,
                            route=last_route,
                            usage=last_usage,
                            chunk_model=last_model,
                        ),
                        done=False,
                    )

            if not saw_done:
                raise self._runtime_error(
                    request=request,
                    trace_id=trace_id,
                    started_at=started_at,
                    code="malformed_upstream",
                    safe_message=_safe_message_for_b14("malformed_upstream"),
                    error_class=ErrorClass.PROVIDER_BAD_RESPONSE,
                    route=last_route,
                    usage=last_usage,
                    chunk_model=last_model,
                )
        except ExecutionRuntimeError:
            raise
        except B14ExecutionError as exc:
            raise self._runtime_error(
                request=request,
                trace_id=trace_id,
                started_at=started_at,
                code=exc.code,
                safe_message=_safe_message_for_b14(exc.code),
                error_class=_error_class_for_b14(exc.code),
                retryable=exc.retryable,
                route=last_route,
                usage=last_usage,
                chunk_model=last_model,
            ) from None
        except Exception:
            raise self._runtime_error(
                request=request,
                trace_id=trace_id,
                started_at=started_at,
                code="execution_failed",
                safe_message="Model streaming execution failed.",
                error_class=ErrorClass.INTERNAL_ERROR,
                route=last_route,
                usage=last_usage,
                chunk_model=last_model,
            ) from None
        finally:
            aclose = getattr(iterator, "aclose", None)
            if callable(aclose):
                await aclose()
