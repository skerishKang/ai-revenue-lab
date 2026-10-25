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
import time
import uuid
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Router

from app.pilot.call_ledger import (
    LedgerDraft,
    OUTCOME_ABORTED,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    new_log_id,
    origin_from_headers,
    utc_now_iso,
)
from app.pilot.call_ledger_store import record_call
from app.pilot.deferred_writes import enqueue, skipped
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import (
    InvalidRequest,
    MalformedUpstreamResponse,
    PilotError,
    StreamNotSupported,
    UnsupportedModel,
)
from app.pilot.gateway import (
    _platform_caller_denial,
    _protocol_for,
    _validate_body,
)
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.stream_types import (
    StreamEvent,
    StreamUsage,
)
from app.pilot.platform import stream_platform_chat_completions
from app.pilot import router_core as rcore
from app.pilot.stream_error_contract import public_stream_error

logger = logging.getLogger("korean-ai-platform.pilot.stream-preview")

router = Router()

_STREAM_PREVIEW_PATH = "/v1/chat/completions/stream-preview"


def _request_id() -> str:
    return f"b14stream_{uuid.uuid4().hex[:12]}"


def _error_response(exc: PilotError, request_id: str) -> JSONResponse:
    code, status_code, message = public_stream_error(exc)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
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

    # #5573 slice 3-A / #4727: a streaming tool call is served only by a route
    # whose provider adapter actually carries one.
    if body.get("tools"):
        from .tool_channel import require_stream_tool_wire
        require_stream_tool_wire(model_id)

    # Slice 12 is deliberately text-only. The installed multimodal validator
    # may accept structured content for the canonical endpoint; preview
    # streaming does not widen that contract yet.
    # #4727: the tool channel's own turns are the one documented exception. An
    # assistant turn whose answer is a call carries no text, and the result of
    # that call is the turn the model reads before its final answer.
    if any(
        not isinstance(message.get("content"), str)
        and not (message.get("role") == "assistant" and message.get("tool_calls"))
        for message in body["messages"]
    ):
        raise StreamNotSupported()

    b14_opts = body.get("business14", {})
    if b14_opts.get("allow_external_fallback") is True:
        raise StreamNotSupported()

    decision = rcore.resolve_route(model_id, b14_opts)
    # Only the existing owner-selected tier roster may be traversed. Arbitrary
    # catalog fallback remains disabled; traversal is finite and bounded by
    # the canonical route decision's eligible_fallback field.
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
    # #4317: there is no attempt budget to validate. The streaming lane walks
    # the candidates the declared product grade allows, in order.

    return body, decision


def _usage_dict(usage: StreamUsage) -> dict[str, int | None]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def _ledger_usage(usage: StreamUsage) -> dict[str, Any]:
    """The usage the ledger sees, which is the wire usage plus the reasoning part.

    The public frame keeps its existing three counts; a provider that bills
    reasoning tokens beside the answer is recorded with them, because the
    ledger has a column for exactly that number and a stored total would
    otherwise exceed the parts stored with it.
    """
    recorded = _usage_dict(usage)
    if usage.reasoning_tokens is not None:
        recorded["completion_tokens_details"] = {
            "reasoning_tokens": usage.reasoning_tokens,
        }
    return recorded


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
    if event.tool_call is not None:
        call = event.tool_call
        payload = {
            "id": call.id, "name": call.name,
            "arguments": call.arguments, "index": call.index,
        }
        # #4727: an opaque provider continuation token is relayed only when
        # the provider issued one; a call without it keeps its exact shape.
        if call.signature is not None:
            payload["signature"] = call.signature
        return b"event: tool_call\n" + _encode_data_frame(payload)
    if event.done:
        if event.finish_reason is not None:
            return b"event: done\n" + _encode_data_frame({
                "finish_reason": event.finish_reason,
            })
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
    code, _, message = public_stream_error(exc)
    payload = {
        "error": {
            "code": code,
            "message": message,
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


def _enqueue_ledger(record) -> None:
    async def write() -> None:
        status = await record_call(record)
        logger.info(
            "b14_ledger request_id=%s log_id=%s outcome=%s attempts=%d status=%s",
            record.request_id, record.log_id, record.outcome, record.attempt_count, status,
        )

    enqueue(write, request_id=record.request_id)


async def _write_terminal_ledger(
    ledger: LedgerDraft | None, request_id: str, *, error_code: str,
    elapsed_ms: int | None,
) -> None:
    """Append a failure record for a request that never produced a stream.

    A request refused before its first event still consumed gateway work and
    may have made real provider attempts. Recording only the streamed cases
    would leave every pre-token failure invisible.
    """
    from app.pilot.platform import _provider_mode

    if ledger is None or _provider_mode() == "mock" or not ledger.attempts:
        return
    try:
        record = ledger.finish(
            outcome=OUTCOME_ERROR, error_code=error_code, elapsed_ms=elapsed_ms,
        )
        _enqueue_ledger(record)
    except Exception as ledger_exc:
        skipped(request_id, ledger_exc)


async def _finalize_stream_ledger(
    ledger: LedgerDraft, candidate: dict[str, str], decision: rcore.RouteDecision,
    *, outcome: str, error_code: str | None, usage: dict[str, Any] | None,
    finish_reason: str | None, response_model: str | None,
    attempt_started: float | None, ttft_ms: int | None, fallback_used: bool,
    tools_declared: bool,
) -> None:
    """Close one streamed attempt and append its ledger row.

    This runs in the generator's ``finally`` so a client that disconnects
    mid-stream still leaves a row. A stream that produced output and was then
    cancelled consumed model tokens; dropping the record would understate
    usage and hide the abort from the operator.
    """
    elapsed = (
        int((time.perf_counter() - attempt_started) * 1000)
        if attempt_started is not None else None
    )
    protocol = _protocol_for(
        candidate.get("platform_provider_id"), candidate.get("upstream_model"),
        tools_declared=tools_declared,
    )
    ledger.record_attempt(
        provider=candidate.get("provider"), model_id=candidate.get("model_id"),
        upstream_model=candidate.get("upstream_model"), route_id=candidate.get("route_id"),
        outcome=outcome, error_code=error_code, elapsed_ms=elapsed, usage=usage,
        finish_reason=finish_reason, actual_response_model=response_model,
        protocol=protocol,
    )
    # The gate is the mode the platform adapter dispatched with, not the config
    # singleton read on its own: an explicit B14_PROVIDER_MODE wins at runtime,
    # so trusting the singleton alone could drop the record of a call that
    # really ran, or store a simulated answer as consumption.
    from app.pilot.platform import _provider_mode

    if _provider_mode() == "mock":
        return
    ledger.protocol = protocol
    ledger.ttft_ms = ttft_ms
    record = ledger.finish(
        outcome=outcome, error_code=error_code, finish_reason=finish_reason,
        elapsed_ms=elapsed, usage=usage,
        selected_model_id=candidate.get("model_id"),
        selected_provider=candidate.get("provider"),
        selected_upstream_model=candidate.get("upstream_model"),
        selected_route_id=candidate.get("route_id"),
        actual_response_model=response_model, route_mode=decision.route_mode,
        fallback_used=fallback_used,
    )
    _enqueue_ledger(record)


async def _stream_body(
    iterator: AsyncIterator[StreamEvent],
    initial_events: list[StreamEvent],
    *,
    request_id: str,
    decision: rcore.RouteDecision,
    attempt_count: int,
    fallback_used: bool,
    ledger: LedgerDraft | None = None,
    candidate: dict[str, str] | None = None,
    attempt_started: float | None = None,
    tools_declared: bool = False,
) -> AsyncIterator[bytes]:
    """Emit the primed events; after the first visible event, never switch routes."""
    # #5318: the stream lane is where TTFT is observable at all. First visible
    # output means the first non-blank token or the first completed tool call,
    # not the first frame the transport happened to send.
    outcome = OUTCOME_ABORTED
    error_code: str | None = None
    reported_usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    response_model: str | None = None
    ttft_ms: int | None = ledger.ttft_ms if ledger is not None else None

    def _observe(event: StreamEvent) -> None:
        nonlocal ttft_ms, response_model, reported_usage, finish_reason
        if event.model:
            response_model = event.model
        if event.usage is not None:
            reported_usage = _ledger_usage(event.usage)
        if event.finish_reason:
            finish_reason = event.finish_reason
        if ttft_ms is None and attempt_started is not None and (
            (isinstance(event.delta_content, str) and bool(event.delta_content.strip()))
            or event.tool_call is not None
        ):
            ttft_ms = int((time.perf_counter() - attempt_started) * 1000)

    try:
        for event in initial_events:
            _observe(event)
            yield _encode_event(
                event, request_id=request_id, decision=decision,
                attempt_count=attempt_count, fallback_used=fallback_used,
            )
            if event.done:
                outcome = OUTCOME_SUCCESS
                return

        async for event in iterator:
            _observe(event)
            yield _encode_event(
                event, request_id=request_id, decision=decision,
                attempt_count=attempt_count, fallback_used=fallback_used,
            )
            if event.done:
                outcome = OUTCOME_SUCCESS
                return
    except PilotError as exc:
        outcome = OUTCOME_ERROR
        error_code = exc.code
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
        outcome = OUTCOME_ERROR
        error_code = "internal_error"
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
        if ledger is not None and candidate is not None:
            try:
                await _finalize_stream_ledger(
                    ledger, candidate, decision, outcome=outcome,
                    error_code=error_code, usage=reported_usage,
                    finish_reason=finish_reason, response_model=response_model,
                    attempt_started=attempt_started, ttft_ms=ttft_ms,
                    fallback_used=fallback_used, tools_declared=tools_declared,
                )
            except Exception as ledger_exc:
                skipped(request_id, ledger_exc)


@router.route(_STREAM_PREVIEW_PATH, methods=["POST"])
async def pilot_stream_preview(request: Request, *, parsed_body: Any | None = None):
    """Stream a manual platform route with finite owner-tier pre-token fallback.

    Canonical gateway passes already parsed bytes to avoid re-reading JSON via
    the Cloudflare Python/ASGI bridge; the dedicated route uses the same
    canonical admission checks and keeps arbitrary external fallback disabled.
    """
    request_id = _request_id()
    handler_started = time.perf_counter()
    iterator: AsyncIterator[StreamEvent] | None = None
    ledger: LedgerDraft | None = None

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
        # #4317: every candidate the declared product grade allows is tried,
        # in order. There is no attempt ceiling to apply here.
        attempt_candidates: list[dict[str, str] | None] = [
            None,
            *fallback_candidates,
        ]
        # A declared tool decides which Google wire family serves the request,
        # so the ledger needs it before it knows who answered.
        tools_declared = bool(body.get("tools"))
        # #5318: the streaming lane is the only place TTFT can be measured, and
        # it is also where a pre-token fallback can hide a failed provider. The
        # draft stays open across candidates so both survive into one record.
        ledger = None
        try:
            ledger = LedgerDraft(
                log_id=new_log_id(), request_id=request_id, endpoint=request.url.path,
                protocol=_protocol_for(decision.platform_provider_id,
                                       decision.selected_upstream_model,
                                       tools_declared=tools_declared),
                streaming=True, requested_model_id=body["model"],
                started_at=utc_now_iso(), origin=origin_from_headers(request.headers),
            )
        except Exception as ledger_exc:
            skipped(request_id, ledger_exc)

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

            attempt_candidate = {
                "model_id": selected_model,
                "upstream_model": upstream_model,
                "provider": provider,
                "route_id": attempt_decision.selected_route_id,
                "platform_provider_id": platform_provider_id,
            }
            dispatched = False
            attempt_started = time.perf_counter()

            if tools_declared:
                # #4727: a fallback candidate is a different provider wire, so
                # the adapter check runs again for the model that will answer.
                # A candidate refused here never reached a provider, and the
                # ledger keeps that distinction.
                from .tool_channel import require_stream_tool_wire
                try:
                    require_stream_tool_wire(selected_model, platform_provider_id)
                except PilotError as exc:
                    if ledger is not None:
                        try:
                            ledger.record_attempt(
                                provider=provider, model_id=selected_model,
                                upstream_model=upstream_model,
                                route_id=attempt_candidate["route_id"], outcome="error",
                                error_code=exc.code, dispatched=False,
                                protocol=_protocol_for(platform_provider_id,
                                                       upstream_model,
                                                       tools_declared=tools_declared),
                            )
                        except Exception as ledger_exc:
                            ledger = None
                            skipped(request_id, ledger_exc)
                    raise

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
                **({"tools": body["tools"], "tool_choice": body.get("tool_choice")}
                   if body.get("tools") else {}),
                transport=transport,
            )

            initial_events: list[StreamEvent] = []
            try:
                # Buffer only pre-visible events. A recoverable provider failure
                # before the first nonblank token may try the next owner-tier
                # candidate. Once a visible token is selected, this route is final.
                dispatched = True
                while True:
                    try:
                        event = await anext(iterator)
                    except StopAsyncIteration as exc:
                        raise MalformedUpstreamResponse() from exc
                    initial_events.append(event)
                    if event.done or event.tool_call is not None or (
                        isinstance(event.delta_content, str)
                        and bool(event.delta_content.strip())
                    ):
                        break
            except PilotError as exc:
                from .opencode_go_wire import log_go_vendor_error
                log_go_vendor_error(
                    logger, exc, request_id=request_id,
                    request_path=request.url.path, attempt=attempt_index + 1,
                    fallback=attempt_index > 0,
                )
                # #5318: the attempt that just failed is the fact a fallback
                # would otherwise erase. It is written whether or not this
                # failure is retried on the next candidate.
                if ledger is not None:
                    try:
                        ledger.record_attempt(
                            provider=provider, model_id=selected_model,
                            upstream_model=upstream_model,
                            route_id=attempt_candidate["route_id"], outcome="error",
                            error_code=exc.code,
                            elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
                            usage=next((_usage_dict(event.usage)
                                        for event in reversed(initial_events)
                                        if event.usage is not None), None),
                            finish_reason=next((event.finish_reason
                                                for event in reversed(initial_events)
                                                if event.finish_reason), None),
                            dispatched=dispatched,
                            protocol=_protocol_for(platform_provider_id, upstream_model,
                                                   tools_declared=tools_declared),
                        )
                    except Exception as ledger_exc:
                        ledger = None
                        skipped(request_id, ledger_exc)
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
                    ledger=ledger,
                    candidate=attempt_candidate,
                    attempt_started=attempt_started,
                    tools_declared=tools_declared,
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
        await _write_terminal_ledger(
            ledger, request_id, error_code=exc.code,
            elapsed_ms=int((time.perf_counter() - handler_started) * 1000),
        )
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
        await _write_terminal_ledger(
            ledger, request_id, error_code="internal_error",
            elapsed_ms=int((time.perf_counter() - handler_started) * 1000),
        )
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
