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


def test_kilo_nemotron_catalog_snapshot_is_approved_free_route():
    model = get_catalog_by_id("kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
    assert model is not None
    assert model.upstream_model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert model.provider == "Kilo Gateway / NVIDIA"
    assert model.enabled is True
    assert model.input_price_usd_per_1m == 0.0
    assert model.output_price_usd_per_1m == 0.0
    assert model.context_window == 1_000_000
    assert {"chat", "coding", "free"}.issubset(model.capabilities)


def test_only_known_zero_price_models_are_tagged_free_and_catalog_has_one_entry():
    assert len(CATALOG_MODELS) == 1
    free_models = [model for model in CATALOG_MODELS if "free" in model.capabilities]
    assert {model.model_id for model in free_models} == {"kilo/nvidia-nemotron-3-ultra-550b-a55b-free"}
    for model in free_models:
        assert model.price_is_known is True
        assert model.input_price_usd_per_1m == 0.0
        assert model.output_price_usd_per_1m == 0.0

    paid_models = [model for model in CATALOG_MODELS if "free" not in model.capabilities]
    assert len(paid_models) == 0


def test_general_free_route_selects_kilo_and_has_no_fallback():
    decision = resolve_auto_route(
        task_type="general",
        required_capabilities=["free"],
        optimize_for="korean",
        allow_external_fallback=True,
        max_attempts=3,
    )
    assert decision.selected_model == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
    assert decision.eligible_fallback == []
    assert decision.max_attempts == 3


@pytest.mark.parametrize(
    ("task_type", "required"),
    [
        ("general", ["free"]),
        ("coding", ["free"]),
        ("document", ["free"]),
    ],
)
def test_specialized_free_routes_select_kilo(task_type, required):
    decision = resolve_auto_route(
        task_type=task_type,
        required_capabilities=required,
        optimize_for="balanced",
        allow_external_fallback=True,
        max_attempts=3,
    )
    assert decision.selected_model == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
    assert decision.eligible_fallback == []
    assert decision.max_attempts == 3


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


def test_required_capability_free_includes_kilo_free():
    candidates = filter_catalog(required_capabilities=["free"])
    candidate_ids = {m.model_id for m in candidates}
    assert candidate_ids == {"kilo/nvidia-nemotron-3-ultra-550b-a55b-free"}
    for m in candidates:
        assert m.price_is_known is True
        assert m.input_price_usd_per_1m == 0.0
        assert m.output_price_usd_per_1m == 0.0
        assert "free" in m.capabilities


def test_free_first_default_routing_selects_evidenced_free_models_only():
    """Default auto routing (allow_paid=False) selects only evidenced-free models."""
    for opt in ["balanced", "cost", "latency", "korean"]:
        decision = resolve_auto_route(optimize_for=opt)
        selected = get_catalog_by_id(decision.selected_model)
        assert selected is not None
        assert "free" in selected.capabilities
        assert selected.price_is_known is True
        assert selected.input_price_usd_per_1m == 0.0
        assert selected.output_price_usd_per_1m == 0.0
        assert "free_first:default" in decision.reason_codes
        assert decision.eligible_fallback == []


def test_gateway_resolve_endpoint_honors_allow_paid(client):
    """The /api/pilot/router/resolve endpoint passes allow_paid option properly."""
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
    assert data_default["selected_model"] == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
    assert "free_first:default" in data_default["reason_codes"]

    # Explicit allow_paid=True -> free_first:opt_in
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
    assert "free_first:opt_in" in data_opt_in["reason_codes"]


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

