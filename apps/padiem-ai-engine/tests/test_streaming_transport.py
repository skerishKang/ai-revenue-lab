from __future__ import annotations

import json

import httpx
import pytest

from padiem_ai_core import (
    B14_CHAT_COMPLETIONS_PATH,
    B14_STREAM_PREVIEW_PATH,
    B14ChatRequest,
    B14ExecutionConfig,
    B14ExecutionError,
    B14RoutingOptions,
    B14StreamingClient,
)
from padiem_ai_core.b14_streaming import B14_AUTO_STREAM_PREVIEW_PATH

from app.cloudflare_transport import B14_INTERNAL_ORIGIN
from tests.test_cloudflare_transport import FakeResponse, transport_for


def _chunk(
    content: str | None,
    *,
    finish_reason: str | None = None,
    usage: dict | None = None,
) -> bytes:
    payload = {
        "id": "resp-1",
        "object": "chat.completion.chunk",
        "model": "provider/free-model",
        "choices": [
            {
                "index": 0,
                "delta": ({"content": content} if content is not None else {}),
                "finish_reason": finish_reason,
            }
        ],
        "business14": {
            "request_id": "b14stream-test",
            "route_mode": "manual",
            "selected_provider": "openrouter",
            "selected_model": "openrouter/free",
            "selected_upstream_model": "provider/free-model",
            "selected_route_id": "route-1",
            "fallback_allowed": False,
            "fallback_used": False,
            "attempt_count": 1,
            "route_evidence_status": "test_stream",
        },
    }
    if usage is not None:
        payload["usage"] = usage
    return (
        "data: "
        + json.dumps(payload, separators=(",", ":"))
        + "\n\n"
    ).encode()


def _sse_chunks(*, done: bool = True) -> list[bytes]:
    chunks = [
        _chunk("hel"),
        _chunk(
            "lo",
            finish_reason="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        ),
    ]
    if done:
        chunks.append(b"data: [DONE]\n\n")
    return chunks


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        B14_CHAT_COMPLETIONS_PATH,
        B14_STREAM_PREVIEW_PATH,
        B14_AUTO_STREAM_PREVIEW_PATH,
    ],
)
async def test_transport_allows_exact_core_owned_paths_only(path: str) -> None:
    response = FakeResponse(chunks=[b"{}"])
    transport, binding, factory = transport_for(response=response)
    request = httpx.Request("POST", B14_INTERNAL_ORIGIN + path, json={"x": 1})

    result = await transport.handle_async_request(request)
    await result.aclose()

    assert len(binding.calls) == 1
    assert len(factory.calls) == 1
    assert factory.calls[0].url == B14_INTERNAL_ORIGIN + path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://b14.internal/api/pilot/v1/unknown",
        B14_INTERNAL_ORIGIN + B14_STREAM_PREVIEW_PATH + "?target=x",
        "http://b14.internal" + B14_STREAM_PREVIEW_PATH,
        "https://example.com" + B14_STREAM_PREVIEW_PATH,
        # httpx canonicalizes an explicit default :443 to the same authority as
        # no port before AsyncBaseTransport receives the request. A non-default
        # port is the observable authority override and must fail closed.
        "https://b14.internal:444" + B14_STREAM_PREVIEW_PATH,
        B14_INTERNAL_ORIGIN + B14_STREAM_PREVIEW_PATH + "#fragment",
    ],
)
async def test_transport_rejects_stream_target_override_before_binding(url: str) -> None:
    transport, binding, factory = transport_for(
        response=FakeResponse(chunks=[b"{}"])
    )
    request = httpx.Request("POST", url, json={"x": 1})

    with pytest.raises(httpx.RequestError):
        await transport.handle_async_request(request)

    assert binding.calls == []
    assert factory.calls == []


@pytest.mark.asyncio
async def test_actual_core_manual_stream_client_uses_manual_binding_path() -> None:
    response = FakeResponse(
        chunks=_sse_chunks(),
        content_type="text/event-stream; charset=utf-8",
    )
    transport, binding, factory = transport_for(response=response)
    client = B14StreamingClient(
        B14ExecutionConfig(base_url=B14_INTERNAL_ORIGIN),
        transport=transport,
    )
    request = B14ChatRequest(
        messages=({"role": "user", "content": "hi"},),
        model="openrouter/free",
        routing=B14RoutingOptions(
            allow_external_fallback=False,
            max_attempts=1,
        ),
    )

    events = [event async for event in client.stream(request)]

    assert len(binding.calls) == 1
    assert len(factory.calls) == 1
    assert factory.calls[0].url == B14_INTERNAL_ORIGIN + B14_STREAM_PREVIEW_PATH
    assert [event.delta_content for event in events if event.delta_content] == ["hel", "lo"]
    assert events[-1].done is True
    assert events[-1].route.selected_provider == "openrouter"
    assert events[-1].route.selected_model == "openrouter/free"
    assert response.body.reader.release_calls == 1


@pytest.mark.asyncio
async def test_actual_core_auto_stream_client_uses_auto_binding_path() -> None:
    response = FakeResponse(
        chunks=_sse_chunks(),
        content_type="text/event-stream",
    )
    transport, binding, factory = transport_for(response=response)
    client = B14StreamingClient(
        B14ExecutionConfig(base_url=B14_INTERNAL_ORIGIN),
        transport=transport,
    )
    request = B14ChatRequest(
        messages=({"role": "user", "content": "hi"},),
        model="b14/auto",
    )

    events = [event async for event in client.stream_auto(request)]

    assert len(binding.calls) == 1
    assert len(factory.calls) == 1
    assert factory.calls[0].url == B14_INTERNAL_ORIGIN + B14_AUTO_STREAM_PREVIEW_PATH
    assert events[-1].done is True
    assert response.body.reader.release_calls == 1


@pytest.mark.asyncio
async def test_core_stream_response_ceiling_remains_authoritative() -> None:
    response = FakeResponse(
        chunks=[_chunk("x" * 300), b"data: [DONE]\n\n"],
        content_type="text/event-stream",
    )
    transport, binding, _ = transport_for(response=response)
    client = B14StreamingClient(
        B14ExecutionConfig(
            base_url=B14_INTERNAL_ORIGIN,
            max_response_bytes=64,
        ),
        transport=transport,
    )
    request = B14ChatRequest(
        messages=({"role": "user", "content": "hi"},),
        model="openrouter/free",
        routing=B14RoutingOptions(
            allow_external_fallback=False,
            max_attempts=1,
        ),
    )

    with pytest.raises(B14ExecutionError) as captured:
        _ = [event async for event in client.stream(request)]

    assert captured.value.code == "upstream_response_too_large"
    assert len(binding.calls) == 1
    assert response.body.reader.release_calls == 1


@pytest.mark.asyncio
async def test_core_rejects_stream_without_done_marker() -> None:
    response = FakeResponse(
        chunks=_sse_chunks(done=False),
        content_type="text/event-stream",
    )
    transport, binding, _ = transport_for(response=response)
    client = B14StreamingClient(
        B14ExecutionConfig(base_url=B14_INTERNAL_ORIGIN),
        transport=transport,
    )
    request = B14ChatRequest(
        messages=({"role": "user", "content": "hi"},),
        model="openrouter/free",
        routing=B14RoutingOptions(
            allow_external_fallback=False,
            max_attempts=1,
        ),
    )

    with pytest.raises(B14ExecutionError) as captured:
        _ = [event async for event in client.stream(request)]

    assert captured.value.code == "malformed_upstream"
    assert len(binding.calls) == 1
    assert response.body.reader.release_calls == 1
