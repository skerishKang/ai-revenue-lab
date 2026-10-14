"""Claw complete response is separate from bounded saved history (#4379).

Tests require no live P01/Engine/B14 and protect owner-only persistence.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import claw_general_routes as routes
from app.history import MAX_HISTORY_MESSAGE_CHARS


class CaptureHistory:
    def __init__(self):
        self.exchanges = []

    async def append_exchange(self, *args, product_scope: str):
        from app.history import PRODUCT_SCOPE_CHAT
        assert product_scope == PRODUCT_SCOPE_CHAT
        self.exchanges.append(args)
        return "chat_" + "a" * 32


def request_with_store(store):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=store)))


def test_claw_long_completed_answer_passes_full_text_to_owner_history_store(monkeypatch):
    store = CaptureHistory()
    req = request_with_store(store)
    monkeypatch.setattr(routes, "auth_ready", lambda _request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda _request: "canonical-user")

    long_answer = ("긴 답변 " * 2000) + "완료"
    long_request = ("긴 요청 " * 2000) + "완료"
    cid = asyncio.run(routes._save_claw_exchange(
        req, conversation_id=None, user_text=long_request, answer=long_answer,
    ))
    assert cid == "chat_" + "a" * 32
    assert len(store.exchanges) == 1
    uid, prior, user_preview, answer_preview, project_id = store.exchanges[0]
    assert uid == "canonical-user"
    assert prior is None and project_id is None
    # The route must not pre-truncate: the real D1HistoryStore saves a labeled
    # preview and the exact long bytes into private R2 for later model turns.
    assert len(user_preview) > MAX_HISTORY_MESSAGE_CHARS
    assert len(answer_preview) > MAX_HISTORY_MESSAGE_CHARS
    assert user_preview == long_request
    assert answer_preview == long_answer



def test_claw_short_completed_answer_preserves_text_exactly(monkeypatch):
    store = CaptureHistory()
    monkeypatch.setattr(routes, "auth_ready", lambda _request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda _request: "canonical-user")
    asyncio.run(routes._save_claw_exchange(
        request_with_store(store), conversation_id=None,
        user_text="질문", answer="정상 완료",
    ))
    assert store.exchanges[0][2:4] == ("질문", "정상 완료")


def test_claw_history_remains_owner_scoped_and_fails_closed(monkeypatch):
    store = CaptureHistory()
    monkeypatch.setattr(routes, "auth_ready", lambda _request: False)
    monkeypatch.setattr(routes, "current_user_id", lambda _request: None)
    cid = asyncio.run(routes._save_claw_exchange(
        request_with_store(store), conversation_id=None,
        user_text="valid", answer="valid",
    ))
    assert cid is None
    assert store.exchanges == []
