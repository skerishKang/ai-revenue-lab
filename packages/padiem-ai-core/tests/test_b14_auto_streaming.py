from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core.b14_execution import (
    B14ChatRequest,
    B14ExecutionConfig,
    B14ExecutionError,
    B14RoutingOptions,
)
from padiem_ai_core.b14_streaming import B14StreamingClient


BASE_URL = "https://b14.internal"
AUTO_PATH = "/api/pilot/v1/chat/completions/auto-stream-preview"


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self, first: bytes):
        self.first = first
        self.closed = False
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()

    async def __aiter__(self):
        yield self.first
        self.blocked.set()
        await self.release.wait()
        yield b"data: [DONE]\n\n"

    async def aclose(self) -> None:
        self.closed = True
        self.release.set()


def auto_request(
    *,
    routing: B14RoutingOptions | None = None,
) -> B14ChatRequest:
    return B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model="b14/auto",
        temperature=0.3,
        max_tokens=128,
        routing=routing
        or B14RoutingOptions(
            task_type="general",
            required_capabilities=("free",),
            optimize_for="balanced",
            allow_external_fallback=True,
            max_attempts=2,
        ),
    )


def chunk_payload(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: dict | None = None,
    selected_model: str = "openrouter/free",
    selected_provider: str = "OpenRouter (free router)",
    attempt: int = 2,
    fallback_used: bool = True,
) -> dict:
    choices = []
    if content is not None or finish_reason is not None:
        choices = [
            {
                "index": 0,
                "delta": {} if content is None else {"content": content},
                "finish_reason": finish_reason,
            }
        ]
    payload = {
        "id": "b14req_auto_stream",
        "object": "chat.completion.chunk",
        "model": selected_model,
        "choices": choices,
        "business14": {
            "request_id": "b14req_auto_stream",
            "route_mode": "auto",
            "selected_provider": selected_provider,
            "selected_model": selected_model,
            "selected_upstream_model": selected_model,
            "selected_route_id": f"openrouter:{selected_model}",
            "reason_codes": ["capabilities:free", f"selected:{selected_model}"],
            "fallback_used": fallback_used,
            "attempt_count": attempt,
            "route_evidence_status": "live_streaming_router_preview",
            "committed": bool(content),
        },
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


async def collect_auto(client: B14StreamingClient, req: B14ChatRequest):
    return [event async for event in client.stream_auto(req)]


def test_auto_stream_uses_fixed_staged_endpoint_and_preserves_routing_options():
    seen_url = None
    seen_body = None

    raw = (
        sse(chunk_payload(content="자동"))
        + sse(
            chunk_payload(
                finish_reason="stop",
                usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            )
        )
        + b"data: [DONE]\n\n"
    )

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal seen_url, seen_body
        seen_url = str(req.url)
        seen_body = json.loads(req.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            stream=ChunkStream([raw[:13], raw[13:67], raw[67:]]),
        )

    routing = B14RoutingOptions(
        task_type="korean",
        required_capabilities=("free",),
        optimize_for="korean",
        allow_external_fallback=True,
        provider_order=("OpenRouter (free router)", "Stealth"),
        max_attempts=2,
    )
    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    events = asyncio.run(collect_auto(client, auto_request(routing=routing)))

    assert seen_url == BASE_URL + AUTO_PATH
    assert seen_body == {
        "model": "b14/auto",
        "messages": [{"role": "user", "content": "안녕하세요"}],
        "temperature": 0.3,
        "max_tokens": 128,
        "business14": {
            "task_type": "korean",
            "required_capabilities": ["free"],
            "optimize_for": "korean",
            "allow_external_fallback": True,
            "provider_order": ["OpenRouter (free router)", "Stealth"],
            "max_attempts": 2,
        },
        "stream": True,
    }
    assert events[0].delta_content == "자동"
    assert events[0].route.route_mode == "auto"
    assert events[0].route.selected_model == "openrouter/free"
    assert events[0].route.selected_provider == "OpenRouter (free router)"
    assert events[0].route.fallback_used is True
    assert events[0].route.attempt_count == 2
    assert "capabilities:free" in events[0].route.reason_codes
    assert events[1].finish_reason == "stop"
    assert events[1].usage.total_tokens == 5
    assert events[-1].done is True
    assert events[-1].route.selected_model == "openrouter/free"
    assert events[-1].route.attempt_count == 2


def test_stream_auto_rejects_explicit_model_before_network():
    calls = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    req = B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model="openrouter/free",
    )

    with pytest.raises(B14ExecutionError) as exc:
        asyncio.run(collect_auto(client, req))
    assert exc.value.code == "streaming_request_unsupported"
    assert calls == 0


def test_existing_manual_stream_still_rejects_auto_and_fallback_before_network():
    calls = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )

    async def manual_collect(req: B14ChatRequest):
        return [event async for event in client.stream(req)]

    with pytest.raises(B14ExecutionError) as auto_exc:
        asyncio.run(manual_collect(auto_request()))
    assert auto_exc.value.code == "streaming_request_unsupported"

    explicit_with_fallback = B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model="openrouter/free",
        routing=B14RoutingOptions(allow_external_fallback=True, max_attempts=2),
    )
    with pytest.raises(B14ExecutionError) as fallback_exc:
        asyncio.run(manual_collect(explicit_with_fallback))
    assert fallback_exc.value.code == "streaming_request_unsupported"
    assert calls == 0


def test_auto_post_start_error_event_is_bounded_and_not_completion():
    error_payload = {
        "error": {
            "code": "upstream_rate_limited",
            "message": "Provider rate limit에 도달했습니다.",
            "request_id": "b14req_auto_stream",
            "after_stream_start": True,
        },
        "business14": {
            "selected_model": "openrouter/free",
            "attempt_count": 2,
        },
    }
    raw = (
        sse(chunk_payload(content="부분"))
        + b"event: error\ndata: "
        + json.dumps(error_payload, ensure_ascii=False).encode("utf-8")
        + b"\n\n"
    )

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([raw]),
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )

    async def exercise():
        received = []
        try:
            async for event in client.stream_auto(auto_request()):
                received.append(event)
        except B14ExecutionError as exc:
            return received, exc
        raise AssertionError("expected B14ExecutionError")

    received, exc = asyncio.run(exercise())
    assert [event.delta_content for event in received] == ["부분"]
    assert all(event.done is False for event in received)
    assert exc.code == "upstream_rate_limited"
    assert exc.retryable is False
    assert exc.upstream_status_code == 200


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "upstream_auth_error", False),
        (403, "upstream_auth_error", False),
        (429, "upstream_rate_limited", True),
        (422, "upstream_request_error", False),
        (500, "upstream_server_error", True),
    ],
)
def test_auto_http_status_normalization_reuses_core_contract(status, code, retryable):
    async def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == AUTO_PATH
        return httpx.Response(status, content=b"raw secret-like body")

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        asyncio.run(collect_auto(client, auto_request()))
    assert exc.value.code == code
    assert exc.value.retryable is retryable
    assert "raw secret-like body" not in exc.value.safe_message


def test_auto_wrong_content_type_and_missing_done_fail_closed():
    async def wrong_type(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(wrong_type),
    )
    with pytest.raises(B14ExecutionError) as wrong_exc:
        asyncio.run(collect_auto(client, auto_request()))
    assert wrong_exc.value.code == "malformed_upstream"

    async def no_done(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([sse(chunk_payload(content="미완료"))]),
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(no_done),
    )
    with pytest.raises(B14ExecutionError) as done_exc:
        asyncio.run(collect_auto(client, auto_request()))
    assert done_exc.value.code == "malformed_upstream"
    assert "completion marker" in done_exc.value.safe_message


def test_auto_cumulative_byte_cap_is_shared():
    raw = sse(chunk_payload(content="x" * 200)) + b"data: [DONE]\n\n"

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([raw]),
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL, max_response_bytes=80),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        asyncio.run(collect_auto(client, auto_request()))
    assert exc.value.code == "upstream_response_too_large"


def test_auto_timeout_and_transport_errors_are_secret_free():
    async def timeout_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("auto secret timeout", request=req)

    timeout_client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(B14ExecutionError) as timeout_exc:
        asyncio.run(collect_auto(timeout_client, auto_request()))
    assert timeout_exc.value.code == "upstream_timeout"
    assert "auto secret timeout" not in timeout_exc.value.safe_message

    async def error_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("auto secret transport", request=req)

    transport_client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(error_handler),
    )
    with pytest.raises(B14ExecutionError) as transport_exc:
        asyncio.run(collect_auto(transport_client, auto_request()))
    assert transport_exc.value.code == "upstream_unavailable"
    assert "auto secret transport" not in transport_exc.value.safe_message


def test_auto_consumer_close_closes_underlying_response_stream():
    async def scenario():
        body = BlockingStream(sse(chunk_payload(content="첫 토큰")))

        async def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=body,
            )

        client = B14StreamingClient(
            B14ExecutionConfig(BASE_URL),
            transport=httpx.MockTransport(handler),
        )
        stream = client.stream_auto(auto_request())
        first = await anext(stream)
        assert first.delta_content == "첫 토큰"
        await stream.aclose()
        assert body.closed is True

    asyncio.run(scenario())
