from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.b14_client import B14Client, ChatRuntimeError
from app.config import Settings
from app.dispatch_quota import (
    DispatchAwareB14Client,
    DispatchAwareUsageCounterStore,
    _refund_active_reservation,
)
from app.usage_gate import UsageDecision


MODEL = "openrouter/free"
MESSAGES = [{"role": "user", "content": "안녕하세요"}]
WORKER_PATH = Path(__file__).resolve().parents[1] / "worker.py"
MAIN_PATH = Path(__file__).resolve().parents[1] / "app" / "main.py"


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _frame(content: str) -> bytes:
    payload = {
        "id": "b62_private_stream_1",
        "object": "chat.completion.chunk",
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
        "business14": {
            "request_id": "b14_private_stream_1",
            "route_mode": "manual",
            "selected_provider": "OpenRouter",
            "selected_model": MODEL,
            "selected_upstream_model": MODEL,
            "selected_route_id": f"openrouter:{MODEL}",
            "fallback_used": False,
            "attempt_count": 1,
            "route_evidence_status": "stream_preview",
        },
    }
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


def _settings() -> Settings:
    return Settings(runtime_mode="b14", b14_base_url="https://b14.internal")


def test_private_stream_uses_core_contract_and_manual_free_only_payload():
    async def scenario():
        seen = None
        upstream = ChunkStream([_frame("첫 토큰"), b"data: [DONE]\n\n"])

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal seen
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
            async for event in client.stream_text_preview(
                MESSAGES,
                model=MODEL,
                additional_system_context="PROJECT CONTEXT",
            )
        ]

        assert events[0].delta_content == "첫 토큰"
        assert events[0].route.selected_model == MODEL
        assert events[-1].done is True
        assert seen["stream"] is True
        assert seen["model"] == MODEL
        assert seen["business14"]["allow_external_fallback"] is False
        assert seen["business14"]["max_attempts"] == 1
        assert seen["business14"]["required_capabilities"] == ["free"]
        assert seen["messages"][0]["role"] == "system"
        assert "PROJECT CONTEXT" in seen["messages"][0]["content"]
        assert upstream.closed is True

    asyncio.run(scenario())


def test_private_stream_requires_explicit_manual_model_before_network():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = B14Client(_settings(), stream_transport=httpx.MockTransport(handler))

    async def scenario():
        with pytest.raises(ValueError, match="explicit manual model"):
            async for _ in client.stream_text_preview(MESSAGES, model="b14/auto"):
                pass

    asyncio.run(scenario())
    assert calls == 0


def test_private_stream_missing_required_binding_fails_closed_without_public_http():
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
            async for _ in client.stream_text_preview(MESSAGES, model=MODEL):
                pass
        assert info.value.status_code == 503
        assert info.value.code == "upstream_binding_unavailable"

    asyncio.run(scenario())
    assert public_calls == 0


def test_private_stream_translates_core_error_without_raw_body_or_exception_text():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b"SECRET-UPSTREAM-BODY")

    client = B14Client(_settings(), stream_transport=httpx.MockTransport(handler))

    async def scenario():
        with pytest.raises(ChatRuntimeError) as info:
            async for _ in client.stream_text_preview(MESSAGES, model=MODEL):
                pass
        assert info.value.status_code == 503
        assert info.value.code == "upstream_busy"
        assert "SECRET-UPSTREAM-BODY" not in info.value.user_message

    asyncio.run(scenario())


def test_private_stream_consumer_close_closes_core_transport():
    async def scenario():
        upstream = ChunkStream([_frame("부분"), b"data: [DONE]\n\n"])

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=upstream,
            )

        client = B14Client(_settings(), stream_transport=httpx.MockTransport(handler))
        stream = client.stream_text_preview(MESSAGES, model=MODEL)
        first = await anext(stream)
        assert first.delta_content == "부분"
        await stream.aclose()
        assert upstream.closed is True

    asyncio.run(scenario())


def test_mock_private_stream_is_deterministic_and_never_calls_service_transport():
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
        events = [event async for event in client.stream_text_preview(MESSAGES, model=MODEL)]
        assert events[0].delta_content.startswith("모의 스트리밍 상태입니다")
        assert events[-1].done is True

    asyncio.run(scenario())
    assert calls == 0


def test_private_stream_does_not_claim_attachment_or_tool_arguments():
    client = B14Client(Settings(runtime_mode="mock"))
    with pytest.raises(TypeError):
        client.stream_text_preview(MESSAGES, model=MODEL, attachments=())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        client.stream_text_preview(MESSAGES, model=MODEL, tool="web_search")  # type: ignore[call-arg]


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
        subject_key="user-1",
        minute_bucket="2026-08-26T09:00",
        day_bucket="2026-08-26",
        burst_limit=8,
        daily_limit=100,
        global_daily_limit=1000,
        updated_at="2026-08-26T09:00:00Z",
    )


def test_dispatch_aware_stream_refunds_only_missing_binding_pre_dispatch_failure():
    async def scenario():
        store = ReservationStore()
        await _reserve(store)
        client = DispatchAwareB14Client(_settings(), require_service_binding=True)

        with pytest.raises(ChatRuntimeError) as info:
            async for _ in client.stream_text_preview(MESSAGES, model=MODEL):
                pass

        assert info.value.code == "upstream_binding_unavailable"
        assert len(store.refunds) == 3
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_dispatch_aware_stream_clears_refundability_before_transport_attempt():
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
            async for _ in client.stream_text_preview(MESSAGES, model=MODEL):
                pass

        assert calls == 1
        assert store.refunds == []
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_worker_wires_completed_and_streaming_transports_but_public_route_stays_non_streaming():
    worker = WORKER_PATH.read_text(encoding="utf-8")
    main = MAIN_PATH.read_text(encoding="utf-8")

    assert "CloudflareB14ServiceTransport(b14_binding)" in worker
    assert "CloudflareB14StreamingServiceTransport(b14_binding)" in worker
    assert "stream_transport=stream_transport" in worker
    assert 'Route("/api/chat", api_chat, methods=["POST"])' in main
    assert "/api/chat/stream" not in main
    assert "/api/stream" not in main
