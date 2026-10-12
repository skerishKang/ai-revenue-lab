"""#4379: B62 Chat resumed model context comes from owner D1/R2, never UI previews.

Network-free HTTP route tests. Neither browser-provided history nor cross-user
objects can be promoted to model context, and long text is never silently clipped.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import (
    HISTORY_PREVIEW_SUFFIX, MAX_HISTORY_MESSAGE_CHARS,
    MAX_MODEL_CONTEXT_BYTES, HistoryContextIncomplete,
)
from app.main import create_app
from test_public_streaming import ScriptedClient, _event

OWNER = "usr_" + "a" * 32
FOREIGN = "usr_" + "b" * 32
CONVERSATION_ID = "chat_" + "c" * 32
SECRET = "test-only-auth-signature-not-a-real-secret-0000000000"
LONG_USER = "긴 원문 질문" * 1800 + "::ORIGINAL_QUESTION_END"
LONG_ANSWER = "긴 실제 답변" * 1800 + "::ORIGINAL_ANSWER_END"
PREVIEW_USER = LONG_USER[:MAX_HISTORY_MESSAGE_CHARS-len(HISTORY_PREVIEW_SUFFIX)] + HISTORY_PREVIEW_SUFFIX
PREVIEW_ANSWER = LONG_ANSWER[:MAX_HISTORY_MESSAGE_CHARS-len(HISTORY_PREVIEW_SUFFIX)] + HISTORY_PREVIEW_SUFFIX


class OwnerHistory:
    def __init__(self, *, incomplete=False, huge=False):
        self.incomplete = incomplete
        self.huge = huge
        self.history_reads = 0
        self.full_reads = 0
        self.saved = []

    async def get_conversation(self, user_id, conversation_id):
        self.history_reads += 1
        if (user_id, conversation_id) != (OWNER, CONVERSATION_ID):
            return None
        return {
            "id": CONVERSATION_ID, "project_id": None,
            "messages": [
                {"role": "user", "content": PREVIEW_USER},
                {"role": "assistant", "content": PREVIEW_ANSWER},
            ],
        }

    async def get_conversation_model_context(self, user_id, conversation_id):
        assert (user_id, conversation_id) == (OWNER, CONVERSATION_ID)
        self.full_reads += 1
        if self.incomplete:
            raise HistoryContextIncomplete("legacy preview-only message")
        first = "z" * MAX_MODEL_CONTEXT_BYTES if self.huge else LONG_USER
        return {
            "id": CONVERSATION_ID, "project_id": None,
            "messages": [
                {"role": "user", "content": first},
                {"role": "assistant", "content": LONG_ANSWER},
            ],
        }

    async def append_exchange(self, user_id, conversation_id, user_text, assistant_text, project_id=None):
        self.saved.append((user_id, conversation_id, user_text, assistant_text, project_id))
        return CONVERSATION_ID


class CaptureCompleted:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append([dict(m) for m in messages])
        return {"answer": "Completed response", "runtime": "test"}


def settings():
    return Settings.from_values(
        runtime_mode="mock", auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="test-only-secret",
        session_secret=SECRET,
    )


def payload():
    return {
        "mode": "auto",
        "conversation_id": CONVERSATION_ID,
        "messages": [
            {"role": "user", "content": PREVIEW_USER},
            {"role": "assistant", "content": "FORGED_FROM_BROWSER"},
            {"role": "user", "content": "새 후속 질문"},
        ],
    }


async def post(endpoint, store, model, *, user=OWNER):
    config = settings()
    app = create_app(config, history_store=store)
    app.state.b14_client = model
    app.state.usage_gate_enforced = False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(config, user),
                           domain="chat.example.test", path="/")
        return await client.post(endpoint, json=payload())


def test_completed_chat_restores_full_owner_history():
    store, model = OwnerHistory(), CaptureCompleted()
    response = asyncio.run(post("/api/chat", store, model))
    assert response.status_code == 200, response.text
    assert len(model.calls) == 1
    assert [m["content"] for m in model.calls[0]] == [
        LONG_USER, LONG_ANSWER, "새 후속 질문",
    ]
    assert "FORGED_FROM_BROWSER" not in str(model.calls)
    assert "::ORIGINAL_QUESTION_END" in str(model.calls)
    assert "::ORIGINAL_ANSWER_END" in str(model.calls)
    assert store.saved[0][:3] == (OWNER, CONVERSATION_ID, "새 후속 질문")
    assert store.full_reads == 1


def test_stream_chat_restores_full_owner_history():
    store, model = OwnerHistory(), ScriptedClient([_event("Live response"), _event(done=True)])
    response = asyncio.run(post("/api/chat/stream", store, model))
    assert response.status_code == 200, response.text
    assert 'event: done' in response.text
    assert [m["content"] for m in model.calls[0]["messages"]] == [
        LONG_USER, LONG_ANSWER, "새 후속 질문",
    ]
    assert store.saved[0][:3] == (OWNER, CONVERSATION_ID, "새 후속 질문")


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_missing_legacy_full_context_denied_before_model(endpoint):
    store = OwnerHistory(incomplete=True)
    model = CaptureCompleted() if endpoint == "/api/chat" else ScriptedClient([])
    response = asyncio.run(post(endpoint, store, model))
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conversation_context_incomplete"
    assert model.calls == [] and store.saved == []


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_foreign_owner_cannot_read_private_history(endpoint):
    store = OwnerHistory()
    model = CaptureCompleted() if endpoint == "/api/chat" else ScriptedClient([])
    response = asyncio.run(post(endpoint, store, model, user=FOREIGN))
    assert response.status_code == 404
    assert store.full_reads == 0 and model.calls == []


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_full_history_larger_than_transport_budget_is_explicit(endpoint):
    store = OwnerHistory(huge=True)
    model = CaptureCompleted() if endpoint == "/api/chat" else ScriptedClient([])
    response = asyncio.run(post(endpoint, store, model))
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "model_context_transport_limit"
    assert model.calls == [] and store.saved == []
