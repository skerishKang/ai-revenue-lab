"""Network-free Poolside Provider 01 replacement-candidate regressions."""

from __future__ import annotations

import asyncio

import httpx
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import get_catalog_by_id
from app.pilot.platform import call_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.poolside_provider import (
    POOLSIDE_BASE_ORIGIN,
    POOLSIDE_MODEL_ID,
    POOLSIDE_PROVIDER_ID,
)


def _poolside_provider(data: dict) -> dict:
    matches = [
        provider
        for provider in data["providers"]
        if provider["provider_id"] == POOLSIDE_PROVIDER_ID
    ]
    assert len(matches) == 1
    return matches[0]


def test_poolside_registration_is_exact_and_not_permanently_free():
    spec = get_platform_provider(POOLSIDE_PROVIDER_ID)
    assert spec is not None
    assert spec.base_origin == POOLSIDE_BASE_ORIGIN
    assert spec.allowed_hosts == ("inference.poolside.ai",)
    assert spec.credential_binding_name == "POOLSIDE_API_KEY"

    model = get_catalog_by_id(POOLSIDE_MODEL_ID)
    assert model is not None
    assert model.upstream_model == "poolside/laguna-s-2.1"
    assert model.platform_provider_id == POOLSIDE_PROVIDER_ID
    assert model.provider_type == "platform"
    assert model.input_price_usd_per_1m is None
    assert model.output_price_usd_per_1m is None
    assert "free" not in model.capabilities


def test_poolside_readiness_live_with_poolside_secret(monkeypatch):
    secret = "poolside-health-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("POOLSIDE_API_KEY", secret)
    monkeypatch.delenv("AGNES_API_KEY", raising=False)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    poolside = _poolside_provider(data)
    assert data["status"] == "ready"
    assert poolside["credential_source"] == "platform_secret"
    assert poolside["credential_ready"] is True
    assert poolside["route_ready"] is True
    assert poolside["models"] == [POOLSIDE_MODEL_ID]
    assert secret not in response.text
    assert "POOLSIDE_API_KEY" not in response.text
    assert "credential_binding_name" not in response.text


def test_poolside_secret_is_isolated_from_agnes(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv("POOLSIDE_API_KEY", raising=False)
    monkeypatch.setenv("AGNES_API_KEY", "agnes-only-proof-1234567890abcdef")

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    poolside = _poolside_provider(response.json())
    assert poolside["credential_ready"] is False
    assert poolside["route_ready"] is False


def test_poolside_uses_fixed_direct_origin_and_exact_model(monkeypatch):
    secret = "poolside-direct-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("POOLSIDE_API_KEY", secret)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{POOLSIDE_BASE_ORIGIN}/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {secret}"
        body = __import__("json").loads(request.content)
        assert body["model"] == "poolside/laguna-s-2.1"
        return httpx.Response(
            200,
            json={
                "id": "poolside_test",
                "model": "poolside/laguna-s-2.1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    result = asyncio.run(
        call_platform_chat_completions(
            model_id=POOLSIDE_MODEL_ID,
            upstream_model="poolside/laguna-s-2.1",
            provider="Poolside",
            platform_provider_id=POOLSIDE_PROVIDER_ID,
            messages=[{"role": "user", "content": "hello"}],
            transport=httpx.MockTransport(handler),
        )
    )

    assert result["_live"] is True
    assert result["model"] == "poolside/laguna-s-2.1"
    assert secret not in repr(result)
