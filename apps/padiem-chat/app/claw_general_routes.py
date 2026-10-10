"""B54 Claw general composer → canonical P01 Engine lane (#3539).

The generic Claw composer is a first-class B54 product request. This route
reuses the exact #3382 canonical lane the explicit manual execute route already
drives:

    Claw general composer
    → POST /api/claw/general
    → existing claw_p01_adapter (P01CoreOrchestrationAdapter)
    → P01EngineOrchestrationClient
    → P01_ENGINE_SERVICE (Service Binding)
    → Engine
    → B14
    → assistant result

It is deliberately NOT the manual-intake/quote/order flow and NOT the standalone
B62 ``/api/chat`` composer. There is NO direct-B14 fallback: an unbound P01 lane
fails closed (503) instead of silently degrading into the standalone B62
``/api/chat/stream`` route, and the canonical USER subject is resolved
SERVER-SIDE from the signed Padiem session before the usage gate and before any
P01/Engine dispatch.

No second Engine service binding, identity authority or entitlement authority is
introduced here; the projection vocabulary is the one ``claw_routes`` already
owns.
"""

from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    ProductTierRoutesError,
    active_route_for,
)

from kagent.p01_adapter import (
    P01AdapterError,
    P01CoreOrchestrationAdapter,
    P01DispatchClass,
    P01_FAILURE_DETAIL_CONTRACT,
    P01_FAILURE_DETAIL_UNKNOWN,
    validate_explicit_b14_model_id,
)
from kagent.p01_run_flow import create_claw_run

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_live_canary import live_stream_allowed
from .claw_general_run_history import project_completed_general_run
from .claw_routes import (
    _BROWSER_TIER_MAP,
    _NO_STORE_HEADERS,
    _error,
    _safe_composition_diagnostic,
    _safe_engine_failure_detail,
    _usage_gate_denial,
)
from .dispatch_quota import _clear_reservation, _refund_active_reservation

MAX_CLAW_GENERAL_BODY_BYTES = 64 * 1024  # 64 KiB
MAX_CLAW_GENERAL_MESSAGE_CHARS = 8_000
MAX_CLAW_GENERAL_MESSAGES = 40
CLAW_LIVE_REQUEST_HEADER = "X-Padiem-Claw-Live"
CLAW_LIVE_REQUEST_MARKER = "p01-events-v1"
_CLAW_GENERAL_ROLES = frozenset({"user", "assistant"})

# NO_EXECUTABLE_ROUTE product HOLD (#3568/#3566): these adapter codes mean the
# run was refused before any Engine/B14/provider dispatch because the selected
# tier has no executable route yet. They are product states, not engine
# failures, so they must not surface as a generic 502 engine error.
_MODEL_HOLD_ERROR_CODES = frozenset({"tier_hold", "max_tier_hold"})
_MODEL_HOLD_USER_MESSAGE = (
    "선택한 AI 모델을 현재 사용할 수 없습니다. 다른 모델을 선택해 주세요."
)

# #3655 one-shot canary evidence seam. The final Production canary needs the
# existing correlation/route refs projected to the caller, but the normal user
# surface must stay unchanged. Evidence headers are therefore emitted ONLY when
# the request carries the exact opt-in marker below (the owner one-shot harness
# sets it); every value is grammar-checked and omitted when it does not match.
# Values are opaque refs/counts from existing P01/B14 metadata seams — never
# prompts, answers, credentials, or free text.
CLAW_EVIDENCE_REQUEST_HEADER = "X-Padiem-Claw-Evidence"
CLAW_EVIDENCE_MARKER = "one-shot"
_CLAW_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{24}$")
_EVIDENCE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


def _evidence_header(
    name: str,
    value: Any,
    pattern: re.Pattern[str] = _EVIDENCE_VALUE_RE,
) -> tuple[str, str] | None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        return None
    return name, value


def _claw_evidence_response_headers(claw_run_id: str | None, outcome: Any) -> dict[str, str]:
    """Bounded opt-in canary evidence headers (#3655).

    Emitted only in evidence mode. A value that fails its grammar is omitted
    rather than degraded, so the canary can never record a fabricated ref.
    """
    headers: dict[str, str] = {}
    run_pair = _evidence_header("X-Padiem-Claw-Run-Id", claw_run_id, _CLAW_RUN_ID_RE)
    if run_pair is not None:
        headers[run_pair[0]] = run_pair[1]
    if outcome is None:
        return headers
    orch_pair = _evidence_header(
        "X-Padiem-Orchestration-Run-Id", getattr(outcome, "p01_run_id", None)
    )
    if orch_pair is not None:
        headers[orch_pair[0]] = orch_pair[1]
    route_pair = _evidence_header(
        "X-Padiem-Selected-Route-Id", getattr(outcome, "selected_route_id", None)
    )
    if route_pair is not None:
        headers[route_pair[0]] = route_pair[1]
    attempts = getattr(outcome, "provider_attempt_count", None)
    if isinstance(attempts, int) and not isinstance(attempts, bool) and 0 <= attempts <= 99:
        headers["X-Padiem-Provider-Attempts"] = str(attempts)
    fallback_used = getattr(outcome, "fallback_used", None)
    if isinstance(fallback_used, bool):
        headers["X-Padiem-Fallback-Used"] = "true" if fallback_used else "false"
    return headers


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def _claw_general_sse(
    answer: str,
    evidence_headers: dict[str, str] | None = None,
    *,
    history: tuple[dict[str, object], ...] = (),
) -> Response:
    """Bounded terminal SSE, optionally preceded by real *post-execution* history.

    The current Engine client is synchronous: all P01 events are only available
    AFTER the run. Never misrepresent this event history as live progress.
    Legacy clients still see their canonical delta + done frames unchanged.
    """
    headers = {"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"}
    if evidence_headers:
        headers.update(evidence_headers)
    frames = b""
    if isinstance(history, tuple) and len(history) <= 128:
        # Fixed public fields only: no free-form message/metadata/tool input.
        keys = ("event_id", "run_id", "trace_id", "app_id", "kind", "sequence", "timestamp_iso")
        for event in history:
            if not isinstance(event, dict) or any(key not in event for key in keys):
                frames = b""  # fail closed on malformed provider/history data
                break
            frames += _sse_frame("p01_event", {
                **{key: event[key] for key in keys}, "delivery": "post_execution",
            })
    frames += _sse_frame("delta", {"delta": answer}) + _sse_frame("done", {"done": True})
    return Response(
        frames,
        status_code=200,
        media_type="text/event-stream",
        headers=headers,
    )


def _claw_general_user_text(data: dict[str, Any]) -> tuple[str | None, JSONResponse | None]:
    """Extract the bounded latest user text from the shared chat message shape.

    Reuses the same ``messages`` contract the standalone B62 chat composer
    already sends, so the browser keeps one payload shape. Only the last user
    turn becomes the P01 task text; a malformed, empty or over-bound message set
    fails closed before any quota or dispatch.
    """
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return None, _error(400, "invalid_messages", "메시지를 입력해 주세요.")
    if len(messages) > MAX_CLAW_GENERAL_MESSAGES:
        return None, _error(400, "too_many_messages", "메시지가 너무 많습니다.")
    last_user: str | None = None
    for item in messages:
        if not isinstance(item, dict):
            return None, _error(400, "invalid_messages", "메시지 형식이 올바르지 않습니다.")
        role = item.get("role")
        content = item.get("content")
        if role not in _CLAW_GENERAL_ROLES or not isinstance(content, str):
            return None, _error(400, "invalid_messages", "메시지 형식이 올바르지 않습니다.")
        if len(content) > MAX_CLAW_GENERAL_MESSAGE_CHARS:
            return None, _error(
                400,
                "message_too_long",
                f"메시지는 {MAX_CLAW_GENERAL_MESSAGE_CHARS}자 이하로 입력해 주세요.",
            )
        if role == "user":
            last_user = content
    text = (last_user or "").strip()
    if not text:
        return None, _error(400, "invalid_messages", "메시지를 입력해 주세요.")
    return text, None


async def claw_general_capabilities(request: Request) -> JSONResponse:
    """Read-only server capability, not a read acknowledgment or user authority."""
    from .auth_routes import auth_ready, current_user_id

    adapter = getattr(request.app.state, "claw_p01_adapter", None)
    runner = getattr(adapter, "_runner", None)
    enabled = (
        auth_ready(request)
        and current_user_id(request) is not None
        and getattr(request.app.state, "claw_live_sse_enabled", False) is True
        and callable(getattr(runner, "run_stream", None))
    )
    # Capability remains session-specific and read-only; all CP-verified users
    # are eligible when the server flag is enabled, never anonymous callers.
    if enabled and getattr(adapter, "subject_identity_lane", False) is True:
        from .b54_canonical_session import resolve_current_b54_canonical_session
        session = await resolve_current_b54_canonical_session(request)
        enabled = session is not None and live_stream_allowed(
            request.app.state, session.auth_session.subject.subject_id
        )
    else:
        enabled = False
    return JSONResponse(
        {"live_events_available": bool(enabled)},
        headers=_NO_STORE_HEADERS,
    )


async def claw_general_execute(request: Request) -> JSONResponse | Response:
    """Run one generic B54 Claw request through the canonical P01 Engine lane (#3539).

    Reuses the existing #3382 authority end to end: ``claw_p01_adapter`` composed
    from trusted Worker bindings, the canonical USER subject resolved server-side
    from the signed Padiem session, the existing usage gate, and the existing P01
    result projection. The product boundary stays intact:

    - the canonical subject is resolved BEFORE the usage gate and BEFORE any
      P01/Engine dispatch, and is never read from or returned to the browser;
    - an unbound adapter fails closed with 503 ``engine_not_configured`` — this
      route never falls through to the standalone B62 direct-B14 chat route;
    - no manual-intake/quote/order, B66, connector, Memory or sandbox semantics
      are involved.
    """
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")

    try:
        raw_body = await read_bounded_request_body(
            request,
            max_bytes=MAX_CLAW_GENERAL_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    user_text, text_error = _claw_general_user_text(data)
    if text_error is not None:
        return text_error

    raw_tier = data.get("tier", "plus")
    if not isinstance(raw_tier, str):
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다.")
    product_tier = _BROWSER_TIER_MAP.get(raw_tier.strip().lower())
    if product_tier is None:
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다.")
    raw_model = data.get("model_id")
    selected_model_id: str | None = None
    if raw_model is not None:
        try:
            selected_model_id = validate_explicit_b14_model_id(raw_model)
        except P01AdapterError:
            return _error(422, "invalid_selected_model", "등록된 B14 모델 ID 하나를 선택해 주세요.")
        if product_tier is not ProductTierLabel.PLUS:
            return _error(422, "explicit_model_tier_unsupported", "모델 직접 선택은 현재 Plus에서만 지원됩니다.")
    try:
        tier_route = active_route_for(product_tier)
    except ProductTierRoutesError:
        return _error(503, "tier_unavailable", "AI 등급 설정을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if selected_model_id is None and (tier_route is None or not tier_route.model_id):
        return _error(503, "tier_unavailable", "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.")

    # #3382/#3539: the canonical USER subject is resolved SERVER-SIDE before the
    # usage gate and before any P01/Engine dispatch, so a failed revalidation
    # never consumes quota and never reaches a provider.
    adapter: P01CoreOrchestrationAdapter | None = getattr(
        request.app.state, "claw_p01_adapter", None
    )
    subject_id: str | None = None
    if adapter is not None and getattr(
        adapter, "subject_identity_lane", False
    ) is True:
        from .b54_canonical_session import resolve_current_b54_canonical_session

        b54_session = await resolve_current_b54_canonical_session(request)
        if b54_session is None:
            return _error(
                403,
                "canonical_b54_session_unavailable",
                "인증된 Claw 실행 권한을 확인할 수 없습니다.",
            )
        subject_id = b54_session.auth_session.subject.subject_id

    live_requested = (
        request.headers.get(CLAW_LIVE_REQUEST_HEADER, "").strip()
        == CLAW_LIVE_REQUEST_MARKER
    )
    if live_requested and not live_stream_allowed(request.app.state, subject_id):
        # Admission is pre-quota, pre-Engine and cannot be broadened by
        # a forged browser header or a stale GET capability response.
        return _error(503, "claw_live_stream_unavailable", "Claw 실시간 실행 상태를 사용할 수 없습니다.")

    denial = await _usage_gate_denial(request)
    if denial is not None:
        return denial

    if adapter is None:
        # No composed P01 lane exists, so the consumed authorization is provably
        # un-dispatched: compensate the exact receipt (#2226). This route has no
        # direct-B14 fallback (#3539); it fails closed instead.
        await _refund_active_reservation()
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "engine_not_configured",
                    "message": "Engine 클라이언트가 설정되지 않았습니다.",
                    "detail": _safe_composition_diagnostic(request),
                },
            },
            status_code=503,
            headers=_NO_STORE_HEADERS,
        )

    # #3930: An explicitly requested live SSE relay requires BOTH the reviewed
    # server authority and the canonical P01 stream port. No silent fallback to
    # completed requests, direct B14, or an unapproved UI mode is permitted.
    if live_requested:
        runner = getattr(adapter, "_runner", None)
        if (
            getattr(request.app.state, "claw_live_sse_enabled", False) is not True
            or not callable(getattr(runner, "run_stream", None))
        ):
            await _refund_active_reservation()
            return _error(503, "claw_live_stream_unavailable", "Claw 실시간 실행 상태를 사용할 수 없습니다.")

    run = create_claw_run("padiem-chat", user_text)

    # #3655: evidence mode is opt-in per request; normal callers see the exact
    # same response surface as before.
    evidence_requested = (
        request.headers.get(CLAW_EVIDENCE_REQUEST_HEADER, "").strip() == CLAW_EVIDENCE_MARKER
    )

    if live_requested:
        if evidence_requested:
            await _refund_active_reservation()
            return _error(422, "live_evidence_mode_unsupported", "실시간 상태와 감사 증거 요청은 동시에 사용할 수 없습니다.")
        from .claw_live_events import live_claw_sse
        live_args = {"product_tier": product_tier, "subject_id": subject_id}
        if selected_model_id is not None:
            live_args["selected_model_id"] = selected_model_id
        return live_claw_sse(adapter, run, live_args)

    try:
        dispatch_args = {"product_tier": product_tier, "subject_id": subject_id}
        if selected_model_id is not None:
            dispatch_args["selected_model_id"] = selected_model_id
        outcome = await adapter.execute(run, **dispatch_args)
    except P01AdapterError as exc:
        if exc.dispatch_class == P01DispatchClass.NOT_DISPATCHED:
            await _refund_active_reservation()
        else:
            _clear_reservation()
        if exc.code in _MODEL_HOLD_ERROR_CODES:
            # NO_EXECUTABLE_ROUTE product HOLD (#3568): the run never dispatched,
            # so the user sees a bounded model-unavailable state instead of a
            # generic engine failure. Same code family as the pre-dispatch
            # tier_unavailable projection used by the other tiers. Evidence
            # mode (#3655 seam) carries only the route-minted Claw run id on
            # this path — no orchestration ref, selected route, provider
            # attempts, or fallback, because no orchestration run materialized.
            # The HOLD projection stays 503 and never becomes an
            # engine_execution_failed.
            hold_headers = dict(_NO_STORE_HEADERS)
            if evidence_requested:
                hold_headers.update(_claw_evidence_response_headers(run.run_id, None))
            return JSONResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "tier_unavailable",
                        "message": _MODEL_HOLD_USER_MESSAGE,
                    },
                },
                status_code=503,
                headers=hold_headers,
            )
        failure_headers = dict(_NO_STORE_HEADERS)
        if evidence_requested:
            # The outcome never materialized, so only the route-minted Claw run
            # id is available as the correlation ref on this path.
            failure_headers.update(_claw_evidence_response_headers(run.run_id, None))
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "engine_execution_failed",
                    "message": "Engine 실행에 실패했습니다.",
                    "detail": _safe_engine_failure_detail(exc),
                },
            },
            status_code=502,
            headers=failure_headers,
        )
    except Exception:
        _clear_reservation()
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "engine_execution_failed",
                    "message": "Engine 실행에 실패했습니다.",
                    "detail": P01_FAILURE_DETAIL_UNKNOWN,
                },
            },
            status_code=502,
            headers=_NO_STORE_HEADERS,
        )
    _clear_reservation()

    status_value = outcome.projection.status.value
    if status_value == "waiting_approval":
        # The generic lane exposes no approval-consent surface; an
        # approval-requiring run is refused rather than reported as an answer.
        return _error(
            409,
            "claw_general_approval_required",
            "승인이 필요한 요청입니다. Claw 업무 화면에서 진행해 주세요.",
        )
    if status_value != "completed" or not outcome.answer:
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "engine_execution_failed",
                    "message": "Engine 실행이 완료되지 않았습니다.",
                    "detail": P01_FAILURE_DETAIL_CONTRACT,
                },
            },
            status_code=502,
            headers=_NO_STORE_HEADERS,
        )

    # #4072/#3928: preserve successful P01 execution in the pre-existing
    # owner-scoped read model when D1 supports it. This is NOT a same-thread
    # or artifact lineage claim. A failed history write must never replay
    # Engine/tool execution or suppress an already-completed answer.
    await project_completed_general_run(
        request, run_id=run.run_id, user_text=user_text, answer=outcome.answer
    )
    return _claw_general_sse(
        outcome.answer,
        _claw_evidence_response_headers(run.run_id, outcome) if evidence_requested else None,
        history=getattr(outcome, "p01_event_history", ()),
    )


__all__ = ["claw_general_execute"]
