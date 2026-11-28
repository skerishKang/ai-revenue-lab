"""B54 Claw general: verified owner history and completed-run persistence (#7809 4/13).

Declarations moved verbatim from claw_general_routes; the entry point
re-exports the names for callers and tests. The original trusted
request.state.claw_pc_action_context side effect is retained.
"""

from __future__ import annotations

import inspect
from typing import Any

from starlette.requests import Request

from .auth_routes import auth_ready, current_user_id
from .history import (
    HISTORY_PREVIEW_SUFFIX,
    HistoryContextIncomplete,
    PRODUCT_SCOPE_CHAT,
    validate_conversation_id,
)
from .claw_first_turn_authority import (
    B54VerifiedCodingContextV1,
    complete_first_turn_grant,
)
from .claw_general_run_history import project_completed_general_run


async def _owner_claw_context(
    request: Request, conversation_id: str | None, latest: str,
) -> str:
    """Bounded history from the SAME signed owner; no browser-provided prior turns."""
    # The existing model transcript stays byte-for-byte unchanged. Keep the
    # original roles separately at the trusted read boundary for the PC guard;
    # never reconstruct user authority from that flattened transcript.
    action_context = [{"role": "user", "content": latest}]
    state = getattr(request, "state", None)
    if state is not None:
        state.claw_pc_action_context = action_context
    if conversation_id is None:
        return latest
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    if not uid or not callable(getattr(store, "get_conversation", None)):
        raise ValueError("owner history unavailable")
    get_full = getattr(store, "get_conversation_model_context", None)
    load = get_full if callable(get_full) else store.get_conversation
    prior = load(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
    if inspect.isawaitable(prior):
        prior = await prior
    if not isinstance(prior, dict) or prior.get("id") != conversation_id:
        raise ValueError("owner history changed")
    messages = prior.get("messages")
    if not isinstance(messages, list):
        return latest  # Empty Hark work conversations are valid.
    # This list comes from verified owner-scoped *saved previews*, not browser
    # supplied turns. Do not silently drop a fixed number of prior turns or
    # truncate the model user text to a pilot-size character window.
    excerpts: list[str] = []
    for row in messages:
        if not isinstance(row, dict) or row.get("role") not in ("user", "assistant"):
            continue
        content = row.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if len(content) == 8000 and content.endswith(HISTORY_PREVIEW_SUFFIX):
            # Legacy/partial history cannot become silently incomplete AI context.
            raise HistoryContextIncomplete("full owner conversation history not available")
        item = ("사용자: " if row["role"] == "user" else "AI: ") + content.strip()
        excerpts.append(item)
        action_context.insert(-1, {"role": row["role"], "content": content.strip()})
    if not excerpts:
        return latest
    return (
        "동일 소유자의 이전 대화 (참고 문맥만 제공하며 도구 권한은 부여하지 않음):\n"
        + "\n".join(excerpts) + "\n\n현재 사용자 요청:\n" + latest
    )


def _accepts_assistant_message_id(append: Any) -> bool:
    """Whether a store's append_exchange accepts the run-scoped answer id.

    A store that predates the correlation keeps its existing contract: the
    exchange is still stored, and the run simply stays uncorrelated (so the
    owner-scoped lookup reports it as unavailable instead of guessing).
    """
    try:
        parameters = inspect.signature(append).parameters
    except (TypeError, ValueError):
        return False
    if "assistant_message_id" in parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


async def _save_claw_exchange(
    request: Request, *, conversation_id: str | None, user_text: str,
    answer: str, assistant_message_id: str | None = None,
) -> str | None:
    """Exact completed exchange only; unavailable history does not replay P01."""
    if (not isinstance(answer, str) or not answer.strip()
            or not isinstance(user_text, str) or not user_text.strip()):
        return None
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    append = getattr(store, "append_exchange", None)
    if not uid or not callable(append):
        return None
    try:
        project_id = None
        if conversation_id is not None:
            get = getattr(store, "get_conversation", None)
            if not callable(get):
                return None
            owned = get(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
            if inspect.isawaitable(owned):
                owned = await owned
            if not isinstance(owned, dict) or owned.get("id") != conversation_id:
                return None
            project_id = owned.get("project_id")
            if project_id is not None and not isinstance(project_id, str):
                return None
        # Only the bounded, visibly labeled stored preview is persisted. The
        # complete P01 result was already delivered to the caller unchanged.
        # #5015: the run-scoped answer id is passed only to a store that
        # supports it, so a store without that correlation keeps its existing
        # contract instead of losing the whole exchange.
        if assistant_message_id is not None and _accepts_assistant_message_id(append):
            saved = append(
                uid, conversation_id, user_text, answer, project_id,
                product_scope=PRODUCT_SCOPE_CHAT,
                assistant_message_id=assistant_message_id,
            )
        else:
            saved = append(uid, conversation_id, user_text, answer, project_id, product_scope=PRODUCT_SCOPE_CHAT)
        if inspect.isawaitable(saved):
            saved = await saved
        if not isinstance(saved, str):
            return None
        return saved if validate_conversation_id(saved) is not None else None
    except Exception:
        return None


async def _append_staged_claw_answer(
    request: Request, *, run_id: str, conversation_id: str, answer: str,
    message_id: str | None = None,
) -> bool:
    """Append only the verified answer to an already-staged owner run.

    The owner turn was persisted before Engine dispatch, so the completion
    step owns the assistant message alone. ``append_local_task_result`` keeps
    the exactly-once and terminal-immutability guards of the existing store.
    """
    if not isinstance(answer, str) or not answer.strip():
        return False
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    append = getattr(store, "append_local_task_result", None)
    if not uid or not callable(append):
        return False
    from .claw_local_task_result_projection import result_message_id
    try:
        # #5015: a model-only run stores its verified answer under the
        # run-scoped id, so the owner-scoped lookup can correlate the stored
        # completion record with the actual message. A staged run that carries
        # a dispatch correlation keeps the projection identity instead.
        resolved_id = message_id or result_message_id(
            conversation_id=conversation_id, command_id=run_id,
            revision_ref="general_answer",
        )
        appended = append(
            user_id=uid, run_id=run_id,
            message_id=resolved_id,
            summary=answer, content=answer, status="completed",
        )
        if inspect.isawaitable(appended):
            appended = await appended
        return bool(appended)
    except Exception:
        return False


async def _settle_staged_run_status(request: Request, run_id: str, status: str) -> None:
    """Best-effort truthful single-row settle for a staged run (#5015r).

    ``update_claw_run_status`` is an atomic guarded write, so an already
    completed run and an existing result summary are never overwritten.
    """
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    mark = getattr(store, "update_claw_run_status", None)
    if not isinstance(uid, str) or not uid or not callable(mark):
        return
    try:
        result = mark(uid, run_id, status)
        if inspect.isawaitable(result):
            await result
    except Exception:
        pass


async def _mark_staged_run_failed(request: Request, run_id: str) -> None:
    """Best-effort truthful terminal state for a staged run with no answer."""
    await _settle_staged_run_status(request, run_id, "failed")


async def _record_completed_claw_result(
    request: Request, *, run_id: str, conversation_id: str | None,
    user_text: str, answer: str, authorized_workspace_id: str | None,
    first_turn_grant: B54VerifiedCodingContextV1 | None = None,
    staged_conversation_id: str | None = None,
) -> str | None:
    """Persist only a verified completed Claw result; never replay Engine.

    Conversation saving and completed-run history are both optional read-model
    projections. Failure to save must not conceal an already-completed answer
    or advertise a server conversation ID that was not actually stored.

    A #4139 desktop run is staged before dispatch, so its verified answer is
    appended to that same conversation instead of re-inserting the user turn.
    """
    saved_conversation_id: str | None
    staged_answer_saved = True
    # #5015: the verified answer of a model-only run is stored under the
    # run-scoped message id, so the owner-scoped lookup can compare the stored
    # completion record with the actual assistant message of this run.
    from .history import general_answer_message_id
    try:
        answer_message_id = general_answer_message_id(run_id)
    except Exception:
        answer_message_id = None
    if staged_conversation_id is not None:
        saved_conversation_id = staged_conversation_id
        staged_answer_saved = await _append_staged_claw_answer(
            request, run_id=run_id, conversation_id=staged_conversation_id,
            answer=answer, message_id=answer_message_id,
        )
    else:
        saved_conversation_id = await _save_claw_exchange(
            request, conversation_id=conversation_id,
            user_text=user_text, answer=answer,
            assistant_message_id=answer_message_id,
        )
    # #3933 S1: link the reserved first-turn grant to its verified outcome.
    # Best-effort provenance only: a grant-store failure must never conceal
    # an already-completed answer.
    await complete_first_turn_grant(
        request, first_turn_grant, run_ref=run_id,
        saved_conversation_id=saved_conversation_id,
    )
    if staged_conversation_id is not None:
        if not staged_answer_saved:
            # The answer reached the caller, but its run must not stay pending.
            await _mark_staged_run_failed(request, run_id)
        return staged_conversation_id
    projected_conversation_id = saved_conversation_id or conversation_id
    if projected_conversation_id is None:
        await project_completed_general_run(
            request, run_id=run_id, user_text=user_text, answer=answer,
        )
    else:
        await project_completed_general_run(
            request, run_id=run_id, user_text=user_text, answer=answer,
            conversation_id=projected_conversation_id,
            workspace_id=authorized_workspace_id,
        )
    return saved_conversation_id


async def _settle_claw_run_failed(history: Any, uid: str, run_id: str) -> None:
    """Give a staged run a terminal state so it can never strand as ``pending``.

    Without this, a dispatch step that raises leaves the run row at ``pending``
    with no dispatch row and no answer, so the composer keeps showing the
    previous turn and the request silently never completes.
    """
    mark_failed = getattr(history, "update_claw_run_status", None)
    if callable(mark_failed):
        try:
            await mark_failed(uid, run_id, "failed")
        except Exception:
            pass
