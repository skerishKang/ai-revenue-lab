"""Network-free provider readiness regressions for Business 14."""

from __future__ import annotations

from starlette.testclient import TestClient

from app.factory import create_app


def _agnes_provider(data: dict) -> dict:
    matches = [
        provider
        for provider in data["providers"]
        if provider["provider_id"] == "agnes-ai"
    ]
    assert len(matches) == 1
    return matches[0]


def test_provider_readiness_mock_without_agnes_secret_is_not_ready(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    monkeypatch.delenv("AGNES_API_KEY", raising=False)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    agnes = _agnes_provider(data)
    assert data["status"] == "not_ready"
    assert data["provider_mode"] == "mock"
    assert agnes["credential_source"] == "platform_secret"
    assert agnes["credential_ready"] is False
    assert agnes["route_ready"] is False


def test_provider_readiness_live_with_agnes_secret_is_ready(monkeypatch):
    secret = "agnes-health-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("AGNES_API_KEY", secret)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    agnes = _agnes_provider(data)
    assert data["status"] == "ready"
    assert data["provider_mode"] == "live"
    assert data["ready_provider_count"] >= 1
    assert agnes["credential_ready"] is True
    assert agnes["route_ready"] is True
    assert agnes["models"] == ["agnes-ai/agnes-2.5-flash"]
    assert secret not in response.text
    assert "AGNES_API_KEY" not in response.text
    assert "credential_binding_name" not in response.text


def test_provider_readiness_live_with_placeholder_secret_fails_closed(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("AGNES_API_KEY", "test-key")

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    agnes = _agnes_provider(data)
    assert data["status"] == "not_ready"
    assert agnes["credential_ready"] is False
    assert agnes["route_ready"] is False


def test_provider_readiness_makes_no_upstream_provider_call(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("AGNES_API_KEY", "agnes-health-proof-no-network-abcdef")

    async def _unexpected_call(**kwargs):
        raise AssertionError("provider readiness must not make an upstream call")

    monkeypatch.setattr(
        "app.pilot.platform.call_platform_chat_completions",
        _unexpected_call,
    )

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
