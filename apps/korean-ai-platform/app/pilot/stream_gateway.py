"""Preview-only HTTP/SSE gateway for Business 14 Router streaming.

The canonical ``/v1/chat/completions`` endpoint still rejects ``stream=true``.
This preview surface validates Router-backed manual/auto streaming and bounded
pre-content fallback before any canonical endpoint or public B62 promotion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
import logging
import uuid
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Router

from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import (
    InvalidRequest,
    MalformedUpstreamResponse,
    PilotError,
    PilotNotConfigured,
    UnsupportedModel,
    UpstreamAuthFailed,
    UpstreamClientError,
    UpstreamRateLimited,
    UpstreamResponseTooLarge,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.gateway import _validate_body
from app.pilot.openrouter_config import openrouter_config
from app.pilot.openrouter_stream import stream_openrouter_chat_completions
from app.pilot import router_core as rcore
from app.pilot.streaming_router import RouterStreamEvent, stream_routed_chat_completions

logger = logging.getLogger("korean-ai-platform.pilot.stream-preview")

router = Router()

_STREAM_PREVIEW_PATH = "/v1/chat/completions/stream-preview"


def _request_id() -> str:
    return f"b14stream_{uuid.uuid4().hex[:12]}"


def _error_response(exc: PilotError, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
            }
        },
    )


def _invalid_json_response(request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_body",
                "message": "Request body must be valid JSON.",
                "request_id": request_id,
            }
        },
    )


def _validate_preview_body(raw: Any) -> tuple[dict[str, Any], rcore.RouteDecision]:
    """Reuse canonical validation, then resolve one immutable Router decision."""
    if not isinstance(raw, dict):
        raise InvalidRequest("Streaming preview request body must be a JSON object.")
    if raw.get("stream") is not True:
        raise InvalidRequest("Streaming preview requires stream=true.")

    # Canonical validation still rejects stream=true. Validate an otherwise
    # identical copy with stream=false so message/field/routing limits remain
    # authoritative instead of creating a second request schema.
    canonical_raw = dict(raw)
    canonical_raw["stream"] = False
    body = _validate_body(canonical_raw)

    model_id = body["model"]
    if model_id != "b14/auto" and get_catalog_by_id(model_id) is None:
        # Preserve the preview's existing explicit-model error contract rather
        # than converting a legacy/non-catalog ID into a generic no-safe-route.
        raise UnsupportedModel(model_id)

    # Streaming preview remains deliberately text-only.
    if any(not isinstance(message.get("content"), str) for message in body["messages"]):
        raise InvalidRequest("Streaming preview currently supports text-only messages.")

    decision = rcore.resolve_route(model_id, body.get("business14", {}))
    return body, decision


def _usage_dict(event: RouterStreamEvent) -> dict[str, int | None] | None:
    usage = event.usage
    if usage is None:
        return None
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def _route_metadata(
    event: RouterStreamEvent,
    *,
    decision: rcore.RouteDecision,
) -> dict[str, Any]:
    return {
        "request_id": event.request_id,
        "route_mode": event.route_mode,
        "selected_provider": event.selected_provider,
        "selected_model": event.selected_model,
        "selected_upstream_model": event.selected_upstream_model,
        "selected_route_id": event.selected_route_id,
        "reason_codes": list(event.reason_codes),
        "fallback_allowed": decision.fallback_allowed,
        "fallback_used": event.fallback_used,
        "attempt_count": event.attempt,
        "provider_mode": openrouter_config.provider_mode,
        "route_evidence_status": (
            "mock_no_upstream_call"
            if openrouter_config.is_mock
            else "live_streaming_router"
        ),
    }


def _encode_data_frame(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"data: {encoded}\n\n".encode("utf-8")


def _encode_event(
    event: RouterStreamEvent,
    *,
    decision: rcore.RouteDecision,
) -> bytes:
    if event.done:
        return b"data: [DONE]\n\n"

    usage = _usage_dict(event)
    choices: list[dict[str, Any]]
    if usage is not None and event.delta_content is None and event.finish_reason is None:
        choices = []
    else:
        delta: dict[str, Any] = {}
        if event.delta_content is not None:
            delta["content"] = event.delta_content
        choices = [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": event.finish_reason,
            }
        ]

    payload: dict[str, Any] = {
        "id": event.request_id,
        "object": "chat.completion.chunk",
        "model": event.actual_response_model or event.selected_upstream_model,
        "choices": choices,
        "business14": _route_metadata(event, decision=decision),
    }
    if usage is not None:
        payload["usage"] = usage
    return _encode_data_frame(payload)


def _pilot_error_from_router_code(code: str) -> PilotError:
    """Restore bounded HTTP/SSE error semantics from a Router terminal code."""
    if code == "upstream_auth_failed":
        return UpstreamAuthFailed()
    if code == "upstream_rate_limited":
        return UpstreamRateLimited()
    if code == "upstream_timeout":
        return UpstreamTimeout()
    if code == "upstream_server_error":
        return UpstreamServerError()
    if code == "upstream_client_error":
        return UpstreamClientError()
    if code == "upstream_response_too_large":
        return UpstreamResponseTooLarge(openrouter_config.max_response_bytes)
    if code == "pilot_not_configured":
        return PilotNotConfigured()
    if code in {
        "malformed_upstream_response",
        "empty_stream_answer",
        "stream_ended_without_done",
    }:
        return MalformedUpstreamResponse()
    if code == "stream_execution_error":
        return PilotError(
            code="internal_error",
            message="스트리밍 응답 처리 중 내부 오류가 발생했습니다.",
            status_code=500,
        )
    return PilotError(
        code="stream_execution_error",
        message="스트리밍 실행을 완료하지 못했습니다.",
        status_code=502,
    )


def _encode_stream_error(
    exc: PilotError,
    *,
    event: RouterStreamEvent,
    decision: rcore.RouteDecision,
) -> bytes:
    payload = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": event.request_id,
            "after_stream_start": True,
        },
        "business14": {
            **_route_metadata(event, decision=decision),
            "stream_status": "aborted",
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: error\ndata: {encoded}\n\n".encode("utf-8")


async def _close_iterator(iterator: AsyncIterator[RouterStreamEvent]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception:
            pass


async def _stream_body(
    iterator: AsyncIterator[RouterStreamEvent],
    first_event: RouterStreamEvent,
    *,
    decision: rcore.RouteDecision,
) -> AsyncIterator[bytes]:
    """Emit the primed Router event and preserve post-start terminal semantics."""
    last_event = first_event
    try:
        if first_event.error_code is not None:
            yield _encode_stream_error(
                _pilot_error_from_router_code(first_event.error_code),
                event=first_event,
                decision=decision,
            )
            return

        yield _encode_event(first_event, decision=decision)
        if first_event.done:
            return

        async for event in iterator:
            last_event = event
            if event.error_code is not None:
                yield _encode_stream_error(
                    _pilot_error_from_router_code(event.error_code),
                    event=event,
                    decision=decision,
                )
                return
            yield _encode_event(event, decision=decision)
            if event.done:
                return
    except Exception:
        logger.error(
            "stream_preview_post_start_internal_error request_id=%s",
            last_event.request_id,
        )
        generic = PilotError(
            code="internal_error",
            message="스트리밍 응답 처리 중 내부 오류가 발생했습니다.",
            status_code=500,
        )
        yield _encode_stream_error(generic, event=last_event, decision=decision)
    finally:
        await _close_iterator(iterator)


@router.route(_STREAM_PREVIEW_PATH, methods=["POST"])
async def pilot_stream_preview(request: Request):
    """Preview one resolved manual/auto route as Router-backed SSE."""
    request_id = _request_id()
    iterator: AsyncIterator[RouterStreamEvent] | None = None

    try:
        try:
            raw = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _invalid_json_response(request_id)

        body, decision = _validate_preview_body(raw)
        request_id = decision.request_id

        # Tests may inject MockTransport through app.state. Production has no
        # injected transport and therefore uses the provider's normal client.
        transport = getattr(request.app.state, "openrouter_stream_transport", None)
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise InvalidRequest("Invalid streaming transport configuration.")

        if transport is None:
            stream_call = stream_openrouter_chat_completions
        else:
            def stream_call(**kwargs):
                return stream_openrouter_chat_completions(**kwargs, transport=transport)

        iterator = stream_routed_chat_completions(
            decision=decision,
            messages=body["messages"],
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            stream_call=stream_call,
        )

        # Prime before downstream HTTP 200. The Router suppresses failed
        # pre-content attempts; a terminal error as the first emitted event
        # therefore means no route committed and can retain a bounded JSON
        # status instead of being trapped inside SSE 200.
        try:
            first_event = await anext(iterator)
        except StopAsyncIteration as exc:
            raise MalformedUpstreamResponse() from exc

        if first_event.error_code is not None and not first_event.committed:
            raise _pilot_error_from_router_code(first_event.error_code)

        return StreamingResponse(
            _stream_body(iterator, first_event, decision=decision),
            status_code=200,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    except PilotError as exc:
        if iterator is not None:
            await _close_iterator(iterator)
        logger.warning(
            "stream_preview_pre_start_error request_id=%s code=%s status=%d",
            request_id,
            exc.code,
            exc.status_code,
        )
        return _error_response(exc, request_id)
    except Exception:
        if iterator is not None:
            await _close_iterator(iterator)
        logger.error(
            "stream_preview_pre_start_internal_error request_id=%s",
            request_id,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "스트리밍 요청을 준비하는 중 내부 오류가 발생했습니다.",
                    "request_id": request_id,
                }
            },
        )
