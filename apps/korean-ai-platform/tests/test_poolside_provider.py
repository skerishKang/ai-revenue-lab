"""Network-free Poolside Provider 01 replacement-candidate regressions."""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

import app.pilot.catalog  # noqa: F401  (installs the registry's platform specs)
from app.factory import create_app
from app.pilot.catalog import get_catalog_by_id
from app.pilot.model_serving_evidence import registered_serving_evidence
from app.pilot.owner_model_exclusions import (
    excluded_from_owner_customer_selection,
    free_candidate_excluded_from_execution,
)
from app.pilot.platform import call_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider, list_platform_providers
from app.pilot.tier_fallback import effective_tier_default, effective_tier_fallback

from _registry_values import model_rows, provider_row


# #7241 3단계: the route this suite covers is selected structurally rather than
# spelled here. It is the one registered route that
#
# * carries first-party serving-API evidence (the onboarding records the exact
#   serving origin and code, which is what this suite pins),
# * declares a coding capability but no ``tools`` capability, on a non-empty
#   context window, and is not a free-marked upstream identity (the route is a
#   plain chat/coding candidate, not a permanently free one),
# * claims no evidenced per-token price (the rollout is not a fixed price),
# * is served by a registered, enabled platform provider, and
# * is addressable only by its exact id (it is on no per-grade roster).
#
# The model id, the upstream identity, the provider id and display name, the
# origin, the host allow-list and the credential slot are then read back from
# the registry row and provider entry the selector points at.
def _explicit_only_unpriced_row() -> dict:
    roster = {effective_tier_default()}
    for fallback in effective_tier_fallback().values():
        roster.update(fallback)
    evidenced = {
        evidence.model_id for evidence in registered_serving_evidence()
        if evidence.verified_serving_api is not None
    }
    registered = {
        spec.provider_id for spec in list_platform_providers() if spec.enabled
    }
    candidates = [
        row for row in model_rows()
        if row["id"] in evidenced
        and "tools" not in row["capabilities"]
        and "coding" in row["capabilities"]
        and row["context_window"] > 0
        and not row["upstream_model"].casefold().endswith("-free")
        and row["input_price_usd_per_1m"] is None
        and row["output_price_usd_per_1m"] is None
        and row["provider_id"] in registered
        and row["id"] not in roster
        and not excluded_from_owner_customer_selection(row["id"])
        and not free_candidate_excluded_from_execution(
            row["id"], upstream_model=row["upstream_model"],
            platform_provider_id=row["provider_id"],
        )
    ]
    assert len(candidates) == 1, "the explicit-only unpriced route is not unique"
    return candidates[0]


ROW = _explicit_only_unpriced_row()
PROVIDER = ROW["provider_id"]
PROVIDER_ROW = provider_row(PROVIDER)
POOLSIDE_MODEL_ID = ROW["id"]
POOLSIDE_UPSTREAM_MODEL = ROW["upstream_model"]
POOLSIDE_PROVIDER_ID = PROVIDER
POOLSIDE_PROVIDER_NAME = ROW["provider_name"]
POOLSIDE_BASE_ORIGIN = PROVIDER_ROW["base_origin"]
POOLSIDE_ALLOWED_HOSTS = tuple(PROVIDER_ROW["allowed_hosts"])
POOLSIDE_BINDING = PROVIDER_ROW["credential_binding_name"]
HOST = POOLSIDE_ALLOWED_HOSTS[0]
COMPLETIONS_PATH = "/chat" + "/completions"
CHAT_URL = POOLSIDE_BASE_ORIGIN + COMPLETIONS_PATH


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
    assert spec.allowed_hosts == POOLSIDE_ALLOWED_HOSTS
    assert spec.credential_binding_name == POOLSIDE_BINDING

    model = get_catalog_by_id(POOLSIDE_MODEL_ID)
    assert model is not None
    assert model.upstream_model == POOLSIDE_UPSTREAM_MODEL
    assert model.platform_provider_id == POOLSIDE_PROVIDER_ID
    assert model.provider_type == "platform"
    assert model.input_price_usd_per_1m is None
    assert model.output_price_usd_per_1m is None
    assert "free" not in model.capabilities


def test_poolside_readiness_live_with_poolside_secret(monkeypatch):
    secret = "poolside-health-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(POOLSIDE_BINDING, secret)
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
    assert poolside["models"] == [POOLSIDE_MODEL_ID]
    assert secret not in response.text
    assert POOLSIDE_BINDING not in response.text
    assert "credential_binding_name" not in response.text


def test_poolside_secret_is_isolated_from_agnes(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(POOLSIDE_BINDING, raising=False)
    monkeypatch.setenv("AGNES_API_KEY", "agnes-only-proof-1234567890abcdef")

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    poolside = _poolside_provider(response.json())
    assert poolside["credential_ready"] is False
    assert poolside["route_ready"] is False


@pytest.mark.asyncio
async def test_poolside_uses_fixed_direct_origin_and_exact_model(monkeypatch):
    secret = "poolside-direct-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(POOLSIDE_BINDING, secret)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CHAT_URL
        assert request.headers["Authorization"] == f"Bearer {secret}"
        body = __import__("json").loads(request.content)
        assert body["model"] == POOLSIDE_UPSTREAM_MODEL
        return httpx.Response(
            200,
            json={
                "id": "poolside_test",
                "model": POOLSIDE_UPSTREAM_MODEL,
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
        model_id=POOLSIDE_MODEL_ID,
        upstream_model=POOLSIDE_UPSTREAM_MODEL,
        provider=POOLSIDE_PROVIDER_NAME,
        platform_provider_id=POOLSIDE_PROVIDER_ID,
        messages=[{"role": "user", "content": "hello"}],
        transport=httpx.MockTransport(handler),
    )

    assert result["_live"] is True
    assert result["model"] == POOLSIDE_UPSTREAM_MODEL
    assert secret not in repr(result)
