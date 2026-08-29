"""Network-free Poolside Provider 01 replacement-candidate regressions."""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import get_catalog_by_id
from app.pilot.platform import call_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.poolside_provider import (
    POOLSIDE_BASE_ORIGIN,
    POOLSIDE_MODEL_ID,
    POOLSIDE_PROVIDER_ID,
    POOLSIDE_XS_MODEL_ID,
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

    medium = get_catalog_by_id(POOLSIDE_MODEL_ID)
    assert medium is not None
    assert medium.upstream_model == "poolside/laguna-s-2.1"
    assert medium.platform_provider_id == POOLSIDE_PROVIDER_ID
    assert medium.provider_type == "platform"
    assert medium.input_price_usd_per_1m is None
    assert medium.output_price_usd_per_1m is None
    assert "free" not in medium.capabilities

    low = get_catalog_by_id(POOLSIDE_XS_MODEL_ID)
    assert low is not None
    assert low.upstream_model == "poolside/laguna-xs-2.1"
    assert low.platform_provider_id == POOLSIDE_PROVIDER_ID
    assert low.provider_type == "platform"
    assert low.input_price_usd_per_1m is None
    assert low.output_price_usd_per_1m is None
    assert "free" not in low.capabilities


def test_poolside_readiness_live_with_poolside_secret(monkeypatch):
    secret = "poolside-health-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("POOLSIDE_API_KEY", secret)
    monkeypatch.delenv("AGNES_API_KEY", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    poolside = _poolside_provider(data)
    assert data["status"] == "ready"
    assert poolside["credential_source"] == "platform_secret"
    assert poolside["credential_ready"] is True
    assert poolside["route_ready"] is True
    assert poolside["models"] == [POOLSIDE_MODEL_ID, POOLSIDE_XS_MODEL_ID]
    assert secret not in response.text
    assert "POOLSIDE_API_KEY" not in response.text
    assert "credential_binding_name" not in response.text


def test_poolside_secret_is_isolated_from_agnes(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv("POOLSIDE_API_KEY", raising=False)
    monkeypatch.setenv("AGNES_API_KEY", "agnes-only-proof-1234567890abcdef")

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    poolside = _poolside_provider(response.json())
    assert poolside["credential_ready"] is False
    assert poolside["route_ready"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_id", "upstream_model"),
    [
        (POOLSIDE_MODEL_ID, "poolside/laguna-s-2.1"),
        (POOLSIDE_XS_MODEL_ID, "poolside/laguna-xs-2.1"),
    ],
)
async def test_poolside_uses_fixed_direct_origin_and_exact_model(
    monkeypatch,
    model_id: str,
    upstream_model: str,
):
    secret = "poolside-direct-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("POOLSIDE_API_KEY", secret)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{POOLSIDE_BASE_ORIGIN}/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {secret}"
        body = __import__("json").loads(request.content)
        assert body["model"] == upstream_model
        return httpx.Response(
            200,
            json={
                "id": "poolside_test",
                "model": upstream_model,
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

    result = await call_platform_chat_completions(
        model_id=model_id,
        upstream_model=upstream_model,
        provider="Poolside",
        platform_provider_id=POOLSIDE_PROVIDER_ID,
        messages=[{"role": "user", "content": "hello"}],
        transport=httpx.MockTransport(handler),
    )

    assert result["_live"] is True
    assert result["model"] == upstream_model
    assert secret not in repr(result)
