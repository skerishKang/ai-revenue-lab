"""Language-neutral streaming contract for the internal Padiem AI Engine.

The module stays Cloudflare-neutral. It reuses the exact request builder,
delegates execution semantics to Padiem AI Core's StreamingExecutionRuntime,
and serializes only Core public events as NDJSON.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any, Protocol

from padiem_ai_core import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionRuntimeError,
    StreamingExecutionEvent,
)
from padiem_ai_core.contextual_execution import prepare_execution
from padiem_ai_core.execution_context import IdempotencyConflictError
from padiem_ai_core.execution_runtime import ExecutionResult

from app.evidence_projection import project_terminal_evidence
from app.service import (
    MAX_REQUEST_BODY_BYTES,
    ServiceContractError,
    ServiceResponse,
    _service_error,
    _status_for_runtime_error,
    build_execution_request,
)

STREAM_PATH = "/internal/v1/stream"
NDJSON_CONTENT_TYPE = "application/x-ndjson; charset=utf-8"


class StreamingRunner(Protocol):
    def stream(
        self, request: ExecutionRequest
    ) -> AsyncIterator[StreamingExecutionEvent]: ...


StreamingRuntimeFactory = Callable[[str], StreamingRunner]


@dataclass(frozen=True, slots=True)
class StreamIdempotencyBinding:
    """Bounded idempotency reservation context for an active streaming run."""

    adapter: Any
    app_id: str
    idempotency_key: str
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class PreparedStream:
    """A primed Core stream whose first visible event is already validated."""

    first_event: StreamingExecutionEvent
    iterator: AsyncIterator[StreamingExecutionEvent]
    context: ExecutionContext | None = None
    replayed: bool = False
    idempotency: StreamIdempotencyBinding | None = None


def _runtime_error_response(exc: ExecutionRuntimeError) -> ServiceResponse:
    return _service_error(
        exc.code,
        exc.safe_message,
        status_code=_status_for_runtime_error(exc),
        retryable=exc.retryable,
        metadata=exc.metadata.to_public_dict(),
    )


def _internal_error_response() -> ServiceResponse:
    return _service_error(
        "engine_internal_error",
        "Padiem AI Engine streaming execution failed.",
        status_code=500,
    )


def _encode_line(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n"


def _event_line(event: StreamingExecutionEvent, *, replayed: bool = False) -> str:
    # #1745 parity chokepoint: the settling terminal event line is extended with
    # the same canonical Engine evidence projection used by execute and research.
    # Core's streaming contract carries no grounded evidence, so today this adds
    # nothing and stream output is byte-identical; when Core settles evidence on
    # a terminal event, stream converges with non-stream automatically instead
    # of forking a second streaming evidence protocol.
    payload: dict[str, Any] = {
        "ok": True,
        "event": {**event.to_public_dict(), **project_terminal_evidence(event)},
    }
    if replayed:
        payload["replayed"] = True
    return _encode_line(payload)


def _error_line(response: ServiceResponse) -> str:
    return _encode_line(dict(response.body))


async def _close_iterator(iterator: Any | None) -> None:
    if iterator is None:
        return
    close = getattr(iterator, "aclose", None)
    if not callable(close):
        return
    try:
        await close()
    except Exception:
        pass


async def _empty_iterator() -> AsyncIterator[StreamingExecutionEvent]:
    if False:
        yield  # type: ignore[unreachable]


class StreamingEngineService:
    """Prepare and serialize one internal completed-answer streaming run."""

    def __init__(
        self,
        *,
        runtime_factory: StreamingRuntimeFactory,
        b14_service_bound: bool,
        idempotency_adapter: Any | None = None,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        self._runtime_factory = runtime_factory
        self._b14_service_bound = bool(b14_service_bound)
        self._idempotency_adapter = idempotency_adapter

    async def prepare(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> PreparedStream | ServiceResponse:
        """Validate, construct and prime a Core stream before HTTP 200 commits."""

        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != STREAM_PATH:
            return _service_error(
                "not_found", "Internal Engine route not found.", status_code=404
            )
        if normalized_method != "POST":
            return _service_error(
                "method_not_allowed", "Method not allowed.", status_code=405
            )
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _service_error(
                "unsupported_media_type",
                "Content-Type must be application/json.",
                status_code=415,
            )
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error(
                "invalid_request", "Request body is invalid.", status_code=400
            )
        raw = bytes(body)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            return _service_error(
                "request_too_large",
                "Request body exceeds the internal Engine safety limit.",
                status_code=413,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error(
                "invalid_json",
                "Request body must contain valid UTF-8 JSON.",
                status_code=400,
            )

        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )

        try:
            app_id, request, context = build_execution_request(payload)
        except ServiceContractError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=exc.status_code,
            )

        idempotency_binding: StreamIdempotencyBinding | None = None
        if context is not None and context.idempotency_key is not None:
            if self._idempotency_adapter is None:
                return _service_error(
                    "stream_idempotency_unavailable",
                    "Streaming idempotency requires a product-owned replay adapter.",
                    status_code=422,
                )

            try:
                prep = prepare_execution(
                    context=context,
                    app_id=app_id,
                    payload=payload,
                )
                replay = await self._idempotency_adapter.begin(
                    app_id=app_id,
                    idempotency_key=context.idempotency_key,
                    request_fingerprint=prep.request_fingerprint,
                )
            except IdempotencyConflictError:
                return _service_error(
                    "idempotency_conflict",
                    "Idempotency key is already bound to a different execution request.",
                    status_code=409,
                )
            except Exception:
                return _service_error(
                    "idempotency_unavailable",
                    "Trusted durable idempotency authority is unavailable.",
                    status_code=503,
                )

            if replay is not None:
                if not isinstance(replay, ExecutionResult):
                    return _service_error(
                        "idempotency_conflict",
                        "Idempotency key returned invalid replay.",
                        status_code=409,
                    )
                replay_event = StreamingExecutionEvent(
                    delta_content=None,
                    answer=replay.answer,
                    finish_reason="stop",
                    route=replay.route,
                    metadata=replay.metadata,
                    done=True,
                )
                return PreparedStream(
                    first_event=replay_event,
                    iterator=_empty_iterator(),
                    context=context,
                    replayed=True,
                    idempotency=None,
                )

            idempotency_binding = StreamIdempotencyBinding(
                adapter=self._idempotency_adapter,
                app_id=app_id,
                idempotency_key=context.idempotency_key,
                request_fingerprint=prep.request_fingerprint,
            )

        iterator: AsyncIterator[StreamingExecutionEvent] | None = None
        try:
            runtime = self._runtime_factory(app_id)
            iterator = runtime.stream(request)
            first_event = await anext(iterator)
            if not isinstance(first_event, StreamingExecutionEvent):
                await _close_iterator(iterator)
                if idempotency_binding is not None:
                    await idempotency_binding.adapter.abort(
                        app_id=idempotency_binding.app_id,
                        idempotency_key=idempotency_binding.idempotency_key,
                    )
                return _service_error(
                    "invalid_stream_event",
                    "Padiem AI Engine returned an invalid streaming event.",
                    status_code=502,
                )
            return PreparedStream(
                first_event=first_event,
                iterator=iterator,
                context=context,
                replayed=False,
                idempotency=idempotency_binding,
            )
        except StopAsyncIteration:
            await _close_iterator(iterator)
            if idempotency_binding is not None:
                await idempotency_binding.adapter.abort(
                    app_id=idempotency_binding.app_id,
                    idempotency_key=idempotency_binding.idempotency_key,
                )
            return _service_error(
                "malformed_upstream",
                "Model streaming execution ended before producing an event.",
                status_code=502,
            )
        except ExecutionRuntimeError as exc:
            await _close_iterator(iterator)
            if idempotency_binding is not None:
                await idempotency_binding.adapter.abort(
                    app_id=idempotency_binding.app_id,
                    idempotency_key=idempotency_binding.idempotency_key,
                )
            return _runtime_error_response(exc)
        except Exception:
            await _close_iterator(iterator)
            if idempotency_binding is not None:
                await idempotency_binding.adapter.abort(
                    app_id=idempotency_binding.app_id,
                    idempotency_key=idempotency_binding.idempotency_key,
                )
            return _internal_error_response()

    async def iter_ndjson(self, prepared: PreparedStream) -> AsyncIterator[str]:
        """Emit one public Core event per line, then one bounded error if needed."""

        if not isinstance(prepared, PreparedStream):
            raise ValueError("prepared must be PreparedStream")

        iterator = prepared.iterator
        idempotency = prepared.idempotency
        completed = False
        last_answer: str | None = None
        last_route = prepared.first_event.route
        last_metadata = prepared.first_event.metadata
        accumulated_deltas: list[str] = []

        try:
            yield _event_line(prepared.first_event, replayed=prepared.replayed)
            if prepared.first_event.done:
                completed = True
                if idempotency is not None:
                    answer = prepared.first_event.answer or "".join(accumulated_deltas)
                    res = ExecutionResult(
                        answer=answer,
                        route=prepared.first_event.route,
                        metadata=prepared.first_event.metadata,
                    )
                    await idempotency.adapter.complete(
                        app_id=idempotency.app_id,
                        idempotency_key=idempotency.idempotency_key,
                        request_fingerprint=idempotency.request_fingerprint,
                        result=res.to_public_dict(),
                    )
                return

            if prepared.first_event.delta_content:
                accumulated_deltas.append(prepared.first_event.delta_content)

            async for event in iterator:
                if not isinstance(event, StreamingExecutionEvent):
                    raise RuntimeError("invalid private stream event")
                last_route = event.route
                last_metadata = event.metadata
                if event.delta_content:
                    accumulated_deltas.append(event.delta_content)
                if event.done:
                    last_answer = event.answer
                yield _event_line(event)
                if event.done:
                    completed = True
                    if idempotency is not None:
                        answer = last_answer or "".join(accumulated_deltas)
                        res = ExecutionResult(
                            answer=answer,
                            route=last_route,
                            metadata=last_metadata,
                        )
                        await idempotency.adapter.complete(
                            app_id=idempotency.app_id,
                            idempotency_key=idempotency.idempotency_key,
                            request_fingerprint=idempotency.request_fingerprint,
                            result=res.to_public_dict(),
                        )
                    return
        except ExecutionRuntimeError as exc:
            yield _error_line(_runtime_error_response(exc))
        except Exception:
            yield _error_line(_internal_error_response())
        finally:
            await _close_iterator(iterator)
            if idempotency is not None and not completed:
                try:
                    await idempotency.adapter.abort(
                        app_id=idempotency.app_id,
                        idempotency_key=idempotency.idempotency_key,
                    )
                except Exception:
                    pass
