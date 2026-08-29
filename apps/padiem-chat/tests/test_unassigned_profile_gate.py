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
    DEFAULT_CHAT_PROFILE,
    MEDIUM_B14_MODEL_ID,
    model_profile_is_assigned,
)
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
        subject_key="user-assigned-medium",
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


def test_owner_assigned_default_profile_is_recognized():
    assert DEFAULT_CHAT_PROFILE == "medium"
    assert MEDIUM_B14_MODEL_ID == "poolside/laguna-s-2.1"
    assert model_profile_is_assigned(MEDIUM_B14_MODEL_ID) is True
    assert model_profile_is_assigned("padiem-profile/medium-unassigned") is False


def test_live_completed_chat_reaches_service_binding_for_assigned_medium_profile():
    async def scenario():
        store = ReservationStore()
        await reserve(store)
        calls = 0

        class ServiceTransport:
            async def post_json(self, url, payload):
                nonlocal calls
                calls += 1
                assert payload["model"] == MEDIUM_B14_MODEL_ID
                return 503, b'{"error":{"code":"upstream_error"}}'

        client = DispatchAwareB14Client(
            live_settings(),
            service_transport=ServiceTransport(),
            require_service_binding=True,
        )

        with pytest.raises(ChatRuntimeError):
            await client.complete(MESSAGES)

        assert calls == 1
        assert len(store.refunds) == 0
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_live_stream_reaches_transport_for_assigned_medium_profile():
    async def scenario():
        store = ReservationStore()
        await reserve(store)
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert MEDIUM_B14_MODEL_ID.encode() in request.content
            return httpx.Response(503, json={"error": {"code": "upstream_error"}})

        client = DispatchAwareB14Client(
            live_settings(),
            stream_transport=httpx.MockTransport(handler),
            require_service_binding=True,
        )

        with pytest.raises(ChatRuntimeError):
            async for _ in client.stream_text_auto(MESSAGES):
                pass

        assert calls == 1
        assert len(store.refunds) == 0
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
        assert result["route"]["model"] == MEDIUM_B14_MODEL_ID
        assert calls == 0

    asyncio.run(scenario())
