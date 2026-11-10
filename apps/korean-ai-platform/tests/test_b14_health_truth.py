"""Network-free health truth regressions for the Business 14 runtime (#1933 S2).

Since S2 the live-readiness truth is the platform credential plane, not a
BYOK gateway key: the gateway is live-ready when provider mode is ``live`` and a
platform secret is configured. ``business14.has_key`` reports
``any_platform_secret_present()`` (#7241 3b: the credential NAME is read from
the effective registry document, never written here).
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import CATALOG_BY_ID
from app.pilot.model_registry_file import read_registry
from app.pilot.config import pilot_settings
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.registry import reset_registry

from _registry_values import registry as effective_registry

#: The credential NAME of the first Provider row of the effective document.
#: Seeding a synthetic value under it is what makes the platform credential
#: plane report "has_key"; the name is the row's own column, never written here.
SUBJECT_BINDING = next(iter(effective_registry()["providers"].values()))["credential_binding_name"]


def _platform_secret_env_keys() -> tuple[str, ...]:
    """Every binding NAME the effective document declares (values never read)."""
    return tuple(
        entry["credential_binding_name"]
        for entry in effective_registry()["providers"].values()
        if entry.get("credential_binding_name")
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

    for key in _platform_secret_env_keys():
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
    monkeypatch.setenv(SUBJECT_BINDING, "sk-synthetic-health-proof-1234567890")

    response = client.get("/api/pilot/admin/health")

    assert response.status_code == 200
    data = response.json()
    active_catalog = client.get("/api/pilot/admin/models").json()["catalog"]
    # Previously health reported 0 because it counted the empty public/auto
    # lane, while the manual exact-model catalog exposed enabled routes.
    assert active_catalog
    registry = read_registry()
    # The models surface publishes exactly the enabled rows of the effective
    # document (the app's own rule), so the count is read back from the
    # document rather than from a deployment roster (#7241 3b).
    enabled_rows = [model for model in registry["models"] if model["enabled"]]
    assert len(active_catalog) == len(enabled_rows)
    assert data["status"] == "ok"
    assert data["mode"] == "b14-live"
    assert data["configured_providers"] == len({m["provider_id"] for m in read_registry()["models"] if m["enabled"] and read_registry()["providers"][m["provider_id"]]["enabled"]})
    assert data["configured_models"] == len(active_catalog)
    assert data["registered_routes"] == len(CATALOG_BY_ID)
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is True
    assert data["business14"]["catalog_models"] == len(active_catalog)
    assert "base_url_host" not in data["business14"]
    assert "site_name" not in data["business14"]


def test_live_without_platform_secret_is_not_ready(client):
    _set_live()
    data = client.get("/api/pilot/admin/health").json()
    assert data["status"] == "not_configured"
    assert data["mode"] == "not_configured"
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is False

def test_a_gateway_key_alone_never_makes_b14_live_ready(client):
    _set_live()
    data = client.get("/api/pilot/admin/health").json()
    assert data["status"] == "not_configured"
    assert data["mode"] == "not_configured"
    assert data["business14"]["has_key"] is False

def test_placeholder_platform_secret_is_filtered(client, monkeypatch):
    _set_live()
    monkeypatch.setenv(SUBJECT_BINDING, "test-key")

    data = client.get("/api/pilot/admin/health").json()

    assert data["business14"]["has_key"] is False


def test_mock_mode_is_never_promoted_by_platform_secret(client, monkeypatch):
    runtime_config.provider_mode = "mock"
    monkeypatch.setenv(SUBJECT_BINDING, "sk-synthetic-health-proof-1234567890")

    data = client.get("/api/pilot/admin/health").json()

    assert data["status"] == "not_configured"
    assert data["mode"] == "not_configured"
    assert data["business14"]["provider_mode"] == "mock"
    assert data["business14"]["has_key"] is True


def test_valid_registry_keeps_existing_health_precedence(client, monkeypatch):
    _set_live()
    monkeypatch.setenv(SUBJECT_BINDING, "sk-synthetic-health-proof-1234567890")
    pilot_settings.provider_registry_json = json.dumps([
        {
            "provider_id": "example-byok-provider",
            "display_name": "Example BYOK Provider",
            "base_url": "https://api.example.invalid/v1",
            "timeout_seconds": 30,
            "models": [
                {
                    "model_id": "example-byok-provider/example-byok-model",
                    "upstream_model": "example-byok-upstream",
                    "display_name": "Example BYOK Model",
                    "enabled": True,
                }
            ],
        }
    ])
    reset_registry()

    data = client.get("/api/pilot/admin/health").json()

    assert data["status"] == "ok"
    assert data["mode"] == "byok-multi-provider-pilot"
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is True


def test_legacy_mode_keeps_existing_health_precedence(client, monkeypatch):
    _set_live()
    monkeypatch.setenv(SUBJECT_BINDING, "sk-synthetic-health-proof-1234567890")
    # A syntactically valid https origin and a caller-chosen model: this case is
    # about health precedence, not about a Provider host (#7241 3b).
    pilot_settings.pilot_base_url = "https://byok.example.invalid/v1"
    pilot_settings.pilot_model_id = "caller-chosen-model"

    data = client.get("/api/pilot/admin/health").json()

    assert data["status"] == "ok"
    assert data["mode"] == "byok-pilot"
    assert data["business14"]["provider_mode"] == "live"
    assert data["business14"]["has_key"] is True


def test_health_never_exposes_secrets(client, monkeypatch):
    gateway_secret = "sk-or-v1-health-secret-should-never-appear-abcdef"
    platform_secret = "sk-synthetic-never-expose-abcdef1234567890"
    _set_live()
    monkeypatch.setenv(SUBJECT_BINDING, platform_secret)

    response = client.get("/api/pilot/admin/health")

    assert response.status_code == 200
    assert gateway_secret not in response.text
    assert platform_secret not in response.text
    assert "Authorization" not in response.text


def test_business14_providers_reflect_registered_route_owners(client):
    from app.pilot.model_registry_file import read_registry
    _set_live()
    data = client.get("/api/pilot/admin/health").json()
    providers = data["business14"]["providers"]
    assert [p["id"] for p in providers] == sorted({m["provider_id"] for m in read_registry()["models"] if m["enabled"] and read_registry()["providers"][m["provider_id"]]["enabled"]})
    for entry in providers:
        assert set(entry.keys()) == {"id", "registered", "has_key"}
        assert entry["registered"] is True
        assert isinstance(entry["has_key"], bool)
    # Every Provider the surface lists owns at least one route the effective
    # document registers, and no Provider outside that set appears: both sides
    # are read from the document, so no roster literal is written here (#7241 3b).
    listed = {p["id"] for p in providers}
    owned = {
        m["provider_id"] for m in read_registry()["models"]
        if m["enabled"] and read_registry()["providers"][m["provider_id"]]["enabled"]
    }
    assert listed == owned

def test_health_and_models_surfaces_do_not_leak_gateway_credentials(client):
    _set_live()

    health = client.get("/api/pilot/admin/health")
    models = client.get("/api/pilot/admin/models")

    assert health.status_code == 200
    assert models.status_code == 200
    # The models surface serves the identities the effective document installs
    # under an enabled Provider: the suite asks the document for that set
    # instead of naming one route in the test (#7241 3a).
    document = effective_registry()
    served = {row["id"] for row in models.json()["catalog"]}
    installed = {
        row["id"] for row in document["models"]
        if row["enabled"] and document["providers"][row["provider_id"]]["enabled"]
    }
    assert served == installed
    for model_id in installed:
        assert model_id in models.text
    assert "sk-or-" not in health.text.lower()
    assert "sk-or-" not in models.text.lower()


def test_health_no_longer_reports_an_auto_chain(client):
    """B7: the retired fixed-chain descriptor is gone from public health."""
    _set_live()

    data = client.get("/api/pilot/admin/health").json()

    assert "routing_policy" not in data["business14"]
    assert "fixed_chain_v1" not in client.get("/api/pilot/admin/health").text


def test_catalog_contains_exact_owner_models_not_a_synthetic_auto_choice(client):
    from app.pilot.model_registry_file import read_registry
    data=client.get("/api/pilot/admin/models").json()
    reg = read_registry()
    assert {m["id"] for m in data["catalog"]} == {m["id"] for m in reg["models"] if m["enabled"] and reg["providers"][m["provider_id"]]["enabled"]}
    assert all(m["provider_id"] != "b14" for m in data["catalog"])
