"""Network-free B.AI provider regressions for #2133.

B.AI is onboarded as an explicit manual-pin candidate with the ONLY
officially-proven hosted model id (qwen3.8-flash). GLM-5.3-Flash stays
unregistered because its exact API model string has not been published.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.bai_provider import (
    BAI_ALLOWED_HOST,
    BAI_BASE_ORIGIN,
    BAI_CREDENTIAL_BINDING,
    BAI_PROVIDER_ID,
    BAI_QWEN_MODEL_ID,
    BAI_QWEN_UPSTREAM_MODEL,
)
from app.pilot.catalog import CATALOG_BY_ID, CATALOG_MODELS, get_catalog_by_id
from app.pilot.errors import PilotNotConfigured
from app.pilot.platform import call_platform_chat_completions, stream_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider


def _bai_provider(data: dict) -> dict:
    matches = [
        provider
        for provider in data["providers"]
        if provider["provider_id"] == BAI_PROVIDER_ID
    ]
    assert len(matches) == 1
    return matches[0]


def test_bai_registration_is_exact_and_not_permanently_free():
    spec = get_platform_provider(BAI_PROVIDER_ID)
    assert spec is not None
    assert spec.base_origin == BAI_BASE_ORIGIN
    assert spec.allowed_hosts == (BAI_ALLOWED_HOST,)
    assert spec.credential_source.value == "platform_secret"
    assert spec.credential_binding_name == BAI_CREDENTIAL_BINDING == "PADIEM_B_AI_API_KEY"

    model = get_catalog_by_id(BAI_QWEN_MODEL_ID)
    assert model is not None
    assert model.upstream_model == BAI_QWEN_UPSTREAM_MODEL
    assert model.platform_provider_id == BAI_PROVIDER_ID
    assert model.provider_type == "platform"
    assert model.input_price_usd_per_1m is None
    assert model.output_price_usd_per_1m is None
    assert "free" not in model.capabilities


def test_glm_5_3_flash_route_stays_unregistered_without_authority():
    """#2133: never derive an exact upstream id from a display name."""

    assert "b-ai/glm-5.3-flash" not in CATALOG_BY_ID
    assert "b-ai/GLM-5.3-Flash" not in CATALOG_BY_ID
    assert get_catalog_by_id("b-ai/glm-5.3-flash") is None


def test_bai_is_manual_pin_only_never_public_or_auto():
    public_ids = {m.model_id for m in CATALOG_MODELS}
    assert BAI_QWEN_MODEL_ID not in public_ids
    assert BAI_QWEN_MODEL_ID in CATALOG_BY_ID

    with TestClient(create_app()) as client:
        data = client.get("/api/pilot/models").json()
    catalog_ids = [m["id"] for m in data["catalog"]]
    route = next(r for r in data["registered_routes"] if r["id"] == BAI_QWEN_MODEL_ID)
    assert BAI_QWEN_MODEL_ID not in catalog_ids
    assert route["explicit_only"] is True
    assert route["public"] is False
    assert route["auto_eligible"] is False
    assert route["free"] is False


def test_bai_readiness_reported_by_generic_plane_without_leakage(monkeypatch):
    secret = "sk-bai-health-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BAI_CREDENTIAL_BINDING, secret)

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    bai = _bai_provider(response.json())
    assert bai["credential_source"] == "platform_secret"
    assert bai["credential_ready"] is True
    assert bai["route_ready"] is True
    assert bai["models"] == [BAI_QWEN_MODEL_ID]
    assert secret not in response.text
    assert BAI_CREDENTIAL_BINDING not in response.text


@pytest.mark.asyncio
async def test_bai_missing_secret_fails_closed_with_zero_upstream_calls(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(BAI_CREDENTIAL_BINDING, raising=False)
    called = {"hit": False}

    def handler(request: httpx.Request) -> httpx.Response:
        called["hit"] = True
        return httpx.Response(200, json={})

    with pytest.raises(PilotNotConfigured):
        await call_platform_chat_completions(
            model_id=BAI_QWEN_MODEL_ID,
            upstream_model=BAI_QWEN_UPSTREAM_MODEL,
            provider="B.AI / Alibaba Qwen",
            platform_provider_id=BAI_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )

    assert called["hit"] is False


def test_bai_credential_is_isolated_from_other_providers(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(BAI_CREDENTIAL_BINDING, raising=False)
    monkeypatch.setenv("PADIEM_AGNES_API_KEY", "agnes-only-1234567890abcdef012345")

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    bai = _bai_provider(response.json())
    assert bai["credential_ready"] is False
    assert bai["route_ready"] is False


@pytest.mark.asyncio
async def test_bai_uses_fixed_origin_exact_model_and_bearer(monkeypatch):
    secret = "sk-bai-direct-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BAI_CREDENTIAL_BINDING, secret)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{BAI_BASE_ORIGIN}/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {secret}"
        body = json.loads(request.content)
        assert body["model"] == BAI_QWEN_UPSTREAM_MODEL
        return httpx.Response(
            200,
            json={
                "id": "bai_test",
                "model": BAI_QWEN_UPSTREAM_MODEL,
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
        model_id=BAI_QWEN_MODEL_ID,
        upstream_model=BAI_QWEN_UPSTREAM_MODEL,
        provider="B.AI / Alibaba Qwen",
        platform_provider_id=BAI_PROVIDER_ID,
        messages=[{"role": "user", "content": "hello"}],
        transport=httpx.MockTransport(handler),
    )

    assert result["_live"] is True
    assert result["model"] == BAI_QWEN_UPSTREAM_MODEL
    assert secret not in repr(result)


@pytest.mark.asyncio
async def test_bai_streaming_contract_via_generic_adapter(monkeypatch):
    secret = "sk-bai-stream-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BAI_CREDENTIAL_BINDING, secret)

    payload = (
        b'data: {"id":"q1","model":"qwen3.8-flash","choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["model"] == BAI_QWEN_UPSTREAM_MODEL
        return httpx.Response(200, content=payload)

    events = [
        e
        async for e in stream_platform_chat_completions(
            model_id=BAI_QWEN_MODEL_ID,
            upstream_model=BAI_QWEN_UPSTREAM_MODEL,
            provider="B.AI / Alibaba Qwen",
            platform_provider_id=BAI_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    ]
    assert events[-1].done is True
    assert all(secret not in repr(e) for e in events)
