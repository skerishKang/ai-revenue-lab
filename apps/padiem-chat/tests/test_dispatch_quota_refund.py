from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.dispatch_quota import DispatchAwareB14Client, DispatchAwareUsageCounterStore
from app.main import create_app
from app.model_policy import DEFAULT_B14_MODEL_ID
from app.usage_gate import InMemoryUsageCounterStore


QUOTA_SALT = "dispatch-refund-test-salt-not-a-real-secret-0001"
IP = "203.0.113.77"
MESSAGES = [{"role": "user", "content": "안녕하세요"}]


def _settings(**overrides):
    values = {
        "runtime_mode": "b14",
        "b14_base_url": "https://b14.example",
        "quota_salt": QUOTA_SALT,
        "anonymous_burst_limit": 4,
        "anonymous_daily_limit": 20,
        "user_burst_limit": 8,
        "user_daily_limit": 100,
        "global_daily_limit": 1000,
    }
    values.update(overrides)
    return Settings.from_values(**values)


def _success_body():
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": "안녕하세요."}}],
            "business14": {
                "request_id": "b14req_dispatch_refund",
                "route_mode": "manual",
                "selected_model": DEFAULT_B14_MODEL_ID,
                "selected_provider": "Agnes AI",
            },
        }
    ).encode("utf-8")


class RefundableMemoryStore(InMemoryUsageCounterStore):
    def __init__(self):
        super().__init__()
        self.bucket_refund_calls = 0

    async def _refund(
        self,
        *,
        subject_type: str,
        subject_key: str,
        bucket_type: str,
        bucket_start: str,
        updated_at: str,
    ) -> None:
        del updated_at
        self.bucket_refund_calls += 1
        key = (subject_type, subject_key, bucket_type, bucket_start)
        self.counts[key] = max(0, self.counts.get(key, 0) - 1)


class FakeServiceTransport:
    def __init__(self, *, status: int = 200, body: bytes | None = None, error: Exception | None = None):
        self.status = status
        self.body = body if body is not None else _success_body()
        self.error = error
        self.calls = 0

    async def post_json(self, url, payload):
        self.calls += 1
        assert url.endswith("/api/pilot/v1/chat/completions")
        assert payload["model"] == DEFAULT_B14_MODEL_ID
        assert payload["business14"]["required_capabilities"] == ["chat"]
        assert payload["business14"]["allow_external_fallback"] is False
        assert payload["business14"]["max_attempts"] == 1
        if self.error is not None:
            raise self.error
        return self.status, self.body


def _count_values(store: RefundableMemoryStore):
    return sorted(store.counts.values())


@pytest.mark.asyncio
async def test_missing_required_service_binding_refunds_exact_authorization_once():
    settings = _settings()
    store = RefundableMemoryStore()
    wrapped = DispatchAwareUsageCounterStore(store)
    app = create_app(settings, usage_store=wrapped)
    app.state.b14_client = DispatchAwareB14Client(
        settings,
        require_service_binding=True,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": MESSAGES, "mode": "auto"},
            headers={"cf-connecting-ip": IP},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_binding_unavailable"
    assert _count_values(store) == [0, 0, 0]
    assert store.bucket_refund_calls == 3
    assert IP not in str(store.counts)
    assert IP not in response.text


@pytest.mark.asyncio
async def test_successful_dispatch_consumes_exactly_one_quota_operation():
    settings = _settings()
    store = RefundableMemoryStore()
    wrapped = DispatchAwareUsageCounterStore(store)
    service = FakeServiceTransport()
    app = create_app(settings, usage_store=wrapped)
    app.state.b14_client = DispatchAwareB14Client(
        settings,
        service_transport=service,
        require_service_binding=True,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": MESSAGES, "mode": "auto"},
            headers={"cf-connecting-ip": IP},
        )

    assert response.status_code == 200
    assert service.calls == 1
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


@pytest.mark.asyncio
async def test_ambiguous_transport_failure_is_not_refunded():
    settings = _settings()
    store = RefundableMemoryStore()
    wrapped = DispatchAwareUsageCounterStore(store)
    service = FakeServiceTransport(error=RuntimeError("transport state is ambiguous"))
    app = create_app(settings, usage_store=wrapped)
    app.state.b14_client = DispatchAwareB14Client(
        settings,
        service_transport=service,
        require_service_binding=True,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": MESSAGES, "mode": "auto"},
            headers={"cf-connecting-ip": IP},
        )

    assert response.status_code == 502
    assert service.calls == 1
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0
    assert "ambiguous" not in response.text


@pytest.mark.asyncio
async def test_b14_server_failure_is_not_refunded():
    settings = _settings()
    store = RefundableMemoryStore()
    wrapped = DispatchAwareUsageCounterStore(store)
    service = FakeServiceTransport(status=503, body=b'{"error":{"code":"upstream_error"}}')
    app = create_app(settings, usage_store=wrapped)
    app.state.b14_client = DispatchAwareB14Client(
        settings,
        service_transport=service,
        require_service_binding=True,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": MESSAGES, "mode": "auto"},
            headers={"cf-connecting-ip": IP},
        )

    assert response.status_code in {502, 503}
    assert service.calls == 1
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


@pytest.mark.asyncio
async def test_gate_denial_compensation_remains_owned_by_existing_store():
    settings = _settings(anonymous_burst_limit=1)
    store = RefundableMemoryStore()
    wrapped = DispatchAwareUsageCounterStore(store)

    first = await create_app(settings, usage_store=wrapped).state.usage_gate.authorize(raw_ip=IP, user_id=None)
    second = await create_app(settings, usage_store=wrapped).state.usage_gate.authorize(raw_ip=IP, user_id=None)

    assert first.allowed is True
    assert second.allowed is False
    assert second.code == "rate_limited"
    day_counts = [value for key, value in store.counts.items() if key[0] == "anonymous" and key[2] == "day"]
    global_counts = [value for key, value in store.counts.items() if key[0] == "global"]
    assert day_counts == [1]
    assert global_counts == [1]
    assert store.bucket_refund_calls == 0
