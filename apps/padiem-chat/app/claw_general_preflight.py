"""B54 Claw general: fail-closed grade, history, session and Drive preflight (#7809 6/13).

Definitions relocated verbatim. The same signed owner and independent async
reads remain authoritative, and the entry module re-exports every name.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from kagent.p01_adapter import P01CoreOrchestrationAdapter

from .auth_routes import auth_ready, current_user_id
from .claw_routes import _error, _resolve_intake_session_reference
from .claw_general_stage import (
    CLAW_STAGE_ROUTE,
    CLAW_STAGE_HISTORY,
    CLAW_STAGE_SESSION,
    CLAW_STAGE_DRIVE,
    _claw_stage,
    _claw_timed,
)
from .claw_general_conversation import _owner_claw_context
from .member_grade_access import claw_execution_tier_denial
from .model_policy import ADMIN_B14_MODEL_ID, resolve_claw_execution_grade
from .drive_general_grounding import DriveGroundingError, drive_general_grounding
from .history import HistoryContextIncomplete


async def _no_session_read() -> None:
    """Keep the preflight gather's shape when no identity lane is composed."""
    return None


async def _claw_general_route_preflight(request: Request, data: dict, user_text: str, turn_started: float) -> tuple[JSONResponse | Response | None, dict[str, object]]:
    """등급·경로·대화 참조·선행 읽기 구간(PC 밖)."""
    raw_tier = data.get("tier", "free")
    # #5223: the grade is resolved by the ONE shared authority, exactly like the
    # manual-execution lane. A lane with its own copy of the grade map refused
    # a valid administrator with ``422 invalid_tier`` (#5229).
    grade = resolve_claw_execution_grade(raw_tier)
    if grade is None:
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다."), None
    requested_tier = grade.tier_id
    admin_lane = grade.admin_lane
    # P01 currently transports only member-tier enums. The administrator
    # chooses the separately authorized exact model, never a browser-provided
    # tier/model grant. PLUS here is solely the existing P01 transport profile.
    product_tier = grade.product_tier
    # The administrator lane is not a member grade: its identity answer stays
    # neutral instead of claiming the PLUS transport profile as a membership.
    identity_tier_id = None if admin_lane else requested_tier
    if "tier" in data:
        user_id = current_user_id(request) if auth_ready(request) else None
        tier_denial = await claw_execution_tier_denial(request, user_id, grade)
        if tier_denial is not None:
            return tier_denial, None
    # #4428: the central per-grade route is resolved SERVER-SIDE before any
    # browser model choice is considered. A stored row is authoritative; no row
    # keeps the historical static declaration.
    from .central_model_route_runtime import resolve_claw_tier_model

    if admin_lane:
        claw_route = SimpleNamespace(
            ok=True, model_id=ADMIN_B14_MODEL_ID, fallback_model_id=None, source="admin",
        )
    else:
        try:
            claw_route = await resolve_claw_tier_model(request, requested_tier)
        except Exception:
            return _error(503, "tier_unavailable", "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요."), None
    # #6828: the shared Claw route resolver maps the requested grade server-side.
    # During migration, a legacy model identifier is accepted only as a claim
    # that must exactly match that route; it never selects a different model.
    central_route_model_id: str | None = None
    if not claw_route.ok or not claw_route.model_id:
        return _error(503, "tier_unavailable", "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요."), None
    declared_model_id = data.get("model_id")
    if declared_model_id is not None and declared_model_id != claw_route.model_id:
        return _error(400, "invalid_model_id", "등급 선택은 기본 모델을 사용합니다."), None
    central_route_model_id = claw_route.model_id

    _claw_stage(CLAW_STAGE_ROUTE, turn_started)

    # #3929: optional SAME-CONVERSATION follow-ups are verified against the
    # existing owner-scoped D1 conversation before quota/provider. No model,
    # filename, query string or user-reported owner can bind a conversation.
    conversation_id, conversation_error = await _resolve_intake_session_reference(
        request, data,
    )
    if conversation_error is not None:
        return conversation_error, None

    # #3382/#3539: the canonical USER subject is resolved SERVER-SIDE before the
    # usage gate and before any P01/Engine dispatch, so a failed revalidation
    # never consumes quota and never reaches a provider.
    adapter: P01CoreOrchestrationAdapter | None = getattr(
        request.app.state, "claw_p01_adapter", None
    )
    has_identity_lane = (
        adapter is not None
        and getattr(adapter, "subject_identity_lane", False) is True
    )

    # Explicit transport/resource failure before quota; do not silently
    # truncate the owned prior context or present an Engine ingress guard as a
    # provider model-token ceiling. Full serialized Engine checks stay active.
    #
    # #5554: the owned history read, the canonical B54 session and the Drive
    # grounding are three independent reads of the same signed request. They
    # used to run one after another, so a short Claw message paid their sum
    # before the model was even asked. They are issued together now and each
    # keeps its own stage duration. The refusals below are still evaluated in
    # the original order (history, then the session lane, then Drive), each
    # read is still fail-closed, and nothing reaches a quota, a provider or a
    # PC lane while these preflight reads are in flight.
    if has_identity_lane:
        from .b54_canonical_session import resolve_current_b54_canonical_session

        session_read = _claw_timed(
            CLAW_STAGE_SESSION, resolve_current_b54_canonical_session(request)
        )
    else:
        session_read = _claw_timed(CLAW_STAGE_SESSION, _no_session_read())
    # Load ONLY prior messages from the reverified owner-scoped server history.
    # A browser-supplied array of prior turns never becomes model context.
    # Use the signed owner and Control Plane workspace for the connected Drive.
    # Never let browser-provided historical turns choose file access.
    history_read, b54_session, drive_result = await asyncio.gather(
        _claw_timed(
            CLAW_STAGE_HISTORY,
            _owner_claw_context(request, conversation_id, user_text),
        ),
        session_read,
        _claw_timed(CLAW_STAGE_DRIVE, drive_general_grounding(request, user_text)),
        return_exceptions=True,
    )
    if isinstance(history_read, Exception):
        if isinstance(history_read, HistoryContextIncomplete):
            return _error(409, "conversation_context_incomplete",
                          "이전 대화 원문을 복원할 수 없습니다. 새 대화를 시작하거나 원문을 다시 입력해 주세요."), None
        return _error(503, "conversation_authority_unavailable",
                      "대화 문맥을 안전하게 확인할 수 없습니다."), None
    if isinstance(history_read, BaseException):
        raise history_read
    model_user_text = history_read
    return None, {
        "grade": grade,
        "requested_tier": requested_tier,
        "admin_lane": admin_lane,
        "product_tier": product_tier,
        "identity_tier_id": identity_tier_id,
        "claw_route": claw_route,
        "central_route_model_id": central_route_model_id,
        "conversation_id": conversation_id,
        "adapter": adapter,
        "has_identity_lane": has_identity_lane,
        "model_user_text": model_user_text,
        "b54_session": b54_session,
        "drive_result": drive_result,
    }


async def _claw_general_authority_context(
    conversation_id: str | None,
    has_identity_lane: bool,
    b54_session: Any,
    drive_result: Any,
) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """#7814 4/4b: moved verbatim from the pre-refactor main.
    Every early return keeps its exact response as ``(response, None)``.
    """
    subject_id: str | None = None
    authorized_workspace_id: str | None = None
    canonical_session_id: str | None = None
    if conversation_id is not None and not has_identity_lane:
        return _error(403, "canonical_b54_session_unavailable",
                      "인증된 Claw 실행 권한을 확인할 수 없습니다."), None
    if has_identity_lane:
        if isinstance(b54_session, BaseException):
            raise b54_session
        if b54_session is None:
            return _error(
                403,
                "canonical_b54_session_unavailable",
                "인증된 Claw 실행 권한을 확인할 수 없습니다.",
            ), None
        subject_id = b54_session.auth_session.subject.subject_id
        authorized_workspace_id = getattr(b54_session.auth_session, "tenant_id", None)
        canonical_session_id = getattr(b54_session.auth_session, "session_id", None)
        if conversation_id is not None:
            if not isinstance(authorized_workspace_id, str) or not authorized_workspace_id:
                return _error(403, "workspace_scope_unavailable",
                              "대화 작업 공간을 확인할 수 없습니다."), None

    if isinstance(drive_result, Exception):
        if isinstance(drive_result, DriveGroundingError):
            return _error(drive_result.status_code, drive_result.code, drive_result.message), None
        raise drive_result
    if isinstance(drive_result, BaseException):
        raise drive_result
    drive_context, drive_sources = drive_result
    return None, {
        "subject_id": subject_id,
        "authorized_workspace_id": authorized_workspace_id,
        "canonical_session_id": canonical_session_id,
        "drive_context": drive_context,
        "drive_sources": drive_sources,
    }
