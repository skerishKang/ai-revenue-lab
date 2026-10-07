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
from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    DEFAULT_CHAT_PROFILE,
    LOW_B14_MODEL_ID,
    request_tier_context,
)
from app.usage_gate import UsageDecision
from padiem_control_plane.product_tier_routes import PLUS_HOLD_MODEL_ID


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


def test_live_completed_held_tier_refunds_before_service_binding_dispatch():
    """#3554 leaves Pro/Max held, so the refund-before-dispatch guarantee is
    proven on a tier that still cannot run; Plus text now dispatches."""

    async def scenario():
        store = ReservationStore()
        await reserve(store)
        calls = 0

        class ServiceTransport:
            async def post_json(self, url, payload):
                nonlocal calls
                calls += 1
                return 503, b'{"error":{"code":"upstream_error"}}'

        client = DispatchAwareB14Client(
            live_settings(),
            service_transport=ServiceTransport(),
            require_service_binding=True,
        )

        with request_tier_context("pro"), pytest.raises(ChatRuntimeError) as info:
            await client.complete(MESSAGES)

        assert info.value.status_code == 503
        assert info.value.code == "model_profile_unassigned"
        assert DEFAULT_CHAT_PROFILE == "low"
        assert DEFAULT_B14_MODEL_ID == LOW_B14_MODEL_ID != PLUS_HOLD_MODEL_ID
        assert calls == 0
        assert len(store.refunds) == 3
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_live_stream_held_tier_refunds_before_stream_transport_dispatch():
    async def scenario():
        store = ReservationStore()
        await reserve(store)
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500, content=b"upstream failure")

        client = DispatchAwareB14Client(
            live_settings(),
            stream_transport=httpx.MockTransport(handler),
            require_service_binding=True,
        )

        with request_tier_context("pro"), pytest.raises(ChatRuntimeError) as info:
            async for _ in client.stream_text_auto(MESSAGES):
                pass

        assert info.value.status_code == 503
        assert info.value.code == "model_profile_unassigned"
        assert calls == 0
        assert len(store.refunds) == 3
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_non_live_b14_default_held_tier_still_fails_before_transport():
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
        with request_tier_context("pro"), pytest.raises(ChatRuntimeError) as info:
            await client.complete(MESSAGES)
        assert info.value.code == "tier_unavailable"
        assert calls == 0

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
        # Mock stays mock: the Plus lane identity is the selected text route, and
        # mock mode must still never reach the provider.
        assert result["route"]["model"] == DEFAULT_B14_MODEL_ID == LOW_B14_MODEL_ID
        assert calls == 0

    asyncio.run(scenario())
