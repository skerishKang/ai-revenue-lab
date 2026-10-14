"""#4657: B66 customer AI-dialogue history — owner- and product-scoped (B66 only).

WHAT THIS IS
    The B66 quote screen keeps its AI dialogue in a browser array, so a reload,
    a new chat or a sign-in on another device loses it. These routes expose the
    owner's stored B66 dialogue for the previous-conversation rail: bounded
    list, bounded search, one restore read and one explicit delete.

AUTHORITY BOUNDARY (must stay true)
    SERVER_OWNER       The owner is the canonical signed-in session only. No
                       query parameter, header or body field can name a user,
                       tenant, workspace or product scope.
    PRODUCT_SCOPED     Every call goes through ``B66ConversationStore``, which
                       pins the server-owned ``PRODUCT_SCOPE_B66`` in storage.
                       A B66 request can therefore never list, read or delete
                       the same account's Chat/Claw conversations, and Chat/Claw
                       can never see a B66 dialogue.
    NON_DISCLOSING     A conversation that is not this owner's B66 one is the
                       same bounded 404 as an unknown id; nothing about another
                       account's existence is disclosed.
    BOUNDED            The list and the search query are length/count bounded
                       before they reach the store. An unusable search never
                       degrades into a full listing.
    READ_ONLY_SURFACE  These routes only read and delete dialogue. They never
                       create a quote, dispatch a model or grant tool authority.
"""
from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .b66_conversation_store import (
    MAX_B66_CONVERSATIONS,
    MAX_B66_SEARCH_QUERY_CHARS,
)
from .b66_quote_routes import _error, _member_access, _NO_STORE, _owner
from .history import validate_conversation_id

__all__ = [
    "B66_DIALOGUE_AUTHORITY",
    "b66_dialogue_delete",
    "b66_dialogue_detail",
    "b66_dialogue_list",
    "b66_dialogue_store",
    "persist_b66_turn",
]

B66_DIALOGUE_AUTHORITY = "b66-dialogue"

# The rail shows a bounded recent page; the store's own ceiling is the hard cap.
_DEFAULT_LIST_LIMIT = 20
_MAX_LIST_LIMIT = MAX_B66_CONVERSATIONS
_LIMIT_RE = re.compile(r"^[0-9]{1,3}$")

_DIALOGUE_UNAVAILABLE = (
    "dialogue_history_unavailable",
    "이전 AI 대화를 현재 사용할 수 없습니다.",
)
_NOT_FOUND = ("conversation_not_found", "대화를 찾을 수 없습니다.")


def b66_dialogue_store(request: Request) -> Any | None:
    """The composed B66 dialogue adapter, or ``None`` when it is not available.

    Duck-typed rather than ``isinstance`` so a test double that implements the
    reviewed four methods is accepted without importing a production class.
    """
    store = getattr(request.app.state, "b66_conversation_store", None)
    if store is None:
        return None
    for name in ("list_recent", "search", "load", "delete"):
        if not callable(getattr(store, name, None)):
            return None
    return store


def _dialogue_unavailable() -> JSONResponse:
    return _error(503, _DIALOGUE_UNAVAILABLE[0], _DIALOGUE_UNAVAILABLE[1])


def _conversation_not_found() -> JSONResponse:
    return _error(404, _NOT_FOUND[0], _NOT_FOUND[1])


def _bounded_limit(raw: object) -> int | None:
    """A bounded page size, or ``None`` when the value is not a usable integer."""
    if raw is None:
        return _DEFAULT_LIST_LIMIT
    if not isinstance(raw, str) or not _LIMIT_RE.fullmatch(raw):
        return None
    value = int(raw)
    if value < 1:
        return None
    return min(value, _MAX_LIST_LIMIT)


async def b66_dialogue_list(request: Request) -> JSONResponse:
    """List or search the signed-in owner's own B66 AI dialogues.

    Read-only. ``?q=`` performs a bounded literal search; without it the recent
    page is returned. The query is normalized and bounded before it reaches the
    store, and a blank query never degrades into a full listing.
    """
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    access, denied = await _member_access(request, uid)
    if denied is not None:
        return denied
    store = b66_dialogue_store(request)
    if store is None:
        return _dialogue_unavailable()

    query = request.query_params.get("q", "")
    if not isinstance(query, str):
        return _error(400, "invalid_query", "검색어 형식이 올바르지 않습니다.")
    if len(query) > MAX_B66_SEARCH_QUERY_CHARS * 4:
        return _error(400, "query_too_long", "검색어가 너무 깁니다.")
    limit = _bounded_limit(request.query_params.get("limit"))
    if limit is None:
        return _error(400, "invalid_limit", "목록 개수가 올바르지 않습니다.")

    normalized = " ".join(query.split())[:MAX_B66_SEARCH_QUERY_CHARS]
    try:
        if normalized:
            conversations = await store.search(uid, normalized, limit=limit)
        else:
            conversations = await store.list_recent(uid, limit=limit)
    except Exception:
        return _dialogue_unavailable()
    return JSONResponse(
        {
            "ok": True,
            "authority": B66_DIALOGUE_AUTHORITY,
            "conversations": conversations,
            "query": normalized,
        },
        headers=_NO_STORE,
    )


async def b66_dialogue_detail(request: Request) -> JSONResponse:
    """Restore one B66 dialogue (GET) or delete it after explicit confirmation (DELETE).

    The id grammar is validated before the store is touched, so a malformed id
    never discloses whether any lookup happened. A same-owner Chat/Claw id is
    the same 404 as an unknown one.
    """
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    access, denied = await _member_access(request, uid)
    if denied is not None:
        return denied
    try:
        conversation_id = validate_conversation_id(request.path_params.get("conversation_id"))
    except ValueError:
        conversation_id = None
    if conversation_id is None:
        return _conversation_not_found()
    store = b66_dialogue_store(request)
    if store is None:
        return _dialogue_unavailable()

    if request.method == "DELETE":
        try:
            deleted = await store.delete(uid, conversation_id)
        except Exception:
            return _dialogue_unavailable()
        if not deleted:
            return _conversation_not_found()
        return JSONResponse(
            {"ok": True, "deleted": True, "conversation_id": conversation_id},
            headers=_NO_STORE,
        )

    try:
        conversation = await store.load(uid, conversation_id)
    except Exception:
        return _dialogue_unavailable()
    if conversation is None:
        return _conversation_not_found()
    return JSONResponse({"ok": True, "conversation": conversation}, headers=_NO_STORE)


# Explicit aliases so the route table reads the same as the sibling B66 modules.
b66_dialogue_delete = b66_dialogue_detail


async def persist_b66_turn(
    store: Any | None,
    owner_id: str,
    *,
    conversation_id: str | None,
    user_text: str,
    assistant_text: str,
    prior_messages: list[dict[str, str]] | None = None,
) -> str | None:
    """Append one completed B66 exchange; return its stable id, or ``None``.

    Only a real model-origin answer reaches here, so a failed upstream leaves no
    record. For a continuation the append is idempotent: when the server-stored
    dialogue already ends with exactly this exchange, it is skipped and the
    existing id is returned, so a retried request cannot duplicate the turn.
    """
    if store is None or not callable(getattr(store, "record_turn", None)):
        return None
    if conversation_id is not None and isinstance(prior_messages, list):
        tail = prior_messages[-2:]
        if (
            len(tail) == 2
            and tail[0].get("role") == "user"
            and tail[0].get("content") == user_text
            and tail[1].get("role") == "assistant"
            and tail[1].get("content") == assistant_text
        ):
            return conversation_id
    try:
        return await store.record_turn(
            owner_id, user_text, assistant_text, conversation_id=conversation_id
        )
    except Exception:
        return None
