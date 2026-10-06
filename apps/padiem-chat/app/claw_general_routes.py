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
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_control_plane.product_tier_routes import (
    ProductTierRoutesError,
    active_route_for,
)

from kagent.p01_adapter import (
    P01AdapterError,
    P01CoreOrchestrationAdapter,
    P01DispatchClass,
    P01_FAILURE_DETAIL_CONTRACT,
    P01_FAILURE_DETAIL_UNKNOWN,
)
from kagent.p01_run_flow import create_claw_run

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
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
_CLAW_GENERAL_ROLES = frozenset({"user", "assistant"})


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def _claw_general_sse(answer: str) -> Response:
    """One bounded terminal SSE projection (delta + done).

    Same framing the orchestration bridge already returns to the browser, so the
    existing SSE reader handles the canonical P01 answer without a second client
    protocol. The P01 lane resolves one terminal result; no partial upstream is
    streamed and no answer is fabricated.
    """
    frames = _sse_frame("delta", {"delta": answer}) + _sse_frame("done", {"done": True})
    return Response(
        frames,
        status_code=200,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
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
    try:
        tier_route = active_route_for(product_tier)
    except ProductTierRoutesError:
        return _error(503, "tier_unavailable", "AI 등급 설정을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if tier_route is None or not tier_route.model_id:
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

    run = create_claw_run("padiem-chat", user_text)

    try:
        outcome = await adapter.execute(
            run, product_tier=product_tier, subject_id=subject_id
        )
    except P01AdapterError as exc:
        if exc.dispatch_class == P01DispatchClass.NOT_DISPATCHED:
            await _refund_active_reservation()
        else:
            _clear_reservation()
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
            headers=_NO_STORE_HEADERS,
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

    return _claw_general_sse(outcome.answer)


__all__ = ["claw_general_execute"]
