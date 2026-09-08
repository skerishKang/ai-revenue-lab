"""Tests for the D14 owner-designated fixed fallback chain (b14/auto, #2044).

No scorer is consulted: selection is the first chain position whose platform
secret is present. All tests are network-free and manage the platform secret
environment explicitly so ambient developer keys cannot change the outcome.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.pilot import routing_policy as rp
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.errors import NoSafeRoute, RoutingError
from app.pilot.kilo_provider import KILO_NEMOTRON_MODEL_ID
from app.pilot.poolside_provider import POOLSIDE_MODEL_ID
from app.pilot.router_core import resolve_route
from app.pilot.sensenova_provider import SENSENOVA_MODEL_ID

SENSENOVA_KEY = "sk-chain-unit-sensenova-0123456789"
POOLSIDE_KEY = "sk-chain-unit-poolside-0123456789"


@pytest.fixture(autouse=True)
def _deterministic_chain_env(monkeypatch):
    """Clear chain-affecting env; tests opt in to secrets explicitly."""
    monkeypatch.delenv("PADIEM_SENSENOVA_API_KEY", raising=False)
    monkeypatch.delenv("PADIEM_POOLSIDE_API_KEY", raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved = {"provider_mode": rcfg.provider_mode}
    rcfg.provider_mode = "mock"
    yield
    rcfg.provider_mode = saved["provider_mode"]


def _set_all_secrets(monkeypatch):
    monkeypatch.setenv("PADIEM_SENSENOVA_API_KEY", SENSENOVA_KEY)
    monkeypatch.setenv("PADIEM_POOLSIDE_API_KEY", POOLSIDE_KEY)


def test_chain_order_is_owner_designated(monkeypatch):
    _set_all_secrets(monkeypatch)
    assert rp.chain_models()[0].model_id == SENSENOVA_MODEL_ID
    assert [m.model_id for m in rp.chain_models()] == [
        SENSENOVA_MODEL_ID,
        KILO_NEMOTRON_MODEL_ID,
        POOLSIDE_MODEL_ID,
    ]
    assert rp.ROUTING_POLICY_ID == "fixed_chain_v1"


def test_full_chain_selects_sensenova_first(monkeypatch):
    _set_all_secrets(monkeypatch)
    d = rp.resolve_chain_route()
    assert d.route_mode == "auto"
    assert d.selected_model == SENSENOVA_MODEL_ID
    assert d.selected_route_id == f"platform:{SENSENOVA_MODEL_ID}"
    assert d.reason_codes[:3] == [
        "routing_policy:fixed_chain_v1",
        "chain_position:1",
        f"selected:{SENSENOVA_MODEL_ID}",
    ]
    assert d.fallback_allowed is True
    assert d.max_attempts == 3
    assert [f["model_id"] for f in d.eligible_fallback] == [
        KILO_NEMOTRON_MODEL_ID,
        POOLSIDE_MODEL_ID,
    ]
    assert all(f["reason"] == "fixed_chain_fallback" for f in d.eligible_fallback)
    assert all(f["route_id"] == f"platform:{f['model_id']}" for f in d.eligible_fallback)
    assert [f["platform_provider_id"] for f in d.eligible_fallback] == [
        "kilo",
        "poolside",
    ]
    assert d.excluded_candidates == []
    assert d.credential_available is True
    assert d.credential_status == "key_available"
    assert d.platform_provider_id == "sensenova"
    assert d.evidence_status == "resolved_not_called"


def test_missing_sensenova_secret_selects_kilo_and_excludes(monkeypatch):
    monkeypatch.setenv("PADIEM_POOLSIDE_API_KEY", POOLSIDE_KEY)
    d = rp.resolve_chain_route()
    assert d.selected_model == KILO_NEMOTRON_MODEL_ID
    assert d.selected_route_id == f"platform:{KILO_NEMOTRON_MODEL_ID}"
    excluded = {e["model_id"]: e["reason"] for e in d.excluded_candidates}
    assert excluded[SENSENOVA_MODEL_ID] == "provider_secret_missing"
    assert [f["model_id"] for f in d.eligible_fallback] == [
        POOLSIDE_MODEL_ID,
    ]


def test_no_secrets_selects_keyless_kilo_routes():
    d = rp.resolve_chain_route()
    assert d.selected_model == KILO_NEMOTRON_MODEL_ID
    excluded = {e["model_id"]: e["reason"] for e in d.excluded_candidates}
    assert excluded == {
        SENSENOVA_MODEL_ID: "provider_secret_missing",
        POOLSIDE_MODEL_ID: "provider_secret_missing",
    }
    assert [f["model_id"] for f in d.eligible_fallback] == []


def test_allow_external_fallback_false_is_single_attempt(monkeypatch):
    _set_all_secrets(monkeypatch)
    d = rp.resolve_chain_route(allow_external_fallback=False)
    assert d.fallback_allowed is False
    assert d.eligible_fallback == []
    assert d.max_attempts == 1
    assert "external_fallback_disabled" in d.reason_codes


def test_max_attempts_bounds_chain_walk(monkeypatch):
    _set_all_secrets(monkeypatch)
    assert rp.resolve_chain_route(max_attempts=2).max_attempts == 2
    assert rp.resolve_chain_route(max_attempts=99).max_attempts == 3
    assert rp.resolve_chain_route().max_attempts == 3


def test_scorer_options_are_accepted_but_ignored(monkeypatch):
    _set_all_secrets(monkeypatch)
    plain = resolve_route("b14/auto", {})
    ignored = resolve_route(
        "b14/auto",
        {
            "task_type": "coding",
            "required_capabilities": ["chat", "coding"],
            "optimize_for": "cost",
            "provider_order": ["Someone Else"],
            "allow_paid": True,
        },
    )
    assert ignored.selected_model == plain.selected_model == SENSENOVA_MODEL_ID
    assert any(
        rc == "ignored_options:allow_paid,optimize_for,provider_order,required_capabilities,task_type"
        for rc in ignored.reason_codes
    )


def test_unregistered_chain_model_fails_closed(monkeypatch):
    import app.pilot.catalog as cat

    _set_all_secrets(monkeypatch)
    reduced = {k: v for k, v in cat.CATALOG_BY_ID.items() if k != SENSENOVA_MODEL_ID}
    monkeypatch.setattr(cat, "CATALOG_BY_ID", reduced)
    with pytest.raises(RoutingError) as exc_info:
        rp.resolve_chain_route()
    assert exc_info.value.code == "routing_policy_invalid"


def test_disabled_chain_model_fails_closed(monkeypatch):
    import app.pilot.catalog as cat

    _set_all_secrets(monkeypatch)
    cm = cat.CATALOG_BY_ID[KILO_NEMOTRON_MODEL_ID]
    disabled = dataclasses.replace(cm, enabled=False)
    monkeypatch.setitem(cat.CATALOG_BY_ID, KILO_NEMOTRON_MODEL_ID, disabled)
    with pytest.raises(RoutingError) as exc_info:
        rp.resolve_chain_route()
    assert exc_info.value.code == "routing_policy_invalid"


def test_zero_usable_candidates_raises_no_safe_route(monkeypatch):
    monkeypatch.setattr(rp, "_platform_secret_present", lambda m: False)
    with pytest.raises(NoSafeRoute) as exc_info:
        rp.resolve_chain_route()
    assert exc_info.value.reason_code == "no_chain_candidate_available"
    assert exc_info.value.upstream_called is False


def test_resolve_endpoint_reports_fixed_chain(client, monkeypatch):
    _set_all_secrets(monkeypatch)
    resp = client.post(
        "/api/pilot/router/resolve",
        json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["route_mode"] == "auto"
    assert body["selected_model"] == SENSENOVA_MODEL_ID
    assert body["selected_route_id"] == f"platform:{SENSENOVA_MODEL_ID}"
    assert "routing_policy:fixed_chain_v1" in body["reason_codes"]
    assert body["max_attempts"] == 3
