"""Staged b14/auto HTTP/SSE gateway backed by Router streaming execution.

This surface deliberately does not promote streaming on the canonical
``/v1/chat/completions`` endpoint.  Its job is to prove that automatic route
selection, hard capability filters, bounded pre-content fallback, and
post-content route commitment survive the HTTP/SSE boundary before a product
client depends on them.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import logging
import uuid
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Router

from app.pilot.errors import InvalidRequest, PilotError, StreamNotSupported
from app.pilot.gateway import _validate_body
from app.pilot.openrouter_config import openrouter_config
from app.pilot.openrouter_stream import stream_openrouter_chat_completions
from app.pilot import router_core as rcore
from app.pilot.streaming_router import RouterStreamEvent, stream_routed_chat_completions

logger = logging.getLogger("korean-ai-platform.pilot.auto-stream-preview")

router = Router()

_AUTO_STREAM_PREVIEW_PATH = "/v1/chat/completions/auto-stream-preview"

_PRESTART_ERRORS: dict[str, tuple[int, str]] = {
    "upstream_auth_failed": (401, "Provider 인증에 실패했습니다."),
    "upstream_rate_limited": (429, "Provider rate limit에 도달했습니다. 잠시 후 다시 시도하십시오."),
    "upstream_timeout": (504, "Provider 요청 시간이 초과되었습니다. 나중에 다시 시도하십시오."),
    "upstream_server_error": (502, "Provider 서버 오류가 발생했습니다. 나중에 다시 시도하십시오."),
    "upstream_client_error": (502, "Provider가 요청을 거부했습니다."),
    "malformed_upstream_response": (502, "Provider 응답 형식이 올바르지 않습니다."),
    "upstream_response_too_large": (502, "Provider 응답이 허용된 크기를 초과하여 중단되었습니다."),
    "pilot_not_configured": (503, "Business 14 Provider 연결이 준비되지 않았습니다."),
    "no_safe_route": (503, "안전한 라우팅 경로를 찾을 수 없습니다."),
    "empty_stream_answer": (502, "Provider가 표시 가능한 답변을 반환하지 않았습니다."),
    "stream_ended_without_done": (502, "Provider 스트리밍 응답이 정상적으로 종료되지 않았습니다."),
    "stream_execution_error": (502, "Provider 스트리밍 실행에 실패했습니다."),
}


def _gateway_request_id() -> str:
    return f"b14autostream_{uuid.uuid4().hex[:12]}"


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


def _validate_auto_preview_body(raw: Any) -> tuple[dict[str, Any], rcore.RouteDecision]:
    """Reuse canonical validation, then require the staged auto-stream contract."""
    if not isinstance(raw, dict):
        raise InvalidRequest("Auto streaming preview request body must be a JSON object.")
    if raw.get("stream") is not True:
        raise InvalidRequest("Auto streaming preview requires stream=true.")

    canonical_raw = dict(raw)
    canonical_raw["stream"] = False
    body = _validate_body(canonical_raw)

    if body["model"] != "b14/auto":
        raise InvalidRequest("Auto streaming preview requires model=b14/auto.")

    # The staged Router stream remains text-only.  The installed canonical
    # multimodal validator may accept structured content, but this route does
    # not widen the provider streaming contract yet.
    if any(not isinstance(message.get("content"), str) for message in body["messages"]):
        raise StreamNotSupported()

    decision = rcore.resolve_route("b14/auto", body.get("business14", {}))
    if decision.route_mode != "auto":
        raise InvalidRequest("Auto streaming preview could not resolve an automatic route.")
    return body, decision


def _usage_dict(event: RouterStreamEvent) -> dict[str, int | None] | None:
    if event.usage is None:
        return None
    return {
        "prompt_tokens": event.usage.prompt_tokens,
        "completion_tokens": event.usage.completion_tokens,
        "total_tokens": event.usage.total_tokens,
    }


def _route_metadata(
    event: RouterStreamEvent,
    decision: rcore.RouteDecision,
) -> dict[str, Any]:
    return {
        "request_id": event.request_id,
        "route_mode": event.route_mode,
        "selected_provider": event.selected_provider,
        "selected_model": event.selected_model,
        "selected_upstream_model": event.selected_upstream_model,
        "actual_response_model": event.actual_response_model,
        "selected_route_id": event.selected_route_id,
        "reason_codes": list(event.reason_codes),
        "fallback_allowed": decision.fallback_allowed,
        "fallback_used": event.fallback_used,
        "attempt_count": event.attempt,
        "committed": event.committed,
        "provider_mode": decision.provider_mode,
        "route_evidence_status": (
            "mock_no_upstream_call"
            if openrouter_config.is_mock
            else "live_streaming_router_preview"
        ),
    }


def _encode_data_frame(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"data: {encoded}\n\n".encode("utf-8")


def _safe_error_details(code: str) -> tuple[int, str]:
    return _PRESTART_ERRORS.get(
        code,
        (502, "Provider 스트리밍 응답을 안전하게 완료하지 못했습니다."),
    )


def _pilot_error_from_router_event(event: RouterStreamEvent) -> PilotError:
    code = event.error_code or "stream_execution_error"
    status_code, message = _safe_error_details(code)
    return PilotError(code=code, message=message, status_code=status_code)


def _encode_stream_error(
    *,
    code: str,
    message: str,
    event: RouterStreamEvent,
    decision: rcore.RouteDecision,
) -> bytes:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "request_id": event.request_id,
            "after_stream_start": True,
        },
        "business14": {
            **_route_metadata(event, decision),
            "stream_status": "aborted",
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: error\ndata: {encoded}\n\n".encode("utf-8")


def _encode_router_event(
    event: RouterStreamEvent,
    decision: rcore.RouteDecision,
) -> bytes:
    if event.error_code is not None:
        _, message = _safe_error_details(event.error_code)
        return _encode_stream_error(
            code=event.error_code,
            message=message,
            event=event,
            decision=decision,
        )
    if event.done:
        return b"data: [DONE]\n\n"

    usage = _usage_dict(event)
    if usage is not None and event.delta_content is None and event.finish_reason is None:
        choices: list[dict[str, Any]] = []
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
        "business14": _route_metadata(event, decision),
    }
    if usage is not None:
        payload["usage"] = usage
    return _encode_data_frame(payload)


async def _close_iterator(iterator: Any) -> None:
    closer = getattr(iterator, "aclose", None)
    if callable(closer):
        try:
            await closer()
        except Exception:
            # Cleanup must not replace the already-normalized gateway result.
            pass


async def _prime_until_visible(
    iterator: AsyncIterator[RouterStreamEvent],
) -> tuple[list[RouterStreamEvent], RouterStreamEvent]:
    """Hold HTTP 200 until Router execution actually produces visible content."""
    buffered: list[RouterStreamEvent] = []
    while True:
        try:
            event = await anext(iterator)
        except StopAsyncIteration as exc:
            raise PilotError(
                code="empty_stream_answer",
                message="Provider가 표시 가능한 답변을 반환하지 않았습니다.",
                status_code=502,
            ) from exc

        if event.error_code is not None:
            if event.committed:
                # A committed error before the gateway has observed visible
                # content is an inconsistent internal contract; fail closed.
                raise PilotError(
                    code="stream_execution_error",
                    message="Provider 스트리밍 실행 상태를 확인할 수 없습니다.",
                    status_code=502,
                )
            raise _pilot_error_from_router_event(event)

        if event.delta_content:
            if not event.committed:
                raise PilotError(
                    code="stream_execution_error",
                    message="Provider 스트리밍 실행 상태를 확인할 수 없습니다.",
                    status_code=502,
                )
            return buffered, event

        if event.done:
            raise PilotError(
                code="empty_stream_answer",
                message="Provider가 표시 가능한 답변을 반환하지 않았습니다.",
                status_code=502,
            )

        buffered.append(event)


async def _stream_body(
    iterator: AsyncIterator[RouterStreamEvent],
    buffered: list[RouterStreamEvent],
    first_visible: RouterStreamEvent,
    *,
    decision: rcore.RouteDecision,
) -> AsyncIterator[bytes]:
    """Emit the winning attempt only after the visible-token commitment gate."""
    last_event = first_visible
    try:
        for event in buffered:
            yield _encode_router_event(event, decision)
        yield _encode_router_event(first_visible, decision)

        async for event in iterator:
            last_event = event
            if event.error_code is not None:
                yield _encode_router_event(event, decision)
                return
            yield _encode_router_event(event, decision)
            if event.done:
                return
    except asyncio.CancelledError:
        raise
    except (GeneratorExit, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        logger.error(
            "auto_stream_preview_post_start_internal_error request_id=%s",
            last_event.request_id,
        )
        yield _encode_stream_error(
            code="internal_error",
            message="스트리밍 응답 처리 중 내부 오류가 발생했습니다.",
            event=last_event,
            decision=decision,
        )
    finally:
        await _close_iterator(iterator)


@router.route(_AUTO_STREAM_PREVIEW_PATH, methods=["POST"])
async def pilot_auto_stream_preview(request: Request):
    """Preview Router-owned b14/auto execution as staged SSE."""
    gateway_request_id = _gateway_request_id()
    iterator: AsyncIterator[RouterStreamEvent] | None = None

    try:
        try:
            raw = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _invalid_json_response(gateway_request_id)

        body, decision = _validate_auto_preview_body(raw)

        transport = getattr(request.app.state, "openrouter_stream_transport", None)
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise InvalidRequest("Invalid streaming transport configuration.")

        def stream_call(**kwargs: Any):
            return stream_openrouter_chat_completions(**kwargs, transport=transport)

        iterator = stream_routed_chat_completions(
            decision=decision,
            messages=body["messages"],
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            stream_call=stream_call,
        )

        buffered, first_visible = await _prime_until_visible(iterator)

        return StreamingResponse(
            _stream_body(
                iterator,
                buffered,
                first_visible,
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
        request_id = (
            getattr(exc, "request_id", None)
            if isinstance(getattr(exc, "request_id", None), str)
            else gateway_request_id
        )
        logger.warning(
            "auto_stream_preview_pre_start_error request_id=%s code=%s status=%d",
            request_id,
            exc.code,
            exc.status_code,
        )
        return _error_response(exc, request_id)
    except Exception:
        if iterator is not None:
            await _close_iterator(iterator)
        logger.error(
            "auto_stream_preview_pre_start_internal_error request_id=%s",
            gateway_request_id,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "자동 스트리밍 요청을 준비하는 중 내부 오류가 발생했습니다.",
                    "request_id": gateway_request_id,
                }
            },
        )
