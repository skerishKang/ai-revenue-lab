from __future__ import annotations

import json

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


@pytest.fixture(autouse=True)
def _enable_archived_auto_route_tests(monkeypatch):
    """Archived fixed-chain tests explicitly opt in; live default stays deferred."""
    monkeypatch.setenv("B14_ENABLE_FUTURE_AUTO", "1")


@pytest.fixture(autouse=True)
def _restore_runtime_config():
    saved_mode = runtime_config.provider_mode
    yield
    runtime_config.provider_mode = saved_mode


def test_kilo_nemotron_is_permanently_unregistered():
    assert get_catalog_by_id("kilo/nvidia-nemotron-3-ultra-550b-a55b-free") is None
    assert get_catalog_by_id("kilo/poolside-laguna-s-2.1-free") is None

def test_removed_free_models_not_in_public_or_exact_catalog():
    from app.pilot.catalog import CATALOG_BY_ID
    assert CATALOG_MODELS == []
    # Historical Kilo promotional free routes remain retired. Explicitly
    # registered free-tagged B14 models include the owner-approved Cat Jam.
    assert {m.model_id for m in CATALOG_BY_ID.values() if "free" in m.capabilities and m.enabled} == {
        "tokenharbor/claude-haiku-5.5:free",
        "tokenharbor/deepseek-v4.1-flash:free",
        "opencode-go/cat-jam-free",
    }
    assert all(m not in CATALOG_BY_ID for m in [
        "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        "kilo/poolside-laguna-s-2.1-free",
    ])





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




def test_gateway_resolve_endpoint_ignores_allow_paid_for_fixed_chain(client, monkeypatch):
    """D14 (#2044): /api/pilot/router/resolve b14/auto ignores allow_paid (fixed chain)."""
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_01", "sk-test-agnes-route-0123456789")
    monkeypatch.delenv("PADIEM_B14_CREDENTIAL_12", raising=False)
    resp_default = client.post(
        "/api/pilot/router/resolve",
        json={
            "model": "b14/auto",
            "messages": [{"role": "user", "content": "hi"}],
            "business14": {"task_type": "coding"},
        },
    )
    assert resp_default.status_code == 200
    data_default = resp_default.json()
    assert data_default["selected_model"] == "agnes-ai/agnes-3.0-flash"
    assert "routing_policy:fixed_chain_v1" in data_default["reason_codes"]

    # Explicit allow_paid=True changes nothing: same chain head, recorded as ignored.
    resp_opt_in = client.post(
        "/api/pilot/router/resolve",
        json={
            "model": "b14/auto",
            "messages": [{"role": "user", "content": "hi"}],
            "business14": {"task_type": "coding", "allow_paid": True},
        },
    )
    assert resp_opt_in.status_code == 200
    data_opt_in = resp_opt_in.json()
    assert data_opt_in["selected_model"] == data_default["selected_model"]
    assert any(
        rc.startswith("ignored_options:") and "allow_paid" in rc
        for rc in data_opt_in["reason_codes"]
    )


def test_gateway_allow_paid_must_be_boolean_422(client):
    """business14.allow_paid with non-boolean value returns 422."""
    resp = client.post(
        "/api/pilot/router/resolve",
        json={
            "model": "b14/auto",
            "messages": [{"role": "user", "content": "hi"}],
            "business14": {"allow_paid": "yes"},
        },
    )
    assert resp.status_code == 422
    assert "business14.allow_paid must be a boolean" in resp.json()["error"]["message"]
