"""Network-free health truth regressions for the Business 14 runtime (#1933 S2).

Since S2 the live-readiness truth is the platform credential plane, not the
OpenRouter key: the gateway is live-ready when provider mode is ``live`` and
either a platform secret is configured or the keyless Kilo route is registered.
``business14.has_key`` reports ``any_platform_secret_present()``.
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import CATALOG_BY_ID, list_catalog_summaries
from app.pilot.config import pilot_settings
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.registry import reset_registry

PLATFORM_SECRET_ENV_KEYS = (
    "KILO_API_KEY",
    "AGNES_API_KEY",
    "PADIEM_POOLSIDE_API_KEY",
    "PADIEM_SENSENOVA_API_KEY",
    "PADIEM_AGNES_API_KEY",
    "PADIEM_B_AI_API_KEY",
)


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _reset_runtime_state(monkeypatch):
    saved_runtime = {
        "provider_mode": runtime_config.provider_mode,
    }
    saved_pilot = {
        "pilot_base_url": pilot_settings.pilot_base_url,
        "pilot_model_id": pilot_settings.pilot_model_id,
        "pilot_provider_id": pilot_settings.pilot_provider_id,
        "pilot_upstream_model": pilot_settings.pilot_upstream_model,
        "provider_registry_json": pilot_settings.provider_registry_json,
    }

    for key in PLATFORM_SECRET_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    runtime_config.provider_mode = "mock"
    pilot_settings.pilot_base_url = ""
    pilot_settings.pilot_model_id = ""
    pilot_settings.pilot_upstream_model = ""
    pilot_settings.provider_registry_json = ""
    reset_registry()

    yield

    runtime_config.provider_mode = saved_runtime["provider_mode"]
    pilot_settings.pilot_base_url = saved_pilot["pilot_base_url"]
    pilot_settings.pilot_model_id = saved_pilot["pilot_model_id"]
    pilot_settings.pilot_provider_id = saved_pilot["pilot_provider_id"]
    pilot_settings.pilot_upstream_model = saved_pilot["pilot_upstream_model"]
    pilot_settings.provider_registry_json = saved_pilot["provider_registry_json"]
    reset_registry()


def _set_live() -> None:
    runtime_config.provider_mode = "live"


def test_live_with_platform_secret_is_top_level_healthy(client, monkeypatch):
    _set_live()
    monkeypatch.setenv("PADIEM_SENSENOVA_API_KEY", "sk-sensenova-health-proof-1234567890")

    response = client.get("/api/pilot/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "b14-live"
    assert data["configured_providers"] == 5
    assert data["configured_models"] == len(list_catalog_summaries())
    assert data["registered_routes"] == len(CATALOG_BY_ID)
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is True
    assert data["business14"]["catalog_models"] == len(list_catalog_summaries())
    assert "base_url_host" not in data["business14"]
    assert "site_name" not in data["business14"]


def test_live_without_platform_secret_is_still_ready_via_keyless_kilo(client):
    """Live readiness no longer depends on the OpenRouter key (#1933 S2)."""
    _set_live()

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "ok"
    assert data["mode"] == "b14-live"
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is False


def test_openrouter_key_alone_is_not_has_key_truth(client):
    """The OpenRouter key is no longer the live/has_key truth source."""
    _set_live()

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "ok"
    assert data["mode"] == "b14-live"
    assert data["business14"]["has_key"] is False


def test_placeholder_platform_secret_is_filtered(client, monkeypatch):
    _set_live()
    monkeypatch.setenv("PADIEM_POOLSIDE_API_KEY", "test-key")

    data = client.get("/api/pilot/health").json()

    assert data["business14"]["has_key"] is False


def test_mock_mode_is_never_promoted_by_platform_secret(client, monkeypatch):
    runtime_config.provider_mode = "mock"
    monkeypatch.setenv("PADIEM_SENSENOVA_API_KEY", "sk-sensenova-health-proof-1234567890")

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "not_configured"
    assert data["mode"] == "not_configured"
    assert data["business14"]["provider_mode"] == "mock"
    assert data["business14"]["has_key"] is True


def test_valid_registry_keeps_existing_health_precedence(client, monkeypatch):
    _set_live()
    monkeypatch.setenv("PADIEM_SENSENOVA_API_KEY", "sk-sensenova-health-proof-1234567890")
    pilot_settings.provider_registry_json = json.dumps([
        {
            "provider_id": "provider-a",
            "display_name": "Provider A",
            "base_url": "https://api.provider-a.example",
            "timeout_seconds": 30,
            "models": [
                {
                    "model_id": "model-a-v1",
                    "upstream_model": "upstream-a",
                    "display_name": "Model A",
                    "enabled": True,
                }
            ],
        }
    ])
    reset_registry()

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "ok"
    assert data["mode"] == "byok-multi-provider-pilot"
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is True


def test_legacy_mode_keeps_existing_health_precedence(client, monkeypatch):
    _set_live()
    monkeypatch.setenv("PADIEM_SENSENOVA_API_KEY", "sk-sensenova-health-proof-1234567890")
    pilot_settings.pilot_base_url = "https://api.example.com"
    pilot_settings.pilot_model_id = "legacy-model"

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "ok"
    assert data["mode"] == "byok-pilot"
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is True


def test_health_never_exposes_secrets(client, monkeypatch):
    openrouter_secret = "sk-or-v1-health-secret-should-never-appear-abcdef"
    platform_secret = "sk-sensenova-never-expose-abcdef1234567890"
    _set_live()
    monkeypatch.setenv("PADIEM_SENSENOVA_API_KEY", platform_secret)

    response = client.get("/api/pilot/health")

    assert response.status_code == 200
    assert openrouter_secret not in response.text
    assert platform_secret not in response.text
    assert "Authorization" not in response.text


def test_business14_providers_reflect_registered_route_owners(client):
    _set_live()

    data = client.get("/api/pilot/health").json()

    providers = data["business14"]["providers"]
    assert [p["id"] for p in providers] == [
        "agnes-ai",
        "b-ai",
        "kilo",
        "poolside",
        "sensenova",
    ]
    for entry in providers:
        assert set(entry.keys()) == {"id", "registered", "has_key"}
        assert entry["registered"] is True
        assert isinstance(entry["has_key"], bool)
    kilo = next(p for p in providers if p["id"] == "kilo")
    assert kilo["has_key"] is False


def test_health_and_models_surfaces_have_zero_openrouter_mentions(client):
    _set_live()

    health = client.get("/api/pilot/health")
    models = client.get("/api/pilot/models")

    assert health.status_code == 200
    assert models.status_code == 200
    assert "openrouter" not in health.text.lower()
    assert "openrouter" not in models.text.lower()


def test_health_reports_fixed_chain_routing_policy(client):
    """D14 (#2044): health pins the owner-designated b14/auto chain."""
    _set_live()

    data = client.get("/api/pilot/health").json()

    policy = data["business14"]["routing_policy"]
    assert policy["id"] == "fixed_chain_v1"
    assert policy["chain"] == [
        "sensenova/sensenova-6.8-flash-lite",
        "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        "poolside/laguna-s-2.1",
    ]


def test_catalog_auto_lane_is_b14_router_not_a_provider(client):
    catalog = client.get("/api/pilot/models").json()["catalog"]
    auto = next(entry for entry in catalog if entry["id"] == "b14/auto")

    assert auto["provider_id"] == "b14"
    assert auto["provider_name"] == "B14 Router"
