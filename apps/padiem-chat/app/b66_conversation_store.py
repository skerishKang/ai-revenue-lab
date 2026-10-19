"""#4657: B66 AI-dialogue conversations over the existing canonical HistoryStore.

WHAT THIS IS
    The B66 quote app keeps its model dialogue in a browser array, so a reload,
    a new chat or a sign-in on another device loses it. This module persists that
    dialogue per owner and exposes list/search/load/delete for it.

NON-AUTHORITY CONTRACT (must stay true)
    NO_SECOND_STORE   It wraps the existing canonical `HistoryStore`. It creates
                      no table, database, index or migration of its own.
    PRODUCT_ISOLATED  Every call passes `PRODUCT_SCOPE_B66`, and the storage layer
                      filters on the server-owned `product_scope` column. Owner
                      scoping alone was not enough: the same account also owns
                      Chat/Claw conversations, so without the discriminator B66
                      could list, read or delete them — and Chat could read B66
                      dialogue. Isolation is enforced at the data-access
                      boundary, in both directions, not by a post-filter here.
    OWNER_SCOPED      An absent/blank owner fails closed before any store call.
    DIALOGUE_ONLY     AI dialogue and saved quotes are different record types.
                      This module never reads or writes quote history.
    CLOSED_PROJECTION Only reviewed fields leave this module; extra stored
                      columns are dropped rather than forwarded.
    BOUNDED           List/search/load results are capped and the search query is
                      length-bounded before it reaches the store.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from .history import PRODUCT_SCOPE_B66

MAX_B66_CONVERSATIONS = 50
MAX_B66_SEARCH_RESULTS = 20
MAX_B66_SEARCH_QUERY_CHARS = 200


class _ConversationHistoryStore(Protocol):
    """The subset of the canonical HistoryStore this module depends on."""

    async def append_exchange(
        self,
        user_id: str,
        conversation_id: str | None,
        user_text: str,
        assistant_text: str,
        project_id: str | None = None,
        *,
        product_scope: str,
    ) -> str: ...

    async def list_conversations(
        self, user_id: str, *, product_scope: str, limit: int = ...
    ) -> list[dict[str, Any]]: ...

    async def search_conversations(
        self, user_id: str, query: str, *, product_scope: str, limit: int = ...
    ) -> list[dict[str, Any]]: ...

    async def get_conversation(
        self, user_id: str, conversation_id: str, *, product_scope: str
    ) -> dict[str, Any] | None: ...

    async def get_conversation_model_context(
        self, user_id: str, conversation_id: str, *, product_scope: str
    ) -> dict[str, Any] | None: ...

    async def delete_conversation(
        self, user_id: str, conversation_id: str, *, product_scope: str
    ) -> bool: ...


def _owner(owner_id: object) -> str:
    """A conversation is only ever addressed by a real owner."""
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("owner_id must be a non-empty string")
    return owner_id.strip()


def _bounded_limit(value: object, maximum: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return min(value, maximum)


def _normalize_query(query: object) -> str:
    if not isinstance(query, str):
        return ""
    return " ".join(query.split())[:MAX_B66_SEARCH_QUERY_CHARS]


def _summarize(row: object) -> dict[str, Any] | None:
    """Closed projection: only reviewed dialogue-summary fields leave here."""
    if not isinstance(row, Mapping):
        return None
    conversation_id = row.get("id") or row.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        return None
    title = row.get("title")
    updated_at = row.get("updated_at")
    return {
        "conversation_id": conversation_id,
        "title": title if isinstance(title, str) else "",
        "updated_at": updated_at if isinstance(updated_at, str) else None,
    }


def _project_conversation(row: object) -> dict[str, Any] | None:
    summary = _summarize(row)
    if summary is None or not isinstance(row, Mapping):
        return None
    raw_messages = row.get("messages")
    messages: list[dict[str, str]] = []
    if isinstance(raw_messages, list):
        for message in raw_messages:
            if not isinstance(message, Mapping):
                continue
            role = message.get("role")
            content = message.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})
    summary["messages"] = messages
    return summary


class B66ConversationStore:
    """Owner- and product-scoped AI-dialogue persistence for B66."""

    def __init__(self, store: _ConversationHistoryStore) -> None:
        self._store = store

    async def record_turn(
        self,
        owner_id: str,
        user_text: str,
        assistant_text: str,
        *,
        conversation_id: str | None = None,
    ) -> str:
        """Persist one completed exchange and return its conversation id.

        Continuing an existing conversation only works for a B66 conversation:
        the storage layer rejects a conversation that belongs to another product
        scope, even when the same owner owns it.
        """
        owner = _owner(owner_id)
        if not isinstance(user_text, str) or not isinstance(assistant_text, str):
            raise ValueError("dialogue text must be strings")
        return await self._store.append_exchange(
            owner,
            conversation_id,
            user_text,
            assistant_text,
            product_scope=PRODUCT_SCOPE_B66,
        )

    async def list_recent(
        self, owner_id: str, limit: int = MAX_B66_CONVERSATIONS
    ) -> list[dict[str, Any]]:
        owner = _owner(owner_id)
        rows = await self._store.list_conversations(
            owner,
            product_scope=PRODUCT_SCOPE_B66,
            limit=_bounded_limit(limit, MAX_B66_CONVERSATIONS, MAX_B66_CONVERSATIONS),
        )
        return [item for item in (_summarize(row) for row in rows) if item is not None]

    async def search(
        self, owner_id: str, query: str, limit: int = MAX_B66_SEARCH_RESULTS
    ) -> list[dict[str, Any]]:
        owner = _owner(owner_id)
        normalized = _normalize_query(query)
        if not normalized:
            # An unusable query must not degrade into "return everything".
            return []
        rows = await self._store.search_conversations(
            owner,
            normalized,
            product_scope=PRODUCT_SCOPE_B66,
            limit=_bounded_limit(limit, MAX_B66_SEARCH_RESULTS, MAX_B66_SEARCH_RESULTS),
        )
        return [item for item in (_summarize(row) for row in rows) if item is not None]

    async def load(self, owner_id: str, conversation_id: str) -> dict[str, Any] | None:
        """Load one B66 conversation, or None when it is not this owner's B66 one."""
        owner = _owner(owner_id)
        if not isinstance(conversation_id, str) or not conversation_id:
            return None
        row = await self._store.get_conversation(
            owner, conversation_id, product_scope=PRODUCT_SCOPE_B66
        )
        return _project_conversation(row)

    async def load_model_context(
        self, owner_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        """Full-original messages for the next model dispatch, B66-scoped.

        A continued B66 dialogue must reach the model with the owner's real
        history, not the bounded D1 preview, so this uses the canonical
        full-context projection (private R2 originals). It is the same read the
        Chat/Claw model paths use, pinned to ``PRODUCT_SCOPE_B66``.

        Returns ``None`` when the id is not this owner's B66 conversation.
        Propagates the canonical store's own ``HistoryContextIncomplete`` when
        the conversation exists but its original is unavailable, so the caller
        can fail closed instead of dispatching on a truncated preview.
        """
        owner = _owner(owner_id)
        if not isinstance(conversation_id, str) or not conversation_id:
            return None
        loader = getattr(self._store, "get_conversation_model_context", None)
        if not callable(loader):
            raise RuntimeError("b66 full dialogue context is not composed")
        row = await loader(owner, conversation_id, product_scope=PRODUCT_SCOPE_B66)
        return _project_conversation(row)

    async def delete(self, owner_id: str, conversation_id: str) -> bool:
        owner = _owner(owner_id)
        if not isinstance(conversation_id, str) or not conversation_id:
            return False
        return await self._store.delete_conversation(
            owner, conversation_id, product_scope=PRODUCT_SCOPE_B66
        )


__all__ = [
    "B66ConversationStore",
    "MAX_B66_CONVERSATIONS",
    "MAX_B66_SEARCH_QUERY_CHARS",
    "MAX_B66_SEARCH_RESULTS",
]
