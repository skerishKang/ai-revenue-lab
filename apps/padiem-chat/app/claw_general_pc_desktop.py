"""B54 Claw general: PC desktop dispatch, input redaction and typed cards (#7809 10/13).

Declarations relocated verbatim. The legacy entry module re-exports all
symbols, and Oracle Mesh keeps its five stable entry-point exports.
"""

from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from kagent.p01_run_flow import create_claw_run

from .auth_routes import auth_ready, current_user_id
from .claw_desktop_intent import ACTION_DESKTOP_TYPE, desktop_type_confirmation_card
from .claw_general_pc_intent import (
    _QUOTED_TEXT_RE, _requested_desktop_control, _requested_local_desktop,
)
from .claw_general_response import _claw_general_sse
from .claw_routes import _error, _resolve_intake_session_reference
from .history import PRODUCT_SCOPE_CHAT


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
