"""B14 model first-response wait matches the 600s model idle policy (offline).

The Workers Fetch HTTPX 'connect' phase can encompass waiting for the first
response headers. No 30/55-second model-specific early cut is allowed.
"""
from __future__ import annotations

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.b14_timeout_policy import (
    CONNECT_SECONDS, READ_SECONDS, WRITE_SECONDS, POOL_SECONDS,
    build_provider_http_timeout,
)


@pytest.mark.parametrize("model_id", [
    None,
    "google/gemma-4-31b-it",
    "google/gemma-4-26b-a4b-it",
    "google/gemini-3.5-flash-lite",
    "agnes-ai/agnes-3.0-flash",
    "poolside/laguna-s-2.1",
    "opencode-go/step-5-preview-free",
])
def test_uniform_wait_all_model_ids(model_id):
    assert CONNECT_SECONDS == READ_SECONDS == 600.0
    timeout = build_provider_http_timeout(model_id)
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
        600.0, 600.0, WRITE_SECONDS, POOL_SECONDS
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.parametrize("model_id,upstream,provider_id", (
    ("google/gemma-4-31b-it", "gemma-4-31b-it", "google"),
    ("google/gemma-4-26b-a4b-it", "gemma-4-26b-a4b-it", "google"),
    ("agnes-ai/agnes-3.0-flash", "agnes-3.0-flash", "agnes-ai"),
    ("poolside/laguna-s-2.1", "laguna-s-2.1", "poolside"),
))
async def test_completed_and_stream_adapter_transport_no_early_cut(
    monkeypatch, stream, model_id, upstream, provider_id,
):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(
        plat, "_request_headers",
        lambda spec, model_id="": {"Content-Type": "application/json"},
    )
    observed = []

    def respond(request):
        observed.append((request.extensions["timeout"]["connect"],
                         request.extensions["timeout"]["read"]))
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
    assert observed == [(600.0, 600.0)]
