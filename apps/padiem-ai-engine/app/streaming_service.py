"""Language-neutral streaming contract for the internal Padiem AI Engine.

The module stays Cloudflare-neutral. It reuses the exact request builder,
delegates execution semantics to Padiem AI Core's StreamingExecutionRuntime,
and serializes only Core public events as NDJSON.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
import json
from typing import Any, Protocol

from padiem_ai_core import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionRuntimeError,
    StreamingExecutionEvent,
)

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
class PreparedStream:
    """A primed Core stream whose first visible event is already validated."""

    first_event: StreamingExecutionEvent
    iterator: AsyncIterator[StreamingExecutionEvent]
    context: ExecutionContext | None = None


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


def _event_line(event: StreamingExecutionEvent) -> str:
    return _encode_line({"ok": True, "event": event.to_public_dict()})


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


class StreamingEngineService:
    """Prepare and serialize one internal completed-answer streaming run."""

    def __init__(
        self,
        *,
        runtime_factory: StreamingRuntimeFactory,
        b14_service_bound: bool,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        self._runtime_factory = runtime_factory
        self._b14_service_bound = bool(b14_service_bound)

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

        # Stream replay cannot yet be proven safe by the product-owned
        # idempotency adapter contract. Never silently execute a keyed stream
        # twice; require a completed-run adapter in a future slice instead.
        if context is not None and context.idempotency_key is not None:
            return _service_error(
                "stream_idempotency_unavailable",
                "Streaming idempotency requires a product-owned replay adapter.",
                status_code=422,
            )

        iterator: AsyncIterator[StreamingExecutionEvent] | None = None
        try:
            runtime = self._runtime_factory(app_id)
            iterator = runtime.stream(request)
            first_event = await anext(iterator)
            if not isinstance(first_event, StreamingExecutionEvent):
                await _close_iterator(iterator)
                return _service_error(
                    "invalid_stream_event",
                    "Padiem AI Engine returned an invalid streaming event.",
                    status_code=502,
                )
            return PreparedStream(
                first_event=first_event,
                iterator=iterator,
                context=context,
            )
        except StopAsyncIteration:
            await _close_iterator(iterator)
            return _service_error(
                "malformed_upstream",
                "Model streaming execution ended before producing an event.",
                status_code=502,
            )
        except ExecutionRuntimeError as exc:
            await _close_iterator(iterator)
            return _runtime_error_response(exc)
        except Exception:
            await _close_iterator(iterator)
            return _internal_error_response()

    async def iter_ndjson(self, prepared: PreparedStream) -> AsyncIterator[str]:
        """Emit one public Core event per line, then one bounded error if needed."""

        if not isinstance(prepared, PreparedStream):
            raise ValueError("prepared must be PreparedStream")

        iterator = prepared.iterator
        try:
            yield _event_line(prepared.first_event)
            if prepared.first_event.done:
                return

            async for event in iterator:
                if not isinstance(event, StreamingExecutionEvent):
                    raise RuntimeError("invalid private stream event")
                yield _event_line(event)
                if event.done:
                    return
        except ExecutionRuntimeError as exc:
            yield _error_line(_runtime_error_response(exc))
        except Exception:
            yield _error_line(_internal_error_response())
        finally:
            await _close_iterator(iterator)
