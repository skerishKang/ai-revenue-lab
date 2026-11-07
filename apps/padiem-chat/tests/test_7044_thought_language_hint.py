"""#7044: the thinking-summary language hint rides only on the streaming copy.

The measured defect: the platform instruction reaches the model, yet the
thinking summary stays in the model's own working language while the answer is
Korean. A short aside appended to the outgoing copy of the last user message is
the one lever that changed it. This suite locks the four boundaries the change
must not cross: the copy carries the hint, the stored turn never does, the
switch turns it off, and the tool lane is never touched.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.b14_client as b14
from app.b14_client import (
    B14Client,
    THOUGHT_LANGUAGE_HINT,
    THOUGHT_LANGUAGE_HINT_ENV,
)
from app.config import Settings

MESSAGES = [{"role": "user", "content": "고린도전서 3장의 핵심은 무엇인가요?"}]


async def _empty_stream(request):
    if False:  # pragma: no cover - keeps this an async iterator
        yield None


def _client(monkeypatch):
    """A client whose core dispatch is captured instead of sent."""

    captured: dict = {}

    def fake_request(messages, **kwargs):
        captured["messages"] = messages
        return SimpleNamespace(messages=messages)

    monkeypatch.setattr(b14, "_execution_request", fake_request)
    monkeypatch.setattr(
        b14,
        "_resolve_b62_policy",
        lambda messages, require_executable: SimpleNamespace(
            messages=list(messages), profile="free", model_id="synthetic/contract-model",
        ),
    )
    client = B14Client(Settings(runtime_mode="b14"))
    monkeypatch.setattr(client, "_stream_core", _empty_stream)
    return client, captured


async def _drain(client, messages, **kwargs):
    async for _event in client.stream_text_auto(messages, **kwargs):
        pass


@pytest.fixture(autouse=True)
def _unset_switch(monkeypatch):
    monkeypatch.delenv(THOUGHT_LANGUAGE_HINT_ENV, raising=False)


def test_streaming_copy_carries_the_hint(monkeypatch):
    client, captured = _client(monkeypatch)
    asyncio.run(_drain(client, MESSAGES))

    sent = captured["messages"]
    assert sent[-1]["role"] == "user"
    assert sent[-1]["content"] == f"{MESSAGES[0]['content']}\n\n{THOUGHT_LANGUAGE_HINT}"


def test_stored_messages_never_carry_the_hint(monkeypatch):
    client, _captured = _client(monkeypatch)
    original = [dict(message) for message in MESSAGES]
    asyncio.run(_drain(client, MESSAGES))

    assert MESSAGES == original
    assert THOUGHT_LANGUAGE_HINT not in MESSAGES[0]["content"]


def test_switch_off_sends_the_message_unchanged(monkeypatch):
    monkeypatch.setenv(THOUGHT_LANGUAGE_HINT_ENV, "0")
    client, captured = _client(monkeypatch)
    asyncio.run(_drain(client, MESSAGES))

    assert captured["messages"][-1]["content"] == MESSAGES[0]["content"]


def test_tool_lane_never_carries_the_hint(monkeypatch):
    client, captured = _client(monkeypatch)
    asyncio.run(_drain(client, MESSAGES, tools=(object(),)))

    assert THOUGHT_LANGUAGE_HINT not in captured["messages"][-1]["content"]


def test_hint_targets_only_the_last_user_message(monkeypatch):
    client, captured = _client(monkeypatch)
    history = [
        {"role": "user", "content": "첫 질문"},
        {"role": "assistant", "content": "첫 답변"},
        {"role": "user", "content": "두 번째 질문"},
    ]
    asyncio.run(_drain(client, history))

    sent = captured["messages"]
    assert sent[0]["content"] == "첫 질문"
    assert sent[1]["content"] == "첫 답변"
    assert sent[2]["content"].endswith(THOUGHT_LANGUAGE_HINT)
