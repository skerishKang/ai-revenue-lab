"""Network-free provider readiness regressions for Business 14."""

from __future__ import annotations

from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.sensenova_provider import (
    SENSENOVA_CREDENTIAL_BINDING,
    SENSENOVA_MODEL_ID,
    SENSENOVA_PROVIDER_ID,
)


def _provider(data: dict, provider_id: str) -> dict:
    matches = [
        provider
        for provider in data["providers"]
        if provider["provider_id"] == provider_id
    ]
    assert len(matches) == 1
    return matches[0]


def _sensenova_provider(data: dict) -> dict:
    return _provider(data, SENSENOVA_PROVIDER_ID)


def test_provider_readiness_mock_without_sensenova_secret_is_not_ready(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    monkeypatch.delenv(SENSENOVA_CREDENTIAL_BINDING, raising=False)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    sensenova = _sensenova_provider(data)
    kilo = _provider(data, "kilo")
    assert data["status"] == "not_ready"
    assert data["provider_mode"] == "mock"
    assert sensenova["credential_source"] == "platform_secret"
    assert sensenova["credential_ready"] is False
    assert sensenova["route_ready"] is False
    assert kilo["credential_source"] == "none"
    assert kilo["credential_ready"] is True
    assert kilo["route_ready"] is False


def test_provider_readiness_live_with_sensenova_secret_is_ready(monkeypatch):
    secret = "snsv_live_abcdefghijklmnopqrstuvwxyz1234"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, secret)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    sensenova = _sensenova_provider(data)
    kilo = _provider(data, "kilo")
    assert data["status"] == "ready"
    assert data["provider_mode"] == "live"
    assert data["ready_provider_count"] >= 2
    assert sensenova["credential_ready"] is True
    assert sensenova["route_ready"] is True
    assert sensenova["models"] == [SENSENOVA_MODEL_ID]
    assert kilo["credential_ready"] is True
    assert kilo["route_ready"] is True
    assert secret not in response.text
    assert SENSENOVA_CREDENTIAL_BINDING not in response.text
    assert "credential_binding_name" not in response.text


def test_provider_readiness_live_with_placeholder_sensenova_still_has_keyless_kilo(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, "test-key")

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    sensenova = _sensenova_provider(data)
    kilo = _provider(data, "kilo")
    assert data["status"] == "ready"
    assert data["ready_provider_count"] >= 1
    assert sensenova["credential_ready"] is False
    assert sensenova["route_ready"] is False
    assert kilo["credential_source"] == "none"
    assert kilo["credential_ready"] is True
    assert kilo["route_ready"] is True


def test_provider_readiness_makes_no_upstream_provider_call(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, "snsv_live_abcdefghijklmnopqrstuvwxyz1234")

    async def _unexpected_call(**kwargs):
        raise AssertionError("provider readiness must not make an upstream call")

    monkeypatch.setattr(
        "app.pilot.platform.call_platform_chat_completions",
        _unexpected_call,
    )

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_agnes_legacy_binding_name_never_satisfies_reonboarded_provider(monkeypatch):
    # #2133 re-onboards Agnes under PADIEM_AGNES_API_KEY. The #1933 S2-b
    # retirement intent survives as an isolation contract: the legacy intake
    # name AGNES_API_KEY must not satisfy readiness for anything.
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("AGNES_API_KEY", "legacy-name-1234567890abcdef")
    monkeypatch.delenv("PADIEM_AGNES_API_KEY", raising=False)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    providers = {p["provider_id"]: p for p in response.json()["providers"]}
    assert "agnes-ai" in providers
    assert "kilo" in providers
    assert providers["agnes-ai"]["credential_ready"] is False
    assert providers["agnes-ai"]["route_ready"] is False
