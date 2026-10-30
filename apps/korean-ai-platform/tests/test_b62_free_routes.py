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
    # registered free-tagged B14 models include the current Beam Free primary.
    assert {m.model_id for m in CATALOG_BY_ID.values() if "free" in m.capabilities and m.enabled} == {
        "tokenharbor/deepseek-v4.1-flash:free",
        "opencode-go/beam-free",
        "opencode-go/longcat-2.5-preview-free",
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




def test_gateway_rejects_the_retired_auto_id_and_drops_scorer_options(
    client, monkeypatch
):
    """B7: b14/auto is refused outright. B4 grace: the scorer-era names are
    accepted, logged, and dropped — they never reach routing."""
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_01", "sk-test-agnes-route-0123456789")
    resp_default = client.post(
        "/api/pilot/router/resolve",
        json={
            "model": "b14/auto",
            "messages": [{"role": "user", "content": "hi"}],
            "business14": {"task_type": "coding"},
        },
    )
    assert resp_default.status_code == 422
    assert resp_default.json()["error"]["code"] == "invalid_body"

    # B4 grace: the retired names are accepted, logged, and dropped.
    resp_opt_in = client.post(
        "/api/pilot/router/resolve",
        json={
            "model": "agnes-ai/agnes-3.0-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "business14": {"task_type": "coding", "allow_paid": True},
        },
    )
    assert resp_opt_in.status_code == 200
    assert resp_opt_in.json()["selected_model"] == "agnes-ai/agnes-3.0-flash"


def test_gateway_allow_paid_is_dropped_whatever_the_value(client, monkeypatch):
    """B4 grace: allow_paid is ignored (logged), so its type is not checked."""
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_01", "sk-test-agnes-route-0123456789")
    resp = client.post(
        "/api/pilot/router/resolve",
        json={
            "model": "agnes-ai/agnes-3.0-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "business14": {"allow_paid": "yes"},
        },
    )
    # B4 grace: allow_paid is dropped whatever the value.
    assert resp.status_code == 200
    assert "allow_paid" not in (resp.json().get("business14") or {})
