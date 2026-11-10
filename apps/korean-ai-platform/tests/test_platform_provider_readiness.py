"""Network-free provider readiness regressions for Business 14.

#7241 3단계: which Providers the readiness surface reports is the effective
registry document's answer, not a list written here. The subject Provider is a
row of that document and its credential NAME is the row's own column; a lane
the document no longer disables (or a document that registers no keyless
Provider) skips that one case instead of failing on an old deployment decision.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import CATALOG_BY_ID
from app.pilot.platform_secrets import _PLATFORM_PROVIDERS

from _registry_values import provider_of, provider_row

#: The subject row: the credential plane this suite proves is a platform secret
#: the app resolves by NAME. Its identity and binding come from the document.
SUBJECT_ROW = next(
    (model for model in CATALOG_BY_ID.values() if model.platform_provider_id),
    None,
)
assert SUBJECT_ROW is not None, "the effective registry installs no platform row"

SUBJECT_PROVIDER_ID = SUBJECT_ROW.platform_provider_id
SUBJECT_BINDING = provider_row(SUBJECT_PROVIDER_ID)["credential_binding_name"]


def _provider(data: dict, provider_id: str) -> dict:
    matches = [
        provider
        for provider in data["providers"]
        if provider["provider_id"] == provider_id
    ]
    assert len(matches) == 1
    return matches[0]


def _subject_provider(data: dict) -> dict:
    return _provider(data, SUBJECT_PROVIDER_ID)


def _require_subject_disabled() -> None:
    spec = _PLATFORM_PROVIDERS.get(SUBJECT_PROVIDER_ID)
    if spec is None or spec.enabled:
        pytest.skip("the effective document enables this Provider (no disabled-route pin)")


def test_provider_readiness_mock_without_subject_secret_is_not_ready(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    monkeypatch.delenv(SUBJECT_BINDING, raising=False)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    subject = _subject_provider(data)
    assert data["status"] == "not_ready"
    assert data["provider_mode"] == "mock"
    assert subject["credential_source"] == "platform_secret"
    assert subject["credential_ready"] is False
    assert subject["route_ready"] is False


def test_provider_readiness_live_with_subject_secret_is_disabled(monkeypatch):
    # The disabled-route pin only holds on a host whose document disables it.
    _require_subject_disabled()
    secret = "snsv_live_abcdefghijklmnopqrstuvwxyz1234"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SUBJECT_BINDING, secret)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    subject = _subject_provider(data)
    assert data["status"] == "not_ready"
    assert data["provider_mode"] == "live"
    assert data["ready_provider_count"] == 0
    assert subject["enabled"] is False
    assert subject["credential_ready"] is True
    assert subject["route_ready"] is False
    assert subject["models"] == []
    assert secret not in response.text
    assert SUBJECT_BINDING not in response.text
    assert "credential_binding_name" not in response.text


def test_provider_readiness_live_with_placeholder_secret_still_reports_it_without_secret(monkeypatch):
    # A template value never satisfies a platform-secret Provider, and it does
    # not promote *another* Provider either: the surface keeps reporting each
    # row's own truth, and a neighbouring row that has no enabled model stays
    # route-unready while this one's binding holds a placeholder.
    subject_models = sorted(
        model.model_id
        for model in CATALOG_BY_ID.values()
        if model.platform_provider_id == SUBJECT_PROVIDER_ID
    )
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SUBJECT_BINDING, "test-key")

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    subject = _subject_provider(data)
    assert data["status"] == "not_ready"
    assert data["ready_provider_count"] == 0
    assert subject["credential_ready"] is False
    assert subject["route_ready"] is False
    # The subject's model rows are exactly the document's own, so no Provider
    # was promoted by the placeholder written into this binding.
    assert subject["models"] == subject_models


def test_provider_readiness_makes_no_upstream_provider_call(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SUBJECT_BINDING, "snsv_live_abcdefghijklmnopqrstuvwxyz1234")

    async def _unexpected_call(**kwargs):
        raise AssertionError("provider readiness must not make an upstream call")

    monkeypatch.setattr(
        "app.pilot.platform.call_platform_chat_completions",
        _unexpected_call,
    )

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    # Serving one secret is not the same as being ready: the surface still
    # answers per-Provider truth, computed the same way for every row, and the
    # stubbed adapter above proved no upstream call was attempted.
    assert data["providers"]
    assert all(
        item["route_ready"]
        is bool(item["enabled"] and item["credential_ready"] and item["models"])
        for item in data["providers"]
    )


def test_a_retired_binding_name_never_satisfies_a_provider(monkeypatch):
    # A retired intake binding name must not satisfy readiness for anything: the
    # current binding is the Provider row's own name, read from the registry.
    #
    # #7241 3단계: both names are deployment values. The legacy alias is derived
    # from the current name (the intake name without the platform prefix), and
    # the current name is the row's own column, so neither is written here.
    current_binding = SUBJECT_BINDING
    legacy_binding = current_binding.split("_", 1)[1]
    assert legacy_binding and legacy_binding != current_binding

    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(legacy_binding, "legacy-name-1234567890abcdef")
    monkeypatch.delenv(current_binding, raising=False)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    providers = {p["provider_id"]: p for p in response.json()["providers"]}
    assert SUBJECT_PROVIDER_ID in providers
    # The legacy name satisfies nothing: the Provider whose current binding it
    # is not reports exactly the truth a missing credential gives.
    assert providers[SUBJECT_PROVIDER_ID]["credential_ready"] is False
    assert providers[SUBJECT_PROVIDER_ID]["route_ready"] is False
