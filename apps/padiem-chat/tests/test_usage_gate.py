from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.usage_gate import InMemoryUsageCounterStore, UsageGate


FIXED_NOW = datetime(2026, 8, 26, 1, 2, 3, tzinfo=timezone.utc)
QUOTA_SALT = "b62-unit-test-quota-salt-not-a-real-secret-0001"
USER_MESSAGES = [{"role": "user", "content": "안녕하세요"}]


def _live_settings(**overrides):
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


def _success_payload():
    return {
        "choices": [{"message": {"role": "assistant", "content": "안녕하세요."}}],
        "business14": {
            "request_id": "b14req_usage_gate",
            "route_mode": "auto",
            "selected_model": "openrouter/free",
            "selected_provider": "OpenRouter",
        },
    }


@pytest.mark.asyncio
async def test_mock_runtime_consumes_zero_quota_even_when_store_is_bound():
    store = InMemoryUsageCounterStore()
    gate = UsageGate(Settings(runtime_mode="mock"), store, clock=lambda: FIXED_NOW)

    for _ in range(20):
        decision = await gate.authorize(raw_ip=None, user_id=None)
        assert decision.allowed is True

    assert store.consume_calls == 0
    assert store.counts == {}


@pytest.mark.asyncio
async def test_live_runtime_fails_closed_without_store_or_salt():
    missing_store = UsageGate(_live_settings(), None, clock=lambda: FIXED_NOW)
    decision = await missing_store.authorize(raw_ip="203.0.113.10", user_id=None)
    assert decision.allowed is False
    assert decision.code == "live_abuse_gate_unavailable"
    assert decision.status_code == 503

    no_salt = UsageGate(
        Settings.from_values(runtime_mode="b14", b14_base_url="https://b14.example"),
        InMemoryUsageCounterStore(),
        clock=lambda: FIXED_NOW,
    )
    decision = await no_salt.authorize(raw_ip="203.0.113.10", user_id=None)
    assert decision.allowed is False
    assert decision.code == "live_abuse_gate_unavailable"


@pytest.mark.asyncio
async def test_anonymous_subject_is_hashed_and_raw_ip_is_never_a_store_key():
    store = InMemoryUsageCounterStore()
    gate = UsageGate(_live_settings(), store, clock=lambda: FIXED_NOW)
    raw_ip = "203.0.113.10"

    decision = await gate.authorize(raw_ip=raw_ip, user_id=None)

    assert decision.allowed is True
    joined_keys = " ".join(str(key) for key in store.counts)
    assert raw_ip not in joined_keys
    anonymous_keys = [key[1] for key in store.counts if key[0] == "anonymous"]
    assert anonymous_keys
    assert all(value.startswith("anon_") and len(value) == 69 for value in anonymous_keys)


@pytest.mark.asyncio
async def test_missing_or_invalid_anonymous_ip_fails_closed_before_store_use():
    for raw_ip in (None, "", "not-an-ip"):
        store = InMemoryUsageCounterStore()
        gate = UsageGate(_live_settings(), store, clock=lambda: FIXED_NOW)
        decision = await gate.authorize(raw_ip=raw_ip, user_id=None)
        assert decision.allowed is False
        assert decision.code == "live_identity_unavailable"
        assert decision.status_code == 503
        assert store.consume_calls == 0


@pytest.mark.asyncio
async def test_anonymous_burst_limit_denies_fifth_request_and_refunds_other_buckets():
    store = InMemoryUsageCounterStore()
    gate = UsageGate(_live_settings(anonymous_burst_limit=4), store, clock=lambda: FIXED_NOW)

    results = [await gate.authorize(raw_ip="203.0.113.10", user_id=None) for _ in range(5)]

    assert all(item.allowed for item in results[:4])
    assert results[4].allowed is False
    assert results[4].code == "rate_limited"
    assert results[4].status_code == 429
    assert results[4].retry_after_seconds == 60
    daily_counts = [value for key, value in store.counts.items() if key[0] == "anonymous" and key[2] == "day"]
    assert daily_counts == [4]
    global_counts = [value for key, value in store.counts.items() if key[0] == "global"]
    assert global_counts == [4]


@pytest.mark.asyncio
async def test_signed_in_user_has_distinct_limits_and_does_not_require_ip():
    store = InMemoryUsageCounterStore()
    gate = UsageGate(_live_settings(user_burst_limit=2, user_daily_limit=3), store, clock=lambda: FIXED_NOW)

    first = await gate.authorize(raw_ip=None, user_id="usr_0123456789abcdef0123456789abcdef")
    second = await gate.authorize(raw_ip=None, user_id="usr_0123456789abcdef0123456789abcdef")
    third = await gate.authorize(raw_ip=None, user_id="usr_0123456789abcdef0123456789abcdef")

    assert first.allowed and second.allowed
    assert third.allowed is False
    assert third.code == "rate_limited"
    assert any(key[0] == "user" and key[1].startswith("usr_") for key in store.counts)
    assert not any(key[0] == "anonymous" for key in store.counts)


@pytest.mark.asyncio
async def test_daily_and_global_limits_are_finite_and_fail_closed():
    daily_store = InMemoryUsageCounterStore()
    daily_gate = UsageGate(
        _live_settings(anonymous_burst_limit=10, anonymous_daily_limit=2),
        daily_store,
        clock=lambda: FIXED_NOW,
    )
    assert (await daily_gate.authorize(raw_ip="203.0.113.20", user_id=None)).allowed
    assert (await daily_gate.authorize(raw_ip="203.0.113.20", user_id=None)).allowed
    denied_daily = await daily_gate.authorize(raw_ip="203.0.113.20", user_id=None)
    assert denied_daily.allowed is False
    assert denied_daily.code == "quota_exhausted"

    global_store = InMemoryUsageCounterStore()
    global_gate = UsageGate(
        _live_settings(anonymous_burst_limit=10, anonymous_daily_limit=10, global_daily_limit=1),
        global_store,
        clock=lambda: FIXED_NOW,
    )
    assert (await global_gate.authorize(raw_ip="203.0.113.21", user_id=None)).allowed
    denied_global = await global_gate.authorize(raw_ip="203.0.113.22", user_id=None)
    assert denied_global.allowed is False
    assert denied_global.code == "service_limit_reached"


@pytest.mark.asyncio
async def test_api_denial_happens_before_b14_and_allowed_request_calls_once():
    provider_calls = 0

    async def handler(request):
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json=_success_payload())

    store = InMemoryUsageCounterStore()
    app = create_app(
        _live_settings(anonymous_burst_limit=1),
        transport=httpx.MockTransport(handler),
        usage_store=store,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        allowed = await client.post(
            "/api/chat",
            json={"messages": USER_MESSAGES, "mode": "auto"},
            headers={"cf-connecting-ip": "203.0.113.30"},
        )
        denied = await client.post(
            "/api/chat",
            json={"messages": USER_MESSAGES, "mode": "auto"},
            headers={"cf-connecting-ip": "203.0.113.30"},
        )

    assert allowed.status_code == 200
    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "rate_limited"
    assert denied.headers["retry-after"] == "60"
    assert provider_calls == 1


@pytest.mark.asyncio
async def test_api_missing_identity_is_rejected_before_b14_call():
    provider_calls = 0

    async def handler(request):
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json=_success_payload())

    app = create_app(
        _live_settings(),
        transport=httpx.MockTransport(handler),
        usage_store=InMemoryUsageCounterStore(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat", json={"messages": USER_MESSAGES, "mode": "auto"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "live_identity_unavailable"
    assert provider_calls == 0


@pytest.mark.asyncio
async def test_health_reports_truthful_abuse_gate_readiness_without_secret_values():
    live_app = create_app(_live_settings(), usage_store=InMemoryUsageCounterStore())
    mock_app = create_app(Settings(runtime_mode="mock"))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=live_app), base_url="http://test") as client:
        live = (await client.get("/health")).json()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app), base_url="http://test") as client:
        mock = (await client.get("/health")).json()

    assert live["quota_store_bound"] is True
    assert live["live_abuse_gate_ready"] is True
    assert live["live_enabled"] is True
    assert mock["quota_store_bound"] is False
    assert mock["live_abuse_gate_ready"] is False
    assert mock["live_enabled"] is False
    assert QUOTA_SALT not in str(live)


def test_quota_migration_contains_accounting_metadata_only():
    root = Path(__file__).resolve().parents[1]
    sql = (root / "migrations/005_live_usage_quota.sql").read_text(encoding="utf-8").lower()
    assert "live_usage_buckets" in sql
    assert "subject_type" in sql
    assert "subject_key" in sql
    assert "bucket_type" in sql
    assert "request_count" in sql
    for forbidden_column in (
        "prompt_text",
        "assistant_text",
        "raw_ip",
        "oauth_token",
        "provider_key",
        "attachment_bytes",
        "upstream_response",
    ):
        assert forbidden_column not in sql
