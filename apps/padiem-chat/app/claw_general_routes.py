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
B62 ``/api/chat`` composer. #4139 intercepts explicit owner PC TXT READ intents
before provider dispatch and uses the existing Broker command/result pipeline. There is NO direct-B14 fallback: an unbound P01 lane
fails closed (503) instead of silently degrading into the standalone B62
``/api/chat/stream`` route, and the canonical USER subject is resolved
SERVER-SIDE from the signed Padiem session before the usage gate and before any
P01/Engine dispatch.

No second Engine service binding, identity authority or entitlement authority is
introduced here; the projection vocabulary is the one ``claw_routes`` already
owns.
"""

from __future__ import annotations

from .file_lane import file_resolver
from .claw_desktop_intent import (
    ACTION_DESKTOP_TYPE,
    DESKTOP_EXCEPTION_WORDS,
    desktop_exception_matched,
    desktop_type_confirmation_card,
    direct_typing_eligible,
    explicit_pc_instruction,
    screen_coordinates,
)

import asyncio
import inspect
import json
import time
from .native_calendar_intent import parse_native_calendar_intent
from .native_calendar_adapter import execute_native_calendar_plan
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .member_grade_access import claw_execution_tier_denial
from .model_policy import ADMIN_B14_MODEL_ID, resolve_claw_execution_grade
from types import SimpleNamespace
from padiem_ai_core.pc_device_identity import is_pc_device_id

from kagent.p01_adapter import (
    P01AdapterError,
    P01CoreOrchestrationAdapter,
    P01DispatchClass,
    P01_FAILURE_DETAIL_CONTRACT,
    P01_FAILURE_DETAIL_UNKNOWN,
)
from kagent.p01_run_flow import create_claw_run
from .claw_search_decision import (
    build_judgement_digest,
    evidence_agent,
    verdict_from_model,
)

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .byok_client import CustomProviderError, complete_owner_custom
from .byok_credentials import CustomProviderSelectionError
from .drive_general_grounding import DriveGroundingError, drive_general_grounding
from .binary_attachment_frame import decode_binary_attachment_frame
from .claw_attachment_context import (
    CLAW_IMAGE_ATTACHMENT_UNSUPPORTED,
    AttachmentValidationError,
    parse_claw_turn_attachments_async,
)
from .request_contract import BrowserRequestError, parse_custom_selection
from .claw_first_turn_authority import (
    B54VerifiedCodingContextV1,
    FirstTurnAuthorityError,
    claim_first_turn_grant,
    complete_first_turn_grant,
    fail_first_turn_grant,
    reserve_first_turn_grant,
)
from .claw_live_canary import live_stream_allowed
from .claw_general_run_history import project_completed_general_run
from .claw_routes import (
    _NO_STORE_HEADERS,
    _error,
    _safe_composition_diagnostic,
    _safe_engine_failure_detail,
    _usage_gate_denial,
    _resolve_intake_session_reference,
)
from .dispatch_quota import _clear_reservation, _refund_active_reservation
from .request_telemetry import default_emitter
from .auth_routes import auth_ready, current_user_id
from .history import HISTORY_PREVIEW_SUFFIX, HistoryContextIncomplete, validate_conversation_id, PRODUCT_SCOPE_CHAT

# #7809: the shared contract constants, the stage timing and the terminal response
# assembly live in their own modules; every name other code imports is re-exported
# here, so importers (and the tests that patch these names) keep working unchanged.
from .claw_general_contract import (
    MAX_CLAW_GENERAL_BODY_BYTES,
    MAX_CLAW_GENERAL_MESSAGE_CHARS,
    MAX_CLAW_GENERAL_MESSAGES,
    P01_ENGINE_REQUEST_ENVELOPE_BYTES,
    CLAW_LIVE_REQUEST_HEADER,
    CLAW_LIVE_REQUEST_MARKER,
    _MODEL_HOLD_ERROR_CODES,
    _MODEL_HOLD_USER_MESSAGE,
)
from .claw_general_stage import (
    CLAW_STAGE_ROUTE,
    CLAW_STAGE_HISTORY,
    CLAW_STAGE_SESSION,
    CLAW_STAGE_DRIVE,
    CLAW_STAGE_PC_CONTEXT,
    CLAW_STAGE_CATALOG,
    CLAW_STAGE_QUOTA,
    CLAW_STAGE_JUDGEMENT,
    CLAW_STAGE_ANSWER,
    CLAW_STAGE_PERSIST,
    _claw_stage,
    _claw_timed,
)
from .claw_general_response import (
    CLAW_EVIDENCE_REQUEST_HEADER,
    CLAW_EVIDENCE_MARKER,
    _claw_evidence_response_headers,
    _claw_general_sse,
)

from .claw_general_pc_intent import (
    _requested_local_txt_path,
    _COMMAND_PC_MARKERS,
    _COMMAND_VERBS,
    _COMMAND_BODY,
    _requested_local_command,
    _NATURAL_PC_QUERY_MARKERS,
    _NATURAL_PC_QUERY_NOUNS,
    _NATURAL_PC_QUERY_VERBS,
    _natural_pc_query_command,
    _requested_natural_pc_query,
    _PC_FILE_NOUNS,
    _PC_FILE_VERBS,
    _requested_natural_pc_files,
    _DESKTOP_PC_MARKERS,
    _DESKTOP_VERBS,
    _SCREEN_VIEW_NOUNS,
    _SCREEN_VIEW_VERBS,
    _SCREEN_INPUT_WORDS,
    _requested_read_only_screen_view,
    _DESKTOP_KEY_PHRASES,
    _DESKTOP_TYPING_WORDS,
    _QUOTED_TEXT_RE,
    _MAX_TYPED_CHARS,
    _DESKTOP_EXCEPTION_WORDS,
    _desktop_exception_question,
    _requested_desktop_control,
    _DESKTOP_TASK_VERBS,
    _requested_desktop_task,
    _requested_local_desktop,
)

from .claw_general_conversation import (
    _owner_claw_context,
    _accepts_assistant_message_id,
    _save_claw_exchange,
    _append_staged_claw_answer,
    _settle_staged_run_status,
    _mark_staged_run_failed,
    _record_completed_claw_result,
    _settle_claw_run_failed,
)

from .claw_general_catalog import (
    _drain_task_result,
    _start_selectable_model_read,
    _claw_general_pc_work_context,
    _claw_general_catalog_gate,
)

from .claw_general_preflight import (
    _no_session_read,
    _claw_general_route_preflight,
    _claw_general_authority_context,
)

from .claw_general_intake import (
    _CLAW_GENERAL_ROLES,
    _claw_general_user_text,
    _claw_custom_direct,
    _claw_general_intake,
    _claw_general_session_custom,
)

from .claw_general_context import (
    _combine_system_context,
    _claw_general_grounding,
    _claw_general_staging,
    _claw_general_context_bundle,
)

from .claw_general_quota import (
    _claw_general_quota_gate,
)

from .claw_general_pc_desktop import (
    _SCREEN_VIEW_FAILURE_COPY,
    _screen_view_failure_copy,
    _redact_typed_value,
    _typed_text_marker,
    _deposit_typed_text,
    _dispatch_user_desktop_request,
    _typed_value_from_staged_turn,
    _stage_desktop_type_confirmation,
    _confirmed_staged_desktop_type,
)

from .claw_general_pc_command import (
    _confirmed_staged_pc_command,
    _stage_pc_command_confirmation,
    _dispatch_user_command_request,
    _dispatch_user_txt_request,
)

from .claw_general_pc_branch import (
    _claw_general_pc_branch,
)

from .claw_general_search import (
    CLAW_PUBLIC_SEARCH_STATE_FLAG,
    MAX_CLAW_SEARCH_SOURCES,
    MAX_CLAW_SEARCH_SOURCE_TITLE_CHARS,
    CLAW_GROUNDING_PREAMBLE_MARKER,
    CLAW_WEB_SEARCH_EVENT,
    _SAFE_ERROR_NAME,
    _elapsed_ms,
    _emit_claw_web_search,
    _project_search_sources,
    _claw_public_search_grounding,
)

from .claw_general_capabilities import (
    claw_general_capabilities,
)

# Same canonical device identity grammar the Broker device directory and the
# saved PC preference expose, including the composed Mesh node identity.


















#: #6460 S1 — what a failed read-only screen request tells the owner, by the
#: refusal the existing desktop dispatch already answers with.














































async def _claw_general_run_claim(
    request: Request,
    model_user_text: str,
    first_turn_context: B54VerifiedCodingContextV1 | None,
    live_requested: bool,
) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """#7814 4/4b: moved verbatim from the pre-refactor main.
    Every early return keeps its exact response as ``(response, None)``.
    """
    run = create_claw_run("padiem-chat", model_user_text, model_only_text=True)

    # #3933 S1: the reservation above never authorizes a dispatch by itself.
    # Exactly one atomic claim may proceed; a concurrent or replayed attach
    # loses here, gets a status-only 409, and the quota reservation is
    # refunded. No provider/Engine dispatch happens on this path.
    if first_turn_context is not None:
        store = getattr(request.app.state, "claw_first_turn_grant_store", None)
        try:
            claimed = await claim_first_turn_grant(store, first_turn_context)
        except FirstTurnAuthorityError as claim_exc:
            await _refund_active_reservation()
            return _error(claim_exc.status_code, claim_exc.code, claim_exc.message), None
        if not claimed:
            await _refund_active_reservation()
            return _error(409, "first_turn_dispatch_in_progress",
                          "같은 요청이 이미 처리 중입니다. 잠시 후 다시 시도해 주세요."), None

    # #3655: evidence mode is opt-in per request; normal callers see the exact
    # same response surface as before.
    evidence_requested = (
        request.headers.get(CLAW_EVIDENCE_REQUEST_HEADER, "").strip() == CLAW_EVIDENCE_MARKER
    )

    # #3936/#3655: a request this route is going to refuse must be refused before any
    # search judgement, so a rejected call can never spend a model inference or reach a
    # provider. The quota refund and first-turn release stay exactly as they were.
    if live_requested and evidence_requested:
        await _refund_active_reservation()
        # Proven pre-dispatch denial after a successful claim: the claimed grant must
        # fail here, or it stays active (in-progress) until expiry and blocks the key.
        await fail_first_turn_grant(request, first_turn_context)
        return _error(422, "live_evidence_mode_unsupported", "실시간 상태와 감사 증거 요청은 동시에 사용할 수 없습니다."), None
    return None, {
        "run": run,
        "evidence_requested": evidence_requested,
    }








async def _claw_general_terminal(
    request: Request,
    run: Any,
    staged_conversation_id: str | None,
    evidence_requested: bool,
    conversation_id: str | None,
    user_text: str,
    authorized_workspace_id: str | None,
    first_turn_context: B54VerifiedCodingContextV1 | None,
    outcome: Any,
    search_sources: tuple,
) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """#7814 4/4b: moved verbatim from the pre-refactor main.
    Every early return keeps its exact response as ``(response, None)``.
    """
    status_value = outcome.projection.status.value
    if status_value == "waiting_approval":
        # The generic lane exposes no approval-consent surface; an
        # approval-requiring run is refused rather than reported as an answer.
        return _error(
            409,
            "claw_general_approval_required",
            "승인이 필요한 요청입니다. Claw 업무 화면에서 진행해 주세요.",
        ), None
    if status_value != "completed" or not outcome.answer:
        if staged_conversation_id is not None:
            await _mark_staged_run_failed(request, run.run_id)
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
        ), None

    # Preserve the existing completed-path persistence contract; the live
    # callback above now uses the exact same authority and read-model logic.
    persist_started = time.perf_counter()
    saved_conversation_id = await _record_completed_claw_result(
        request, run_id=run.run_id, conversation_id=conversation_id,
        user_text=user_text, answer=outcome.answer,
        authorized_workspace_id=authorized_workspace_id,
        first_turn_grant=first_turn_context,
        staged_conversation_id=staged_conversation_id,
    )
    _claw_stage(CLAW_STAGE_PERSIST, persist_started)
    # #6460 step 3: the owner's stop control uses the run id the live SSE
    # response already carries; the non-live terminal surface keeps its
    # byte-identical response and evidence headers stay opt-in as before.
    return _claw_general_sse(
        outcome.answer,
        _claw_evidence_response_headers(run.run_id, outcome) if evidence_requested else None,
        history=getattr(outcome, "p01_event_history", ()),
        conversation_id=saved_conversation_id,
        sources=search_sources,
    ), None


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
    # Owner decision 2026-11-05: Claw execution is signed-in only. Refuse a
    # guest before the body is read, before quota, and before any Engine/model
    # dispatch. The mock runtime is the network-free CI harness.
    intake_error, intake = await _claw_general_intake(request)
    if intake_error is not None:
        return intake_error
    turn_started = intake["turn_started"]
    data = intake["data"]
    user_text = intake["user_text"]
    document_context = intake["document_context"]
    attachment_conflict = intake["attachment_conflict"]
    session_custom_error, _session_custom = await _claw_general_session_custom(
        request, data, user_text, document_context, attachment_conflict)
    if session_custom_error is not None:
        return session_custom_error
    pc_branch_error, pc_branch = await _claw_general_pc_branch(
        request, data, user_text, attachment_conflict)
    if pc_branch_error is not None:
        return pc_branch_error
    initial_pc_capture = pc_branch["initial_pc_capture"]
    desktop_task_requested = pc_branch["desktop_task_requested"]
    desktop_device_id = pc_branch["desktop_device_id"]
    requested_device_id = pc_branch["requested_device_id"]
    pc_browser_requested = pc_branch["pc_browser_requested"]
    pc_browser_device_id = pc_branch["pc_browser_device_id"]
    pc_files_requested = pc_branch["pc_files_requested"]
    pc_files_device_id = pc_branch["pc_files_device_id"]
    initial_pc_drive_query = pc_branch["initial_pc_drive_query"]
    route_error, route = await _claw_general_route_preflight(request, data, user_text, turn_started)
    if route_error is not None:
        return route_error
    grade = route["grade"]
    requested_tier = route["requested_tier"]
    admin_lane = route["admin_lane"]
    product_tier = route["product_tier"]
    identity_tier_id = route["identity_tier_id"]
    claw_route = route["claw_route"]
    central_route_model_id = route["central_route_model_id"]
    conversation_id = route["conversation_id"]
    adapter = route["adapter"]
    has_identity_lane = route["has_identity_lane"]
    model_user_text = route["model_user_text"]
    b54_session = route["b54_session"]
    drive_result = route["drive_result"]
    if not pc_browser_requested:
        from .pc_browser_intent import requested_pc_browser
        pc_browser_requested = requested_pc_browser(user_text, records=getattr(request.state, "claw_pc_action_context", ()))
        if pc_browser_requested:
            pc_browser_device_id = requested_device_id
            pc_files_requested = False
    authority_error, authority = await _claw_general_authority_context(
        conversation_id, has_identity_lane, b54_session, drive_result,
    )
    if authority_error is not None:
        return authority_error
    subject_id = authority["subject_id"]
    authorized_workspace_id = authority["authorized_workspace_id"]
    canonical_session_id = authority["canonical_session_id"]
    drive_context = authority["drive_context"]
    drive_sources = authority["drive_sources"]

    catalog_error, catalog = await _claw_general_catalog_gate(
        request, central_route_model_id, claw_route, initial_pc_drive_query,
        pc_files_requested, pc_browser_requested, desktop_device_id,
        pc_files_device_id, pc_browser_device_id, canonical_session_id,
    )
    if catalog_error is not None:
        return catalog_error
    pc_work_text = catalog["pc_work_text"]
    desktop_device_id = catalog["desktop_device_id"]
    pc_files_device_id = catalog["pc_files_device_id"]
    pc_browser_device_id = catalog["pc_browser_device_id"]
    central_route_model_id = catalog["central_route_model_id"]

    live_requested = (
        request.headers.get(CLAW_LIVE_REQUEST_HEADER, "").strip()
        == CLAW_LIVE_REQUEST_MARKER
    )
    quota_error, quota = await _claw_general_quota_gate(
        request, data, user_text, conversation_id,
        subject_id, authorized_workspace_id, adapter, live_requested,
    )
    if quota_error is not None:
        return quota_error
    first_turn_context = quota["first_turn_context"]
    # continue normal P01 path below
    run_error, run_bundle = await _claw_general_run_claim(
        request, model_user_text, first_turn_context, live_requested,
    )
    if run_error is not None:
        return run_error
    run = run_bundle["run"]
    evidence_requested = run_bundle["evidence_requested"]

    _grounding_error, grounding = await _claw_general_grounding(
        request, adapter, model_user_text, central_route_model_id,
        drive_context, drive_sources, initial_pc_drive_query,
        pc_files_requested, pc_browser_requested,
    )
    grounding_context = grounding["grounding_context"]
    search_sources = grounding["search_sources"]

    staging_error, staging = await _claw_general_staging(
        request, user_text, conversation_id, run, first_turn_context,
        initial_pc_capture, initial_pc_drive_query, pc_files_requested,
        pc_browser_requested, desktop_task_requested,
    )
    if staging_error is not None:
        return staging_error
    staged_conversation_id = staging["staged_conversation_id"]
    stage_uid = staging["stage_uid"]

    _context_error, context = await _claw_general_context_bundle(
        request, user_text, grounding_context, document_context, pc_work_text,
        drive_context, initial_pc_drive_query, pc_files_requested,
        pc_browser_requested, stage_uid,
    )
    combined_system_context = context["combined_system_context"]
    pc_action_context = context["pc_action_context"]
    pc_delegation = context["pc_delegation"]

    if live_requested:
        from .claw_live_events import live_claw_sse
        live_args = {"product_tier": product_tier, "subject_id": subject_id,
                     "identity_tier_id": identity_tier_id}
        if initial_pc_capture:
            live_args["desktop_capture"] = True
            live_args["desktop_device_id"] = desktop_device_id
        if initial_pc_drive_query:
            live_args["pc_drive_query"] = True
        if initial_pc_drive_query:
            live_args["pc_drive_query"] = True
            if desktop_device_id is not None:
                # Carries the SAME server-verified target the context named;
                # the Engine forwards it to the signed Mesh dispatch.
                live_args["desktop_device_id"] = desktop_device_id
        if pc_files_requested:
            live_args["pc_files_query"] = True
            live_args["pc_files_device_id"] = pc_files_device_id
        if pc_browser_requested:
            live_args["pc_browser_query"] = True
            live_args["pc_browser_device_id"] = pc_browser_device_id
        if initial_pc_drive_query or pc_files_requested or pc_browser_requested:
            live_args["pc_action_context"] = pc_action_context
            live_args["pc_delegation"] = pc_delegation
        if central_route_model_id is not None:
            live_args["central_route_model_id"] = central_route_model_id
        if combined_system_context is not None:
            live_args["additional_system_context"] = combined_system_context
        async def after_verified_live_completion(answer: str) -> str | None:
            # Runs after validated terminal P01 completion, never on pause,
            # failure, disconnect or an unverified/empty answer.
            return await _record_completed_claw_result(
                request, run_id=run.run_id, conversation_id=conversation_id,
                user_text=user_text, answer=answer,
                authorized_workspace_id=authorized_workspace_id,
                first_turn_grant=first_turn_context,
                staged_conversation_id=staged_conversation_id,
            )

        async def after_live_terminal_without_answer(terminal_class: str) -> None:
            # The SSE relay only settles terminals with a proven execution
            # verdict (#5015r): proven_not_dispatched / verified_failure
            # settle as failed, verified_cancelled settles as cancelled.
            # An approval pause, a browser disconnect and an unverifiable
            # outcome are not PC execution failures and are never claimed,
            # so this handler keeps them untouched.
            if staged_conversation_id is None:
                return
            if terminal_class in ("verified_failure", "proven_not_dispatched"):
                await _mark_staged_run_failed(request, run.run_id)
            elif terminal_class == "verified_cancelled":
                await _settle_staged_run_status(request, run.run_id, "cancelled")

        return live_claw_sse(
            adapter, run, live_args,
            on_completed=after_verified_live_completion,
            on_terminal_without_answer=after_live_terminal_without_answer,
            sources=search_sources,
        )

    try:
        dispatch_args = {"product_tier": product_tier, "subject_id": subject_id,
                         "identity_tier_id": identity_tier_id}
        if initial_pc_capture:
            dispatch_args["desktop_capture"] = True
            dispatch_args["desktop_device_id"] = desktop_device_id
        if initial_pc_drive_query:
            dispatch_args["pc_drive_query"] = True
        if initial_pc_drive_query:
            dispatch_args["pc_drive_query"] = True
            if desktop_device_id is not None:
                dispatch_args["desktop_device_id"] = desktop_device_id
        if pc_files_requested:
            dispatch_args["pc_files_query"] = True
            dispatch_args["pc_files_device_id"] = pc_files_device_id
        if pc_browser_requested:
            dispatch_args["pc_browser_query"] = True
            dispatch_args["pc_browser_device_id"] = pc_browser_device_id
        if initial_pc_drive_query or pc_files_requested or pc_browser_requested:
            dispatch_args["pc_action_context"] = pc_action_context
            dispatch_args["pc_delegation"] = pc_delegation
        if central_route_model_id is not None:
            dispatch_args["central_route_model_id"] = central_route_model_id
        if combined_system_context is not None:
            dispatch_args["additional_system_context"] = combined_system_context
        answer_started = time.perf_counter()
        outcome = await adapter.execute(run, **dispatch_args)
        _claw_stage(CLAW_STAGE_ANSWER, answer_started)
    except P01AdapterError as exc:
        if staged_conversation_id is not None:
            await _mark_staged_run_failed(request, run.run_id)
        if exc.dispatch_class == P01DispatchClass.NOT_DISPATCHED:
            await _refund_active_reservation()
            # Proven non-dispatch: the claimed grant may terminally fail.
            # Any other class leaves it active until expiry (no auto-retry).
            await fail_first_turn_grant(request, first_turn_context)
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
        if staged_conversation_id is not None:
            await _mark_staged_run_failed(request, run.run_id)
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

    terminal_error, _terminal = await _claw_general_terminal(
        request, run, staged_conversation_id, evidence_requested,
        conversation_id, user_text, authorized_workspace_id,
        first_turn_context, outcome, search_sources,
    )
    return terminal_error

__all__ = ["claw_general_execute"]
