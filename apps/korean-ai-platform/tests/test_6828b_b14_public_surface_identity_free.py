"""#6828 stage 2 ①: the public B14 read surfaces name no provider or model.

`b14.padiem.net` is reachable from the open internet, so `/api/pilot/models`
and `/api/pilot/health` may only answer in the product vocabulary: PADIEM
grades, counts and readiness flags. Everything that names a provider, a model
or a route lives on `/api/pilot/admin/...` behind the caller proof.

Needles are read from the owner registry at test time, so this module writes no
model or provider name of its own. Network-free.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.factory import create_app

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "app" / "pilot" / "b14_models.json"

#: One registered provider id is the login-method brand, not a model identity.
LOGIN_BRAND_EXCEPTIONS = frozenset({"google"})

PUBLIC_MODELS = "/api/pilot/models"
PUBLIC_HEALTH = "/api/pilot/health"
ADMIN_MODELS = "/api/pilot/admin/models"
GRADE_NAMES = ("free", "plus", "pro", "max")


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _needles() -> list[str]:
    """Registered identities.

    Names shorter than six characters are skipped: they collide with ordinary
    English words in the JSON keys, and no real identifier is that short.
    """
    register = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    values: list[str] = []
    for model in register.get("models", []):
        values.append(model["id"])
        values.append(model.get("upstream_model", ""))
        values.append(model.get("provider_name", ""))
    values += [
        provider
        for provider in register.get("providers", {})
        if provider not in LOGIN_BRAND_EXCEPTIONS
    ]
    needles = sorted({value for value in values if isinstance(value, str) and len(value) >= 6})
    assert needles, "the owner registry must yield identity needles"
    return needles


def _leaks(text: str) -> list[str]:
    return [needle for needle in _needles() if needle in text]


def test_public_models_answers_with_grades_only(client):
    """A visitor learns which PADIEM grades are available, and nothing more."""
    response = client.get(PUBLIC_MODELS)
    assert response.status_code == 200, response.text
    body = response.json()

    assert [row["grade"] for row in body["grades"]] == list(GRADE_NAMES)
    assert all(isinstance(row["available"], bool) for row in body["grades"])
    assert body["grades"][0]["available"] is True
    assert isinstance(body["catalog_models"], int) and body["catalog_models"] > 0
    assert isinstance(body["registered_routes"], int) and body["registered_routes"] > 0

    # The route and catalog detail is gone, not merely renamed.
    assert "catalog" not in body
    assert "models" not in body
    assert "model_groups" not in body
    assert _leaks(response.text) == []


def test_public_health_answers_with_counts_only(client):
    """Readiness is a status; the providers behind it stay server-side."""
    response = client.get(PUBLIC_HEALTH)
    assert response.status_code == 200, response.text
    body = response.json()

    business14 = body["business14"]
    assert "providers" not in business14
    assert isinstance(business14["provider_count"], int) and business14["provider_count"] > 0
    assert isinstance(business14["catalog_models"], int) and business14["catalog_models"] > 0
    assert isinstance(business14["has_key"], bool)
    assert _leaks(response.text) == []


def test_the_release_tooling_still_reads_the_detail(client):
    """The proof-gated path keeps the identities the owner's tooling needs."""
    detail = client.get(ADMIN_MODELS)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["catalog"] and body["registered_routes"]
    assert _leaks(detail.text), "the internal detail must still carry the registry"
