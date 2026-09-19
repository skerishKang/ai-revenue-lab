"""Network-free B14 onboarding regressions for the four confirmed candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import CATALOG_BY_ID, CATALOG_MODELS, get_catalog_by_id
from app.pilot.errors import PilotNotConfigured
from app.pilot.platform import call_platform_chat_completions, stream_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider


@dataclass(frozen=True)
class Candidate:
    provider_id: str
    binding: str
    origin: str
    host: str
    model_id: str
    upstream_model: str
    provider: str


CANDIDATES = (
    Candidate(
        "infron",
        "PADIEM_INFRON_API_KEY",
        "https://llm.onerouter.pro/v1",
        "llm.onerouter.pro",
        "infron/motif/motif-3",
        "motif/motif-3",
        "Infron",
    ),
    Candidate(
        "inception",
        "PADIEM_INCEPTION_MERCURY_API_KEY",
        "https://api.inceptionlabs.ai/v1",
        "api.inceptionlabs.ai",
        "inception/mercury-2.5",
        "mercury-2.5",
        "Inception",
    ),
    Candidate(
        "atria",
        "PADIEM_ATRIA_API_KEY",
        "https://api.atria-asi.ai/v1",
        "api.atria-asi.ai",
        "atria/Atria-Dawn-Preview",
        "Atria-Dawn-Preview",
        "Atria",
    ),
    Candidate(
        "experiential",
        "PADIEM_EXLAB_API_KEY",
        "https://api.experientiallabs.ai/v1",
        "api.experientiallabs.ai",
        "experiential/gpt-5.6-luna",
        "gpt-5.6-luna",
        "Experiential Labs",
    ),
)


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
def test_candidate_registration_identity_and_manual_pin_only(candidate: Candidate):
    spec = get_platform_provider(candidate.provider_id)
    assert spec is not None
    assert spec.provider_id == candidate.provider_id
    assert spec.base_origin == candidate.origin
    assert spec.allowed_hosts == (candidate.host,)
    assert spec.credential_source.value == "platform_secret"
    assert spec.credential_binding_name == candidate.binding

    model = get_catalog_by_id(candidate.model_id)
    assert model is not None
    assert model.model_id == candidate.model_id
    assert model.upstream_model == candidate.upstream_model
    assert model.platform_provider_id == candidate.provider_id
    assert model.provider_type == "platform"
    assert model.input_price_usd_per_1m is None
    assert model.output_price_usd_per_1m is None
    assert "free" not in model.capabilities
    assert candidate.model_id not in {item.model_id for item in CATALOG_MODELS}
    assert candidate.model_id in CATALOG_BY_ID

    with TestClient(create_app()) as client:
        route = next(
            item
            for item in client.get("/api/pilot/models").json()["registered_routes"]
            if item["id"] == candidate.model_id
        )
    assert route["provider_id"] == candidate.provider_id
    assert route["upstream_model"] == candidate.upstream_model
    assert route["explicit_only"] is True
    assert route["public"] is False
    assert route["auto_eligible"] is False
    assert route["free"] is False


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
def test_candidate_readiness_is_metadata_only_and_does_not_leak(candidate, monkeypatch):
    secret = f"{candidate.provider_id}-readiness-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(candidate.binding, secret)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    entry = next(
        item for item in response.json()["providers"] if item["provider_id"] == candidate.provider_id
    )
    assert entry["credential_source"] == "platform_secret"
    assert entry["credential_ready"] is True
    assert entry["route_ready"] is True
    assert entry["models"] == [candidate.model_id]
    assert candidate.binding not in response.text
    assert secret not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_missing_secret_fails_closed_with_zero_upstream_calls(candidate, monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(candidate.binding, raising=False)
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with pytest.raises(PilotNotConfigured):
        await call_platform_chat_completions(
            model_id=candidate.model_id,
            upstream_model=candidate.upstream_model,
            provider=candidate.provider,
            platform_provider_id=candidate.provider_id,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_mock_mode_makes_zero_upstream_calls(candidate, monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        raise AssertionError("mock mode must not call upstream")

    result = await call_platform_chat_completions(
        model_id=candidate.model_id,
        upstream_model=candidate.upstream_model,
        provider=candidate.provider,
        platform_provider_id=candidate.provider_id,
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert result["_mock"] is True
    assert result["model"] == candidate.upstream_model
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_secret_isolated_from_other_provider(candidate, monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(candidate.binding, raising=False)
    monkeypatch.setenv("PADIEM_B_AI_API_KEY", "other-provider-only-1234567890abcdef")
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with pytest.raises(PilotNotConfigured):
        await call_platform_chat_completions(
            model_id=candidate.model_id,
            upstream_model=candidate.upstream_model,
            provider=candidate.provider,
            platform_provider_id=candidate.provider_id,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_direct_request_uses_fixed_origin_bearer_and_actual_model(
    candidate, monkeypatch
):
    secret = f"{candidate.provider_id}-direct-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(candidate.binding, secret)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{candidate.origin}/chat/completions"
        assert request.url.host == candidate.host
        assert request.headers["Authorization"] == f"Bearer {secret}"
        assert json.loads(request.content)["model"] == candidate.upstream_model
        return httpx.Response(
            200,
            json={
                "id": "candidate_test",
                "model": candidate.upstream_model,
                "choices": [{"message": {"content": "ok"}}],
            },
        )

    result = await call_platform_chat_completions(
        model_id=candidate.model_id,
        upstream_model=candidate.upstream_model,
        provider=candidate.provider,
        platform_provider_id=candidate.provider_id,
        messages=[{"role": "user", "content": "hello"}],
        transport=httpx.MockTransport(handler),
    )
    assert result["_live"] is True
    assert result["model"] == candidate.upstream_model
    assert result["_actual_response_model"] == candidate.upstream_model
    assert secret not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_streaming_uses_exact_model_and_actual_model_evidence(candidate, monkeypatch):
    secret = f"{candidate.provider_id}-stream-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(candidate.binding, secret)
    payload = (
        f'data: {{"id":"q1","model":"{candidate.upstream_model}",'
        '"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{candidate.origin}/chat/completions"
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["model"] == candidate.upstream_model
        assert request.headers["Authorization"] == f"Bearer {secret}"
        return httpx.Response(200, content=payload)

    events = [
        event
        async for event in stream_platform_chat_completions(
            model_id=candidate.model_id,
            upstream_model=candidate.upstream_model,
            provider=candidate.provider,
            platform_provider_id=candidate.provider_id,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    ]
    assert events[0].model == candidate.upstream_model
    assert events[-1].done is True
    assert all(secret not in repr(event) for event in events)
