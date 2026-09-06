"""#2003 — SenseNova direct route: catalog entry, adapter shape, retryable
busy-429 normalization, and fail-closed key handling.

The owner-provisioned key lives ONLY in the Worker env binding
``PADIEM_SENSENOVA_API_KEY``; these tests use fake values and never assert on
real credentials.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform as plat
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import (
    PilotNotConfigured,
    UpstreamBusyRateLimited,
    UpstreamRateLimited,
)
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.sensenova_provider import (
    SENSENOVA_ALLOWED_HOST,
    SENSENOVA_BASE_ORIGIN,
    SENSENOVA_CREDENTIAL_BINDING,
    SENSENOVA_MODEL_ID,
    SENSENOVA_PROVIDER_ID,
    SENSENOVA_UPSTREAM_MODEL,
    is_transient_busy_429,
)

SENSENOVA_SECRET = "fake-sensenova-key-for-tests-0123456789"


@pytest.fixture()
def client():
    return TestClient(create_app())


def _completion_json(model: str = SENSENOVA_UPSTREAM_MODEL) -> dict:
    return {
        "id": "cmpl-sn-1",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


# ---------------------------------------------------------------------------
# Catalog entry
# ---------------------------------------------------------------------------

def test_catalog_entry_registered_with_evidenced_shape():
    model = get_catalog_by_id(SENSENOVA_MODEL_ID)
    assert model is not None
    assert model.upstream_model == SENSENOVA_UPSTREAM_MODEL
    assert model.provider == "SenseNova"
    assert model.platform_provider_id == SENSENOVA_PROVIDER_ID
    assert model.capabilities == frozenset({"chat", "coding"})
    # Owner-plan cost: no fabricated price.
    assert model.input_price_usd_per_1m is None
    assert model.output_price_usd_per_1m is None
    assert not model.price_is_known
    # Manual-pin only: never in the legacy auto-routing surface.
    from app.pilot.catalog import CATALOG_MODELS

    assert SENSENOVA_MODEL_ID not in {m.model_id for m in CATALOG_MODELS}


def test_provider_spec_pinned_origin_and_binding():
    spec = get_platform_provider(SENSENOVA_PROVIDER_ID)
    assert spec is not None
    assert spec.base_origin == SENSENOVA_BASE_ORIGIN
    assert spec.allowed_hosts == (SENSENOVA_ALLOWED_HOST,)
    assert spec.credential_binding_name == SENSENOVA_CREDENTIAL_BINDING
    assert spec.enabled


def test_kilo_secondary_route_preserved():
    # #2003 non-goal: the Kilo entry must remain registered.
    from app.pilot.kilo_provider import KILO_MODEL_ID

    assert get_catalog_by_id(KILO_MODEL_ID) is not None
    assert get_platform_provider("kilo") is not None


# ---------------------------------------------------------------------------
# Adapter request shape (endpoint / Bearer / model)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adapter_request_shape(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, SENSENOVA_SECRET)

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion_json())

    result = await plat.call_platform_chat_completions(
        model_id=SENSENOVA_MODEL_ID,
        upstream_model=SENSENOVA_UPSTREAM_MODEL,
        provider="SenseNova",
        platform_provider_id=SENSENOVA_PROVIDER_ID,
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )

    assert captured["url"] == f"{SENSENOVA_BASE_ORIGIN}/chat/completions"
    assert captured["authorization"] == f"Bearer {SENSENOVA_SECRET}"
    assert captured["body"]["model"] == SENSENOVA_UPSTREAM_MODEL
    assert result["choices"][0]["message"]["content"] == "ok"


# ---------------------------------------------------------------------------
# Fail-closed without key (never anonymous)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_key_fails_closed_never_anonymous(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(SENSENOVA_CREDENTIAL_BINDING, raising=False)

    called = []

    async def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json=_completion_json())

    with pytest.raises(PilotNotConfigured):
        await plat.call_platform_chat_completions(
            model_id=SENSENOVA_MODEL_ID,
            upstream_model=SENSENOVA_UPSTREAM_MODEL,
            provider="SenseNova",
            platform_provider_id=SENSENOVA_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    assert called == []  # zero upstream calls without the key


def test_readiness_reports_not_ready_without_key(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(SENSENOVA_CREDENTIAL_BINDING, raising=False)
    monkeypatch.delenv("KILO_API_KEY", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    sensenova = next(
        p for p in response.json()["providers"] if p["provider_id"] == SENSENOVA_PROVIDER_ID
    )
    assert sensenova["enabled"] is True
    assert sensenova["credential_ready"] is False
    assert sensenova["route_ready"] is False
    assert SENSENOVA_MODEL_ID in sensenova["models"]
    # no secret metadata leaks
    assert SENSENOVA_CREDENTIAL_BINDING not in response.text


def test_readiness_ready_with_key(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, SENSENOVA_SECRET)

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    sensenova = next(
        p for p in response.json()["providers"] if p["provider_id"] == SENSENOVA_PROVIDER_ID
    )
    assert sensenova["credential_ready"] is True
    assert sensenova["route_ready"] is True
    assert SENSENOVA_SECRET not in response.text


# ---------------------------------------------------------------------------
# 429 busy -> retryable normalization
# ---------------------------------------------------------------------------

def test_transient_busy_marker_detection():
    assert is_transient_busy_429(
        '{"error":{"type":"rate_limit_error","message":"Server is busy"}}'
    )
    assert is_transient_busy_429("server is BUSY")
    assert not is_transient_busy_429('{"error":{"message":"quota exceeded"}}')


def test_busy_429_maps_to_retryable_busy_class():
    with pytest.raises(UpstreamBusyRateLimited) as exc_info:
        plat._raise_upstream_error(
            429,
            "sensenova",
            '{"error":{"type":"rate_limit_error","message":"Server is busy"}}',
        )
    assert exc_info.value.code == "upstream_rate_limited_busy"
    assert exc_info.value.status_code == 429
    assert exc_info.value.retryable is True


def test_non_busy_429_stays_hourly_class():
    with pytest.raises(UpstreamRateLimited):
        plat._raise_upstream_error(429, "sensenova", '{"error":{"message":"quota"}}')


def test_busy_class_is_same_route_retryable():
    from app.pilot.gateway import _SAME_ROUTE_RETRYABLE_CODES

    assert "upstream_rate_limited_busy" in _SAME_ROUTE_RETRYABLE_CODES


@pytest.mark.asyncio
async def test_busy_429_absorbed_by_gateway_retry(client, monkeypatch):
    """End-to-end through the manual-pin route: first attempt answers the
    measured busy 429, the #1988 same-route retry absorbs it."""
    from app.pilot import gateway as gw

    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, SENSENOVA_SECRET)

    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                429,
                json={"error": {"type": "rate_limit_error", "message": "Server is busy"}},
            )
        return httpx.Response(200, json=_completion_json())

    original = plat.call_platform_chat_completions

    async def fake(**kwargs):
        return await original(
            **{**kwargs, "transport": httpx.MockTransport(handler)}
        )

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)

    # instant backoff for test speed
    real_sleep = gw.asyncio.sleep

    async def fast_sleep(seconds, *a, **k):
        return await real_sleep(0)

    monkeypatch.setattr(gw.asyncio, "sleep", fast_sleep)

    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={"model": SENSENOVA_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert len(calls) == 2
    biz14 = response.json()["business14"]
    assert biz14["selected_model"] == SENSENOVA_MODEL_ID
    assert biz14["attempt_count"] == 2
    assert "upstream_retry:1" in biz14["reason_codes"]
    assert biz14["attempt_evidence"][0]["error_code"] == "upstream_rate_limited_busy"
    assert biz14["attempt_evidence"][1]["outcome"] == "success"
