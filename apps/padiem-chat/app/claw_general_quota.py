"""B54 Claw general: same-task quota and first-turn grant gate (#7809 9/13).

The implementation is relocated verbatim. The active usage reservation is
held by dispatch_quota.ContextVar across awaits within the same caller task.
No detached child tasks or alternative usage authority are introduced.
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from kagent.p01_run_flow import create_claw_run

from .auth_routes import auth_ready, current_user_id
from .claw_first_turn_authority import (
    B54VerifiedCodingContextV1,
    FirstTurnAuthorityError,
    claim_first_turn_grant,
    fail_first_turn_grant,
    reserve_first_turn_grant,
)
from .claw_general_conversation import _record_completed_claw_result
from .claw_general_response import _claw_general_sse
from .claw_general_stage import CLAW_STAGE_QUOTA, _claw_stage
from .claw_live_canary import live_stream_allowed
from .claw_routes import (
    _NO_STORE_HEADERS,
    _error,
    _safe_composition_diagnostic,
    _usage_gate_denial,
)
from .dispatch_quota import _clear_reservation, _refund_active_reservation
from .native_calendar_intent import parse_native_calendar_intent
from .native_calendar_adapter import execute_native_calendar_plan


async def _claw_general_quota_gate(
    request: Request,
    data: dict,
    user_text: str,
    conversation_id: str | None,
    subject_id: str | None,
    authorized_workspace_id: str | None,
    adapter: Any,
    live_requested: bool,
) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """#7814 4/4a: quota gate, pre-Engine denials and native calendar turn.

    Body below is moved verbatim from the pre-refactor main; every early
    return keeps its exact response and becomes ``(response, None)``.
    The live header is read in the caller, keeping the #5479 catalog finally
    span's source marker in place.
    """
    if live_requested and not live_stream_allowed(request.app.state, subject_id):
        # Admission is pre-quota, pre-Engine and cannot be broadened by
        # a forged browser header or a stale GET capability response.
        return _error(503, "claw_live_stream_unavailable", "Claw 실시간 실행 상태를 사용할 수 없습니다."), None

    # #3933 S1: optional first-turn trusted coding context. OFF by default:
    # the helper returns None without touching any store, keeping the exact
    # historical first-turn path below byte-for-byte identical. When enabled,
    # a missing canonical subject or tenant fails closed here, pre-quota.
    quota_started = time.perf_counter()
    first_turn_context: B54VerifiedCodingContextV1 | None = None
    if conversation_id is None:
        try:
            first_turn_context = await reserve_first_turn_grant(
                request,
                user_id=current_user_id(request) if auth_ready(request) else None,
                subject_id=subject_id,
                tenant_id=authorized_workspace_id,
                route_scope="claw_general_execute",
            )
        except FirstTurnAuthorityError as gate_exc:
            return _error(gate_exc.status_code, gate_exc.code, gate_exc.message), None

    denial = await _usage_gate_denial(request)
    _claw_stage(CLAW_STAGE_QUOTA, quota_started)
    if denial is not None:
        return denial, None

    if adapter is None:
        # No composed P01 lane exists, so the consumed authorization is provably
        # un-dispatched: compensate the exact receipt (#2226). This route has no
        # direct-B14 fallback (#3539); it fails closed instead.
        await _refund_active_reservation()
        await fail_first_turn_grant(request, first_turn_context)
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
        ), None

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
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "claw_live_stream_unavailable", "Claw 실시간 실행 상태를 사용할 수 없습니다."), None

    timezone_name = data.get("timezone") if isinstance(data.get("timezone"), str) else None
    native_plan = parse_native_calendar_intent(user_text, timezone_name=timezone_name)
    if native_plan.get("op") != "none":
        native_store = getattr(request.app.state, "calendar_store", None)
        if native_store is None:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다."), None
        native_uid = current_user_id(request) if auth_ready(request) else None
        if native_uid is None:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(401, "unauthorized", "로그인이 필요합니다."), None
        client_turn_id = data.get("calendar_turn_id") if isinstance(data.get("calendar_turn_id"), str) else request.headers.get("X-Padiem-Calendar-Turn-Id")
        if not isinstance(client_turn_id, str) or not client_turn_id or len(client_turn_id) > 128:
            client_turn_id = None
        turn_seed = "|".join(str(v) for v in (native_uid, conversation_id, user_text, timezone_name, client_turn_id or ""))

        turn_key = "claw-" + __import__("hashlib").sha256(turn_seed.encode("utf-8")).hexdigest()[:16]
        run = create_claw_run("padiem-chat", user_text, model_only_text=True)
        if native_plan.get("op") == "clarify":
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(422, "clarification_required", str(native_plan.get("question"))), None
        # Claim after the reserved grant exists. Do not fake state if the request
        # was never eligible for a first-turn grant.
        if first_turn_context is not None:
            first_turn_store = getattr(request.app.state, "claw_first_turn_grant_store", None)
            try:
                claimed = await claim_first_turn_grant(first_turn_store, first_turn_context)
            except Exception:
                await _refund_active_reservation()
                await fail_first_turn_grant(request, first_turn_context)
                return _error(503, "first_turn_grant_unavailable", "대화 권한 저장소를 사용할 수 없습니다."), None
            if not claimed:
                await _refund_active_reservation()
                return _error(409, "first_turn_dispatch_in_progress", "같은 요청이 이미 처리 중입니다. 잠시 후 다시 시도해 주세요."), None
        try:
            native_result = await execute_native_calendar_plan(request, native_store, native_uid, native_plan, turn_key=turn_key)
        except Exception as exc:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(getattr(exc, "status_code", 503), getattr(exc, "code", "calendar_unavailable"), getattr(exc, "message", "Calendar operation failed")), None
        if not native_result.get("ok"):
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(502, "calendar_unavailable", "Calendar operation failed"), None
        if native_result.get("operation") == "create_appointment":
            apt = native_result.get("appointment", {})
            native_answer = "네이티브 일정이 등록되었습니다: " + str(apt.get("title")) + " (" + str(apt.get("date")) + ")"
        elif native_result.get("operation") == "read":
            items = native_result.get("items", [])
            if not items:
                native_answer = "해당 기간에 저장된 네이티브 일정이 없습니다 (" + str(native_result.get("timezone")) + ")."
            else:
                native_answer = "네이티브 일정 " + str(len(items)) + "건입니다."
        else:
            native_answer = str(native_result.get("question", "일정 정보가 필요합니다."))
        _clear_reservation()
        saved_conversation_id = await _record_completed_claw_result(request, run_id=run.run_id, conversation_id=conversation_id, user_text=user_text, answer=native_answer, authorized_workspace_id=authorized_workspace_id, first_turn_grant=first_turn_context)
        return _claw_general_sse(native_answer, None, conversation_id=saved_conversation_id), None
    return None, {
        "first_turn_context": first_turn_context,
    }
