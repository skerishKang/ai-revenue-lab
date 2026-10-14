"""Long Claw history stays private in R2 and is restored only under D1 ownership."""
import asyncio
from types import SimpleNamespace

import pytest

from app.history import (
    PRODUCT_SCOPE_CHAT,
    D1HistoryStore, HISTORY_PREVIEW_SUFFIX, HistoryError,
    MAX_HISTORY_MESSAGE_CHARS,
)
from app.claw_general_routes import _owner_claw_context

CID = "chat_" + "a" * 32
OWNER = "usr_" + "b" * 32


class PrivateR2:
    def __init__(self):
        self.objects = {}
        self.reads = 0

    async def put(self, key, payload, **_kwargs):
        self.objects[key] = bytes(payload)

    async def get(self, key):
        self.reads += 1
        data = self.objects.get(key)
        return None if data is None else SimpleNamespace(
            size=len(data), arrayBuffer=lambda: data,
        )

    async def delete(self, key):
        self.objects.pop(key, None)


def fixture():
    bucket = PrivateR2()
    store = D1HistoryStore(object(), full_context_bucket=bucket)
    messages = []

    async def first(sql, *args):
        if "MAX(sequence_number)" in sql:
            return None if not messages else {"max_sequence": max(r["sequence_number"] for r in messages)}
        if "FROM conversations" in sql:
            # #4657: the read now binds (conversation_id, user_id, product_scope).
            # Accept either argument count so the fixture is order-agnostic, and
            # still require the owner to match.
            return ({"id": CID, "project_id": None, "title": "fixture", "created_at": "x", "updated_at": "x"}
                    if args[0] == CID and OWNER in args else None)
        raise AssertionError(sql)

    async def all_rows(sql, *args):
        assert "FROM messages" in sql and args == (CID,)
        return sorted([dict(row) for row in messages], key=lambda r: r["sequence_number"])

    async def run(sql, *args):
        if sql.startswith("INSERT INTO messages"):
            mid, cid, seq, body, created_at = args
            assert cid == CID
            messages.append({"id": mid, "role": "user" if "'user'" in sql else "assistant",
                             "content": body, "sequence_number": seq, "created_at": created_at})
        elif sql.startswith("DELETE FROM conversations"):
            messages.clear()
        elif sql.startswith("UPDATE "):
            pass
        else:
            raise AssertionError(sql)

    store._first, store._all, store._run = first, all_rows, run
    return store, bucket, messages


def test_full_long_exchange_r2_round_trip_and_owner_only(monkeypatch):
    store, bucket, rows = fixture()
    user_text = "사용자입력" * 3500 + "::USER_TAIL"
    assistant_text = "긴응답" * 7200 + "::ANSWER_TAIL"
    assert len(user_text) > MAX_HISTORY_MESSAGE_CHARS
    assert asyncio.run(store.append_exchange(OWNER, CID, user_text, assistant_text, product_scope=PRODUCT_SCOPE_CHAT)) == CID
    assert len(bucket.objects) == 2
    displayed = asyncio.run(store.get_conversation(OWNER, CID, product_scope=PRODUCT_SCOPE_CHAT))
    assert all(len(m["content"]) <= MAX_HISTORY_MESSAGE_CHARS for m in displayed["messages"])
    assert all(m["content"].endswith(HISTORY_PREVIEW_SUFFIX) for m in displayed["messages"])
    full = asyncio.run(store.get_conversation_model_context(OWNER, CID, product_scope=PRODUCT_SCOPE_CHAT))
    assert [m["content"] for m in full["messages"]] == [user_text, assistant_text]
    before = bucket.reads
    assert asyncio.run(store.get_conversation_model_context("foreign", CID, product_scope=PRODUCT_SCOPE_CHAT)) is None
    assert bucket.reads == before

    import app.claw_general_routes as routes
    monkeypatch.setattr(routes, "auth_ready", lambda _: True)
    monkeypatch.setattr(routes, "current_user_id", lambda _: OWNER)
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=store)))
    context = asyncio.run(_owner_claw_context(req, CID, "후속 질문"))
    assert "::USER_TAIL" in context and "::ANSWER_TAIL" in context
    assert context.endswith("후속 질문")
    assert asyncio.run(store.delete_conversation(OWNER, CID, product_scope=PRODUCT_SCOPE_CHAT))
    assert not bucket.objects


def test_missing_private_full_context_fails_closed():
    store, bucket, rows = fixture()
    asyncio.run(store.append_exchange(OWNER, CID, "x" * 18000, "answer", product_scope=PRODUCT_SCOPE_CHAT))
    bucket.objects.clear()
    with pytest.raises(HistoryError, match="unavailable"):
        asyncio.run(store.get_conversation_model_context(OWNER, CID, product_scope=PRODUCT_SCOPE_CHAT))


def test_no_r2_never_claims_long_text_is_persisted():
    store, bucket, rows = fixture()
    store.full_context_bucket = None
    with pytest.raises(HistoryError, match="unavailable"):
        asyncio.run(store.append_exchange(OWNER, CID, "x" * 17000, "answer", product_scope=PRODUCT_SCOPE_CHAT))
    assert rows == []


def test_old_legacy_preview_does_not_become_model_truth():
    store, bucket, rows = fixture()
    rows.append({"id": "msg_" + "a" * 32, "role": "user", "sequence_number": 0,
                 "content": "x" * (8000 - len(HISTORY_PREVIEW_SUFFIX)) + HISTORY_PREVIEW_SUFFIX,
                 "created_at": "x"})
    with pytest.raises(HistoryError, match="unavailable"):
        asyncio.run(store.get_conversation_model_context(OWNER, CID, product_scope=PRODUCT_SCOPE_CHAT))


def test_claw_legacy_preview_refuses_before_provider(monkeypatch):
    import app.claw_general_routes as routes
    from app.history import HistoryContextIncomplete
    store, bucket, rows = fixture()
    rows.append({"id": "msg_" + "a" * 32, "role": "user", "sequence_number": 0,
                 "content": "x" * (8000 - len(HISTORY_PREVIEW_SUFFIX)) + HISTORY_PREVIEW_SUFFIX,
                 "created_at": "x"})
    monkeypatch.setattr(routes, "auth_ready", lambda _: True)
    monkeypatch.setattr(routes, "current_user_id", lambda _: OWNER)
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=store)))
    with pytest.raises(HistoryContextIncomplete):
        asyncio.run(_owner_claw_context(req, CID, "추가 질문"))
