"""Chat direct PC command lane (#7165).

Claw's composer turns the owner's own explicit command text into one Meshed
command on the verified PC: a PC marker, an imperative verb and exactly one
backtick span, or a bounded natural PC-state query. Chat direct uses the same
rule functions and the same dispatch, so the two products agree on what is a
command and on who approved it.

The approval rule is Claw's: only the signed-in owner's own words in this turn
can authorize a command. Model output is never an authority here - a model
that wants a shell command has no tool for it - and ambiguous text (no
backtick, two spans, no imperative verb) is not a command and keeps the normal
answer path. Every dispatch still re-verifies the owner, grant and target on
the existing Mesh command lane.

The result lands through the existing Claw run record (#7297/#7310): the run is
staged first, so the PC's own output reaches this conversation when it
completes, exactly like a Claw command run.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PENDING_ANSWER = (
    "연결된 PC에서 명령을 실행하는 중입니다. 실제 출력은 작업이 끝난 뒤 이 대화에 "
    "표시됩니다."
)
PENDING_DECISION = "pc_command_pending"
#: A turn that asks for a file, folder or document is a files-tool turn, not
#: a PC-state inventory: the read tools carry it, so the bounded natural
#: query must not intercept it (Claw's file lane keeps the same precedence).
_PC_FILE_WORDS = re.compile(
    r"(파일|폴더|문서|엑셀|xlsx|docx|pdf|csv|바탕화면|다운로드)",
    re.IGNORECASE,
)


def chat_pc_command_for_turn(user_text: Any) -> str | None:
    """The one command this turn's own words authorize, or None.

    Both rules are Claw's own (#4139): the explicit backtick command and the
    bounded natural PC-state query. Imported lazily so importing this module
    never pulls the Claw route surface into a narrower caller.
    """

    if not isinstance(user_text, str) or not user_text.strip():
        return None
    from .claw_general_routes import (
        _requested_local_command,
        _requested_natural_pc_query,
    )

    explicit, command = _requested_local_command(user_text)
    if explicit and isinstance(command, str) and command:
        return command
    natural, command = _requested_natural_pc_query(user_text)
    if natural and isinstance(command, str) and command:
        if _PC_FILE_WORDS.search(user_text):
            return None
        return command
    return None


def _error(code: str, message: str, status_code: int) -> Any:
    from starlette.responses import JSONResponse

    return JSONResponse({"error": {"code": code, "message": message}},
                        status_code=status_code)


CONFIRM_DECISION = "pc_command_confirm"
CONFIRM_ANSWER_PREFIX = "PC 명령 확인: "


def _confirm_response(*, conversation_id: str | None, answer: str) -> Any:
    """The one-line confirmation card as a normal completed turn.

    Nothing is dispatched here. The staged pending ``pc_command`` run row is
    what a later bare affirmative turn confirms; the decision status is new,
    so every existing UI branch keeps its current meaning.
    """
    from starlette.responses import JSONResponse

    payload: dict[str, Any] = {
        "answer": answer,
        "orchestration": {"events": [], "approval_pause": None,
                          "continuation_ref": None},
        "decision_status": CONFIRM_DECISION,
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return JSONResponse(payload)


async def resolve_confirmed_pc_command(
    store: Any, uid: str, user_text: str, conversation_id: str | None,
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
    if not callable(getattr(store, "list_recent_claw_runs", None))             or not callable(getattr(store, "get_conversation_model_context", None)):
        return None
    row = select_pending_command_row(
        await store.list_recent_claw_runs(uid, limit=10),
        conversation_id=conversation_id,
        now=datetime.now(timezone.utc),
    )
    if row is None:
        return None
    context = await store.get_conversation_model_context(
        uid, conversation_id, product_scope="b62-chat",
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
    command = command_from_staged_turn(_match_command, staged_content)
    if command is None:
        return None
    consume = getattr(store, "update_claw_run_status", None)
    if callable(consume):
        try:
            consumed = await consume(uid, str(row.get("run_id") or ""), "cancelled")
        except Exception:
            consumed = False
        if consumed is not True:
            return None  # an unconsumable card never dispatches
    return command


def _match_command(user_text: str) -> tuple[bool, str | None]:
    """The lane matcher, resolved lazily to avoid an import cycle."""
    from .claw_general_routes import _requested_local_command

    return _requested_local_command(user_text)


async def stage_pc_command_confirmation(
    request: Any,
    *,
    uid: str,
    user_text: str,
    command: str,
    pc_context: Mapping[str, Any],
    conversation_id: str | None,
    store: Any,
) -> Any:
    """Stage the turn and answer with the one-line confirmation card.

    Nothing is dispatched here: the staged pending ``pc_command`` run row is
    what a later bare affirmative turn confirms. A store that cannot stage the
    turn fails closed instead of executing unconfirmed.
    """
    from .history import MAX_HISTORY_TITLE_CHARS
    from .pc_command_confirmation import confirmation_card

    begin = getattr(store, "begin_chat_stream_turn", None)
    if not callable(begin):
        return _error("history_unavailable", "대화 기록을 현재 사용할 수 없습니다.", 503)
    from .chat_pc_drive import _new_lane_run_id

    run_id = _new_lane_run_id()
    workspace_id = pc_context.get("workspace_id") if isinstance(pc_context, Mapping) else None
    if not isinstance(workspace_id, str) or not workspace_id:
        return _error("chat_pc_workspace_unavailable", "PC 작업 범위를 확인할 수 없습니다.", 503)
    try:
        saved_id = await begin(
            user_id=uid, run_id=run_id, workspace_id=workspace_id,
            user_text=user_text, conversation_id=conversation_id,
        )
    except Exception:
        return _error("chat_pc_store_unavailable", "대화 기록을 현재 사용할 수 없습니다.", 503)
    record_run = getattr(store, "record_claw_run", None)
    if callable(record_run):
        title = ("Chat: " + user_text.strip())[:MAX_HISTORY_TITLE_CHARS]
        try:
            await record_run(
                user_id=uid, run_id=run_id, channel="web", action="pc_command",
                title=title, status="pending", conversation_id=saved_id,
                workspace_id=workspace_id,
            )
        except Exception:
            # A card whose run row failed to land can never be confirmed; the
            # staged turn alone does not authorize anything.
            return _error("chat_pc_store_unavailable", "대화 기록을 현재 사용할 수 없습니다.", 503)
    return _confirm_response(conversation_id=saved_id, answer=confirmation_card(command))


def _pending_response(*, run_id: str, conversation_id: str | None) -> Any:
    from starlette.responses import JSONResponse

    payload: dict[str, Any] = {
        "answer": PENDING_ANSWER,
        "orchestration": {"events": [], "approval_pause": None,
                          "continuation_ref": None},
        "decision_status": PENDING_DECISION,
        "pc_pending": True,
        "run_id": run_id,
        "pc_run_id": run_id,
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return JSONResponse(payload)


async def dispatch_chat_pc_command(
    request: Any,
    *,
    uid: str,
    raw: Any,
    user_text: str,
    command: str,
    pc_context: Mapping[str, Any],
    conversation_id: str | None,
    store: Any,
) -> Any:
    """Stage the owner turn and dispatch its own command on the verified PC.

    Returns the Chat JSON response: the pending copy plus the run id the Claw
    run projection uses. A dispatch failure settles the staged run as failed so
    the conversation never strands on a pending row.
    """

    from .chat_pc_drive import (
        ChatPCDriveError,
        _client_lane_run_id,
        _new_lane_run_id,
    )
    from .history import HistoryForbidden
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent

    begin = getattr(store, "begin_chat_stream_turn", None)
    if not callable(begin):
        return _error("history_unavailable", "대화 기록을 현재 사용할 수 없습니다.", 503)
    try:
        run_id = _client_lane_run_id(raw.get("pc_run_id")) if isinstance(raw, Mapping) else None
    except ChatPCDriveError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)
    run_id = run_id or _new_lane_run_id()
    try:
        saved_id = await begin(
            user_id=uid, run_id=run_id, workspace_id=pc_context["workspace_id"],
            user_text=user_text, conversation_id=conversation_id,
        )
    except HistoryForbidden:
        return _error("chat_pc_run_id_conflict", "이미 사용한 PC 작업 실행 ID입니다.", 409)
    except Exception:
        return _error("chat_pc_store_unavailable", "대화 기록을 현재 사용할 수 없습니다.", 503)

    record_run = getattr(store, "record_claw_run", None)
    if callable(record_run):
        from .history import MAX_HISTORY_TITLE_CHARS
        from .request_contract import declared_product_surface

        prefix = "Claw: " if declared_product_surface(raw, request) == "claw" else "Chat: "
        title = (prefix + " ".join(user_text.strip().split()))[:MAX_HISTORY_TITLE_CHARS]
        try:
            await record_run(
                user_id=uid,
                run_id=run_id,
                channel="web",
                action="pc_command",
                title=title,
                status="pending",
                conversation_id=saved_id,
                workspace_id=pc_context["workspace_id"],
            )
        except Exception:
            pass

    pc_tools = pc_context.get("pc_tools") if isinstance(pc_context, Mapping) else None
    device_id = pc_tools.get("device_id") if isinstance(pc_tools, Mapping) else None
    dispatched = await dispatch_oracle_mesh_command_intent(
        request,
        command=command,
        wire={"run_id": run_id, "device_id": device_id, "confirmed": True},
    )
    if getattr(dispatched, "status_code", None) != 200:
        settle = getattr(store, "update_claw_run_status", None)
        if callable(settle):
            try:
                await settle(uid, run_id, "failed")
            except Exception:
                pass
        return _error(
            "chat_pc_command_dispatch_failed",
            "PC 명령을 실행하지 못했습니다. PC 연결 상태를 확인한 뒤 다시 요청해 주세요.",
            502,
        )
    return _pending_response(run_id=run_id, conversation_id=saved_id)
