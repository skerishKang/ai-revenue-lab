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
import hashlib
import inspect
import json
import time
from .native_calendar_intent import parse_native_calendar_intent, latest_user_text as latest_native_calendar_text
from .native_calendar_adapter import execute_native_calendar_plan
import re
import secrets
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
_SCREEN_VIEW_FAILURE_COPY = {
    401: "로그인이 필요합니다.",
    403: "연결된 PC에서 요청한 작업을 실행할 권한이 없습니다. 컴퓨터 연결과 권한을 확인해 주세요.",
    404: "PC 작업 대상을 확인하지 못했습니다. 컴퓨터 연결 상태를 확인해 주세요.",
    409: "PC 작업 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    413: "PC 작업 요청이 허용 크기를 넘었습니다.",
    422: "PC 작업 요청 형식이 올바르지 않습니다.",
    503: "PC 작업을 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
}


def _screen_view_failure_copy(dispatched: JSONResponse) -> str:
    """One owner-facing sentence for a refused screen view, plus its code."""
    code = ""
    try:
        payload = json.loads(bytes(dispatched.body).decode("utf-8"))
        candidate = payload.get("error", {}).get("code")
        if isinstance(candidate, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", candidate):
            code = candidate
    except Exception:
        code = ""
    if code == "oracle_mesh_run_unavailable":
        sentence = "PC 작업 대상을 확인하지 못했습니다. 컴퓨터 연결 상태를 확인해 주세요."
    else:
        sentence = _SCREEN_VIEW_FAILURE_COPY.get(
            dispatched.status_code,
            "요청한 PC 작업을 실행하지 못했습니다. 컴퓨터가 연결되어 있는지 확인해 주세요.",
        )
    return sentence + (" (" + code + ")" if code else "")


def _redact_typed_value(user_text: str) -> str:
    """The user's own sentence with the typed value replaced, for storage.

    The value is what the PC receives; the conversation keeps the request. A
    password the owner pasted must not sit in the thread for ever.
    """
    if not isinstance(user_text, str) or not user_text:
        return user_text
    return _QUOTED_TEXT_RE.sub(lambda match: match.group(0)[0] + "…" + match.group(0)[-1],
                               user_text, count=1)


def _typed_text_marker(text: str) -> str:
    """Length plus eight hex digits of the digest: no way back to the text."""
    from .desktop_typed_text import text_marker
    return text_marker(text)


async def _deposit_typed_text(request: Request, text: str) -> str | None:
    """Give the PC-bound value to the one-shot store and return the marker.

    None means the value could not be handed over safely. The caller then does
    not create a dispatch at all: a typed value that would have to sit in the
    audit row is refused rather than recorded.
    """
    from .desktop_typed_text import deposit_typed_text, type_marker_op
    ref = await deposit_typed_text(
        getattr(request.app.state, "queue_client", None), text,
    )
    return None if ref is None else type_marker_op(text, ref)


async def _dispatch_user_desktop_request(
    request: Request, *, user_text: str, desktop_op: str, data: dict[str, Any],
    pending_copy: str | None = None, failure_guidance: bool = False,
) -> JSONResponse | Response:
    """Claw composer -> one desktop dispatch on the pinned PC.

    The run row is staged first so the result has a conversation to land in;
    the dispatch itself re-verifies the owner session, the canonical account
    and the deployment's command grant (a desktop input drives the PC, so
    the TXT read grant is never enough).
    """
    from .claw_memory_routes import _resolve_memory_workspace
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_desktop_intent

    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None:
        return denial
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required", "로그인이 필요합니다.")
    history = getattr(request.app.state, "history_store", None)
    stage = getattr(history, "record_txt_pending_run", None)
    if not callable(stage):
        return _error(503, "command_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
    try:
        workspace = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return _error(503, "command_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
    stored_user_text = user_text
    if desktop_op.startswith("desktop:type\n"):
        stored_user_text = _redact_typed_value(user_text)
    run = create_claw_run("padiem-chat", stored_user_text, model_only_text=True)
    try:
        cid = await stage(
            user_id=uid, run_id=run.run_id, workspace_id=workspace,
            user_text=stored_user_text, conversation_id=conversation_id,
        )
    except Exception:
        return _error(503, "command_history_unavailable", "대화 저장에 실패했습니다.")
    if desktop_op.startswith("desktop:type\n"):
        prepared = await _deposit_typed_text(request, desktop_op.split("\n", 1)[1])
        if prepared is None:
            mark_failed = getattr(history, "update_claw_run_status", None)
            if callable(mark_failed):
                try:
                    await mark_failed(uid, run.run_id, "failed")
                except Exception:
                    pass
            return _claw_general_sse(
                "입력값을 PC로 안전하게 보내는 통로를 지금 사용할 수 없어 실행하지 않았습니다. "
                "잠시 후 다시 시도해 주세요.",
                conversation_id=cid,
            )
        desktop_op = prepared
    selected = data.get("device_id")
    dispatched = await dispatch_oracle_mesh_desktop_intent(
        request,
        desktop_op=desktop_op,
        wire={
            "run_id": run.run_id,
            "device_id": selected if isinstance(selected, str) and selected else None,
            "confirmed": True,  # derived from this authenticated user's own text
        },
    )
    if dispatched.status_code != 200:
        mark_failed = getattr(history, "update_claw_run_status", None)
        if callable(mark_failed):
            try:
                await mark_failed(uid, run.run_id, "failed")
            except Exception:
                pass
        if failure_guidance:
            # A read-only view never leaves a raw error body in the composer:
            # the owner gets one Korean sentence explaining what to check.
            return _claw_general_sse(
                _screen_view_failure_copy(dispatched), conversation_id=cid,
            )
        return dispatched
    return _claw_general_sse(
        pending_copy or
        "COM1 데스크톱을 조작하는 중입니다. 실제 화면·결과는 작업 완료 후 이 대화에 표시됩니다.",
        conversation_id=cid, pending_run_id=run.run_id,
    )


async def _confirmed_staged_pc_command(
    request: Request, user_text: str, data: dict[str, Any],
) -> str | None:
    """The staged command a bare affirmative turn confirms, or None.

    The command is re-derived from the SERVER-staged turn (the pending
    ``pc_command`` run row), never from a browser-provided card. A row outside
    this conversation, older than the confirm window, or bound to a different
    staged turn never confirms, and the row is consumed before any dispatch so
    one card answers exactly one execution.
    """
    from datetime import datetime, timezone

    from .pc_command_confirmation import (
        binds_row_to_turn,
        command_from_staged_turn,
        is_affirmative_reply,
        select_pending_command_row,
    )

    if not is_affirmative_reply(user_text):
        return None
    store = getattr(request.app.state, "history_store", None)
    if store is None or not callable(getattr(store, "list_recent_claw_runs", None))             or not callable(getattr(store, "get_conversation_model_context", None)):
        return None
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return None
    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None or conversation_id is None:
        return None
    row = select_pending_command_row(
        await store.list_recent_claw_runs(uid, limit=10),
        conversation_id=conversation_id,
        now=datetime.now(timezone.utc),
    )
    if row is None:
        return None
    context = await store.get_conversation_model_context(
        uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT,
    )
    messages = context.get("messages") if isinstance(context, dict) else None
    if not isinstance(messages, list):
        return None
    staged_content = next(
        (item.get("content") for item in reversed(messages)
         if isinstance(item, dict) and item.get("role") == "user"
         and isinstance(item.get("content"), str)),
        None,
    )
    if not binds_row_to_turn(row, staged_content):
        return None
    command = command_from_staged_turn(_requested_local_command, staged_content)
    if command is None:
        return None
    # #7566: one card, one execution — the conditional consume only an
    # unanswered card matches. Without it nothing is dispatched.
    consume = getattr(store, "consume_pc_command_confirmation", None)
    if not callable(consume):
        return None
    try:
        consumed = await consume(uid, str(row.get("run_id") or ""))
    except Exception:
        consumed = False
    if consumed is not True:
        return None  # an unconsumable card never dispatches
    return command


async def _stage_pc_command_confirmation(
    request: Request, *, user_text: str, command: str, data: dict[str, Any],
) -> JSONResponse | Response:
    """Stage the turn and answer with the one-line confirmation card.

    Nothing is dispatched here: the staged pending ``pc_command`` run row is
    what a later bare affirmative turn confirms. A store that cannot stage the
    turn fails closed instead of executing unconfirmed.
    """
    from .claw_memory_routes import _resolve_memory_workspace
    from .pc_command_confirmation import STATUS_AWAITING_CONFIRMATION, confirmation_card

    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None:
        return denial
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required", "로그인이 필요합니다.")
    history = getattr(request.app.state, "history_store", None)
    stage = getattr(history, "record_txt_pending_run", None)
    if not callable(stage):
        return _error(503, "command_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
    try:
        workspace = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return _error(503, "command_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    try:
        cid = await stage(
            user_id=uid, run_id=run.run_id, workspace_id=workspace,
            user_text=user_text, conversation_id=conversation_id,
            action="pc_command", status=STATUS_AWAITING_CONFIRMATION,
        )
    except Exception:
        return _error(503, "command_history_unavailable", "대화 저장에 실패했습니다.")
    return _claw_general_sse(confirmation_card(command), conversation_id=cid)


def _typed_value_from_staged_turn(staged_content: Any) -> str | None:
    """Re-derive the value a staged typing card shows, from the owner's own turn."""
    if not isinstance(staged_content, str) or not staged_content.strip():
        return None
    for matcher in (_requested_desktop_control, _requested_local_desktop):
        matched, op = matcher(staged_content)
        if matched and isinstance(op, str) and op.startswith("desktop:type\n"):
            return op.split("\n", 1)[1]
    return None


async def _stage_desktop_type_confirmation(
    request: Request, *, user_text: str, value: str, data: dict[str, Any],
) -> JSONResponse | Response:
    """Stage a long or multi-line typed value and answer with its card (#7561).

    Nothing reaches the PC here. The owner's next bare affirmative turn
    confirms it; the value is then re-derived from the stored turn, never
    from the browser.
    """
    from .claw_memory_routes import _resolve_memory_workspace
    from .pc_command_confirmation import STATUS_AWAITING_CONFIRMATION

    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None:
        return denial
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required", "로그인이 필요합니다.")
    history = getattr(request.app.state, "history_store", None)
    stage = getattr(history, "record_txt_pending_run", None)
    if not callable(stage):
        return _error(503, "command_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
    try:
        workspace = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return _error(503, "command_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    try:
        cid = await stage(
            user_id=uid, run_id=run.run_id, workspace_id=workspace,
            user_text=user_text, conversation_id=conversation_id,
            action=ACTION_DESKTOP_TYPE, status=STATUS_AWAITING_CONFIRMATION,
        )
    except Exception:
        return _error(503, "command_history_unavailable", "대화 저장에 실패했습니다.")
    return _claw_general_sse(desktop_type_confirmation_card(value), conversation_id=cid)


async def _confirmed_staged_desktop_type(
    request: Request, user_text: str, data: dict[str, Any],
) -> str | None:
    """The staged typed value a bare affirmative turn confirms, or None.

    Same shape as the command card: the newest young pending
    ``desktop_type`` row of this conversation, bound to the latest stored
    owner turn, consumed before anything is sent.
    """
    from datetime import datetime, timezone

    from .pc_command_confirmation import (
        ACTION_PC_COMMAND,
        binds_row_to_turn,
        is_affirmative_reply,
        select_pending_command_row,
    )

    if not is_affirmative_reply(user_text):
        return None
    store = getattr(request.app.state, "history_store", None)
    if store is None or not callable(getattr(store, "list_recent_claw_runs", None)) \
            or not callable(getattr(store, "get_conversation_model_context", None)):
        return None
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return None
    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None or conversation_id is None:
        return None
    rows = [
        {**row, "action": ACTION_PC_COMMAND}
        for row in (await store.list_recent_claw_runs(uid, limit=10) or ())
        if isinstance(row, dict) and row.get("action") == ACTION_DESKTOP_TYPE
    ]
    # The command card's age, conversation and status rules apply unchanged.
    row = select_pending_command_row(
        rows, conversation_id=conversation_id, now=datetime.now(timezone.utc),
    )
    if row is None:
        return None
    context = await store.get_conversation_model_context(
        uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT,
    )
    messages = context.get("messages") if isinstance(context, dict) else None
    if not isinstance(messages, list):
        return None
    staged_content = next(
        (item.get("content") for item in reversed(messages)
         if isinstance(item, dict) and item.get("role") == "user"
         and isinstance(item.get("content"), str)),
        None,
    )
    if not binds_row_to_turn(row, staged_content):
        return None
    value = _typed_value_from_staged_turn(staged_content)
    if value is None:
        return None
    # One card, one input: the same conditional consume the command card uses
    # (#7566), so two racing "네" type the value once.
    consume = getattr(store, "consume_pc_command_confirmation", None)
    if not callable(consume):
        return None
    try:
        consumed = await consume(
            uid, str(row.get("run_id") or ""), action=ACTION_DESKTOP_TYPE,
        )
    except Exception:
        consumed = False
    if consumed is not True:
        return None  # an unconsumable card never dispatches
    return value


async def _dispatch_user_command_request(
    request: Request, *, user_text: str, command: str, data: dict[str, Any],
) -> JSONResponse | Response:
    """Claw composer -> one terminal dispatch on the pinned PC.

    The run row is staged first so the result has a conversation to land in;
    the dispatch itself re-verifies the owner session, the canonical account
    and the deployment's separate command grant.
    """
    from .claw_memory_routes import _resolve_memory_workspace
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent

    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None:
        return denial
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required", "로그인이 필요합니다.")
    history = getattr(request.app.state, "history_store", None)
    stage = getattr(history, "record_txt_pending_run", None)
    if not callable(stage):
        return _error(503, "command_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
    try:
        workspace = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return _error(503, "command_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    try:
        cid = await stage(
            user_id=uid, run_id=run.run_id, workspace_id=workspace,
            user_text=user_text, conversation_id=conversation_id,
        )
    except Exception:
        return _error(503, "command_history_unavailable", "대화 저장에 실패했습니다.")
    selected = data.get("device_id")
    dispatched = await dispatch_oracle_mesh_command_intent(
        request,
        command=command,
        wire={
            "run_id": run.run_id,
            "device_id": selected if isinstance(selected, str) and selected else None,
            "confirmed": True,  # derived from this authenticated user's own text
        },
    )
    if dispatched.status_code != 200:
        mark_failed = getattr(history, "update_claw_run_status", None)
        if callable(mark_failed):
            try:
                await mark_failed(uid, run.run_id, "failed")
            except Exception:
                pass
        return dispatched
    return _claw_general_sse(
        "COM1에서 명령을 실행하는 중입니다. 실제 출력은 작업 완료 후 이 대화에 표시됩니다.",
        conversation_id=cid, pending_run_id=run.run_id,
    )




async def _dispatch_user_txt_request(
    request: Request, *, user_text: str, path_relative: str,
    data: dict[str, Any],
) -> JSONResponse | Response:
    """Claw's existing composer → existing Broker enqueue, with owned run."""
    from .claw_memory_routes import _resolve_memory_workspace
    from .connector_txt_read_routes import (
        choose_verified_txt_device, dispatch_verified_txt_read,
    )

    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None:
        return denial
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required", "로그인이 필요합니다.")
    selected = data.get("device_id")
    if selected is not None and (not isinstance(selected, str) or not selected):
        return _error(422, "txt_read_device_invalid", "선택한 PC를 확인할 수 없습니다.")

    # #4139: an ordinary TXT request may execute on the management host over
    # the verified Mesh ownership map. That decision is made BEFORE the native
    # device directory lookup, so a PC without a native binding is not filtered
    # out first; the native lane below is unchanged for everything else.
    from .oracle_mesh_read_return_routes import (
        dispatch_oracle_mesh_read_intent, resolve_oracle_mesh_execution,
    )
    mesh_target, mesh_error = await resolve_oracle_mesh_execution(
        request, path_relative=path_relative, selected_device_id=selected,
    )
    if mesh_error is not None:
        return mesh_error
    if mesh_target is not None:
        try:
            workspace = await _resolve_memory_workspace(request, uid)
        except Exception:
            workspace = None
        if not isinstance(workspace, str) or not workspace:
            return _error(503, "txt_read_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
        history = getattr(request.app.state, "history_store", None)
        stage = getattr(history, "record_txt_pending_run", None)
        if not callable(stage):
            return _error(503, "txt_read_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
        run = create_claw_run("padiem-chat", user_text, model_only_text=True)
        try:
            cid = await stage(
                user_id=uid, run_id=run.run_id, workspace_id=workspace,
                user_text=user_text, conversation_id=conversation_id,
            )
        except Exception:
            return _error(503, "txt_read_history_unavailable", "대화 저장에 실패했습니다.")
        try:
            staged = await dispatch_oracle_mesh_read_intent(request, {
                "device_id": mesh_target["device_id"],
                "run_id": run.run_id,
                "root_ref": mesh_target["root_ref"],
                "path_relative": mesh_target["path_relative"],
                "confirmed": True,  # derived from this authenticated user's READ text
            })
        except Exception:
            await _settle_claw_run_failed(history, uid, run.run_id)
            return _error(503, "txt_read_dispatch_unavailable",
                          "PC 작업 요청을 보내지 못했습니다.")
        if staged.status_code != 200:
            await _settle_claw_run_failed(history, uid, run.run_id)
            return staged
        return _claw_general_sse(
            "PC의 TXT 파일을 읽는 중입니다. 실제 파일 내용은 작업 완료 후 이 대화에 표시됩니다.",
            conversation_id=cid, pending_run_id=run.run_id,
        )

    device_id, error = await choose_verified_txt_device(
        request, selected_device_id=selected,
    )
    if error is not None:
        return error
    try:
        workspace = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return _error(503, "txt_read_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
    history = getattr(request.app.state, "history_store", None)
    stage = getattr(history, "record_txt_pending_run", None)
    if not callable(stage):
        return _error(503, "txt_read_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    try:
        cid = await stage(
            user_id=uid, run_id=run.run_id, workspace_id=workspace,
            user_text=user_text, conversation_id=conversation_id,
        )
    except Exception:
        return _error(503, "txt_read_history_unavailable", "대화 저장에 실패했습니다.")
    try:
        dispatched = await dispatch_verified_txt_read(request, {
            "device_id": device_id, "root_ref": "root.3140",
            "path_relative": path_relative, "run_id": run.run_id,
            "confirmed": True,  # derived from this authenticated user's actual READ text
        })
    except Exception:
        await _settle_claw_run_failed(history, uid, run.run_id)
        return _error(503, "txt_read_dispatch_unavailable",
                      "PC 작업 요청을 보내지 못했습니다.")
    if dispatched.status_code != 200:
        await _settle_claw_run_failed(history, uid, run.run_id)
        return dispatched
    # Only a wait response is emitted. The *verified* PC body is appended
    # asynchronously on existing run-history/local-result reconciliation.
    return _claw_general_sse(
        "PC의 TXT 파일을 읽는 중입니다. 실제 파일 내용은 작업 완료 후 이 대화에 표시됩니다.",
        conversation_id=cid, pending_run_id=run.run_id,
    )










async def _claw_general_pc_branch(
    request: Request, data: dict, user_text: str, attachment_conflict: object,
) -> tuple[JSONResponse | Response | None, dict[str, object]]:
    """Run the desktop, command, confirmation and PC-classification branches.

    Returns the original response at the same point, or the nine PC context
    values the later PC work-context and staging steps receive.
    """

    # The desktop grammar is narrower than a shell command, so it is checked
    # first: a span that parses as a desktop op is never executed as one.
    desktop_requested, desktop_op = _requested_local_desktop(user_text)
    if desktop_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        if desktop_op is None:
            return _error(422, "desktop_op_required",
                          "수행할 데스크톱 동작을 백틱으로 하나만 지정해 주세요."), None
        if desktop_op.startswith("desktop:type\n") and not (
            "\n" not in user_text.strip()
            and direct_typing_eligible(desktop_op.split("\n", 1)[1])
        ):
            return await _stage_desktop_type_confirmation(
                request, user_text=user_text, value=desktop_op.split("\n", 1)[1], data=data,
            ), None
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op=desktop_op, data=data,
        ), None

    # #6460 S1: a natural-language screen view is the same verified capture as
    # the backtick op, taken once and shown in the conversation. It never asks
    # the model and never reaches an input op.
    if _requested_read_only_screen_view(user_text):
        if attachment_conflict is not None:
            return attachment_conflict, None
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op="desktop:capture", data=data,
            pending_copy="PC 화면을 한 장 가져오는 중입니다. 완료되면 이 대화에 표시됩니다.",
            failure_guidance=True,
        ), None

    # #6460: a plain-language single desktop action. Pre-delegated: the server
    # re-verifies owner, device and the command grant on every send, and no
    # per-action button exists. The four exception families are asked once in
    # the conversation and never start from this lane.
    control_requested, control_op = _requested_desktop_control(user_text)
    if control_requested and control_op is not None:
        if attachment_conflict is not None:
            return attachment_conflict, None
        question = _desktop_exception_question(user_text)
        if question is not None:
            conversation_id, denial = await _resolve_intake_session_reference(request, data)
            if denial is not None:
                return denial, None
            return _claw_general_sse(question, conversation_id=conversation_id), None
        if control_op.startswith("desktop:type\n"):
            value = control_op.split("\n", 1)[1]
            # #7561: one short line typed by the owner runs at once; a
            # multi-line turn or a long value waits for the owner's '네'.
            if "\n" in user_text.strip() or not direct_typing_eligible(value):
                return await _stage_desktop_type_confirmation(
                    request, user_text=user_text, value=value, data=data,
                ), None
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op=control_op, data=data,
            pending_copy="요청한 PC 동작을 보내는 중입니다. 결과는 이 대화에 표시됩니다.",
            failure_guidance=True,
        ), None

    # One owner-requested initial observation runs through P01/Engine ToolRuntime
    # rather than the manual backtick diagnostic lane above.
    # #7561: the screen is only captured for a one-line instruction that
    # names the owner's PC; "내가 화면을 봤는데…" is an ordinary question.
    initial_pc_capture = explicit_pc_instruction(user_text) and bool(re.search(
        r"(?:내|우리|PC|pc|컴퓨터|COM1|com1).{0,40}"
        r"(?:화면|스크린|screen).{0,40}"
        r"(?:캡처|찍|보여|봐|capture|observe)",
        user_text, re.I,
    ))
    # #6460 step 3: a task whose next action depends on the screen runs the
    # same Engine lane, which captures, lets the trusted model choose one
    # action, executes it and captures again until the model finishes or the
    # owner presses 그만. Pre-delegated: no per-action confirmation exists.
    desktop_task_requested = not initial_pc_capture and _requested_desktop_task(user_text)
    if desktop_task_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        question = _desktop_exception_question(user_text)
        if question is not None:
            conversation_id, denial = await _resolve_intake_session_reference(request, data)
            if denial is not None:
                return denial, None
            return _claw_general_sse(question, conversation_id=conversation_id), None
        initial_pc_capture = True
    if initial_pc_capture and attachment_conflict is not None:
        return attachment_conflict, None
    # A selected PC is shape-checked once here and then bound to the two PC
    # lanes below. It is only a target hint: the server re-verifies that the
    # account actually has this Mesh execution target before dispatch.
    requested_device_id = data.get("device_id")
    if requested_device_id is not None and not is_pc_device_id(requested_device_id):
        return _error(422, "oracle_mesh_device_invalid", "PC 장치 선택이 유효하지 않습니다."), None
    desktop_device_id = requested_device_id if initial_pc_capture else None

    # 2026-11-11: a bare affirmative turn confirms the staged PC command card.
    confirmed_command = await _confirmed_staged_pc_command(request, user_text, data)
    if confirmed_command is not None:
        return await _dispatch_user_command_request(
            request, user_text=user_text, command=confirmed_command, data=data,
        ), None
    # #7561: the same bare affirmative confirms a staged typed-value card.
    confirmed_value = await _confirmed_staged_desktop_type(request, user_text, data)
    if confirmed_value is not None:
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op="desktop:type\n" + confirmed_value,
            data=data,
            pending_copy="요청한 PC 입력을 보내는 중입니다. 결과는 이 대화에 표시됩니다.",
            failure_guidance=True,
        ), None

    command_requested, command_text = _requested_local_command(user_text)
    if command_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        if command_text is None:
            return _error(422, "command_text_required",
                          "실행할 명령을 백틱으로 하나만 지정해 주세요."), None
        from .pc_command_confirmation import direct_command_eligible
        if direct_command_eligible(user_text, command_text):
            return await _dispatch_user_command_request(
                request, user_text=user_text, command=command_text, data=data,
            ), None
        return await _stage_pc_command_confirmation(
            request, user_text=user_text, command=command_text, data=data,
        ), None

    # #4976: a natural-language folder/file task (list then read) uses the
    # model-selected PC file tools. It is classified before the older
    # single-command/TXT lanes so a named TXT is read by the model from the
    # actual listing rather than by a fixed-path shortcut.
    from .pc_browser_intent import requested_pc_browser
    pc_browser_requested = requested_pc_browser(user_text)
    pc_browser_device_id = requested_device_id if pc_browser_requested else None
    if pc_browser_requested:
        initial_pc_capture = False
        desktop_device_id = None
    pc_files_requested = not pc_browser_requested and _requested_natural_pc_files(user_text)
    if pc_files_requested and attachment_conflict is not None:
        return attachment_conflict, None
    # The browser hint was already shape-checked once above; the saved target
    # or the server-verified target replaces it before dispatch.
    pc_files_device_id = requested_device_id if pc_files_requested else None

    # #4139: natural-language PC state query (no backtick). Routes a clear
    # question about the verified PC to a bounded inventory command on that PC.
    natural_pc_requested, natural_pc_command = _requested_natural_pc_query(user_text)
    if natural_pc_requested and not pc_browser_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        if natural_pc_command is None:
            return _error(422, "natural_pc_command_required",
                          "PC 조회 명령을 결정할 수 없습니다."), None
        if "Get-PSDrive" not in natural_pc_command:
            return await _dispatch_user_command_request(
                request, user_text=user_text, command=natural_pc_command, data=data,
            ), None
        initial_pc_drive_query = True
        desktop_device_id = requested_device_id
    else:
        initial_pc_drive_query = False

    txt_requested, txt_path = _requested_local_txt_path(user_text)
    if txt_requested and not pc_files_requested and not pc_browser_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        if txt_path is None:
            return _error(422, "txt_read_path_required",
                          "내 PC에서 읽을 TXT 파일의 상대 경로를 하나 지정해 주세요."), None
        return await _dispatch_user_txt_request(
            request, user_text=user_text, path_relative=txt_path, data=data,
        ), None
    return None, {
        "initial_pc_capture": initial_pc_capture,
        "desktop_task_requested": desktop_task_requested,
        "desktop_device_id": desktop_device_id,
        "requested_device_id": requested_device_id,
        "pc_browser_requested": pc_browser_requested,
        "pc_browser_device_id": pc_browser_device_id,
        "pc_files_requested": pc_files_requested,
        "pc_files_device_id": pc_files_device_id,
        "initial_pc_drive_query": initial_pc_drive_query,
    }










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
