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
from app.model_policy import DEFAULT_B14_MODEL_ID, DEFAULT_CHAT_PROFILE, LOW_B14_MODEL_ID
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


def test_live_completed_active_catjam_propagates_provider_error_and_refunds():
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

        with pytest.raises(ChatRuntimeError) as info:
            await client.complete(MESSAGES)

        assert info.value.status_code == 502
        assert info.value.code == "provider_server_error"
        assert DEFAULT_CHAT_PROFILE == "free"
        assert DEFAULT_B14_MODEL_ID == LOW_B14_MODEL_ID == "opencode-go/cat-jam-free"
        assert calls == 1
        assert len(store.refunds) == 0
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_live_stream_active_catjam_propagates_provider_error_and_refunds():
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

        with pytest.raises(ChatRuntimeError) as info:
            async for _ in client.stream_text_auto(MESSAGES):
                pass

        assert info.value.status_code == 502
        assert info.value.code == "upstream_unavailable"
        assert calls == 0
        assert len(store.refunds) == 0
        assert await _refund_active_reservation() is False

    asyncio.run(scenario())


def test_non_live_default_catjam_propagates_transport_failure():
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
        with pytest.raises(ChatRuntimeError) as info:
            await client.complete(MESSAGES)
        assert info.value.code == "provider_server_error"
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
        assert result["route"]["model"] == "opencode-go/cat-jam-free"
        assert calls == 0

    asyncio.run(scenario())

def test_b66_current_product_default_is_catjam_and_propagates_transport_failure():
    """Real B62 HOLD, not the synthetic Plus used in unrelated tests."""
    from app.b66_quote_conversation import B66QuoteConversationInterpreter
    async def scenario():
        calls = []
        class NoProvider:
            async def post_json(self, url, payload):
                calls.append(True)
                raise AssertionError("PROVIDER_MUST_NOT_RUN")
        client = DispatchAwareB14Client(
            live_settings(), service_transport=NoProvider(), require_service_binding=True,
        )
        with pytest.raises(ChatRuntimeError) as error:
            await B66QuoteConversationInterpreter(client).interpret(
                message="거래처 견적 100개",
                skill={"variableSchema":{"recipient":True,"items":True},"fixedDefaults":{}},
            )
        assert error.value.code in ("upstream_unavailable", "upstream_execution_failed", "provider_server_error")
        assert error.value.status_code==502
        assert calls==[True]
    asyncio.run(scenario())
