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
from padiem_ai_core.tool_channel import ToolDefinition


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


async def _collect(client: B14StreamingClient, req: B14ChatRequest):
    return [event async for event in client.stream(req)]


def collect(client: B14StreamingClient, req: B14ChatRequest):
    return asyncio.run(_collect(client, req))


def test_fragmented_sse_normalizes_delta_usage_route_and_done():
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
    events = collect(client, request())

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


def test_comments_and_sse_metadata_are_ignored():
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

    events = collect(
        B14StreamingClient(B14ExecutionConfig(BASE_URL), httpx.MockTransport(handler)),
        request(),
    )
    assert [event.delta_content for event in events if event.delta_content] == ["A"]
    assert events[-1].done is True


@pytest.mark.parametrize(
    "req",
    [
        request(model="b14/auto"),
        request(routing=B14RoutingOptions(allow_external_fallback=True)),
    ],
)
def test_unsupported_stream_policy_fails_before_network(req: B14ChatRequest):
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
        collect(client, req)
    assert exc.value.code == "streaming_request_unsupported"
    assert calls == 0


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
def test_http_status_errors_match_existing_core_contract(status, code, retryable):
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"raw body must not escape")

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        collect(client, request())
    assert exc.value.code == code
    assert exc.value.retryable is retryable
    assert "raw body" not in exc.value.safe_message


def test_post_start_error_event_becomes_safe_non_retryable_error():
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

    async def exercise():
        received = []
        try:
            async for event in client.stream(request()):
                received.append(event)
        except B14ExecutionError as exc:
            return received, exc
        raise AssertionError("expected B14ExecutionError")

    received, exc = asyncio.run(exercise())
    assert received[0].delta_content == "먼저"
    assert exc.code == "upstream_rate_limited"
    assert exc.retryable is False
    assert exc.upstream_status_code == 200


def test_missing_done_fails_closed():
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
        collect(client, request())
    assert exc.value.code == "malformed_upstream"
    assert "completion marker" in exc.value.safe_message


@pytest.mark.parametrize(
    "raw",
    [
        b"data: not-json\n\n",
        b"data: \xff\xfe\n\n",
        b'data: {"object":"wrong","choices":[]}\n\n',
        b'data: {"object":"chat.completion.chunk","choices":[]}\n\n',
    ],
)
def test_malformed_stream_fails_closed(raw: bytes):
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
        collect(client, request())
    assert exc.value.code == "malformed_upstream"


def test_wrong_content_type_fails_closed():
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        collect(client, request())
    assert exc.value.code == "malformed_upstream"


def test_cumulative_byte_cap_aborts_stream():
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
        collect(client, request())
    assert exc.value.code == "upstream_response_too_large"


def test_many_small_sse_frames_exceeding_old_aggregate_ceiling_still_complete():
    # The provider sends 12 short deltas, coalesced by the transport.
    # Each frame is bounded; the total stream is not a new output-token cap.
    frames = [sse(chunk_payload(content=f"delta-{i}")) for i in range(12)]
    cap = max(len(frame) for frame in frames) + 40
    raw = b"".join(frames) + b"data: [DONE]\n\n"
    assert len(raw) > cap * 3

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            stream=ChunkStream([raw]),
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL, max_response_bytes=cap),
        transport=httpx.MockTransport(handler),
    )
    events = collect(client, request())
    assert [e.delta_content for e in events if e.delta_content] == [
        f"delta-{i}" for i in range(12)
    ]
    assert events[-1].done is True


def test_fragmented_single_oversize_sse_frame_fails_closed():
    frame = sse(chunk_payload(content="x" * 900))
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              stream=ChunkStream([frame[:100], frame[100:]]))
    client = B14StreamingClient(B14ExecutionConfig(BASE_URL, max_response_bytes=700),
                                transport=httpx.MockTransport(handler))
    with pytest.raises(B14ExecutionError) as err:
        collect(client, request())
    assert err.value.code == "upstream_response_too_large"

def test_timeout_and_transport_errors_are_normalized():
    async def timeout_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret timeout detail", request=req)

    timeout_client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(B14ExecutionError) as timeout_exc:
        collect(timeout_client, request())
    assert timeout_exc.value.code == "upstream_timeout"
    assert "secret timeout detail" not in timeout_exc.value.safe_message

    async def error_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret transport detail", request=req)

    transport_client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL),
        transport=httpx.MockTransport(error_handler),
    )
    with pytest.raises(B14ExecutionError) as transport_exc:
        collect(transport_client, request())
    assert transport_exc.value.code == "upstream_unavailable"
    assert "secret transport detail" not in transport_exc.value.safe_message


def test_stream_event_is_frozen_public_contract():
    from dataclasses import FrozenInstanceError
    from padiem_ai_core.b14_streaming import B14StreamEvent

    event = B14StreamEvent(delta_content="x")
    with pytest.raises(FrozenInstanceError):
        event.delta_content = "y"  # type: ignore[misc]
    assert event.to_public_dict()["delta_content"] == "x"


class DelayedChunkStream(httpx.AsyncByteStream):
    """A fake stream that can outlive a total deadline while remaining active."""

    def __init__(self, chunks: list[bytes], *, delay: float):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def test_per_chunk_idle_watchdog_allows_healthy_stream_beyond_total_timeout():
    """Two 0.65s chunks should succeed even when total response exceeds 1s."""
    stream = DelayedChunkStream(
        [sse(chunk_payload(content="progress")), b"data: [DONE]\n\n"], delay=0.65
    )

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL, timeout_seconds=1.0),
        transport=httpx.MockTransport(handler),
    )
    result = collect(client, request())
    assert result[0].delta_content == "progress"
    assert result[-1].done is True
    assert stream.closed is True


def test_per_chunk_idle_watchdog_times_out_and_closes_stalled_stream():
    """Even a non-HTTPX-compliant transport cannot wait forever for a chunk."""
    stream = DelayedChunkStream(
        [sse(chunk_payload(content="too late"))], delay=1.15
    )

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL, timeout_seconds=1.0),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        collect(client, request())
    assert exc.value.code == "upstream_timeout"
    assert stream.closed is True


def test_stream_header_wait_has_idle_limit_even_without_httpx_timeout_support():
    async def handler(req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.15)
        return httpx.Response(200, headers={"content-type": "text/event-stream"})

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL, timeout_seconds=1.0),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as exc:
        collect(client, request())
    assert exc.value.code == "upstream_timeout"


@pytest.mark.asyncio
async def test_stream_user_cancel_propagates_without_waiting_for_idle_timeout():
    stream = DelayedChunkStream([sse(chunk_payload(content="late"))], delay=5.0)

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )

    client = B14StreamingClient(
        B14ExecutionConfig(BASE_URL, timeout_seconds=600.0),
        transport=httpx.MockTransport(handler),
    )
    entered = asyncio.Event()

    async def runner():
        entered.set()
        return [event async for event in client.stream(request())]

    task = asyncio.create_task(runner())
    await entered.wait()
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed is True


def test_a_plain_streaming_routing_is_supported():
    """#4317: without an attempt count to refuse, the plain policy streams.

    The old contract refused a routing that carried an attempt count other
    than one. There is no attempt count any more, so the plain routing is an
    ordinary supported streaming request.
    """
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([sse(chunk_payload(content="A")), b"data: [DONE]\n\n"]),
        )

    events = collect(
        B14StreamingClient(B14ExecutionConfig(BASE_URL), httpx.MockTransport(handler)),
        request(),
    )
    assert [event.delta_content for event in events if event.delta_content] == ["A"]
    assert events[-1].done is True


# #5573 slice 3-B-1: the opt-in P01 events added by B14 #5697.
def tool_request() -> B14ChatRequest:
    return B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model="google/gemini-3.1-flash-lite",
        tools=(ToolDefinition(name="pc_files"),),
        tool_choice="auto",
    )


def named_sse(name: str, payload: dict) -> bytes:
    return b"event: " + name.encode() + b"\n" + sse(payload)


def tool_stream_client(raw: bytes):
    stream = ChunkStream([raw[:17], raw[17:53], raw[53:]])
    sent = []

    async def handler(req: httpx.Request) -> httpx.Response:
        sent.append(req.content)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )

    return (
        B14StreamingClient(B14ExecutionConfig(BASE_URL), transport=httpx.MockTransport(handler)),
        stream,
        sent,
    )


@pytest.mark.parametrize("ending", [b"\n\n", b""])
def test_b14_google_tool_call_fixture_parses_complete_arguments_and_done(ending):
    # Exact frames from B14 test_google_tools_emit_tool_call_event (#5697).
    raw = (
        b'event: tool_call\ndata: {"id":"call_native","name":"pc_files","arguments":"{\\"plan\\":\\"files_list\\"}","index":0}\n\n'
        b'event: done\ndata: {"finish_reason":"tool_calls"}' + ending
    )
    client, stream, _ = tool_stream_client(raw)
    events = collect(client, tool_request())
    assert len(events) == 2
    assert events[0].tool_call.to_public_dict() == {
        "id": "call_native", "name": "pc_files",
        "arguments": {"plan": "files_list"}, "index": 0,
    }
    assert events[0].delta_content is None and not events[0].done
    assert events[1].done and events[1].finish_reason == "tool_calls"
    assert events[1].tool_call is None
    assert stream.closed


def test_a_streamed_call_signature_is_preserved_for_the_follow_up():
    client, stream, _ = tool_stream_client(
        named_sse("tool_call", {
            "id": "call_1", "name": "pc_files", "arguments": '{"plan":"files_list"}',
            "index": 0, "signature": "sig_native_abc123",
        })
        + named_sse("done", {"finish_reason": "tool_calls"})
    )

    events = collect(client, tool_request())

    assert events[0].tool_call.signature == "sig_native_abc123"
    assert events[0].tool_call.to_public_dict()["signature"] == "sig_native_abc123"
    assert stream.closed


def test_a_malformed_streamed_signature_is_refused():
    for signature in (123, "", "x" * 65_537):
        client, stream, _ = tool_stream_client(
            named_sse("tool_call", {
                "id": "call_1", "name": "pc_files", "arguments": "{}",
                "index": 0, "signature": signature,
            })
        )

        with pytest.raises(B14ExecutionError) as exc:
            collect(client, tool_request())
        assert exc.value.code == "malformed_upstream"
        assert stream.closed


@pytest.mark.parametrize("finish_reason", ["stop", "length", "tool_calls"])
def test_tool_stream_done_preserves_finish_reason_and_last_text_route(finish_reason):
    client, stream, _ = tool_stream_client(
        sse(chunk_payload(content="text"))
        + named_sse("tool_call", {
            "id": "call_1", "name": "pc_files",
            "arguments": '{"plan":"files_list"}', "index": 0,
        })
        + named_sse("done", {"finish_reason": finish_reason})
    )
    events = collect(client, tool_request())
    assert events[-1].done and events[-1].finish_reason == finish_reason
    assert events[-1].route == events[0].route
    assert events[-1].route.selected_model == MODEL
    assert stream.closed


@pytest.mark.parametrize("arguments", [
    "not-json", "", "[]", "null", "1", '"text"', None, {}, '{"n":NaN}',
])
def test_invalid_streamed_tool_arguments_terminate_before_following_events(arguments):
    client, stream, _ = tool_stream_client(
        named_sse("tool_call", {
            "id": "call_1", "name": "pc_files", "arguments": arguments, "index": 0,
        })
        + sse(chunk_payload(content="must not arrive"))
        + named_sse("done", {"finish_reason": "tool_calls"})
    )

    async def exercise():
        received = []
        with pytest.raises(B14ExecutionError) as exc:
            async for event in client.stream(tool_request()):
                received.append(event)
        assert exc.value.code == "malformed_upstream"
        assert exc.value.upstream_status_code == 200
        assert received == []

    asyncio.run(exercise())
    assert stream.closed


@pytest.mark.parametrize("name,payload", [
    ("tool_call", {"id": "call_1", "name": "pc_files", "arguments": "{}", "index": -1}),
    ("tool_call", {"id": "call_1", "name": "pc_files", "arguments": "{}", "index": True}),
    ("tool_call", {"id": None, "name": "pc_files", "arguments": "{}", "index": 0}),
    ("done", {}),
    ("done", {"finish_reason": 1}),
])
def test_invalid_tool_event_metadata_is_malformed(name, payload):
    client, stream, _ = tool_stream_client(named_sse(name, payload))
    with pytest.raises(B14ExecutionError) as exc:
        collect(client, tool_request())
    assert exc.value.code == "malformed_upstream"
    assert stream.closed


@pytest.mark.parametrize("name,payload", [
    ("tool_call", {"id": "call_1", "name": "pc_files", "arguments": "{}", "index": 0}),
    ("done", {"finish_reason": "stop"}),
])
def test_no_tools_keeps_named_events_unsupported(name, payload):
    client, stream, _ = tool_stream_client(named_sse(name, payload))
    with pytest.raises(B14ExecutionError) as exc:
        collect(client, request())
    assert exc.value.code == "malformed_upstream"
    assert stream.closed


def test_stream_tools_request_bytes_and_legacy_public_objects_are_unchanged():
    raw = sse(chunk_payload(content="hello")) + b"data: [DONE]\n\n"
    client, _, bodies = tool_stream_client(raw)
    events = collect(client, request())
    legacy_body = '{"model":"openrouter/free","messages":[{"role":"user","content":"안녕하세요"}],"stream":true}'.encode()
    assert bodies == [legacy_body]
    expected_route = {
        "request_id": "b14stream_1", "route_mode": "manual",
        "selected_provider": "OpenRouter", "selected_model": MODEL,
        "selected_upstream_model": MODEL, "selected_route_id": f"openrouter:{MODEL}",
        "actual_response_model": None, "reason_codes": [], "fallback_used": False,
        "attempt_count": 1, "route_evidence_status": "live_streaming_preview",
        "estimated_krw": None,
    }
    expected = [
        {
            "response_id": "stream_1" if not done else None,
            "model": MODEL if not done else None,
            "delta_content": "hello" if not done else None, "finish_reason": None,
            "usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None},
            "route": expected_route, "done": done,
        }
        for done in (False, True)
    ]
    actual = [event.to_public_dict() for event in events]
    assert actual == expected
    assert json.dumps(actual).encode() == json.dumps(expected).encode()

    # Explicit empty tools/omitted tool_choice must produce the same wire bytes.
    collect(client, B14ChatRequest(messages=request().messages, model=MODEL, tools=()))
    assert bodies[-1] == legacy_body
    collect(client, tool_request())
    assert bodies[-1] == (
        '{"model":"google/gemini-3.1-flash-lite","messages":[{"role":"user","content":"안녕하세요"}],'
        '"tools":[{"type":"function","function":{"name":"pc_files","parameters":{"type":"object","properties":{}}}}],'
        '"tool_choice":"auto","stream":true}'
    ).encode()


def test_tool_call_without_completion_is_not_a_successful_stream():
    client, stream, _ = tool_stream_client(named_sse("tool_call", {
        "id": "call_1", "name": "pc_files", "arguments": "{}", "index": 0,
    }))
    with pytest.raises(B14ExecutionError) as exc:
        collect(client, tool_request())
    assert exc.value.code == "malformed_upstream"
    assert stream.closed


def test_streamed_tool_call_public_arguments_remain_json_serializable():
    arguments = {"filter": {"extensions": ["txt", "md"]}, "items": [{"nested": {"ok": True}}]}
    client, _, _ = tool_stream_client(
        named_sse("tool_call", {
            "id": "call_1", "name": "pc_files",
            "arguments": json.dumps(arguments), "index": 1,
        }) + named_sse("done", {"finish_reason": "tool_calls"})
    )
    event = collect(client, tool_request())[0]
    public = json.loads(json.dumps(event.to_public_dict()))
    assert public["tool_call"]["arguments"] == arguments
    assert public["tool_call"]["index"] == 1
