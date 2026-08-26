from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.b14_client import B14Client, ChatRuntimeError
from app.config import Settings
from app.dispatch_quota import (
    DispatchAwareB14Client,
    DispatchAwareUsageCounterStore,
    _refund_active_reservation,
)
from app.skills import get_skill
from app.usage_gate import UsageDecision


AUTO_PATH = "/api/pilot/v1/chat/completions/auto-stream-preview"
MESSAGES = [{"role": "user", "content": "안녕하세요"}]
WINNING_MODEL = "openrouter/free"
WINNING_PROVIDER = "OpenRouter (free router)"


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _settings() -> Settings:
    return Settings(runtime_mode="b14", b14_base_url="https://b14.internal")


def _frame(content: str) -> bytes:
    payload = {
        "id": "b62_auto_stream_1",
        "object": "chat.completion.chunk",
        "model": WINNING_MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
        "business14": {
            "request_id": "b14_auto_stream_1",
            "route_mode": "auto",
            "selected_provider": WINNING_PROVIDER,
            "selected_model": WINNING_MODEL,
            "selected_upstream_model": WINNING_MODEL,
            "selected_route_id": f"openrouter:{WINNING_MODEL}",
            "reason_codes": ["capabilities:free", f"selected:{WINNING_MODEL}"],
            "fallback_used": True,
            "attempt_count": 2,
            "route_evidence_status": "live_streaming_router_preview",
        },
    }
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


def _error_frame(code: str = "upstream_rate_limited") -> bytes:
    payload = {
        "error": {
            "code": code,
            "message": "bounded B14 stream error",
            "request_id": "b14_auto_stream_1",
            "after_stream_start": True,
        }
    }
    return (
        b"event: error\ndata: "
        + json.dumps(payload).encode("utf-8")
        + b"\n\n"
    )


def test_private_auto_stream_uses_core_auto_endpoint_and_product_policy():
    async def scenario():
        seen_url = None
        seen = None
        upstream = ChunkStream([_frame("자동 토큰"), b"data: [DONE]\n\n"])

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal seen_url, seen
            seen_url = str(request.url)
            seen = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=upstream,
            )

        client = B14Client(
            _settings(),
            stream_transport=httpx.MockTransport(handler),
            require_service_binding=True,
        )
        events = [
            event
            async for event in client.stream_text_auto(
                MESSAGES,
                additional_system_context="PROJECT CONTEXT",
            )
        ]

        skill = get_skill()
        assert seen_url == "https://b14.internal" + AUTO_PATH
        assert seen["stream"] is True
        assert seen["model"] == "b14/auto"
        assert seen["business14"]["required_capabilities"] == ["free"]
        assert seen["business14"]["allow_external_fallback"] is True
        assert seen["business14"]["max_attempts"] == 3
        assert seen["business14"]["task_type"] == skill.task_type
        assert seen["business14"]["optimize_for"] == skill.optimize_for
        assert seen["messages"][0]["role"] == "system"
        assert "PROJECT CONTEXT" in seen["messages"][0]["content"]

        assert events[0].delta_content == "자동 토큰"
        assert events[0].route.route_mode == "auto"
        assert events[0].route.selected_model == WINNING_MODEL
        assert events[0].route.selected_provider == WINNING_PROVIDER
        assert events[0].route.fallback_used is True
        assert events[0].route.attempt_count == 2
        assert events[-1].done is True
        assert events[-1].route.selected_model == WINNING_MODEL
        assert upstream.closed is True

    asyncio.run(scenario())


def test_private_auto_stream_post_start_error_is_bounded_no_fake_done():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([_frame("부분"), _error_frame()]),
        )

    client = B14Client(_settings(), stream_transport=httpx.MockTransport(handler))

    async def scenario():
        received = []
        with pytest.raises(ChatRuntimeError) as info:
            async for event in client.stream_text_auto(MESSAGES):
                received.append(event)
        assert [event.delta_content for event in received] == ["부분"]
        assert all(event.done is False for event in received)
        assert info.value.status_code == 503
        assert info.value.code == "upstream_busy"
        assert "bounded B14 stream error" not in info.value.user_message

    asyncio.run(scenario())


def test_private_auto_stream_missing_binding_fails_closed_without_public_http():
    public_calls = 0

    async def public_handler(request: httpx.Request) -> httpx.Response:
        nonlocal public_calls
        public_calls += 1
        return httpx.Response(200)

    client = B14Client(
        _settings(),
        transport=httpx.MockTransport(public_handler),
        require_service_binding=True,
    )

    async def scenario():
        with pytest.raises(ChatRuntimeError) as info:
            async for _ in client.stream_text_auto(MESSAGES):
                pass
        assert info.value.status_code == 503
        assert info.value.code == "upstream_binding_unavailable"

    asyncio.run(scenario())
    assert public_calls == 0


def test_private_auto_stream_consumer_close_closes_core_transport():
    async def scenario():
        upstream = ChunkStream([_frame("부분"), b"data: [DONE]\n\n"])

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=upstream,
            )

        client = B14Client(_settings(), stream_transport=httpx.MockTransport(handler))
        stream = client.stream_text_auto(MESSAGES)
        first = await anext(stream)
        assert first.delta_content == "부분"
        await stream.aclose()
        assert upstream.closed is True

    asyncio.run(scenario())


def test_mock_private_auto_stream_is_deterministic_and_zero_network():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = B14Client(
        Settings(runtime_mode="mock"),
        stream_transport=httpx.MockTransport(handler),
        require_service_binding=True,
    )

    async def scenario():
        events = [event async for event in client.stream_text_auto(MESSAGES)]
        assert events[0].delta_content.startswith("모의 자동 스트리밍 상태입니다")
        assert events[0].model == "b14/auto"
        assert events[-1].done is True

    asyncio.run(scenario())
    assert calls == 0


def test_private_auto_stream_does_not_claim_attachment_tool_or_model_arguments():
    client = B14Client(Settings(runtime_mode="mock"))
    with pytest.raises(TypeError):
        client.stream_text_auto(MESSAGES, attachments=())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        client.stream_text_auto(MESSAGES, tool="web_search")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        client.stream_text_auto(MESSAGES, model=WINNING_MODEL)  # type: ignore[call-arg]


class ReservationStore:
    def __init__(self):
        self.refunds: list[dict] = []

    async def consume(self, **kwargs):
        return UsageDecision(allowed=True)

    async def _refund(self, **kwargs):
        self.refunds.append(kwargs)


async def _reserve(store: ReservationStore) -> None:
    await DispatchAwareUsageCounterStore(store).consume(
        subject_type="user",
        subject_key="user-auto",
        minute_bucket="2026-08-26T09:00",
        day_bucket="2026-08-26",
        burst_limit=8,
        daily_limit=100,
        global_daily_limit=1000,
        updated_at="2026-08-26T09:00:00Z",
    )


def test_dispatch_aware_auto_stream_refunds_missing_binding_pre_dispatch():
    async def scenario():
        store = ReservationStore()
        await _reserve(store)
        client = DispatchAwareB14Client(_settings(), require_service_binding=True)

        with pytest.raises(ChatRuntimeError) as info:
            async for _ in client.stream_text_auto(MESSAGES):
                pass

        assert info.value.code == "upstream_binding_unavailable"
        assert len(store.refunds) == 3
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_dispatch_aware_auto_stream_clears_refund_before_transport_attempt():
    async def scenario():
        store = ReservationStore()
        await _reserve(store)
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500, content=b"ambiguous upstream failure")

        client = DispatchAwareB14Client(
            _settings(),
            stream_transport=httpx.MockTransport(handler),
            require_service_binding=True,
        )
        with pytest.raises(ChatRuntimeError):
            async for _ in client.stream_text_auto(MESSAGES):
                pass

        assert calls == 1
        assert store.refunds == []
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())
