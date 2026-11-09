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
from app.pilot.model_registry_file import retired_model_ids
from app.pilot.poolside_provider import POOLSIDE_MODEL_ID
from app.pilot.sensenova_provider import SENSENOVA_MODEL_ID

from _registry_values import adapter_declaring_retired, model_row, model_rows, provider_of

from _registry_values import require_owner_document

require_owner_document()

# Owner retirement is read from the same registry that installs the routes.
RETIRED = retired_model_ids()


def _sole_registered_id(provider_id: str) -> str:
    """The one *installed* identity this provider serves, read from the registry.

    Retired and disabled rows are excluded, so the expectation is the effective
    roster rather than a copy of a deployment name (#7241 3a).
    """
    live = [
        row["id"]
        for row in model_rows()
        if provider_of(row["id"]) == provider_id
        and row["id"] not in RETIRED
        and row["enabled"]
    ]
    assert len(live) == 1, "expected exactly one installed identity for this Provider"
    return live[0]


#: The Provider whose other identities are retired while one is still served,
#: read from the adapter that owns that retirement roster.
_RETIRING_PROVIDER, _, _RETAINED = adapter_declaring_retired()
#: Its one installed identity, and the Provider serving the identical upstream
#: identity: the same upstream model as a *different* Provider's own row, which
#: is what makes the two routes sibling registrations rather than one route.
_INSTALLED_ID = _sole_registered_id(_RETIRING_PROVIDER)
_UPSTREAM_MODEL = model_row(_INSTALLED_ID)["upstream_model"]
_MIRROR_PROVIDER = next(
    provider_of(row["id"])
    for row in model_rows()
    if provider_of(row["id"]) != _RETIRING_PROVIDER
    and row["upstream_model"] == _UPSTREAM_MODEL
)


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _registered_routes(client) -> list[dict]:
    return client.get("/api/pilot/admin/models").json()["registered_routes"]


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


def test_only_owner_registered_manual_models(client):
    routes=_registered_routes(client)
    assert len(routes)==len(CATALOG_BY_ID)
    assert CATALOG_MODELS==[]
    assert all(r["explicit_only"] for r in routes)
    assert not any(r["auto_eligible"] or r["owner_excluded"] for r in routes)

def test_retired_kilo_models_stay_unregistered_while_crouton_is_registered(client):
    routes = _registered_routes(client)
    primary = [r for r in routes if r["provider_id"] == _RETIRING_PROVIDER]
    assert [r["id"] for r in primary] == [_INSTALLED_ID]
    mirror = [r for r in routes if r["provider_id"] == _MIRROR_PROVIDER]
    assert [r["id"] for r in mirror] == [_MIRROR_PROVIDER + "/" + _UPSTREAM_MODEL]
    registered = {r["id"] for r in routes}
    assert not (
        registered
        & {m for m in retired_model_ids() if provider_of(m) == _RETIRING_PROVIDER}
    )

def test_remaining_models_visible_in_exact_catalog(client):
    data=client.get("/api/pilot/admin/models").json()
    ids={m["id"] for m in data["catalog"]}
    assert ids=={m.model_id for m in CATALOG_BY_ID.values() if m.enabled}
    assert POOLSIDE_MODEL_ID in ids and SENSENOVA_MODEL_ID not in ids

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


def test_owner_retired_models_are_not_registered(client):
    assert RETIRED.isdisjoint({r["id"] for r in _registered_routes(client)})

def test_other_registered_routes_are_not_implicitly_excluded(client):
    rows = {r["id"]: r for r in _registered_routes(client)}
    for model_id, route in rows.items():
        if model_id not in RETIRED:
            # Negative on a blocklist is NOT positive customer authorization.
            assert route["owner_excluded"] is False
