from __future__ import annotations

import json

import httpx
import pytest

from app.pilot.openrouter import (
    build_openrouter_provider_policy,
    call_openrouter_chat_completions,
)
from app.pilot.openrouter_config import openrouter_config
from app.pilot.openrouter_stream import stream_openrouter_chat_completions
from app.pilot.schemas import ChatMessage, PilotChatRequest


GEMINI = "google/gemini-2.5-flash"
MESSAGES = [{"role": "user", "content": "안녕하세요"}]
PRIVACY_POLICY = {"data_collection": "deny", "zdr": True}


def _enable_fixture_live_mode(monkeypatch) -> None:
    monkeypatch.setattr(openrouter_config, "provider_mode", "live")
    monkeypatch.setattr(openrouter_config, "api_key", "fixture_value_not_a_secret_123456")
    monkeypatch.setattr(openrouter_config, "base_url", "https://openrouter.ai/api/v1")


def _completion_response(model: str) -> dict:
    return {
        "id": "or_fixture_completion",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "안녕하세요."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }


def _stream_bytes(model: str) -> bytes:
    first = {
        "id": "or_fixture_stream",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": "첫 토큰"},
                "finish_reason": None,
            }
        ],
    }
    final = {
        "id": "or_fixture_stream",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }
    return (
        b"data: "
        + json.dumps(first).encode("utf-8")
        + b"\n\n"
        + b"data: "
        + json.dumps(final).encode("utf-8")
        + b"\n\n"
        + b"data: [DONE]\n\n"
    )


def test_provider_policy_is_exact_and_does_not_spread_to_other_paid_models():
    assert build_openrouter_provider_policy(GEMINI) == PRIVACY_POLICY
    assert build_openrouter_provider_policy("openrouter/free") == {
        "max_price": {"prompt": 0, "completion": 0}
    }
    assert build_openrouter_provider_policy("deepseek/deepseek-chat") is None


def test_caller_schema_cannot_override_openrouter_provider_privacy_policy():
    with pytest.raises(TypeError):
        PilotChatRequest(
            model=GEMINI,
            messages=[ChatMessage(role="user", content="안녕하세요")],
            provider={"data_collection": "allow", "zdr": False},  # type: ignore[call-arg]
        )


@pytest.mark.asyncio
async def test_completed_gemini_request_always_sends_hard_privacy_policy(monkeypatch):
    _enable_fixture_live_mode(monkeypatch)
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_completion_response(GEMINI))

    result = await call_openrouter_chat_completions(
        messages=MESSAGES,
        temperature=0.2,
        max_tokens=256,
        model_id=GEMINI,
        upstream_model=GEMINI,
        provider="Google",
        transport=httpx.MockTransport(handler),
    )

    assert result["model"] == GEMINI
    assert len(seen) == 1
    assert seen[0]["model"] == GEMINI
    assert seen[0]["provider"] == PRIVACY_POLICY


@pytest.mark.asyncio
async def test_streaming_gemini_request_always_sends_same_hard_privacy_policy(monkeypatch):
    _enable_fixture_live_mode(monkeypatch)
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_stream_bytes(GEMINI),
        )

    events = [
        event
        async for event in stream_openrouter_chat_completions(
            messages=MESSAGES,
            temperature=0.2,
            max_tokens=256,
            model_id=GEMINI,
            upstream_model=GEMINI,
            provider="Google",
            transport=httpx.MockTransport(handler),
        )
    ]

    assert len(seen) == 1
    assert seen[0]["model"] == GEMINI
    assert seen[0]["stream"] is True
    assert seen[0]["provider"] == PRIVACY_POLICY
    assert [event.delta_content for event in events if event.delta_content] == ["첫 토큰"]
    assert events[-1].done is True
