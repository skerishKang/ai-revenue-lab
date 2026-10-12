"""#4453 full B14 registry projection must not become a user model grant."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.b66_b14_free_first_resolver import B14FreeFirstQuoteModelResolver
from app.b66_registered_model_boundary import B66ModelRouteError


ENABLED = "provider/active"
DISABLED = "provider/off"
EXCLUDED = "provider/excluded"


def registry():
    return {
        "registered_routes": [
            {"id": ENABLED, "provider_id": "provider", "owner_excluded": False,
             "capabilities": ["chat"], "upstream_model": "private-upstream-active",
             "credential_binding_name": "SHOULD_NOT_LEAK"},
            {"id": DISABLED, "provider_id": "provider", "owner_excluded": False,
             "capabilities": ["chat", "coding"], "base_origin": "PRIVATE_HOST"},
            {"id": EXCLUDED, "provider_id": "provider", "owner_excluded": True,
             "capabilities": ["chat"], "api_key": "SHOULD_NOT_LEAK"},
        ],
        "catalog": [
            {"id": ENABLED, "provider_id": "provider", "name": "Active model", "tags": ["chat"]},
            {"id": EXCLUDED, "provider_id": "provider", "name": "Excluded model", "tags": ["chat"]},
        ],
    }


class Transport:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status
        self.paths = []

    async def get_json(self, path):
        self.paths.append(path)
        assert path == "/api/pilot/models"
        return self.status, json.dumps(self.payload).encode("utf8")


def get(transport):
    return asyncio.run(B14FreeFirstQuoteModelResolver(transport).list_registered_models())


def test_all_models_including_disabled_and_owner_excluded_are_visible_in_admin_projection():
    transport = Transport(registry())
    rows = get(transport)
    assert len(rows) == 3
    assert [row["model_id"] for row in rows] == sorted((ENABLED, DISABLED, EXCLUDED))
    assert next(r for r in rows if r["model_id"] == ENABLED)["b14_enabled"] is True
    assert next(r for r in rows if r["model_id"] == DISABLED)["b14_enabled"] is False
    assert next(r for r in rows if r["model_id"] == EXCLUDED)["owner_excluded"] is True
    assert transport.paths == ["/api/pilot/models"]
    payload = json.dumps(rows)
    assert "api_key" not in payload and "SHOULD_NOT_LEAK" not in payload
    assert "private-upstream" not in payload and "PRIVATE_HOST" not in payload
    assert "credential_binding_name" not in payload
    assert "model_id" in payload


@pytest.mark.parametrize("mutation", [
    lambda x: x["registered_routes"].append(dict(x["registered_routes"][0])),
    lambda x: x["registered_routes"][0].pop("owner_excluded"),
    lambda x: x["registered_routes"][0].update({"owner_excluded": "false"}),
    lambda x: x["registered_routes"][0].update({"provider_id": "other"}),
    lambda x: x["catalog"].append({"id": "provider/not-registered", "provider_id": "provider", "name": "X"}),
    lambda x: x["catalog"][0].update({"provider_id": "other"}),
    lambda x: x["catalog"][0].update({"name": "<fake>\u0000 secret"}),
])
def test_registry_malformed_metadata_denied_not_partially_exposed(mutation):
    payload = registry()
    mutation(payload)
    with pytest.raises(B66ModelRouteError) as exc:
        get(Transport(payload))
    assert exc.value.code == "selection_unavailable"


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_failed_b14_metadata_is_unavailable_not_empty_or_default(status):
    with pytest.raises(B66ModelRouteError) as exc:
        get(Transport(registry(), status))
    assert exc.value.code == "selection_unavailable"


def test_unconfigured_transport_denies():
    with pytest.raises(B66ModelRouteError):
        get(Transport(None, 503))


def test_full_inventory_is_not_an_implicit_b66_selection_or_execution():
    transport = Transport(registry())
    get(transport)
    assert transport.paths == ["/api/pilot/models"]
    # No POST / completions, no tier or membership changes.
