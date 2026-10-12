"""Exact-model Gemma31 Fetch/HTTPX connect-window regression (offline only)."""
from __future__ import annotations

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.b14_timeout_policy import (
    CONNECT_SECONDS,
    GEMMA_31B_CONNECT_SECONDS,
    GEMMA_31B_MODEL_ID,
    ENGINE_MAX_WALL_SECONDS,
    READ_SECONDS,
    build_provider_http_timeout,
)


def test_exact_model_only_gets_extended_connect_window():
    assert CONNECT_SECONDS == 30.0
    assert 31.8 < GEMMA_31B_CONNECT_SECONDS < ENGINE_MAX_WALL_SECONDS
    assert build_provider_http_timeout().connect == CONNECT_SECONDS
    for other in ("google/gemma-4-26b-a4b-it",
                  "google/gemini-3.5-flash-lite",
                  "agnes-ai/agnes-3.0-flash",
                  "opencode-go/step-5-preview-free",
                  "google/gemma-4-31b-it-extra"):
        assert build_provider_http_timeout(other).connect == CONNECT_SECONDS
    scope = build_provider_http_timeout(GEMMA_31B_MODEL_ID)
    assert scope.connect == GEMMA_31B_CONNECT_SECONDS
    assert scope.read == READ_SECONDS
    assert scope.write == build_provider_http_timeout().write
    assert scope.pool == build_provider_http_timeout().pool


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.parametrize("model_id,upstream,provider_id,expected_connect", (
    (GEMMA_31B_MODEL_ID, "gemma-4-31b-it", "google", GEMMA_31B_CONNECT_SECONDS),
    ("google/gemma-4-26b-a4b-it", "gemma-4-26b-a4b-it", "google", CONNECT_SECONDS),
    ("agnes-ai/agnes-3.0-flash", "agnes-3.0-flash", "agnes-ai", CONNECT_SECONDS),
))
async def test_real_adapter_carries_exact_timeout_without_live_provider(
    monkeypatch, stream, model_id, upstream, provider_id, expected_connect,
):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plat, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    observed = []

    def respond(request):
        observed.append((request.extensions["timeout"]["connect"], request.url.host))
        if stream:
            return httpx.Response(
                200, content=(
                    b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
                    b'data: [DONE]\n\n'
                ),
            )
        return httpx.Response(200, json={
            "model": upstream,
            "choices": [{"message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
        })

    arguments = dict(
        model_id=model_id, upstream_model=upstream, provider="synthetic",
        platform_provider_id=provider_id,
        messages=[{"role": "user", "content": "Reply OK."}],
        transport=httpx.MockTransport(respond),
    )
    if stream:
        events = [event async for event in plat.stream_platform_chat_completions(**arguments)]
        assert any(event.delta_content == "OK" for event in events)
        assert events[-1].done
    else:
        result = await plat.call_platform_chat_completions(**arguments)
        assert result["choices"][0]["message"]["content"] == "OK"
    assert len(observed) == 1
    assert observed[0][0] == expected_connect
