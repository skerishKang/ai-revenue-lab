"""Registered-route truth for the Business 14 /models surface (#1933 S1).

The public ``catalog`` key preserves a historic 1-entry route snapshot while
``registered_routes`` reveals every exact-ID route in CATALOG_BY_ID without
prices or secrets.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import CATALOG_BY_ID, CATALOG_MODELS
from app.pilot.kilo_provider import KILO_NEMOTRON_MODEL_ID
from app.pilot.poolside_provider import POOLSIDE_MODEL_ID
from app.pilot.sensenova_provider import SENSENOVA_MODEL_ID


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _registered_routes(client) -> list[dict]:
    return client.get("/api/pilot/models").json()["registered_routes"]


def test_registered_routes_match_exact_id_registry(client):
    routes = _registered_routes(client)

    assert len(routes) == len(CATALOG_BY_ID)
    assert [r["id"] for r in routes] == sorted(CATALOG_BY_ID)
    assert [r["provider_id"] for r in routes] == sorted(
        m.platform_provider_id for m in CATALOG_BY_ID.values()
    )


def test_registered_routes_are_price_and_secret_free(client):
    for entry in _registered_routes(client):
        assert set(entry.keys()) == {
            "id",
            "provider_id",
            "upstream_model",
            "free",
            "public",
            "explicit_only",
            "auto_eligible",
            "owner_excluded",
        }
        assert entry["upstream_model"]
        assert isinstance(entry["free"], bool)
        assert isinstance(entry["public"], bool)
        assert isinstance(entry["explicit_only"], bool)
        assert isinstance(entry["auto_eligible"], bool)
        assert isinstance(entry["owner_excluded"], bool)


def test_only_nine_manual_models(client):
    routes=_registered_routes(client)
    assert len(routes)==9
    assert CATALOG_MODELS==[]
    assert all(r["explicit_only"] for r in routes)
    assert not any(r["auto_eligible"] or r["owner_excluded"] for r in routes)

def test_removed_kilo_models_are_unregistered(client):
    assert not [r for r in _registered_routes(client) if r["provider_id"]=="kilo"]

def test_remaining_models_visible_in_exact_catalog(client):
    data=client.get("/api/pilot/models").json()
    ids={m["id"] for m in data["catalog"]}
    assert ids=={r["id"] for r in data["registered_routes"]}
    assert POOLSIDE_MODEL_ID in ids and SENSENOVA_MODEL_ID in ids
    assert "b14/auto" not in ids

def test_sensenova_route_is_explicit_only_and_not_free(client):
    entry = next(
        r for r in _registered_routes(client) if r["id"] == SENSENOVA_MODEL_ID
    )

    assert entry["provider_id"] == "sensenova"
    assert entry["free"] is False
    assert entry["public"] is False
    assert entry["explicit_only"] is True


def test_poolside_route_is_explicit_only_and_not_free(client):
    entry = next(
        r for r in _registered_routes(client) if r["id"] == POOLSIDE_MODEL_ID
    )

    assert entry["provider_id"] == "poolside"
    assert entry["free"] is False
    assert entry["public"] is False
    assert entry["explicit_only"] is True
    # A separately registered direct Poolside route is NOT the Kilo identity.
    # owner_excluded=False is NOT equivalent to owner-approved=True.
    assert entry["owner_excluded"] is False
    assert entry["auto_eligible"] is False


def test_owner_deleted_five_not_in_registry(client):
    excluded={"kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        "kilo/poolside-laguna-s-2.1-free","b-ai/qwen3.8-flash",
        "infron/motif/motif-3","experiential/gpt-5.6-luna"}
    assert excluded.isdisjoint({r["id"] for r in _registered_routes(client)})

def test_other_registered_routes_are_not_implicitly_excluded(client):
    rows = {r["id"]: r for r in _registered_routes(client)}
    for model_id, route in rows.items():
        if model_id not in {
            "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
            "kilo/poolside-laguna-s-2.1-free",
            "b-ai/qwen3.8-flash",
            "infron/motif/motif-3",
            "experiential/gpt-5.6-luna",
        }:
            # Negative on a blocklist is NOT positive customer authorization.
            assert route["owner_excluded"] is False
