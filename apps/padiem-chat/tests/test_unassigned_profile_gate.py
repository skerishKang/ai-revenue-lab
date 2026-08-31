from __future__ import annotations

import asyncio

import httpx
import pytest

from app.b14_client import ChatRuntimeError
from app.config import Settings
from app.dispatch_quota import (
    DispatchAwareB14Client,
    DispatchAwareUsageCounterStore,
    _refund_active_reservation,
)
from app.model_policy import AUTO_B14_MODEL_ID, DEFAULT_CHAT_PROFILE
from app.usage_gate import UsageDecision


MESSAGES = [{"role": "user", "content": "안녕하세요"}]


class ReservationStore:
    def __init__(self):
        self.refunds: list[dict] = []

    async def consume(self, **kwargs):
        return UsageDecision(allowed=True)

    async def _refund(self, **kwargs):
        self.refunds.append(kwargs)


async def reserve(store: ReservationStore) -> None:
    await DispatchAwareUsageCounterStore(store).consume(
        subject_type="user",
        subject_key="user-auto",
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


def test_live_completed_auto_reaches_service_binding_without_concrete_model_assignment():
    async def scenario():
        store = ReservationStore()
        await reserve(store)
        calls = 0

        class ServiceTransport:
            async def post_json(self, url, payload):
                nonlocal calls
                calls += 1
                assert payload["model"] == AUTO_B14_MODEL_ID
                return 503, b'{"error":{"code":"upstream_error"}}'

        client = DispatchAwareB14Client(
            live_settings(),
            service_transport=ServiceTransport(),
            require_service_binding=True,
        )

        with pytest.raises(ChatRuntimeError):
            await client.complete(MESSAGES)

        assert DEFAULT_CHAT_PROFILE == "medium"
        assert AUTO_B14_MODEL_ID == "b14/auto"
        assert calls == 1
        assert store.refunds == []
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_live_stream_auto_reaches_auto_stream_transport_without_pre_dispatch_refund():
    async def scenario():
        store = ReservationStore()
        await reserve(store)
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert request.url.path.endswith("/auto-stream-preview")
            return httpx.Response(500, content=b"upstream failure")

        client = DispatchAwareB14Client(
            live_settings(),
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


def test_non_live_b14_preflight_remains_available_for_infrastructure_regression():
    async def scenario():
        calls = 0

        class ServiceTransport:
            async def post_json(self, url, payload):
                nonlocal calls
                calls += 1
                assert payload["model"] == AUTO_B14_MODEL_ID
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
        assert result["route"]["model"] == AUTO_B14_MODEL_ID
        assert calls == 0

    asyncio.run(scenario())
