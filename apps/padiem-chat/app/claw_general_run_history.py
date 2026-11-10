"""B54 general Claw completed-run persistence through the existing owner history.

This module does not create a new file/lineage/session/Drive authority. The
canonical provider run completes before this optional projection, so a history
write failure must NEVER turn its answer into a retryable execution error.
"""

from __future__ import annotations

import inspect
import re
import uuid
from typing import Any

from starlette.requests import Request

from .auth_routes import auth_ready, current_user_id
from .history import MAX_RUN_RESULT_SUMMARY_CHARS, MAX_HISTORY_TITLE_CHARS

_CANONICAL_RUN = re.compile(r"^run_[0-9a-f]{24}$")


async def project_completed_general_run(
    request: Request, *, run_id: str, user_text: str, answer: str,
    conversation_id: str | None = None, workspace_id: str | None = None,
    product: str = "claw", action: str = "general",
) -> bool:
    """Return whether a canonical owner history row was actually committed.

    Purely an optional post-execution read-model projection: no replay, no
    hidden new user session/conversation association, and no false durable
    receipt if D1 is absent/unmigrated/revoked. Errors are private and bounded.
    """
    if (
        not isinstance(run_id, str)
        or _CANONICAL_RUN.fullmatch(run_id) is None
        or not isinstance(user_text, str)
        or not user_text.strip()
        or not isinstance(answer, str)
        or not answer.strip()
    ):
        return False

    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return False
    store = getattr(request.app.state, "history_store", None)
    record = getattr(store, "record_claw_run", None)
    if not callable(record):
        return False

    # Non-null session refs must be verified AGAIN at the history authority.
    # Never allow a bare browser-selected conversation to ride on a new result.
    if conversation_id is not None:
        from .history import PRODUCT_SCOPE_CHAT, validate_conversation_id
        try:
            cid = validate_conversation_id(conversation_id)
        except ValueError:
            return False
        if cid is None or not isinstance(workspace_id, str) or not workspace_id:
            return False
        get_conversation = getattr(store, "get_conversation", None)
        if not callable(get_conversation):
            return False
        try:
            owned = get_conversation(uid, cid, product_scope=PRODUCT_SCOPE_CHAT)
            if inspect.isawaitable(owned):
                owned = await owned
        except Exception:
            return False
        if not isinstance(owned, dict) or owned.get("id") != cid:
            return False

    prefix = "Chat: " if product == "chat" else "Claw: "
    title = prefix + " ".join(user_text.strip().split())
    title = title[:MAX_HISTORY_TITLE_CHARS]
    summary = answer[:MAX_RUN_RESULT_SUMMARY_CHARS]
    resolved_action = action if isinstance(action, str) and action.strip() else "general"
    try:
        scoped_kwargs = (
            {"workspace_id": workspace_id}
            if conversation_id is not None else {}
        )
        if resolved_action != "general":
            scoped_kwargs["action"] = resolved_action
        else:
            scoped_kwargs.pop("action", None)
        result: Any = record(
            user_id=uid,
            run_id=run_id,
            channel="web",
            action=scoped_kwargs.pop("action", "general"),
            title=title,
            status="completed",
            result_summary=summary,
            artifact_document_id=None,
            artifact_filename=None,
            artifact_media_type=None,
            conversation_id=conversation_id,
            **scoped_kwargs,
        )
        if inspect.isawaitable(result):
            await result
    except Exception:
        # A P01 execution already succeeded. Returning an HTTP 5xx would invite
        # the user to resubmit, potentially repeating an irreversible tool run.
        return False
    return True




async def project_completed_chat_turn(
    request: Request,
    *,
    user_text: str,
    answer: str,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
    product: str | None = None,
    action="general",
) -> bool:
    """Project a Chat-direct completed turn into the shared claw_run_history
    read-model (#7297).

    Title prefix follows the origin screen label ('Chat: ' vs 'Claw: '). When
    the turn originated on the Claw screen, its verified saved conversation id
    is linked so the recent-conversation list and session reopen continue to
    recognize the thread as a Claw conversation. Best-effort only: a projection
    failure never fails the turn.
    """
    if not isinstance(user_text, str) or not user_text.strip():
        return False
    if not isinstance(answer, str) or not answer.strip():
        return False
    from .request_contract import declared_product_surface

    resolved_product = (
        product if product in ("chat", "claw") else declared_product_surface(None, request)
    )
    resolved_cid = conversation_id
    if resolved_cid is None:
        state = getattr(request, "state", None)
        saved_cid = getattr(state, "chat_saved_conversation_id", None)
        if isinstance(saved_cid, str) and saved_cid:
            resolved_cid = saved_cid
    run_id = f"run_{uuid.uuid4().hex[:24]}"
    try:
        if resolved_product == "claw" and isinstance(resolved_cid, str) and resolved_cid:
            ws_id = workspace_id
            if not isinstance(ws_id, str) or not ws_id:
                uid = current_user_id(request) if auth_ready(request) else None
                if isinstance(uid, str) and uid:
                    try:
                        from .claw_memory_routes import _resolve_memory_workspace

                        ws_id = await _resolve_memory_workspace(request, uid)
                    except Exception:
                        ws_id = None
                if not isinstance(ws_id, str) or not ws_id:
                    ws_id = "personal"
            linked = await project_completed_general_run(
                request,
                run_id=run_id,
                user_text=user_text,
                answer=answer,
                conversation_id=resolved_cid,
                workspace_id=ws_id,
                product="claw",
                action=action,
            )
            if linked:
                return True
        return await project_completed_general_run(
            request,
            run_id=run_id,
            user_text=user_text,
            answer=answer,
            product=resolved_product,
            action=action,
        )
    except Exception:
        return False

__all__ = ["project_completed_chat_turn", "project_completed_general_run"]
