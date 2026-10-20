"""HTTP/SSE gateway for manual B14 routes with owner-tier pre-token fallback.

This router does not change the canonical ``/v1/chat/completions`` endpoint.
It traverses only the finite owner-selected tier roster before the first
nonblank token; arbitrary catalog fallback stays disabled. After a visible
token, failures are terminal SSE error events and never switch providers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
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
from app.pilot.gateway import _platform_caller_denial, _validate_body
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.stream_types import (
    StreamEvent,
    StreamUsage,
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

    decision = rcore.resolve_route(model_id, b14_opts)
    # Only the existing owner-selected tier roster may be traversed. Arbitrary
    # catalog fallback remains disabled; traversal is finite and bounded by the
    # canonical route decision's max_attempts and eligible_fallback fields.
    owner_tier_fallback = any(
        code.startswith("owner_selected_tier_fallback:")
        for code in decision.reason_codes
    )
    if decision.route_mode != "manual":
        raise StreamNotSupported()
    if decision.eligible_fallback and not owner_tier_fallback:
        raise StreamNotSupported()
    if decision.fallback_allowed and not owner_tier_fallback:
        raise StreamNotSupported()
    if (
        isinstance(decision.max_attempts, bool)
        or not isinstance(decision.max_attempts, int)
        or decision.max_attempts < 1
        or decision.max_attempts > 1 + len(decision.eligible_fallback)
    ):
        raise StreamNotSupported()

    return body, decision


def _usage_dict(usage: StreamUsage) -> dict[str, int | None]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def _route_metadata(
    *,
    request_id: str,
    decision: rcore.RouteDecision,
    attempt_count: int = 1,
    fallback_used: bool = False,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "route_mode": "manual",
        "selected_provider": decision.selected_provider,
        "selected_model": decision.selected_model,
        "selected_upstream_model": decision.selected_upstream_model,
        "selected_route_id": decision.selected_route_id,
        "fallback_allowed": bool(decision.fallback_allowed),
        "fallback_used": fallback_used,
        "attempt_count": attempt_count,
        "provider_mode": runtime_config.provider_mode,
        "route_evidence_status": (
            "mock_no_upstream_call"
            if runtime_config.is_mock
            else "live_streaming_preview"
        ),
    }


def _decision_for_attempt(
    decision: rcore.RouteDecision,
    candidate: dict[str, str] | None,
    remaining: list[dict[str, str]],
) -> rcore.RouteDecision:
    """Project one owner-tier attempt without widening route authority."""
    changes: dict[str, Any] = {
        "fallback_allowed": bool(remaining),
        "eligible_fallback": remaining,
        "max_attempts": 1 + len(remaining),
    }
    if candidate is not None:
        registered = get_catalog_by_id(candidate["model_id"])
        if (
            registered is None
            or not registered.enabled
            or registered.provider != candidate["provider"]
            or registered.upstream_model != candidate["upstream_model"]
            or registered.platform_provider_id != candidate["platform_provider_id"]
            or candidate["route_id"] != f"platform:{registered.model_id}"
        ):
            raise InvalidRequest("Invalid owner-tier fallback route.")
        available, status, source, provider_id = rcore._credential_status_for(registered)
        if not available or source != "platform_secret" or not provider_id:
            raise InvalidRequest("Owner-tier fallback credential unavailable.")
        changes.update(
            selected_provider=registered.provider,
            selected_model=registered.model_id,
            selected_upstream_model=registered.upstream_model,
            selected_route_id=candidate["route_id"],
            credential_available=available,
            credential_status=status,
            credential_source=source,
            platform_provider_id=provider_id,
        )
    return replace(decision, **changes)


def _encode_data_frame(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"data: {encoded}\n\n".encode("utf-8")


def _encode_event(
    event: StreamEvent,
    *,
    request_id: str,
    decision: rcore.RouteDecision,
    attempt_count: int = 1,
    fallback_used: bool = False,
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
        "business14": _route_metadata(
            request_id=request_id,
            decision=decision,
            attempt_count=attempt_count,
            fallback_used=fallback_used,
        ),
    }
    if event.usage is not None:
        payload["usage"] = _usage_dict(event.usage)
    return _encode_data_frame(payload)


def _encode_stream_error(
    exc: PilotError,
    *,
    request_id: str,
    decision: rcore.RouteDecision,
    attempt_count: int = 1,
    fallback_used: bool = False,
) -> bytes:
    payload = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": request_id,
            "after_stream_start": True,
        },
        "business14": {
            **_route_metadata(
                request_id=request_id,
                decision=decision,
                attempt_count=attempt_count,
                fallback_used=fallback_used,
            ),
            "stream_status": "aborted",
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: error\ndata: {encoded}\n\n".encode("utf-8")


async def _close_iterator(iterator: AsyncIterator[StreamEvent]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


async def _stream_body(
    iterator: AsyncIterator[StreamEvent],
    initial_events: list[StreamEvent],
    *,
    request_id: str,
    decision: rcore.RouteDecision,
    attempt_count: int,
    fallback_used: bool,
) -> AsyncIterator[bytes]:
    """Emit the primed events; after the first visible event, never switch routes."""
    try:
        for event in initial_events:
            yield _encode_event(
                event, request_id=request_id, decision=decision,
                attempt_count=attempt_count, fallback_used=fallback_used,
            )
            if event.done:
                return

        async for event in iterator:
            yield _encode_event(
                event, request_id=request_id, decision=decision,
                attempt_count=attempt_count, fallback_used=fallback_used,
            )
            if event.done:
                return
    except PilotError as exc:
        logger.warning(
            "stream_preview_post_start_error request_id=%s code=%s attempt=%d",
            request_id,
            exc.code,
            attempt_count,
        )
        yield _encode_stream_error(
            exc, request_id=request_id, decision=decision,
            attempt_count=attempt_count, fallback_used=fallback_used,
        )
    except Exception:
        logger.error(
            "stream_preview_post_start_internal_error request_id=%s attempt=%d",
            request_id,
            attempt_count,
        )
        generic = PilotError(
            code="internal_error",
            message="스트리밍 응답 처리 중 내부 오류가 발생했습니다.",
            status_code=500,
        )
        yield _encode_stream_error(
            generic, request_id=request_id, decision=decision,
            attempt_count=attempt_count, fallback_used=fallback_used,
        )
    finally:
        await _close_iterator(iterator)


@router.route(_STREAM_PREVIEW_PATH, methods=["POST"])
async def pilot_stream_preview(request: Request, *, parsed_body: Any | None = None):
    """Stream a manual platform route with finite owner-tier pre-token fallback.

    Canonical gateway passes already parsed bytes to avoid re-reading JSON via
    the Cloudflare Python/ASGI bridge; the dedicated route uses the same
    canonical admission checks and keeps arbitrary external fallback disabled.
    """
    request_id = _request_id()
    iterator: AsyncIterator[StreamEvent] | None = None

    try:
        # The preview lane spends platform-owned Provider credentials. Refuse an
        # unproven caller before any credential is resolved or any Provider
        # request is built.
        denial = await _platform_caller_denial(request, request_id)
        if denial is not None:
            return denial

        if parsed_body is not None:
            raw = parsed_body
        else:
            try:
                raw = await request.json()
            except (ValueError, UnicodeDecodeError):
                return _invalid_json_response(request_id)

        # Validate the exact manual ID before synchronous route admission.
        if isinstance(raw, dict) and isinstance(raw.get("model"), str):
            from app.pilot.platform_secrets import ensure_route_secrets
            await ensure_route_secrets(raw["model"])
        body, decision = _validate_preview_body(raw)

        # Tests may inject MockTransport through app.state. Production has no
        # injected transport and therefore uses the provider's normal client.
        transport = getattr(request.app.state, "stream_transport", None)
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise InvalidRequest("Invalid streaming transport configuration.")

        fallback_candidates = list(decision.eligible_fallback)
        allowed_attempts = min(
            decision.max_attempts,
            1 + len(fallback_candidates),
        )
        attempt_candidates: list[dict[str, str] | None] = [
            None,
            *fallback_candidates[: max(0, allowed_attempts - 1)],
        ]

        for attempt_index, candidate in enumerate(attempt_candidates):
            remaining = [
                item for item in attempt_candidates[attempt_index + 1:]
                if item is not None
            ]
            attempt_decision = _decision_for_attempt(
                decision, candidate, remaining
            )
            if candidate is None:
                selected_model = decision.selected_model
                upstream_model = decision.selected_upstream_model
                provider = decision.selected_provider
                platform_provider_id = decision.platform_provider_id
            else:
                selected_model = candidate["model_id"]
                upstream_model = candidate["upstream_model"]
                provider = candidate["provider"]
                platform_provider_id = candidate["platform_provider_id"]

            if not platform_provider_id:
                raise InvalidRequest("platform_secret route missing provider binding.")

            iterator = stream_platform_chat_completions(
                model_id=selected_model,
                upstream_model=upstream_model,
                provider=provider,
                platform_provider_id=platform_provider_id,
                messages=body["messages"],
                temperature=body.get("temperature"),
                max_tokens=body.get("max_tokens"),
                **({"model_parameters": body["model_parameters"]}
                   if body.get("model_parameters") else {}),
                transport=transport,
            )

            initial_events: list[StreamEvent] = []
            try:
                # Buffer only pre-visible events. A recoverable provider failure
                # before the first nonblank token may try the next owner-tier
                # candidate. Once a visible token is selected, this route is final.
                while True:
                    try:
                        event = await anext(iterator)
                    except StopAsyncIteration as exc:
                        raise MalformedUpstreamResponse() from exc
                    initial_events.append(event)
                    if event.done or (
                        isinstance(event.delta_content, str)
                        and bool(event.delta_content.strip())
                    ):
                        break
            except PilotError as exc:
                await _close_iterator(iterator)
                if (
                    attempt_index + 1 < len(attempt_candidates)
                    and rcore.is_error_fallback_allowed(exc.code)
                ):
                    logger.warning(
                        "stream_preview_pre_start_fallback request_id=%s attempt=%d code=%s",
                        request_id,
                        attempt_index + 1,
                        exc.code,
                    )
                    continue
                raise

            return StreamingResponse(
                _stream_body(
                    iterator,
                    initial_events,
                    request_id=request_id,
                    decision=attempt_decision,
                    attempt_count=attempt_index + 1,
                    fallback_used=attempt_index > 0,
                ),
                status_code=200,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-store",
                    "X-Accel-Buffering": "no",
                },
            )

        raise MalformedUpstreamResponse()

    except PilotError as exc:
        if iterator is not None:
            await _close_iterator(iterator)
        logger.warning(
            "stream_preview_pre_start_error request_id=%s code=%s status=%d credential_reason=%s",
            request_id,
            exc.code,
            exc.status_code,
            getattr(exc, "credential_reason", ""),
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
