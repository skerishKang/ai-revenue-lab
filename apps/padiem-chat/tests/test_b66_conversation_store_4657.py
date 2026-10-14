"""#4657: B66 dialogue persistence delegates to the canonical store, B66-scoped.

Offline unit tests over a recording fake store: no D1, network or model call.
The load-bearing claims are that no second store is introduced, that an owner is
always required, and that every call carries the B66 product discriminator.
"""
from __future__ import annotations

import asyncio
import inspect
import re

import pytest

from app.b66_conversation_store import (
    B66ConversationStore,
    MAX_B66_CONVERSATIONS,
    MAX_B66_SEARCH_QUERY_CHARS,
)
from app.history import PRODUCT_SCOPE_B66


class RecordingStore:
    """Records every canonical HistoryStore call, including its product scope."""

    def __init__(self, *, conversations=None, search_hits=None, one=None, deleted=True):
        self.calls: list[tuple] = []
        self._conversations = conversations or []
        self._search_hits = search_hits or []
        self._one = one
        self._deleted = deleted

    async def append_exchange(
        self, user_id, conversation_id, user_text, assistant_text,
        project_id=None, *, product_scope=None,
    ):
        self.calls.append(("append_exchange", user_id, conversation_id, product_scope))
        return "conv-minted-1"

    async def list_conversations(self, user_id, *, product_scope=None, limit=0):
        self.calls.append(("list_conversations", user_id, product_scope, limit))
        return list(self._conversations)

    async def search_conversations(self, user_id, query, *, product_scope=None, limit=0):
        self.calls.append(("search_conversations", user_id, product_scope, query, limit))
        return list(self._search_hits)

    async def get_conversation(self, user_id, conversation_id, *, product_scope=None):
        self.calls.append(("get_conversation", user_id, product_scope, conversation_id))
        return self._one

    async def delete_conversation(self, user_id, conversation_id, *, product_scope=None):
        self.calls.append(("delete_conversation", user_id, product_scope, conversation_id))
        return self._deleted


def store(**kwargs) -> tuple[B66ConversationStore, RecordingStore]:
    backing = RecordingStore(**kwargs)
    return B66ConversationStore(backing), backing


@pytest.mark.parametrize("owner", [None, "", "   ", 123])
def test_every_operation_fails_closed_without_an_owner(owner):
    service, backing = store()
    for call in (
        lambda: service.record_turn(owner, "안녕", "안녕하세요"),
        lambda: service.list_recent(owner),
        lambda: service.search(owner, "철근"),
        lambda: service.load(owner, "conv-1"),
        lambda: service.delete(owner, "conv-1"),
    ):
        with pytest.raises(ValueError, match="owner_id"):
            asyncio.run(call())
    assert backing.calls == [], "an unowned request must never reach the store"


def test_every_call_carries_the_b66_product_scope():
    service, backing = store(one={"id": "conv-1", "messages": []})
    asyncio.run(service.record_turn("owner-a", "철근 견적", "네"))
    asyncio.run(service.list_recent("owner-a"))
    asyncio.run(service.search("owner-a", "철근"))
    asyncio.run(service.load("owner-a", "conv-1"))
    asyncio.run(service.delete("owner-a", "conv-1"))
    assert backing.calls, "expected store traffic"
    # `append_exchange` carries the conversation id before the scope.
    def scope_of(call):
        return call[3] if call[0] == "append_exchange" else call[2]

    assert {scope_of(call) for call in backing.calls} == {PRODUCT_SCOPE_B66}


def test_a_turn_is_persisted_through_the_canonical_store_only():
    service, backing = store()
    conversation_id = asyncio.run(
        service.record_turn("owner-a", "철근 견적 알려줘", "네, 알려드릴게요")
    )
    assert conversation_id == "conv-minted-1"
    assert backing.calls == [
        ("append_exchange", "owner-a", None, PRODUCT_SCOPE_B66)
    ]


def test_a_follow_up_turn_continues_the_existing_conversation():
    service, backing = store()
    asyncio.run(service.record_turn("owner-a", "두 번째", "응답", conversation_id="conv-9"))
    assert backing.calls == [("append_exchange", "owner-a", "conv-9", PRODUCT_SCOPE_B66)]


def test_listing_is_scoped_bounded_and_projected():
    service, backing = store(conversations=[
        {
            "id": "conv-1", "title": "철근 견적", "updated_at": "2026-10-14T01:00:00Z",
            "customer_name": "대한건설", "account_ref": "private-owner",
        },
    ])
    rows = asyncio.run(service.list_recent("owner-a", limit=10_000))
    assert rows == [{
        "conversation_id": "conv-1",
        "title": "철근 견적",
        "updated_at": "2026-10-14T01:00:00Z",
    }]
    assert backing.calls == [
        ("list_conversations", "owner-a", PRODUCT_SCOPE_B66, MAX_B66_CONVERSATIONS)
    ]


def test_an_unusable_search_query_never_returns_everything():
    service, backing = store(search_hits=[{"id": "conv-1"}])
    assert asyncio.run(service.search("owner-a", "   ")) == []
    assert asyncio.run(service.search("owner-a", None)) == []
    assert backing.calls == [], "a blank query must not become a full listing"


def test_search_normalizes_and_bounds_the_query_before_the_store():
    service, backing = store(search_hits=[{"id": "conv-1", "title": "철근"}])
    asyncio.run(service.search("owner-a", "  철근   시세  "))
    assert backing.calls[0] == (
        "search_conversations", "owner-a", PRODUCT_SCOPE_B66, "철근 시세", 20,
    )

    backing.calls.clear()
    asyncio.run(service.search("owner-a", "가" * (MAX_B66_SEARCH_QUERY_CHARS + 500)))
    assert len(backing.calls[0][3]) == MAX_B66_SEARCH_QUERY_CHARS


def test_loading_returns_only_reviewed_dialogue_fields():
    service, backing = store(one={
        "id": "conv-1", "title": "철근 견적", "updated_at": "2026-10-14T01:00:00Z",
        "messages": [
            {"role": "user", "content": "철근 견적 알려줘", "token": "secret"},
            {"role": "system", "content": "must not be projected"},
            {"role": "assistant", "content": "네", "raw": {"provider": "x"}},
            {"role": "assistant", "content": 42},
        ],
        "customer_name": "대한건설",
    })
    loaded = asyncio.run(service.load("owner-a", "conv-1"))
    assert loaded == {
        "conversation_id": "conv-1",
        "title": "철근 견적",
        "updated_at": "2026-10-14T01:00:00Z",
        "messages": [
            {"role": "user", "content": "철근 견적 알려줘"},
            {"role": "assistant", "content": "네"},
        ],
    }
    assert "대한건설" not in repr(loaded)
    assert backing.calls == [
        ("get_conversation", "owner-a", PRODUCT_SCOPE_B66, "conv-1")
    ]


def test_a_conversation_the_store_refuses_is_not_returned():
    service, backing = store(one=None)
    assert asyncio.run(service.load("owner-b", "conv-of-owner-a")) is None
    assert backing.calls == [
        ("get_conversation", "owner-b", PRODUCT_SCOPE_B66, "conv-of-owner-a")
    ]


def test_delete_requires_an_owner_and_a_real_conversation_id():
    service, backing = store()
    assert asyncio.run(service.delete("owner-a", "conv-1")) is True
    assert backing.calls == [
        ("delete_conversation", "owner-a", PRODUCT_SCOPE_B66, "conv-1")
    ]
    backing.calls.clear()
    assert asyncio.run(service.delete("owner-a", "")) is False
    assert backing.calls == []


def test_the_module_only_uses_the_five_dialogue_store_methods():
    """AI dialogue and saved quotes stay separate record types."""
    import app.b66_conversation_store as module

    source = inspect.getsource(module)
    used = set(re.findall(r"self\._store\.([a-z_]+)\(", source))
    assert used == {
        "append_exchange",
        "list_conversations",
        "search_conversations",
        "get_conversation",
        "delete_conversation",
    }, used
    # No second persistence layer, table or connection of its own.
    for forbidden in ("import sqlite3", "create_table", "CREATE TABLE", "D1HistoryStore"):
        assert forbidden not in source, forbidden
    # Isolation comes from the storage layer, not from filtering rows here.
    assert "product_scope=PRODUCT_SCOPE_B66" in source
