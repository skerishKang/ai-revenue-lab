"""#1961 — the Worker must tolerate the retired Poolside binding.

The vestigial ``[[unsafe.bindings]] PADIEM_POOLSIDE_API_KEY`` Secrets Store
binding was removed from wrangler.toml because the store item no longer
exists and its authorization check (Cloudflare 10021) blocked every gated
deploy. Poolside provider code stays registered (owner decision: the
provider "code" is preserved), but it must degrade to an explicit
not-ready readiness report — never a crash, never a silent fallback —
and the Kilo route must be unaffected.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.kilo_provider import KILO_MODEL_ID, KILO_PROVIDER_ID
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.poolside_provider import (
    POOLSIDE_CREDENTIAL_BINDING,
    POOLSIDE_MODEL_ID,
    POOLSIDE_PROVIDER_ID,
)

WRANGLER_TOML = Path(__file__).resolve().parent.parent / "wrangler.toml"


def _provider(data: dict, provider_id: str) -> dict:
    matches = [
        provider
        for provider in data["providers"]
        if provider["provider_id"] == provider_id
    ]
    assert len(matches) == 1
    return matches[0]


def test_wrangler_toml_declares_no_unsafe_bindings():
    config = tomllib.loads(WRANGLER_TOML.read_text(encoding="utf-8"))
    assert "unsafe" not in config
    assert POOLSIDE_CREDENTIAL_BINDING not in WRANGLER_TOML.read_text(encoding="utf-8")


def test_startup_and_registration_succeed_without_poolside_binding(monkeypatch):
    # (a) The app constructs and serves with the binding absent from env.
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(POOLSIDE_CREDENTIAL_BINDING, raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    # Poolside registration itself is untouched by the binding removal.
    spec = get_platform_provider(POOLSIDE_PROVIDER_ID)
    assert spec is not None
    assert spec.credential_binding_name == POOLSIDE_CREDENTIAL_BINDING


def test_poolside_reports_not_ready_without_crash_or_fallback(monkeypatch):
    # (b) Readiness is an explicit not-ready truth, never an exception and
    # never a silent re-route to another provider.
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(POOLSIDE_CREDENTIAL_BINDING, raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    data = response.json()
    poolside = _provider(data, POOLSIDE_PROVIDER_ID)
    assert poolside["enabled"] is True
    assert poolside["credential_source"] == "platform_secret"
    assert poolside["credential_ready"] is False
    assert poolside["route_ready"] is False
    assert poolside["models"] == [POOLSIDE_MODEL_ID]
    # No secret metadata leaks into the response.
    assert POOLSIDE_CREDENTIAL_BINDING not in response.text
    assert "credential_binding_name" not in response.text


def test_kilo_route_unaffected_without_poolside_binding(monkeypatch):
    # (c) The keyless Kilo route stays ready and the overall endpoint status
    # remains "ready" purely because of Kilo.
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(POOLSIDE_CREDENTIAL_BINDING, raising=False)

    with TestClient(create_app()) as client:
        readiness = client.get("/api/pilot/provider-readiness")
        models = client.get("/api/pilot/models")

    assert readiness.status_code == 200
    data = readiness.json()
    assert data["status"] == "ready"
    kilo = _provider(data, KILO_PROVIDER_ID)
    assert kilo["credential_ready"] is True
    assert kilo["route_ready"] is True
    assert KILO_MODEL_ID in kilo["models"]

    # The deployed catalog surface must keep serving the Kilo route (the
    # marker the deploy gate smokes) while Poolside stays unreachable from
    # the public/auto catalog even though its readiness entry exists.
    assert models.status_code == 200
    catalog_ids = [entry["id"] for entry in models.json()["catalog"]]
    assert KILO_MODEL_ID in catalog_ids
    assert POOLSIDE_MODEL_ID not in catalog_ids
