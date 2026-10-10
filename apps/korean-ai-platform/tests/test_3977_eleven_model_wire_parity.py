"""#3977: every registered exact model preserves omitted fields on both wire paths.

MockTransport only.  This does not establish live provider support or E2E.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.pilot.model_registry_file import read_registry
from app.pilot import platform
from app.pilot.upstream_answer_contract import UpstreamEmptyAnswer


REGISTERED = read_registry()["models"]
assert len(REGISTERED) >= 11  # Iterate the canonical registry; future JSON additions are included.


@pytest.mark.asyncio
@pytest.mark.parametrize("model", REGISTERED, ids=lambda item: item["id"])
async def test_all_exact_models_omit_defaults_and_reject_empty_upstream(
    monkeypatch, model
):
    """One bounded non-stream and SSE contract for every provider/model tuple."""
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    # Avoid reading or sending any real platform credential.
    monkeypatch.setattr(
        platform, "_request_headers",
        lambda spec, model_id=None: {"Content-Type": "application/json"},
    )
    seen = []
    empty = False
    upstream = model["upstream_model"]

    async def handler(request):
        body = json.loads(request.content)
        seen.append((str(request.url), body))
        answer = "" if empty else "fixture answer"
        if body.get("stream") is True:
            sse = (
                "data: " + json.dumps({
                    "id": "synthetic", "model": upstream,
                    "choices": [{
                        "delta": {"content": answer}, "finish_reason": "stop"
                    }],
                }) + "\n\n"
                "data: [DONE]\n\n"
            )
            return httpx.Response(
                200, content=sse.encode(), headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json={
            "id": "synthetic", "model": upstream,
            "choices": [{
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }],
        })

    kwargs = {
        "model_id": model["id"],
        "upstream_model": upstream,
        "provider": model["provider_name"],
        "platform_provider_id": model["provider_id"],
        "messages": [{"role": "user", "content": "fixture question"}],
        "transport": httpx.MockTransport(handler),
    }
    response = await platform.call_platform_chat_completions(**kwargs)
    assert response["choices"][0]["message"]["content"] == "fixture answer"

    async def run_stream():
        return [event async for event in platform.stream_platform_chat_completions(**kwargs)]

    events = await run_stream()
    assert any(event.delta_content == "fixture answer" for event in events)
    assert len(seen) == 2
    for url, payload in seen:
        assert url.endswith("/chat/completions")
        assert payload["model"] == upstream
        assert payload["messages"] == kwargs["messages"]
        assert not ({"temperature", "max_tokens", "reasoning_effort", "top_p", "top_k"}
                    & set(payload))
    assert set(seen[0][1]) == {"model", "messages"}
    assert set(seen[1][1]) == {"model", "messages", "stream"}
    assert seen[1][1]["stream"] is True

    # HTTP 200 + empty text is never model-quality success on either route.
    empty = True
    with pytest.raises(UpstreamEmptyAnswer):
        await platform.call_platform_chat_completions(**kwargs)
    with pytest.raises(UpstreamEmptyAnswer):
        await run_stream()
