"""#6828: the pilot router resolve lane answers only a proven caller.

``POST /api/pilot/router/resolve`` returns the routing decision metadata:
the selected provider, the selected model, the upstream model and the
fallback candidates. #6828 moves identity-bearing detail behind the
existing B14 caller proof (#5224) — the same proof the ``/admin`` detail
routes already reuse — instead of exposing that decision to the public
internet or introducing a second authority.

Network-free: no upstream call, no real credential, no Production mutation.
The identities below come from the effective registry document, which is the
placeholder fixture in this process, so no real provider or model value is
written anywhere in this file.
"""
from __future__ import annotations

import json
import time

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import get_catalog_by_id
from app.pilot.service_proof import (
    PROOF_HEADER,
    PROOF_TIME_HEADER,
    compute_service_proof,
)
from _registry_values import a_model_id

RESOLVE_PATH = "/api/pilot/router/resolve"

# The identity-bearing field names the decision response carries. An unproven
# caller must not see any of them, so the refusal body is scanned for each.
IDENTITY_FIELDS = (
    "selected_provider",
    "selected_model",
    "selected_upstream_model",
    "selected_route_id",
    "eligible_fallback",
    "excluded_candidates",
)

WRONG_SECRET = "not-the-resolve-secret-" + "x" * 32


def _binding_env_name() -> str:
    """The credential binding name of the first catalog route (name only)."""
    from app.pilot import platform_secrets as ps

    spec = ps.get_platform_provider(get_catalog_by_id(a_model_id()).platform_provider_id)
    return spec.credential_binding_name


@pytest.fixture(autouse=True)
def _route_credential_env(monkeypatch):
    """Give the catalog row's credential binding a fake value, like alpha1 does.

    The placeholder registry's route is a ``platform_secret`` route, so a
    proven resolve reads the binding name from the effective document and the
    test installs only a fake value for it. No provider identity is written
    here; the ambient provider-mode override is cleared so the mock default
    is what the assertions observe.
    """
    monkeypatch.setenv(_binding_env_name(), "sk-test-6828-resolve-0123456789abcdef")
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _resolve_request_parts():
    """(model_id, catalog entry, request payload) from the effective registry."""
    model_id = a_model_id()
    entry = get_catalog_by_id(model_id)
    payload = {"model": model_id, "messages": [{"role": "user", "content": "hi"}]}
    return model_id, entry, payload


@pytest.mark.no_b14_service_proof
def test_an_unproven_resolve_leaks_no_model_or_provider_values(client):
    """No proof, no routing identity: the whole refusal body is scanned."""
    model_id, entry, payload = _resolve_request_parts()
    response = client.post(RESOLVE_PATH, json=payload)

    assert response.status_code == 401, response.text
    error = response.json()["error"]
    assert error["code"] == "b14_service_proof_required"
    assert set(error) == {"code", "message", "request_id"}

    # Full-body inspection: not one identity field name and not one concrete
    # identity value (model id, upstream model, provider, route id) reaches
    # an unproven caller.
    body_text = response.text
    for forbidden in IDENTITY_FIELDS:
        assert forbidden not in body_text, forbidden
    for value in (
        model_id,
        entry.upstream_model,
        entry.provider,
        entry.platform_provider_id,
        f"platform:{model_id}",
    ):
        assert value not in body_text, value


@pytest.mark.no_b14_service_proof
def test_a_wrongly_signed_resolve_is_refused(client):
    """A proof that does not match this exact body authorizes nothing."""
    _model_id, _entry, payload = _resolve_request_parts()
    timestamp = str(int(time.time()))
    response = client.post(
        RESOLVE_PATH,
        json=payload,
        headers={
            PROOF_HEADER: compute_service_proof(
                WRONG_SECRET, timestamp, json.dumps(payload).encode("utf-8")
            ),
            PROOF_TIME_HEADER: timestamp,
        },
    )
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "b14_service_proof_required"


def test_a_proven_resolve_keeps_the_existing_decision_fields(client):
    """The proven caller still reads the full routing decision response."""
    model_id, _entry, payload = _resolve_request_parts()
    response = client.post(RESOLVE_PATH, json=payload)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["route_mode"] == "manual"
    assert data["selected_model"] == model_id
    assert data["selected_route_id"].startswith("platform:")
    assert data["evidence_status"] == "resolved_not_called"
    assert data["fallback_used"] is False
    assert data["attempt_count"] == 1
    assert data["credential_available"] is True
    assert isinstance(data["reason_codes"], list)
    assert isinstance(data["eligible_fallback"], list)
    assert isinstance(data["excluded_candidates"], list)
    for key in (
        "selected_provider",
        "selected_upstream_model",
        "fallback_allowed",
        "credential_available",
        "credential_status",
        "provider_mode",
        "attempt_candidates",
    ):
        assert key in data, key
