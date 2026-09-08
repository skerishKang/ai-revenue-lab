"""Network-free Agnes AI provider regressions for #2133.

Agnes is onboarded as an explicit manual-pin candidate only: fixed origin,
exact upstream id, owner-approved binding name, zero upstream calls when the
secret is absent, and never a member of the public/b14-auto surface.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.agnes_provider import (
    AGNES_ALLOWED_HOST,
    AGNES_BASE_ORIGIN,
    AGNES_CREDENTIAL_BINDING,
    AGNES_MODEL_ID,
    AGNES_PROVIDER_ID,
    AGNES_UPSTREAM_MODEL,
)
from app.pilot.catalog import CATALOG_BY_ID, CATALOG_MODELS, get_catalog_by_id
from app.pilot.errors import PilotNotConfigured
from app.pilot.platform import call_platform_chat_completions, stream_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider


def _agnes_provider(data: dict) -> dict:
    matches = [
        provider
        for provider in data["providers"]
        if provider["provider_id"] == AGNES_PROVIDER_ID
    ]
    assert len(matches) == 1
    return matches[0]


def test_agnes_registration_is_exact_and_not_permanently_free():
    spec = get_platform_provider(AGNES_PROVIDER_ID)
    assert spec is not None
    assert spec.base_origin == AGNES_BASE_ORIGIN
    assert spec.allowed_hosts == (AGNES_ALLOWED_HOST,)
    assert spec.credential_source.value == "platform_secret"
    assert spec.credential_binding_name == AGNES_CREDENTIAL_BINDING == "PADIEM_AGNES_API_KEY"

    model = get_catalog_by_id(AGNES_MODEL_ID)
    assert model is not None
    assert model.upstream_model == AGNES_UPSTREAM_MODEL
    assert model.platform_provider_id == AGNES_PROVIDER_ID
    assert model.provider_type == "platform"
    assert model.input_price_usd_per_1m is None
    assert model.output_price_usd_per_1m is None
    assert "free" not in model.capabilities


def test_agnes_is_manual_pin_only_never_public_or_auto():
    public_ids = {m.model_id for m in CATALOG_MODELS}
    assert AGNES_MODEL_ID not in public_ids
    assert AGNES_MODEL_ID in CATALOG_BY_ID

    with TestClient(create_app()) as client:
        data = client.get("/api/pilot/models").json()
    catalog_ids = [m["id"] for m in data["catalog"]]
    route_ids = [r["id"] for r in data["registered_routes"]]
    agnes_route = next(r for r in data["registered_routes"] if r["id"] == AGNES_MODEL_ID)
    assert AGNES_MODEL_ID in route_ids
    assert AGNES_MODEL_ID not in catalog_ids
    assert agnes_route["explicit_only"] is True
    assert agnes_route["public"] is False
    assert agnes_route["auto_eligible"] is False
    assert agnes_route["free"] is False


def test_agnes_readiness_reported_by_generic_plane_without_leakage(monkeypatch):
    secret = "agnes-health-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(AGNES_CREDENTIAL_BINDING, secret)

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    agnes = _agnes_provider(data)
    assert agnes["credential_source"] == "platform_secret"
    assert agnes["credential_ready"] is True
    assert agnes["route_ready"] is True
    assert agnes["models"] == [AGNES_MODEL_ID]
    assert secret not in response.text
    assert AGNES_CREDENTIAL_BINDING not in response.text


@pytest.mark.asyncio
async def test_agnes_missing_secret_fails_closed_with_zero_upstream_calls(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(AGNES_CREDENTIAL_BINDING, raising=False)
    called = {"hit": False}

    def handler(request: httpx.Request) -> httpx.Response:
        called["hit"] = True
        return httpx.Response(200, json={})

    with pytest.raises(PilotNotConfigured):
        await call_platform_chat_completions(
            model_id=AGNES_MODEL_ID,
            upstream_model=AGNES_UPSTREAM_MODEL,
            provider="Agnes AI",
            platform_provider_id=AGNES_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )

    assert called["hit"] is False


def test_agnes_credential_is_isolated_from_other_providers(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(AGNES_CREDENTIAL_BINDING, raising=False)
    monkeypatch.setenv("PADIEM_SENSENOVA_API_KEY", "sensenova-only-1234567890abcdef0123")

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    agnes = _agnes_provider(response.json())
    assert agnes["credential_ready"] is False
    assert agnes["route_ready"] is False


@pytest.mark.asyncio
async def test_agnes_uses_fixed_origin_exact_model_and_bearer(monkeypatch):
    secret = "agnes-direct-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(AGNES_CREDENTIAL_BINDING, secret)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{AGNES_BASE_ORIGIN}/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {secret}"
        body = json.loads(request.content)
        assert body["model"] == AGNES_UPSTREAM_MODEL
        return httpx.Response(
            200,
            json={
                "id": "agnes_test",
                "model": AGNES_UPSTREAM_MODEL,
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
        model_id=AGNES_MODEL_ID,
        upstream_model=AGNES_UPSTREAM_MODEL,
        provider="Agnes AI",
        platform_provider_id=AGNES_PROVIDER_ID,
        messages=[{"role": "user", "content": "hello"}],
        transport=httpx.MockTransport(handler),
    )

    assert result["_live"] is True
    assert result["model"] == AGNES_UPSTREAM_MODEL
    assert secret not in repr(result)


@pytest.mark.asyncio
async def test_agnes_streaming_contract_via_generic_adapter(monkeypatch):
    secret = "agnes-stream-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(AGNES_CREDENTIAL_BINDING, secret)

    payload = (
        b'data: {"id":"a1","model":"agnes-2.5-flash","choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["model"] == AGNES_UPSTREAM_MODEL
        return httpx.Response(200, content=payload)

    events = [
        e
        async for e in stream_platform_chat_completions(
            model_id=AGNES_MODEL_ID,
            upstream_model=AGNES_UPSTREAM_MODEL,
            provider="Agnes AI",
            platform_provider_id=AGNES_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    ]
    assert events[-1].done is True
    assert all(secret not in repr(e) for e in events)
