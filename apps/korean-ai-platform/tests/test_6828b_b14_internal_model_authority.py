"""#6828 stage 2 ①: identity-bearing model authority is a proven-caller surface.

`/api/pilot/models` and `/api/pilot/health` are reachable from the public
internet and, before this change, answered with provider ids, model ids and
registered routes. The owner's release tooling still needs that detail, so it
moves behind the existing B14 caller proof (#5224) on `/api/pilot/admin/...`
instead of gaining a second authority or a new secret.

Network-free: no Provider call, no real credential, no Production mutation.
"""
from __future__ import annotations

import os
import time

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.service_proof import (
    PROOF_HEADER,
    PROOF_TIME_HEADER,
    SERVICE_PROOF_BINDING,
    compute_service_proof,
)

ADMIN_HEALTH = "/api/pilot/admin/health"
ADMIN_MODELS = "/api/pilot/admin/models"
PUBLIC_HEALTH = "/api/pilot/health"
PUBLIC_MODELS = "/api/pilot/models"
SECRET = "b14-test-service-proof-secret-0123456789abcdef"


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_a_proven_caller_reads_the_authority_detail(client):
    """The release tooling keeps the exact detail it needs, names included."""
    health = client.get(ADMIN_HEALTH)
    models = client.get(ADMIN_MODELS)

    assert health.status_code == 200, health.text
    assert models.status_code == 200, models.text

    providers = health.json()["business14"]["providers"]
    assert isinstance(providers, list) and providers
    assert all(isinstance(row.get("id"), str) and row["id"] for row in providers)

    # Registration and execution are separate lists and both stay available.
    for key in ("catalog", "registered_routes"):
        assert isinstance(models.json().get(key), list), key
    assert isinstance(models.json().get("model_groups"), dict)
    assert models.json()["registered_routes"]


@pytest.mark.no_b14_service_proof
def test_an_unproven_caller_is_refused_before_any_detail(client):
    """No proof, no provider or model name — on both detail routes."""
    for path in (ADMIN_HEALTH, ADMIN_MODELS):
        result = client.get(path)
        assert result.status_code == 401, path
        assert result.json()["error"]["code"] == "b14_service_proof_required"
        assert SECRET not in result.text


@pytest.mark.no_b14_service_proof
def test_a_wrongly_signed_caller_is_refused(client):
    """A proof that does not match this exact request authorizes nothing."""
    timestamp = str(int(time.time()))
    for path in (ADMIN_HEALTH, ADMIN_MODELS):
        result = client.get(
            path,
            headers={
                PROOF_HEADER: compute_service_proof("not-the-secret-" + "x" * 32, timestamp, b""),
                PROOF_TIME_HEADER: timestamp,
            },
        )
        assert result.status_code == 401, path
        assert result.json()["error"]["code"] == "b14_service_proof_required"


@pytest.mark.no_b14_service_proof
def test_an_unconfigured_deployment_secret_fails_closed(client, monkeypatch):
    """Without the deployment binding the detail routes refuse, they do not open."""
    monkeypatch.delenv(SERVICE_PROOF_BINDING, raising=False)
    result = client.get(ADMIN_MODELS)
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "b14_service_proof_unconfigured"


@pytest.mark.no_b14_service_proof
def test_the_public_read_surfaces_stay_open_without_a_proof(client):
    """Stage 1 keeps the public URLs answering; only the detail moved."""
    assert os.environ.get(SERVICE_PROOF_BINDING)
    for path in (PUBLIC_HEALTH, PUBLIC_MODELS):
        assert client.get(path).status_code == 200, path
