from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.b14_client import ChatRuntimeError
from app.config import Settings
from app.dispatch_quota import (
    DispatchAwareB14Client,
    DispatchAwareUsageCounterStore,
    _refund_active_reservation,
)
from app.model_policy import DEFAULT_B14_MODEL_ID, DEFAULT_CHAT_PROFILE
from app.usage_gate import UsageDecision


MESSAGES = [{"role": "user", "content": "안녕하세요"}]


class ReservationStore:
    def __init__(self):
        self.refunds: list[dict] = []

    async def consume(self, **kwargs):
        return UsageDecision(allowed=True)

    async def _refund(self, **kwargs):
        self.refunds.append(kwargs)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


async def reserve(store: ReservationStore) -> None:
    await DispatchAwareUsageCounterStore(store).consume(
        subject_type="user",
        subject_key="user-medium",
        minute_bucket="2026-08-28T09:00",
        day_bucket="2026-08-28",
        burst_limit=8,
        daily_limit=100,
        global_daily_limit=1000,
        updated_at="2026-08-28T09:00:00Z",
    )


def live_settings() -> Settings:
    return Settings(
        runtime_mode="b14",
        b14_base_url="https://b14.internal",
        live_enabled=True,
    )


def _completed_payload() -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "안녕하세요."}}],
        "business14": {
            "request_id": "b14req_medium",
            "route_mode": "manual",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_provider": "Google",
            "fallback_used": False,
            "attempt_count": 1,
        },
    }


def _stream_frame(content: str) -> bytes:
    payload = {
        "id": "b14stream_medium",
        "object": "chat.completion.chunk",
        "model": DEFAULT_B14_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
        "business14": {
            "request_id": "b14stream_medium",
            "route_mode": "manual",
            "selected_provider": "Google",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "fallback_used": False,
            "attempt_count": 1,
            "route_evidence_status": "test",
        },
    }
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


def test_live_completed_medium_passes_deadman_and_dispatches_exact_model():
    async def scenario():
        store = ReservationStore()
        await reserve(store)
        calls: list[tuple[str, dict]] = []

        class ServiceTransport:
            async def post_json(self, url, payload):
                calls.append((url, payload))
                return 200, json.dumps(_completed_payload()).encode("utf-8")

        client = DispatchAwareB14Client(
            live_settings(),
            service_transport=ServiceTransport(),
            require_service_binding=True,
        )

        result = await client.complete(MESSAGES)

        assert DEFAULT_CHAT_PROFILE == "medium"
        assert DEFAULT_B14_MODEL_ID == "google/gemini-2.5-flash"
        assert len(calls) == 1
        assert calls[0][1]["model"] == DEFAULT_B14_MODEL_ID
        assert calls[0][1]["business14"]["required_capabilities"] == ["chat"]
        assert calls[0][1]["business14"]["allow_external_fallback"] is False
        assert calls[0][1]["business14"]["max_attempts"] == 1
        assert result["runtime"] == "b14"
        assert result["route"]["model"] == DEFAULT_B14_MODEL_ID
        assert store.refunds == []
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_live_stream_medium_passes_deadman_and_dispatches_exact_model():
    async def scenario():
        store = ReservationStore()
        await reserve(store)
        seen: list[dict] = []
        upstream = ChunkStream([_stream_frame("첫 토큰"), b"data: [DONE]\n\n"])

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=upstream,
            )

        client = DispatchAwareB14Client(
            live_settings(),
            stream_transport=httpx.MockTransport(handler),
            require_service_binding=True,
        )
        events = [event async for event in client.stream_text_auto(MESSAGES)]

        assert len(seen) == 1
        assert seen[0]["model"] == DEFAULT_B14_MODEL_ID
        assert seen[0]["business14"]["required_capabilities"] == ["chat"]
        assert seen[0]["business14"]["allow_external_fallback"] is False
        assert seen[0]["business14"]["max_attempts"] == 1
        assert events[0].delta_content == "첫 토큰"
        assert events[-1].done is True
        assert upstream.closed is True
        assert store.refunds == []
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_non_live_b14_preflight_remains_available_for_infrastructure_regression():
    async def scenario():
        calls = 0

        class ServiceTransport:
            async def post_json(self, url, payload):
                nonlocal calls
                calls += 1
                return 503, b'{"error":{"code":"upstream_error"}}'

        client = DispatchAwareB14Client(
            Settings(runtime_mode="b14", b14_base_url="https://b14.internal", live_enabled=False),
            service_transport=ServiceTransport(),
            require_service_binding=True,
        )
        with pytest.raises(ChatRuntimeError):
            await client.complete(MESSAGES)
        assert calls == 1

    asyncio.run(scenario())


def test_mock_chat_remains_available_without_provider_dispatch():
    async def scenario():
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        client = DispatchAwareB14Client(
            Settings(runtime_mode="mock"),
            transport=httpx.MockTransport(handler),
        )
        result = await client.complete(MESSAGES)
        assert result["runtime"] == "mock"
        assert result["route"]["model"] == DEFAULT_B14_MODEL_ID
        assert result["route"]["model"] == "google/gemini-2.5-flash"
        assert calls == 0

    asyncio.run(scenario())
