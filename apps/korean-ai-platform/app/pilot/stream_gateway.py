"""Preview-only HTTP/SSE gateway for the Business 14 streaming primitive.

This router deliberately does not change the canonical
``/v1/chat/completions`` endpoint. It exposes one bounded preview endpoint for
manual catalog routes only so HTTP streaming semantics can be validated before
Router Core fallback, shared Core transport, or B62 streaming are enabled.
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
    StreamNotSupported,
    UnsupportedModel,
)
from app.pilot.gateway import _validate_body
from app.pilot.openrouter_config import openrouter_config
from app.pilot.openrouter_stream import (
    OpenRouterStreamEvent,
    OpenRouterStreamUsage,
    stream_openrouter_chat_completions,
)
from app.pilot.platform import stream_platform_chat_completions
from app.pilot import router_core as rcore

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
    """Reuse the canonical validator, then apply preview-only route limits."""
    if not isinstance(raw, dict):
        raise InvalidRequest("Streaming preview request body must be a JSON object.")
    if raw.get("stream") is not True:
        raise InvalidRequest("Streaming preview requires stream=true.")

    # The canonical validator still rejects stream=true. Validate an otherwise
    # identical copy with stream=false so all existing message/field/routing
    # limits remain authoritative instead of forking another request schema.
    canonical_raw = dict(raw)
    canonical_raw["stream"] = False
    body = _validate_body(canonical_raw)

    model_id = body["model"]
    if model_id == "b14/auto":
        raise StreamNotSupported()
    if get_catalog_by_id(model_id) is None:
        raise UnsupportedModel(model_id)

    # Slice 12 is deliberately text-only. The installed multimodal validator
    # may accept structured content for the canonical endpoint; preview
    # streaming does not widen that contract yet.
    if any(not isinstance(message.get("content"), str) for message in body["messages"]):
        raise StreamNotSupported()

    b14_opts = body.get("business14", {})
    if b14_opts.get("allow_external_fallback") is True:
        raise StreamNotSupported()
    if b14_opts.get("max_attempts", 1) != 1:
        raise StreamNotSupported()

    decision = rcore.resolve_route(model_id, b14_opts)
    # platform_secret providers (e.g. Agnes) are now supported by this
    # streaming gateway via stream_platform_chat_completions. The route
    # must still stay manual single-attempt (no fallback) to keep the
    # security/cancellation contract bounded.
    if (
        decision.route_mode != "manual"
        or decision.fallback_allowed
        or decision.max_attempts != 1
    ):
        raise StreamNotSupported()

    return body, decision


def _usage_dict(usage: OpenRouterStreamUsage) -> dict[str, int | None]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def _route_metadata(
    *,
    request_id: str,
    decision: rcore.RouteDecision,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "route_mode": "manual",
        "selected_provider": decision.selected_provider,
        "selected_model": decision.selected_model,
        "selected_upstream_model": decision.selected_upstream_model,
        "selected_route_id": decision.selected_route_id,
        "fallback_allowed": False,
        "fallback_used": False,
        "attempt_count": 1,
        "provider_mode": openrouter_config.provider_mode,
        "route_evidence_status": (
            "mock_no_upstream_call"
            if openrouter_config.is_mock
            else "live_streaming_preview"
        ),
    }


def _encode_data_frame(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"data: {encoded}\n\n".encode("utf-8")


def _encode_event(
    event: OpenRouterStreamEvent,
    *,
    request_id: str,
    decision: rcore.RouteDecision,
) -> bytes:
    if event.done:
        return b"data: [DONE]\n\n"

    choices: list[dict[str, Any]]
    if event.usage is not None and event.delta_content is None and event.finish_reason is None:
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
        "id": event.response_id or request_id,
        "object": "chat.completion.chunk",
        "model": event.model or decision.selected_upstream_model,
        "choices": choices,
        "business14": _route_metadata(request_id=request_id, decision=decision),
    }
    if event.usage is not None:
        payload["usage"] = _usage_dict(event.usage)
    return _encode_data_frame(payload)


def _encode_stream_error(
    exc: PilotError,
    *,
    request_id: str,
    decision: rcore.RouteDecision,
) -> bytes:
    payload = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": request_id,
            "after_stream_start": True,
        },
        "business14": {
            **_route_metadata(request_id=request_id, decision=decision),
            "stream_status": "aborted",
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: error\ndata: {encoded}\n\n".encode("utf-8")


async def _close_iterator(iterator: AsyncIterator[OpenRouterStreamEvent]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


async def _stream_body(
    iterator: AsyncIterator[OpenRouterStreamEvent],
    first_event: OpenRouterStreamEvent,
    *,
    request_id: str,
    decision: rcore.RouteDecision,
) -> AsyncIterator[bytes]:
    """Emit the primed event, then continue with bounded post-start errors."""
    try:
        yield _encode_event(first_event, request_id=request_id, decision=decision)
        if first_event.done:
            return

        async for event in iterator:
            yield _encode_event(event, request_id=request_id, decision=decision)
            if event.done:
                return
    except PilotError as exc:
        logger.warning(
            "stream_preview_post_start_error request_id=%s code=%s",
            request_id,
            exc.code,
        )
        yield _encode_stream_error(
            exc,
            request_id=request_id,
            decision=decision,
        )
    except Exception:
        logger.error(
            "stream_preview_post_start_internal_error request_id=%s",
            request_id,
        )
        generic = PilotError(
            code="internal_error",
            message="스트리밍 응답 처리 중 내부 오류가 발생했습니다.",
            status_code=500,
        )
        yield _encode_stream_error(
            generic,
            request_id=request_id,
            decision=decision,
        )
    finally:
        await _close_iterator(iterator)


@router.route(_STREAM_PREVIEW_PATH, methods=["POST"])
async def pilot_stream_preview(request: Request):
    """Preview one manual, non-fallback OpenRouter route as SSE."""
    request_id = _request_id()
    iterator: AsyncIterator[OpenRouterStreamEvent] | None = None

    try:
        try:
            raw = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _invalid_json_response(request_id)

        body, decision = _validate_preview_body(raw)

        # Tests may inject MockTransport through app.state. Production has no
        # injected transport and therefore uses the provider's normal client.
        transport = getattr(request.app.state, "openrouter_stream_transport", None)
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise InvalidRequest("Invalid streaming transport configuration.")

        if decision.credential_source == "platform_secret":
            if not decision.platform_provider_id:
                raise InvalidRequest("platform_secret route missing provider binding.")
            iterator = stream_platform_chat_completions(
                model_id=decision.selected_model,
                upstream_model=decision.selected_upstream_model,
                provider=decision.selected_provider,
                platform_provider_id=decision.platform_provider_id,
                messages=body["messages"],
                temperature=body.get("temperature"),
                max_tokens=body.get("max_tokens"),
                transport=transport,
            )
        else:
            iterator = stream_openrouter_chat_completions(
                messages=body["messages"],
                temperature=body.get("temperature"),
                max_tokens=body.get("max_tokens"),
                model_id=decision.selected_model,
                upstream_model=decision.selected_upstream_model,
                provider=decision.selected_provider,
                transport=transport,
            )

        # Prime before StreamingResponse commits HTTP 200. Any provider error
        # before the first visible event is therefore returned as normal JSON
        # with the correct bounded status code.
        try:
            first_event = await anext(iterator)
        except StopAsyncIteration as exc:
            raise MalformedUpstreamResponse() from exc

        return StreamingResponse(
            _stream_body(
                iterator,
                first_event,
                request_id=request_id,
                decision=decision,
            ),
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
