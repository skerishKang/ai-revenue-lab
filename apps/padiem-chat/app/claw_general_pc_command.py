"""B54 Claw general PC command confirmation, staging and dispatch (#7809 11/13).

Definitions relocated verbatim; original entrypoint re-exports all three.
"""

from __future__ import annotations

from typing import Any
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from kagent.p01_run_flow import create_claw_run

from .auth_routes import auth_ready, current_user_id
from .claw_general_pc_intent import _requested_local_command
from .claw_general_response import _claw_general_sse
from .claw_general_conversation import _settle_claw_run_failed
from .claw_routes import _error, _resolve_intake_session_reference
from .history import PRODUCT_SCOPE_CHAT


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
