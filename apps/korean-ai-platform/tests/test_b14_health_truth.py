"""Network-free health truth regressions for the Business 14 runtime (#1933 S1)."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import CATALOG_BY_ID, list_catalog_summaries
from app.pilot.config import pilot_settings
from app.pilot.openrouter_config import openrouter_config
from app.pilot.registry import reset_registry


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    saved_openrouter = {
        "api_key": openrouter_config.api_key,
        "provider_mode": openrouter_config.provider_mode,
    }
    saved_pilot = {
        "pilot_base_url": pilot_settings.pilot_base_url,
        "pilot_model_id": pilot_settings.pilot_model_id,
        "pilot_provider_id": pilot_settings.pilot_provider_id,
        "pilot_upstream_model": pilot_settings.pilot_upstream_model,
        "provider_registry_json": pilot_settings.provider_registry_json,
    }

    openrouter_config.api_key = ""
    openrouter_config.provider_mode = "mock"
    pilot_settings.pilot_base_url = ""
    pilot_settings.pilot_model_id = ""
    pilot_settings.pilot_upstream_model = ""
    pilot_settings.provider_registry_json = ""
    reset_registry()

    yield

    openrouter_config.api_key = saved_openrouter["api_key"]
    openrouter_config.provider_mode = saved_openrouter["provider_mode"]
    pilot_settings.pilot_base_url = saved_pilot["pilot_base_url"]
    pilot_settings.pilot_model_id = saved_pilot["pilot_model_id"]
    pilot_settings.pilot_provider_id = saved_pilot["pilot_provider_id"]
    pilot_settings.pilot_upstream_model = saved_pilot["pilot_upstream_model"]
    pilot_settings.provider_registry_json = saved_pilot["provider_registry_json"]
    reset_registry()


def _set_openrouter_live(key: str = "sk-or-v1-health-proof-1234567890abcdef") -> None:
    openrouter_config.provider_mode = "live"
    openrouter_config.api_key = key


def test_live_with_valid_key_is_top_level_healthy(client):
    _set_openrouter_live()

    response = client.get("/api/pilot/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "b14-live"
    assert data["configured_providers"] == 3
    assert data["configured_models"] == len(list_catalog_summaries())
    assert data["registered_routes"] == len(CATALOG_BY_ID)
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is True
    assert data["business14"]["catalog_models"] == len(list_catalog_summaries())
    assert "base_url_host" not in data["business14"]
    assert "site_name" not in data["business14"]


def test_openrouter_live_missing_key_is_not_execution_ready(client):
    openrouter_config.provider_mode = "live"
    openrouter_config.api_key = ""

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "not_configured"
    assert data["mode"] == "not_configured"
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is False


def test_openrouter_live_placeholder_key_is_not_execution_ready(client):
    openrouter_config.provider_mode = "live"
    openrouter_config.api_key = "test-key"

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "not_configured"
    assert data["mode"] == "not_configured"
    assert data["business14"]["has_key"] is False


def test_openrouter_mock_is_not_promoted_by_key_presence(client):
    openrouter_config.provider_mode = "mock"
    openrouter_config.api_key = "sk-or-v1-health-proof-1234567890abcdef"

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "not_configured"
    assert data["mode"] == "not_configured"
    assert data["business14"]["provider_mode"] == "mock"
    assert data["business14"]["has_key"] is True


def test_valid_registry_keeps_existing_health_precedence(client):
    _set_openrouter_live()
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


def test_legacy_mode_keeps_existing_health_precedence(client):
    _set_openrouter_live()
    pilot_settings.pilot_base_url = "https://api.example.com"
    pilot_settings.pilot_model_id = "legacy-model"

    data = client.get("/api/pilot/health").json()

    assert data["status"] == "ok"
    assert data["mode"] == "byok-pilot"
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is True


def test_health_never_exposes_openrouter_key(client):
    secret = "sk-or-v1-health-secret-should-never-appear-abcdef"
    _set_openrouter_live(secret)

    response = client.get("/api/pilot/health")

    assert response.status_code == 200
    assert secret not in response.text
    assert "Authorization" not in response.text


def test_business14_providers_reflect_registered_route_owners(client):
    _set_openrouter_live()

    data = client.get("/api/pilot/health").json()

    providers = data["business14"]["providers"]
    assert [p["id"] for p in providers] == ["kilo", "poolside", "sensenova"]
    for entry in providers:
        assert set(entry.keys()) == {"id", "registered", "has_key"}
        assert entry["registered"] is True
        assert isinstance(entry["has_key"], bool)
    kilo = next(p for p in providers if p["id"] == "kilo")
    assert kilo["has_key"] is False


def test_health_and_models_surfaces_have_zero_openrouter_mentions(client):
    _set_openrouter_live()

    health = client.get("/api/pilot/health")
    models = client.get("/api/pilot/models")

    assert health.status_code == 200
    assert models.status_code == 200
    assert "openrouter" not in health.text.lower()
    assert "openrouter" not in models.text.lower()
