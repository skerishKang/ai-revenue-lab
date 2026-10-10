"""B54 general Claw completed-run persistence through the existing owner history.

This module does not create a new file/lineage/session/Drive authority. The
canonical provider run completes before this optional projection, so a history
write failure must NEVER turn its answer into a retryable execution error.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

from starlette.requests import Request

from .auth_routes import auth_ready, current_user_id
from .history import MAX_RUN_RESULT_SUMMARY_CHARS, MAX_HISTORY_TITLE_CHARS

_CANONICAL_RUN = re.compile(r"^run_[0-9a-f]{24}$")


async def project_completed_general_run(
    request: Request, *, run_id: str, user_text: str, answer: str,
    conversation_id: str | None = None, workspace_id: str | None = None,
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
        from .history import validate_conversation_id
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
            owned = get_conversation(uid, cid)
            if inspect.isawaitable(owned):
                owned = await owned
        except Exception:
            return False
        if not isinstance(owned, dict) or owned.get("id") != cid:
            return False

    title = "Claw: " + " ".join(user_text.strip().split())
    title = title[:MAX_HISTORY_TITLE_CHARS]
    summary = answer[:MAX_RUN_RESULT_SUMMARY_CHARS]
    try:
        scoped_kwargs = (
            {"workspace_id": workspace_id}
            if conversation_id is not None else {}
        )
        result: Any = record(
            user_id=uid,
            run_id=run_id,
            channel="web",
            action="general",
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


__all__ = ["project_completed_general_run"]
