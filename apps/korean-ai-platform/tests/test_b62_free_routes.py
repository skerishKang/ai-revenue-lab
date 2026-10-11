from __future__ import annotations

import json

import httpx
import pytest

from app.pilot.catalog import (
    CATALOG_MODELS,
    CatalogModel,
    ensure_free_tag_requires_known_zero_price,
    filter_catalog,
    get_catalog_by_id,
)
from app.pilot.errors import NoSafeRoute
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.router_core import resolve_auto_route


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
    assert not [m for m in CATALOG_BY_ID.values() if "free" in m.capabilities]
    assert all(m not in CATALOG_BY_ID for m in [
        "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        "kilo/poolside-laguna-s-2.1-free",
    ])

def test_general_free_route_fails_without_a_registered_free_model():
    with pytest.raises(NoSafeRoute) as info:
        resolve_auto_route(task_type="general",required_capabilities=["free"],
                           optimize_for="korean",allow_external_fallback=True,max_attempts=3)
    assert info.value.reason_code == "no_candidate_meets_capabilities"
    assert info.value.upstream_called is False

@pytest.mark.parametrize(
    ("task_type", "required"),
    [
        ("general", ["free"]),
        ("coding", ["free"]),
        ("document", ["free"]),
    ],
)
def test_specialized_free_routes_fail_closed_without_approved_free_models(task_type,required):
    with pytest.raises(NoSafeRoute) as info:
        resolve_auto_route(task_type=task_type,required_capabilities=required,
                           optimize_for="balanced",allow_external_fallback=True,max_attempts=3)
    assert info.value.reason_code == "no_candidate_meets_capabilities"
    assert info.value.upstream_called is False

def test_no_matching_free_route_fails_before_upstream():
    with pytest.raises(NoSafeRoute) as info:
        resolve_auto_route(
            task_type="general",
            required_capabilities=["free", "video"],
            optimize_for="balanced",
        )
    assert info.value.reason_code == "invalid_capability_requirement"
    assert info.value.upstream_called is False


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


def test_required_free_capability_excludes_all_removed_free_models():
    assert filter_catalog(required_capabilities=["free"]) == []
    assert get_catalog_by_id("poolside/laguna-s-2.1") is not None
    assert "free" not in get_catalog_by_id("poolside/laguna-s-2.1").capabilities

def test_free_first_default_fails_closed_not_an_unapproved_paid_upgrade():
    for opt in ("balanced", "cost", "latency", "korean"):
        with pytest.raises(NoSafeRoute) as info:
            resolve_auto_route(optimize_for=opt)
        assert info.value.reason_code == "no_candidate_meets_capabilities"
        assert info.value.upstream_called is False

def test_gateway_resolve_endpoint_ignores_allow_paid_for_fixed_chain(client, monkeypatch):
    """D14 (#2044): /api/pilot/router/resolve b14/auto ignores allow_paid (fixed chain)."""
    monkeypatch.setenv("PADIEM_AGNES_API_KEY", "sk-test-agnes-route-0123456789")
    monkeypatch.delenv("PADIEM_POOLSIDE_API_KEY", raising=False)
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
