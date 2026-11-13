"""HTTP/SSE gateway for manual B14 routes with owner-tier pre-token fallback.

This router does not change the canonical ``/v1/chat/completions`` endpoint.
It traverses only the finite owner-selected tier roster before the first
nonblank token; arbitrary catalog fallback stays disabled. After a visible
token, failures are terminal SSE error events and never switch providers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
import contextlib
import asyncio
import json
import logging
import time
import uuid
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, Router

from app.pilot.call_ledger import (
    LedgerDraft,
    CREDENTIAL_POOL,
    CREDENTIAL_USER,
    OUTCOME_ABORTED,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    declared_membership_tier,
    new_log_id,
    origin_from_headers,
    utc_now_iso,
)
from app.pilot.call_ledger_store import record_call


@contextlib.asynccontextmanager
async def _first_token_attempt_scope(timeout_seconds: float, *, final_completed: bool):
    """One streaming attempt wall, with #7212's rule on the chain's last candidate.

    #7215: while a fallback candidate remains behind this attempt, a slow first
    token is cut at the streaming first-byte bound and the chain moves on. On the
    last candidate there is nothing to fall back to, so its first token may use
    the attempt budget. The attempt wall, the chain budget and the post-first-token
    idle limit are unchanged.
    """
    with final_completed_attempt(final_completed):
        async with asyncio.timeout(timeout_seconds):
            yield
from app.pilot.deferred_writes import enqueue, skipped
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import (
    InvalidRequest,
    MalformedUpstreamResponse,
    PilotError,
    StreamNotSupported,
    ToolsNotSupported,
    UpstreamTimeout,
    UnsupportedModel,
)
from app.pilot.gateway import (
    _platform_caller_denial,
    _protocol_for,
    _validate_body,
)
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.b14_timeout_policy import (
    final_completed_attempt,
    get_timeout_policy,
)
from app.pilot.stream_types import (
    StreamEvent,
    StreamUsage,
)
from app.pilot.platform import stream_platform_chat_completions
from app.pilot.prestream_retry import (
    PRESTREAM_RETRY_DELAY_SECONDS,
    PRESTREAM_RETRY_LIMIT,
    is_prestream_retryable,
)
from app.pilot.user_credential import has_credential
from app.pilot import router_core as rcore
from app.pilot.stream_error_contract import public_stream_error

logger = logging.getLogger("korean-ai-platform.pilot.stream-preview")


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
    # #6828: this metadata is returned to the caller as the response body, so it
    # names no Provider and no upstream model. Which Provider and upstream model
    # answered stays in the call ledger (`selected_provider`,
    # `selected_upstream_model`), which is where a diagnosis is read from.
    return {
        "request_id": request_id,
        "route_mode": "manual",
        "selected_model": decision.selected_model,
        "selected_route_id": decision.selected_route_id,
        "fallback_allowed": bool(decision.fallback_allowed),
        "fallback_used": fallback_used,
        "attempt_count": attempt_count,
        "provider_mode": runtime_config.provider_mode,
        # Only the request-carried lane names where its credential came from
        # (#5824 PR-3a). A platform route keeps the exact metadata it had before.
        **({"credential_source": "user"}
           if decision.credential_source == "request_byok" else {}),
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
    tools_declared: bool = False,
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
        if tools_declared and event.finish_reason is not None:
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
        # thought-summary stream: a thinking-summary fragment rides its own
        # delta field, so an answer frame and a thought frame never share a
        # content byte. The field name mirrors the provider delta B14 parsed.
        if event.delta_thought is not None:
            delta["reasoning_content"] = event.delta_thought
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
        # #6828: echo the model the caller asked for. The upstream model that
        # answered is ledger evidence, never a response field.
        "model": decision.selected_model,
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
    # #4727: the token a provider attached to this chunk's own text part. It is
    # present only when one was issued, so every other provider's frame keeps
    # its exact pre-#4727 bytes.
    if event.signature is not None:
        payload["signature"] = event.signature
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


async def _next_before_chain_deadline(
    iterator: AsyncIterator[StreamEvent], deadline: float | None,
) -> StreamEvent:
    """Get one stream event while preserving the cumulative chain deadline."""
    if deadline is None:
        return await anext(iterator)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UpstreamTimeout(timeout_reason="chain_budget")
    try:
        async with asyncio.timeout(remaining):
            return await anext(iterator)
    except TimeoutError as exc:
        raise UpstreamTimeout(timeout_reason="chain_budget") from exc


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
    timeout_reason: str | None,
    thought_summary_count: int | None = None,
    thought_summary_chars: int | None = None,
    wire_protocol: str | None = None,
    retry_index: int = 0,
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
    protocol = wire_protocol or _protocol_for(
        candidate.get("platform_provider_id"), candidate.get("upstream_model"),
        tools_declared=tools_declared,
    )
    ledger.record_attempt(
        provider=candidate.get("provider"), model_id=candidate.get("model_id"),
        upstream_model=candidate.get("upstream_model"), route_id=candidate.get("route_id"),
        outcome=outcome, error_code=error_code, elapsed_ms=elapsed, usage=usage,
        finish_reason=finish_reason, actual_response_model=response_model,
        timeout_reason=timeout_reason, protocol=protocol, retry_index=retry_index,
        # thought-summary stream: the ledger stores whether thinking summaries
        # arrived and their volume (fragment count, character length) — never
        # the thought text itself.
        thought_summary_count=thought_summary_count,
        thought_summary_chars=thought_summary_chars,
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
        # The route decision's credential plane is the only signal this lane
        # carries: a request-supplied key belongs to the caller, and everything
        # the platform resolved — keyless route included — is pool consumption.
        credential_source=CREDENTIAL_USER
        if decision.credential_source == "request_byok" else CREDENTIAL_POOL,
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
    chain_deadline: float | None = None,
    retry_index: int = 0,
) -> AsyncIterator[bytes]:
    """Emit the primed events; after the first visible event, never switch routes."""
    # #5318: the stream lane is where TTFT is observable at all. First visible
    # output means the first non-blank token or the first completed tool call,
    # not the first frame the transport happened to send.
    outcome = OUTCOME_ABORTED
    error_code: str | None = None
    timeout_reason: str | None = None
    reported_usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    response_model: str | None = None
    ttft_ms: int | None = ledger.ttft_ms if ledger is not None else None
    # thought-summary stream: the ledger counts what arrived, not what it said.
    thought_summary_count = 0
    thought_summary_chars = 0
    wire_protocol: str | None = None

    def _observe(event: StreamEvent) -> None:
        nonlocal ttft_ms, response_model, reported_usage, finish_reason
        nonlocal thought_summary_count, thought_summary_chars, wire_protocol
        if event.wire_protocol is not None:
            wire_protocol = event.wire_protocol
        if event.model:
            response_model = event.model
        if event.usage is not None:
            reported_usage = _ledger_usage(event.usage)
        if event.finish_reason:
            finish_reason = event.finish_reason
        if isinstance(event.delta_thought, str) and event.delta_thought:
            thought_summary_count += 1
            thought_summary_chars += len(event.delta_thought)
        # thought-summary stream: a thinking-summary fragment is a first byte.
        # The 15-second first-byte timeout must not fire while the model is
        # still showing its thinking.
        if ttft_ms is None and attempt_started is not None and (
            (isinstance(event.delta_content, str) and bool(event.delta_content.strip()))
            or event.tool_call is not None
            or (isinstance(event.delta_thought, str) and bool(event.delta_thought.strip()))
        ):
            ttft_ms = int((time.perf_counter() - attempt_started) * 1000)

    try:
        for event in initial_events:
            if chain_deadline is not None and time.monotonic() >= chain_deadline:
                raise UpstreamTimeout(timeout_reason="chain_budget")
            _observe(event)
            yield _encode_event(
                event, request_id=request_id, decision=decision,
                attempt_count=attempt_count, fallback_used=fallback_used,
                tools_declared=tools_declared,
            )
            if event.done:
                outcome = OUTCOME_SUCCESS
                return

        while True:
            try:
                event = await _next_before_chain_deadline(iterator, chain_deadline)
            except StopAsyncIteration:
                break
            _observe(event)
            yield _encode_event(
                event, request_id=request_id, decision=decision,
                attempt_count=attempt_count, fallback_used=fallback_used,
                tools_declared=tools_declared,
            )
            if event.done:
                outcome = OUTCOME_SUCCESS
                return
    except PilotError as exc:
        outcome = OUTCOME_ERROR
        error_code = exc.code
        timeout_reason = getattr(exc, "timeout_reason", None)
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
            exc_info=True,
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
                    timeout_reason=timeout_reason,
                    thought_summary_count=thought_summary_count or None,
                    thought_summary_chars=thought_summary_chars or None,
                    wire_protocol=wire_protocol,
                    retry_index=retry_index,
                )
            except Exception as ledger_exc:
                skipped(request_id, ledger_exc)


def _user_credential_decision(
    request_id: str, body: dict[str, Any], credential: Any
) -> rcore.RouteDecision:
    """The route record for one request-carried credential (#5824 PR-3a).

    No roster exists here: the caller named the provider, the model and the key,
    so the decision says exactly that and allows nothing to fall back to.
    ``platform_provider_id`` carries the credential's own provider id so the
    ledger's protocol projection names this wire the way it names any other
    OpenAI-compatible call; it implies no platform Provider spec and reads no
    platform binding.
    """
    return rcore.RouteDecision(
        route_mode="manual",
        selected_provider=credential.provider_id,
        selected_model=body["model"],
        selected_upstream_model=credential.upstream_model,
        selected_route_id="user_credential",
        reason_codes=["user_credential"],
        fallback_allowed=False,
        eligible_fallback=[],
        excluded_candidates=[],
        credential_available=True,
        credential_status="request_supplied",
        evidence_status="caller_supplied_credential",
        request_id=request_id,
        provider_mode=runtime_config.provider_mode,
        credential_source="request_byok",
        platform_provider_id=credential.provider_id,
    )


async def _user_credential_stream_preview(
    request: Request, request_id: str, raw: Any, handler_started: float
) -> StreamingResponse:
    """Stream one answer from the caller's own key: no pool read, no fallback.

    A failure before the first visible token is the answer; there is no next
    candidate to advance to, because a substitution would either spend a key the
    caller did not offer or answer with a model the caller did not choose.
    """
    from app.pilot.platform import stream_user_credential_chat_completions

    # The canonical validator refuses stream=true by design, so preview runs it
    # on an otherwise identical copy. That keeps one request contract for both
    # lanes instead of a second, weaker BYOK schema.
    canonical_raw = dict(raw)
    canonical_raw["stream"] = False
    body = _validate_body(canonical_raw)
    credential = body["user_credential"]
    if body.get("tools"):
        raise ToolsNotSupported(body["model"])

    transport = getattr(request.app.state, "stream_transport", None)
    if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
        raise InvalidRequest("Invalid streaming transport configuration.")

    decision = _user_credential_decision(request_id, body, credential)
    candidate = {
        "model_id": body["model"],
        "upstream_model": credential.upstream_model,
        "provider": credential.provider_id,
        "route_id": "user_credential",
        "platform_provider_id": credential.provider_id,
    }
    protocol = _protocol_for(credential.provider_id, credential.upstream_model)

    ledger: LedgerDraft | None = None
    try:
        origin = origin_from_headers(request.headers)
        # This lane applies no grade of its own: no routing, no roster. The
        # declared tier is recorded when one arrived, and the row stays unset
        # when none did — there is no server-applied default to observe here.
        origin["membership_tier"] = declared_membership_tier(
            origin, body.get("business14")
        )
        ledger = LedgerDraft(
            log_id=new_log_id(), request_id=request_id, endpoint=request.url.path,
            protocol=protocol, streaming=True, requested_model_id=body["model"],
            started_at=utc_now_iso(), origin=origin,
        )
    except Exception as ledger_exc:
        skipped(request_id, ledger_exc)

    def _record_failure(
        error_code: str, *, dispatched: bool, timeout_reason: str | None = None,
    ) -> None:
        """Close the row for an attempt that produced nothing the caller saw."""
        if ledger is None:
            return
        elapsed = int((time.perf_counter() - handler_started) * 1000)
        try:
            ledger.record_attempt(
                provider=credential.provider_id, model_id=body["model"],
                upstream_model=credential.upstream_model,
                route_id=candidate["route_id"], outcome=OUTCOME_ERROR,
                error_code=error_code, timeout_reason=timeout_reason,
                dispatched=dispatched,
                elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
                protocol=protocol,
            )
            if dispatched:
                _enqueue_ledger(ledger.finish(
                    outcome=OUTCOME_ERROR, error_code=error_code, elapsed_ms=elapsed,
                    selected_model_id=candidate["model_id"],
                    selected_provider=candidate["provider"],
                    selected_upstream_model=candidate["upstream_model"],
                    selected_route_id=candidate["route_id"],
                    route_mode=decision.route_mode, fallback_used=False,
                    credential_source=CREDENTIAL_USER,
                ))
        except Exception as ledger_exc:
            skipped(request_id, ledger_exc)

    iterator: AsyncIterator[StreamEvent] = stream_user_credential_chat_completions(
        credential=credential,
        messages=body["messages"],
        temperature=body.get("temperature"),
        max_tokens=body.get("max_tokens"),
        **({"transport": transport} if transport is not None else {}),
    )
    initial_events: list[StreamEvent] = []
    attempt_started = time.perf_counter()
    chain_deadline = time.monotonic() + get_timeout_policy().chain_budget_seconds
    dispatched = False
    try:
        while True:
            dispatched = True
            try:
                async with asyncio.timeout(max(0.001, chain_deadline - time.monotonic())):
                    event = await anext(iterator)
            except StopAsyncIteration as exc:
                raise MalformedUpstreamResponse() from exc
            except TimeoutError as exc:
                raise UpstreamTimeout(timeout_reason="chain_budget") from exc
            initial_events.append(event)
            if event.done or event.tool_call is not None or (
                isinstance(event.delta_content, str)
                and bool(event.delta_content.strip())
            ):
                break
    except PilotError as exc:
        _record_failure(
            exc.code, dispatched=dispatched,
            timeout_reason=getattr(exc, "timeout_reason", None),
        )
        await _close_iterator(iterator)
        raise
    except Exception:
        _record_failure("internal_error", dispatched=dispatched)
        await _close_iterator(iterator)
        raise

    return StreamingResponse(
        _stream_body(
            iterator,
            initial_events,
            request_id=request_id,
            decision=decision,
            attempt_count=1,
            fallback_used=False,
            ledger=ledger,
            candidate=candidate,
            attempt_started=attempt_started,
            tools_declared=False,
            chain_deadline=chain_deadline,
        ),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


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
        # request is built. The request-carried credential lane is refused by the
        # same gate: who is calling is a separate question from whose key the
        # call spends (#5224 contract, extended by #5824 PR-3a).
        denial = await _platform_caller_denial(request, request_id)
        if denial is not None:
            return denial

        # #5824 PR-3a: a body-carried credential selects its own single-attempt
        # lane below the caller gate.
        probe = parsed_body
        if probe is None:
            try:
                probe = await request.json()
            except (ValueError, UnicodeDecodeError):
                probe = None
        if has_credential(probe):
            return await _user_credential_stream_preview(
                request, request_id, probe, handler_started
            )

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
        # #4317: candidates remain in declared order. Their physical calls
        # share B14's cumulative chain deadline below.
        attempt_candidates: list[dict[str, str] | None] = [
            None,
            *fallback_candidates,
        ]
        # A declared tool decides which Google wire family serves the request,
        # so the ledger needs it before it knows who answered.
        tools_declared = bool(body.get("tools"))
        # #6724: every physical dispatch, a same-route retry included. The
        # streamed answer's metadata reports what actually ran, not the index
        # of the candidate that happened to answer.
        physical_attempts = 0
        # #5318: the streaming lane is the only place TTFT can be measured, and
        # it is also where a pre-token fallback can hide a failed provider. The
        # draft stays open across candidates so both survive into one record.
        ledger = None
        timeout_policy = get_timeout_policy()
        chain_deadline = time.monotonic() + timeout_policy.chain_budget_seconds
        try:
            origin = origin_from_headers(request.headers)
            # Record the grade the routing actually applied: the validated
            # body tier, else the header fallback, else the Free default
            # ``resolve_route`` applied for an undeclared grade.
            origin["membership_tier"] = (
                declared_membership_tier(origin, body.get("business14")) or "free"
            )
            ledger = LedgerDraft(
                log_id=new_log_id(), request_id=request_id, endpoint=request.url.path,
                protocol=_protocol_for(decision.platform_provider_id,
                                       decision.selected_upstream_model,
                                       tools_declared=tools_declared),
                streaming=True, requested_model_id=body["model"],
                started_at=utc_now_iso(), origin=origin,
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
            # #6724: one retry inside this candidate when the attempt failed
            # before a single answer byte was selected. Staying inside the
            # candidate is what keeps the retry on the same model and route.
            retry_index = 0
            while True:
                dispatched = False
                attempt_started = time.perf_counter()
                physical_attempts += 1
                remaining_chain = chain_deadline - time.monotonic()
                if remaining_chain <= 0:
                    timeout_error = UpstreamTimeout(timeout_reason="chain_budget")
                    if ledger is not None:
                        try:
                            ledger.record_attempt(
                                provider=provider, model_id=selected_model,
                                upstream_model=upstream_model,
                                route_id=attempt_candidate["route_id"],
                                outcome=OUTCOME_ERROR, error_code=timeout_error.code,
                                timeout_reason="chain_budget", dispatched=False,
                                retry_index=retry_index,
                                protocol=_protocol_for(platform_provider_id, upstream_model,
                                                       tools_declared=tools_declared),
                            )
                        except Exception as ledger_exc:
                            ledger = None
                            skipped(request_id, ledger_exc)
                    raise timeout_error
                attempt_timeout = min(timeout_policy.attempt_seconds, remaining_chain)
                chain_limits_attempt = remaining_chain <= timeout_policy.attempt_seconds

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

                # #7430: the owner-tier plain surface (no declared tools) rides
                # the native adapter first on this provider family; the
                # compatible endpoint behind the plain wire was the lane that
                # degraded while the native adapter kept answering. Manual
                # preview routes keep today's exact wire.
                native_plain_first = (
                    not tools_declared
                    and platform_provider_id == "google"
                    and (
                        attempt_candidate.get("reason") == "owner_selected_tier_fallback"
                        or any(
                            code.startswith("owner_selected_tier_fallback:")
                            for code in decision.reason_codes
                        )
                    )
                )
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
                    native_plain_first=native_plain_first,
                )

                initial_events: list[StreamEvent] = []
                try:
                    # Buffer only pre-visible events. A recoverable provider failure
                    # before the first nonblank token may retry this same route once,
                    # then try the next owner-tier candidate. Once a visible token is
                    # selected, this route is final.
                    dispatched = True
                    try:
                        async with _first_token_attempt_scope(
                            attempt_timeout,
                            final_completed=attempt_index == len(attempt_candidates) - 1,
                        ):
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
                                # thought-summary stream: a thinking-summary
                                # fragment is a first byte. Waiting for answer
                                # text here would let the 15-second first-byte
                                # timeout fire while the model is still thinking.
                                if (
                                    isinstance(event.delta_thought, str)
                                    and bool(event.delta_thought.strip())
                                ):
                                    break
                    except TimeoutError as exc:
                        timeout_reason = (
                            "chain_budget" if chain_limits_attempt else "attempt_total"
                        )
                        raise UpstreamTimeout(timeout_reason=timeout_reason) from exc
                except PilotError as exc:
                    from .opencode_go_wire import log_go_vendor_error
                    log_go_vendor_error(
                        logger, exc, request_id=request_id,
                        request_path=request.url.path, attempt=physical_attempts,
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
                                http_status=getattr(exc, "upstream_status", None),
                                error_code=exc.code,
                                retry_index=retry_index,
                                timeout_reason=getattr(exc, "timeout_reason", None),
                                elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
                                usage=next((_usage_dict(event.usage)
                                            for event in reversed(initial_events)
                                            if event.usage is not None), None),
                                finish_reason=next((event.finish_reason
                                                    for event in reversed(initial_events)
                                                    if event.finish_reason), None),
                                dispatched=dispatched,
                                protocol=getattr(exc, "wire_protocol", None) or _protocol_for(
                                    platform_provider_id, upstream_model, tools_declared=tools_declared),
                            )
                        except Exception as ledger_exc:
                            ledger = None
                            skipped(request_id, ledger_exc)
                    await _close_iterator(iterator)
                    # #6724: no answer byte was selected yet, so a connect
                    # failure, an upstream 5xx or an error-envelope first frame
                    # may be dispatched once more on this same route. The chain
                    # budget still has to cover the wait.
                    if (
                        retry_index < PRESTREAM_RETRY_LIMIT
                        and is_prestream_retryable(exc)
                        # #6724: retry only the attempt with no successor left.
                        # A candidate that still has an owner-roster candidate
                        # behind it keeps #4317's one-call-per-candidate walk.
                        and attempt_index == len(attempt_candidates) - 1
                        and chain_deadline - time.monotonic() > PRESTREAM_RETRY_DELAY_SECONDS
                    ):
                        retry_index += 1
                        logger.warning(
                            "stream_preview_pre_start_retry request_id=%s attempt=%d code=%s delay_s=%.1f",
                            request_id,
                            physical_attempts,
                            exc.code,
                            PRESTREAM_RETRY_DELAY_SECONDS,
                        )
                        await asyncio.sleep(PRESTREAM_RETRY_DELAY_SECONDS)
                        continue
                    if (
                        attempt_index + 1 < len(attempt_candidates)
                        and rcore.is_error_fallback_allowed(exc.code, reason=getattr(exc, "reason", None))
                    ):
                        logger.warning(
                            "stream_preview_pre_start_fallback request_id=%s attempt=%d code=%s",
                            request_id,
                            attempt_index + 1,
                            exc.code,
                        )
                        break
                    raise

                return StreamingResponse(
                    _stream_body(
                        iterator,
                        initial_events,
                        request_id=request_id,
                        decision=attempt_decision,
                        attempt_count=physical_attempts,
                        fallback_used=attempt_index > 0,
                        ledger=ledger,
                        candidate=attempt_candidate,
                        attempt_started=attempt_started,
                        tools_declared=tools_declared,
                        chain_deadline=chain_deadline,
                        retry_index=retry_index,
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
            exc_info=True,
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


router = Router(
    routes=[
        Route(_STREAM_PREVIEW_PATH, pilot_stream_preview, methods=["POST"]),
    ]
)
