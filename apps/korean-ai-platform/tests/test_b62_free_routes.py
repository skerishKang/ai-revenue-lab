"""Free-route registration rules for the B14 catalog.

#7241 3a: which model is retired, which rows carry the free tag and which
provider owns a route are deployment values, so every expected value below is
derived from the effective registry (or from the app's own catalog) instead of
being written into the file. The promotional free-roster retirement is
selected structurally from the adapter that owns a retirement roster, so no
identity is spelled here.
"""
from __future__ import annotations

import json
import re

import httpx
import pytest

from app.pilot.catalog import (
    CATALOG_MODELS,
    CatalogModel,
    ensure_free_tag_requires_known_zero_price,
    get_catalog_by_id,
)
from app.pilot.errors import NoSafeRoute
from app.pilot.b14_runtime_config import runtime_config

from _registry_values import (
    adapter_declaring_retired,
    model_rows,
    owner_document_present,
    provider_of,
    registry,
    requires_owner_document,
)


def _provider_credential(binding_name: str) -> str:
    """A key-shaped value for the Provider slot the request has to resolve.

    The suite proves that the legacy scorer-era body fields are dropped, so the
    route has to reach its provider. The slot NAME is read from the effective
    registry; only the value is synthetic (and must stay off the app's
    placeholder list, which B14 refuses before routing).
    """
    return "sk-synthetic-" + re.sub(r"[^a-z0-9]", "-", binding_name.lower())


def _server_owned_provider() -> str:
    """One enabled registry Provider that reads a server-owned binding."""
    for model_id in [row["id"] for row in model_rows()]:
        provider_id = provider_of(model_id)
        entry = registry()["providers"][provider_id]
        if entry["enabled"] and entry["credential_source"] == "platform_secret":
            return provider_id
    pytest.skip("the effective registry declares no server-owned Provider")


def _route_model(provider_id: str) -> str:
    """A registered model id of that Provider."""
    for model_id in [row["id"] for row in model_rows()]:
        if provider_of(model_id) == provider_id:
            return model_id
    pytest.skip(f"no registered model for Provider {provider_id!r}")


def _retired_free_routes() -> frozenset[str]:
    """The promotional free lanes that must never regain a catalog entry.

    #7241 3a: the identities are the retirement roster the free-route adapter
    owns (its declared retired ids plus the identities its own constants
    retain), read out of the package rather than restated here.
    """
    _provider_id, _module, retired = adapter_declaring_retired()
    return retired


def _free_rows() -> list[dict]:
    """Every enabled registry row tagged free whose Provider is enabled too."""
    providers = registry()["providers"]
    return [
        row for row in model_rows()
        if row["enabled"] and "free" in row["capabilities"]
        and providers[row["provider_id"]]["enabled"]
    ]


@pytest.fixture(autouse=True)
def _restore_runtime_config():
    saved_mode = runtime_config.provider_mode
    yield
    runtime_config.provider_mode = saved_mode


def test_kilo_nemotron_is_permanently_unregistered():
    """The retirement roster the Owner decided on is absent from the catalog.

    The roster is the adapter's own declaration, so it holds on any host; what
    only an owner host can show is that the roster is non-empty and that the
    document does not re-register one of those identities (#7241 3단계).
    """
    retired = _retired_free_routes()
    for retired_id in sorted(retired):
        assert get_catalog_by_id(retired_id) is None
    if not owner_document_present():
        # The placeholder document names no free lane, so there is nothing on
        # this host for the retirement decision to be about.
        assert retired, "the adapter declares no retirement roster"
        return
    assert retired
    assert {row["id"] for row in model_rows()}.isdisjoint(retired)


@requires_owner_document
def test_removed_free_models_not_in_public_or_exact_catalog():
    from app.pilot.catalog import CATALOG_BY_ID
    assert CATALOG_MODELS == []
    # Historical Kilo promotional free routes remain retired. Explicitly
    # registered free-tagged B14 models include the current Beam Free primary.
    # The tag set is the effective registry's own free roster; the retired
    # identities below are the same Owner pin as the test above.
    assert {m.model_id for m in CATALOG_BY_ID.values() if "free" in m.capabilities and m.enabled} == {
        row["id"] for row in _free_rows()
    }
    assert all(m not in CATALOG_BY_ID for m in _retired_free_routes())





def test_unknown_price_model_is_never_implicitly_classified_free():
    unknown_price = CatalogModel(
        model_id="mystery/unknown-price",
        upstream_model="mystery/unknown-price",
        display_name="Unknown Price Model",
        provider="Mystery",
        provider_type="external",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        capabilities=frozenset({"chat", "free"}),
    )
    assert unknown_price.price_is_known is False
    with pytest.raises(RuntimeError):
        ensure_free_tag_requires_known_zero_price(unknown_price)

    nonzero = CatalogModel(
        model_id="mystery/nonzero",
        upstream_model="mystery/nonzero",
        display_name="Nonzero Price Model",
        provider="Mystery",
        provider_type="external",
        input_price_usd_per_1m=1.0,
        output_price_usd_per_1m=2.0,
        capabilities=frozenset({"chat", "free"}),
    )
    with pytest.raises(RuntimeError):
        ensure_free_tag_requires_known_zero_price(nonzero)




def test_gateway_drops_scorer_options(client, monkeypatch):
    """B4 grace: the scorer-era names are accepted, logged, and dropped —
    they never reach routing."""
    provider_id = _server_owned_provider()
    route_model = _route_model(provider_id)
    binding_name = registry()["providers"][provider_id]["credential_binding_name"]
    monkeypatch.setenv(binding_name, _provider_credential(binding_name))
    # B4 grace: the retired names are accepted, logged, and dropped.
    resp_opt_in = client.post(
        "/api/pilot/router/resolve",
        json={
            "model": route_model,
            "messages": [{"role": "user", "content": "hi"}],
            "business14": {"task_type": "coding", "allow_paid": True},
        },
    )
    assert resp_opt_in.status_code == 200
    assert resp_opt_in.json()["selected_model"] == route_model


def test_gateway_allow_paid_is_dropped_whatever_the_value(client, monkeypatch):
    """B4 grace: allow_paid is ignored (logged), so its type is not checked."""
    provider_id = _server_owned_provider()
    route_model = _route_model(provider_id)
    binding_name = registry()["providers"][provider_id]["credential_binding_name"]
    monkeypatch.setenv(binding_name, _provider_credential(binding_name))
    resp = client.post(
        "/api/pilot/router/resolve",
        json={
            "model": route_model,
            "messages": [{"role": "user", "content": "hi"}],
            "business14": {"allow_paid": "yes"},
        },
    )
    # B4 grace: allow_paid is dropped whatever the value.
    assert resp.status_code == 200
    assert "allow_paid" not in (resp.json().get("business14") or {})
