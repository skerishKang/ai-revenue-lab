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
            "capabilities",
            "free",
            "public",
            "explicit_only",
            "auto_eligible",
            "owner_excluded",
        }
        assert entry["upstream_model"]
        assert isinstance(entry["capabilities"], list)
        assert entry["capabilities"] == sorted(entry["capabilities"])
        assert all(isinstance(tag, str) for tag in entry["capabilities"])
        assert entry["capabilities"] == sorted(
            CATALOG_BY_ID[entry["id"]].capabilities
        )
        assert isinstance(entry["free"], bool)
        assert isinstance(entry["public"], bool)
        assert isinstance(entry["explicit_only"], bool)
        assert isinstance(entry["auto_eligible"], bool)
        assert isinstance(entry["owner_excluded"], bool)


def test_legacy_public_catalog_route_is_owner_excluded_from_auto(client):
    routes = _registered_routes(client)
    public = [r for r in routes if r["public"]]
    explicit = [r for r in routes if r["explicit_only"]]

    assert len(public) == len(CATALOG_MODELS) == 1
    assert public[0]["id"] == KILO_NEMOTRON_MODEL_ID
    assert public[0]["provider_id"] == "kilo"
    assert public[0]["owner_excluded"] is True
    assert public[0]["auto_eligible"] is False
    # #2097: minimax + hy3 retirement unregistered two explicit-only lanes.
    # The owner final retirement decision (2026-10-07) retired the Space Bunny
    # lane too: nine earlier manual-pin routes plus four Google owner-selected
    # manual-pin routes (13 total); public auto lane remains unchanged.
    assert len(explicit) == 13
    assert all(not r["auto_eligible"] for r in explicit)


def test_all_registered_kilo_routes_are_not_customer_auto_eligible(client):
    kilo_routes = [
        r for r in _registered_routes(client) if r["provider_id"] == "kilo"
    ]

    # #2097: two of the four original Kilo free lanes are retired/unregistered.
    # The owner final retirement decision (2026-10-07) retired the Space Bunny
    # lane too. Both remaining Kilo entries are historical free registrations,
    # neither customer-auto-eligible under the latest owner exclusion.
    assert len(kilo_routes) == 2
    assert all(r["free"] is True for r in kilo_routes)
    assert sum(r["auto_eligible"] for r in kilo_routes) == 0
    assert all(r["owner_excluded"] for r in kilo_routes)


def test_poolside_and_sensenova_stay_out_of_public_catalog(client):
    data = client.get("/api/pilot/models").json()
    catalog_ids = [m["id"] for m in data["catalog"]]
    route_ids = [r["id"] for r in data["registered_routes"]]

    assert POOLSIDE_MODEL_ID in route_ids
    assert SENSENOVA_MODEL_ID in route_ids
    assert POOLSIDE_MODEL_ID not in catalog_ids
    assert SENSENOVA_MODEL_ID not in catalog_ids
    assert KILO_NEMOTRON_MODEL_ID in catalog_ids
    assert "b14/auto" in catalog_ids


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


def test_owner_excluded_registered_routes_are_never_auto_eligible(client):
    """Owner exclusion overrides free/public route metadata."""
    excluded = {
        "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        "kilo/poolside-laguna-s-2.1-free",
        "b-ai/qwen3.8-flash",
        "infron/motif/motif-3",
        "experiential/gpt-5.6-luna",
    }
    rows = {r["id"]: r for r in _registered_routes(client)}
    assert excluded.issubset(rows)
    for model_id in excluded:
        assert rows[model_id]["owner_excluded"] is True
        assert rows[model_id]["auto_eligible"] is False

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
