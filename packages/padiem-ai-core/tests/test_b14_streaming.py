from __future__ import annotations

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
MODEL = "openrouter/free"


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def request(*, model: str = MODEL, routing: B14RoutingOptions | None = None) -> B14ChatRequest:
    return B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model=model,
        routing=routing or B14RoutingOptions(),
    )


def chunk_payload(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: dict | None = None,
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
        "id": "stream_1",
        "object": "chat.completion.chunk",
        "model": MODEL,
        "choices": choices,
        "business14": {
            "request_id": "b14stream_1",
            "route_mode": "manual",
            "selected_provider": "OpenRouter",
            "selected_model": MODEL,
            "selected_upstream_model": MODEL,
            "selected_route_id": f"openrouter:{MODEL}",
            "fallback_used": False,
            "attempt_count": 1,
            "route_evidence_status": "live_streaming_preview",
        },
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def sse(payload: dict, *, ending: bytes = b"\n\n") -> bytes:
    return b"data: " + json.dumps(payload).encode() + ending


async def collect(client: B14StreamingClient, req: B14ChatRequest):
    return [event async for event in client.stream(req)]


@pytest.mark.asyncio
async def test_fragmented_sse_normalizes_delta_usage_route_and_done():
    first = sse(chunk_payload(content="안녕"))
    finish = sse(
        chunk_payload(
            finish_reason="stop",
            usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        ),
        ending=b"\r\n\r\n",
    )
    raw = first + finish + b"data: [DONE]\n\n"
    chunks = [raw[:7], raw[7:21], raw[21:83], raw[83:]]
    seen_request = None

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = json.loads(req.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            stream=ChunkStream(chunks),
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    events = await collect(client, request())

    assert seen_request["stream"] is True
    assert seen_request["model"] == MODEL
    assert events[0].delta_content == "안녕"
    assert events[0].route.selected_model == MODEL
    assert events[0].route.selected_provider == "OpenRouter"
    assert events[1].finish_reason == "stop"
    assert events[1].usage.input_tokens == 2
    assert events[1].usage.output_tokens == 3
    assert events[1].usage.total_tokens == 5
    assert events[-1].done is True
    assert events[-1].route.selected_route_id == f"openrouter:{MODEL}"


@pytest.mark.asyncio
async def test_comments_and_sse_metadata_are_ignored():
    raw = (
        b": keepalive\nretry: 1000\nid: ignored\n\n"
        + sse(chunk_payload(content="A"))
        + b"data: [DONE]\n\n"
    )

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([raw]),
        )

    events = await collect(
        B14StreamingClient(B14ExecutionConfig(BASE_URL), httpx.MockTransport(handler)),
        request(),
    )
    assert [event.delta_content for event in events if event.delta_content] == ["A"]
    assert events[-1].done is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "req",
    [
        request(model="b14/auto"),
        request(routing=B14RoutingOptions(allow_external_fallback=True)),
        request(routing=B14RoutingOptions(max_attempts=2)),
    ],
)
async def test_unsupported_stream_policy_fails_before_network(req: B14ChatRequest):
    calls = 0

    async def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        await collect(client, req)
    assert exc.value.code == "streaming_request_unsupported"
    assert calls == 0


@pytest.mark.asyncio
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
async def test_http_status_errors_match_existing_core_contract(status, code, retryable):
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"raw body must not escape")

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        await collect(client, request())
    assert exc.value.code == code
    assert exc.value.retryable is retryable
    assert "raw body" not in exc.value.safe_message


@pytest.mark.asyncio
async def test_post_start_error_event_becomes_safe_non_retryable_error():
    error_payload = {
        "error": {
            "code": "upstream_rate_limited",
            "message": "Provider rate limit에 도달했습니다.",
            "request_id": "b14stream_1",
            "after_stream_start": True,
        }
    }
    raw = (
        sse(chunk_payload(content="먼저"))
        + b"event: error\ndata: "
        + json.dumps(error_payload, ensure_ascii=False).encode()
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
    received = []
    with pytest.raises(B14ExecutionError) as exc:
        async for event in client.stream(request()):
            received.append(event)
    assert received[0].delta_content == "먼저"
    assert exc.value.code == "upstream_rate_limited"
    assert exc.value.retryable is False
    assert exc.value.upstream_status_code == 200


@pytest.mark.asyncio
async def test_missing_done_fails_closed():
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([sse(chunk_payload(content="partial"))]),
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        await collect(client, request())
    assert exc.value.code == "malformed_upstream"
    assert "completion marker" in exc.value.safe_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        b"data: not-json\n\n",
        b"data: \xff\xfe\n\n",
        b'data: {"object":"wrong","choices":[]}\n\n',
        b'data: {"object":"chat.completion.chunk","choices":[]}\n\n',
    ],
)
async def test_malformed_stream_fails_closed(raw: bytes):
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
    with pytest.raises(B14ExecutionError) as exc:
        await collect(client, request())
    assert exc.value.code == "malformed_upstream"


@pytest.mark.asyncio
async def test_wrong_content_type_fails_closed():
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        await collect(client, request())
    assert exc.value.code == "malformed_upstream"


@pytest.mark.asyncio
async def test_cumulative_byte_cap_aborts_stream():
    raw = sse(chunk_payload(content="x" * 100)) + b"data: [DONE]\n\n"

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([raw]),
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL, max_response_bytes=40),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        await collect(client, request())
    assert exc.value.code == "upstream_response_too_large"


@pytest.mark.asyncio
async def test_timeout_and_transport_errors_are_normalized():
    async def timeout_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret timeout detail", request=req)

    timeout_client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(B14ExecutionError) as timeout_exc:
        await collect(timeout_client, request())
    assert timeout_exc.value.code == "upstream_timeout"
    assert "secret timeout detail" not in timeout_exc.value.safe_message

    async def error_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret transport detail", request=req)

    transport_client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(error_handler),
    )
    with pytest.raises(B14ExecutionError) as transport_exc:
        await collect(transport_client, request())
    assert transport_exc.value.code == "upstream_unavailable"
    assert "secret transport detail" not in transport_exc.value.safe_message


def test_stream_event_is_frozen_public_contract():
    from dataclasses import FrozenInstanceError
    from padiem_ai_core.b14_streaming import B14StreamEvent

    event = B14StreamEvent(delta_content="x")
    with pytest.raises(FrozenInstanceError):
        event.delta_content = "y"  # type: ignore[misc]
    assert event.to_public_dict()["delta_content"] == "x"
