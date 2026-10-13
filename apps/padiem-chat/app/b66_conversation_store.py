"""#4657: B66 AI-dialogue conversations over the existing canonical HistoryStore.

WHAT THIS IS
    The B66 quote app keeps its model dialogue in a browser array, so a reload,
    a new chat or a sign-in on another device loses it. This module persists that
    dialogue per owner and exposes list/search/load/delete for it.

NON-AUTHORITY CONTRACT (must stay true)
    NO_SECOND_STORE   It wraps the existing canonical `HistoryStore`
                      (`append_exchange` / `list_conversations` /
                      `search_conversations` / `get_conversation` /
                      `delete_conversation`). It creates no table, database,
                      index or migration of its own.
    OWNER_SCOPED      Every read and write is passed through the caller's owner
                      id, and an absent/blank owner fails closed. There is no
                      cross-owner lookup path here.
    DIALOGUE_ONLY     AI dialogue and saved quotes are different record types.
                      This module never reads or writes quote history, and it
                      never derives a quote from a conversation.
    CLOSED_PROJECTION Only reviewed fields leave this module. Extra fields on a
                      stored row are dropped rather than forwarded.
    BOUNDED           List/search/load results are capped and the search query
                      is length-bounded before it reaches the store.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol

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
    ) -> str: ...

    async def list_conversations(self, user_id: str, limit: int = ...) -> list[dict[str, Any]]: ...

    async def search_conversations(
        self, user_id: str, query: str, limit: int = ...
    ) -> list[dict[str, Any]]: ...

    async def get_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None: ...

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool: ...


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
    """Owner-scoped AI-dialogue persistence for B66, over the canonical store."""

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
        """Persist one completed exchange and return its conversation id."""
        owner = _owner(owner_id)
        if not isinstance(user_text, str) or not isinstance(assistant_text, str):
            raise ValueError("dialogue text must be strings")
        # The canonical store owns id minting and owner binding; this module
        # neither invents nor trusts a conversation id supplied by the browser.
        return await self._store.append_exchange(
            owner, conversation_id, user_text, assistant_text
        )

    async def list_recent(
        self, owner_id: str, limit: int = MAX_B66_CONVERSATIONS
    ) -> list[dict[str, Any]]:
        owner = _owner(owner_id)
        rows = await self._store.list_conversations(
            owner, _bounded_limit(limit, MAX_B66_CONVERSATIONS, MAX_B66_CONVERSATIONS)
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
            owner, normalized, _bounded_limit(limit, MAX_B66_SEARCH_RESULTS, MAX_B66_SEARCH_RESULTS)
        )
        return [item for item in (_summarize(row) for row in rows) if item is not None]

    async def load(
        self, owner_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        """Load one owner's conversation, or None when it is not theirs."""
        owner = _owner(owner_id)
        if not isinstance(conversation_id, str) or not conversation_id:
            return None
        row = await self._store.get_conversation(owner, conversation_id)
        return _project_conversation(row)

    async def delete(self, owner_id: str, conversation_id: str) -> bool:
        owner = _owner(owner_id)
        if not isinstance(conversation_id, str) or not conversation_id:
            return False
        return await self._store.delete_conversation(owner, conversation_id)


__all__ = [
    "B66ConversationStore",
    "MAX_B66_CONVERSATIONS",
    "MAX_B66_SEARCH_QUERY_CHARS",
    "MAX_B66_SEARCH_RESULTS",
]
