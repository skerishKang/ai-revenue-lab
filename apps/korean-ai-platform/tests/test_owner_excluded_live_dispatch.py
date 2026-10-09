"""#3789: fail closed for OWNER-excluded model IDs before any real egress.

Only live resolver/provider paths are newly blocked. Historical mock fixture
paths remain in place without conveying live OWNER approval.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.errors import NoSafeRoute, PilotNotConfigured
from app.pilot.owner_model_exclusions import excluded_from_owner_customer_selection
from app.pilot.model_registry_file import read_registry
from app.pilot.platform import _require_owner_allowed_live_model
from app.pilot.platform import (
    call_platform_chat_completions,
    stream_platform_chat_completions,
)
from app.pilot.router_core import resolve_auto_route, resolve_manual_route
from app.pilot.poolside_provider import POOLSIDE_MODEL_ID

EXCLUDED = (
    ("kilo/nvidia-nemotron-3-ultra-550b-a55b-free", "kilo"),
    ("kilo/poolside-laguna-s-2.1-free", "kilo"),
    ("b-ai/qwen3.8-flash", "b-ai"),
    ("infron/motif/motif-3", "infron"),
    ("experiential/gpt-5.6-luna", "experiential"),
    ("kilo/stepfun/step-3.7-flash", "kilo"),
    ("stepfun/step-3.7-flash", "stepfun"),
    ("thinkingmachines/inkling-small:free", "thinkingmachines"),
    ("kilo/thinkingmachines/inkling-small:free", "kilo"),
)


@pytest.fixture(autouse=True)
def live_only(monkeypatch):
    saved=runtime_config.provider_mode
    runtime_config.provider_mode="live"
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    # No real keys. Providers remain registered as metadata.
    yield
    runtime_config.provider_mode=saved


@pytest.mark.parametrize("mid,provider", EXCLUDED)
def test_owner_excluded_manual_resolver_refuses_before_secret_and_network(mid, provider):
    assert excluded_from_owner_customer_selection(mid)
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(mid, allow_external_fallback=True)
    assert exc.value.reason_code == "owner_model_excluded"
    assert exc.value.upstream_called is False


@pytest.mark.parametrize("mid,provider", EXCLUDED)
def test_provider_json_egress_denied_before_secret_and_transport(mid, provider):
    calls=[]
    def unexpected(request):
        calls.append(request)
        raise AssertionError("excluded model made an upstream call")
    async def invoke():
        return await call_platform_chat_completions(
            model_id=mid, upstream_model="fixture-model", provider=provider,
            platform_provider_id=provider,
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(unexpected),
        )
    with pytest.raises(PilotNotConfigured):
        asyncio.run(invoke())
    assert calls == []


@pytest.mark.parametrize("mid,provider", EXCLUDED)
def test_provider_stream_egress_denied_before_secret_and_transport(mid, provider):
    calls=[]
    def unexpected(request):
        calls.append(request)
        raise AssertionError("excluded model streamed upstream")
    async def invoke():
        async for _ in stream_platform_chat_completions(
            model_id=mid, upstream_model="fixture-model", provider=provider,
            platform_provider_id=provider,
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(unexpected),
        ):
            pass
    with pytest.raises(PilotNotConfigured):
        asyncio.run(invoke())
    assert calls == []


def test_live_manual_fallback_never_advertises_excluded_candidates(monkeypatch):
    monkeypatch.setenv("PADIEM_POOLSIDE_API_KEY","synthetic_poolside_key_abcdefghij")
    assert excluded_from_owner_customer_selection(POOLSIDE_MODEL_ID) is False
    decision=resolve_manual_route(POOLSIDE_MODEL_ID, allow_external_fallback=True)
    assert decision.selected_model == POOLSIDE_MODEL_ID
    assert all(not excluded_from_owner_customer_selection(
        candidate["model_id"]) for candidate in decision.eligible_fallback)
    assert decision.fallback_allowed is True


def test_live_scorer_has_no_excluded_single_free_candidate(monkeypatch):
    monkeypatch.setenv("PADIEM_KILO_API_KEY","synthetic_kilo_key_abcdefghij")
    with pytest.raises(NoSafeRoute) as exc:
        resolve_auto_route(allow_external_fallback=True)
    assert exc.value.upstream_called is False


@pytest.mark.parametrize("mid,provider", EXCLUDED)
def test_resolve_endpoint_excluded_returns_no_safe_route_not_model_call(mid,provider):
    with TestClient(create_app()) as client:
        resp=client.post("/api/pilot/router/resolve",json={
            "model":mid,
            "messages":[{"role":"user","content":"fixture"}],
        })
    assert resp.status_code == 400
    err=resp.json()["error"]
    assert err["code"] == "unsupported_model"
    assert "reason_code" not in err


@pytest.mark.parametrize("retired", [
    "stepfun/step-3.7-flash",
    "stepfun/step-3.7-flash:free",
    "kilo/stepfun/step-3.7-flash",
    "kilo/stepfun/step-3.7-flash:free",
    "kilo/stepfun-step-3.7-flash-free",
])
def test_stepfun_37_all_direct_and_kilo_aliases_are_owner_retired(retired):
    assert excluded_from_owner_customer_selection(retired)


@pytest.mark.parametrize("allowed", [
    "stepfun/step-5-preview-free",
    "kilo/stepfun/step-5-preview-free",
    "stepfun/step-3.5-flash",
    "inception/mercury-2.5",
])
def test_stepfun_37_retirement_does_not_retire_unrelated_models(allowed):
    assert not excluded_from_owner_customer_selection(allowed)


@pytest.mark.parametrize("retired", [
    "thinkingmachines/inkling-small:free",
    "thinkingmachines/inkling-small",
    "kilo/thinkingmachines/inkling-small:free",
    "kilo/thinkingmachines-inkling-small-free",
    "thinkingmachines/Inkling-Small:FREE",
])
def test_inkling_small_direct_and_discovery_aliases_are_owner_retired(retired):
    assert excluded_from_owner_customer_selection(retired)


@pytest.mark.parametrize("allowed", [
    "thinkingmachines/inkling-large:free",
    "thinkingmachines/inkling-medium:free",
    "thinkingmachines/inkling-smallish:free",
    "cohere/north-mini-code:free",
    "google/gemini-3.5-flash-lite",
    "stepfun/step-5-preview-free",
])
def test_inkling_small_retirement_is_specific_to_exact_model(allowed):
    assert not excluded_from_owner_customer_selection(allowed)


def test_inkling_small_upstream_spoof_blocked_before_network():
    calls = []
    def unexpected(request):
        calls.append(request)
        raise AssertionError("retired model reached HTTP egress")
    async def call():
        return await call_platform_chat_completions(
            model_id="test-fixture/neutral-safe-id",
            upstream_model="thinkingmachines/inkling-small:free",
            provider="kilo",
            platform_provider_id="kilo",
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(unexpected),
        )
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call())
    assert calls == []


def test_google_selected_route_keeps_its_own_missing_key_gate(monkeypatch):
    google="google/gemini-3.1-flash-lite"
    assert excluded_from_owner_customer_selection(google) is False
    monkeypatch.delenv("PADIEM_GEMINI_API_KEY",raising=False)
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(google)
    assert exc.value.reason_code=="provider_secret_missing"
    assert exc.value.upstream_called is False


def test_separate_direct_poolside_is_not_inferred_owner_excluded():
    assert excluded_from_owner_customer_selection(POOLSIDE_MODEL_ID) is False
    # False here is NOT equivalent to verified customer approval.


@pytest.mark.parametrize("provider,upstream", [
    ("kilo", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("kilo", "poolside/laguna-s-2.1:free"),
    ("b-ai", "qwen3.8-flash"),
    ("infron", "motif/motif-3"),
    ("experiential", "gpt-5.6-luna"),
    ("kilo", "stepfun/step-3.7-flash"),
    ("stepfun", "stepfun/step-3.7-flash"),
])
def test_spoofed_safe_public_id_cannot_evoke_owner_excluded_upstream(
    provider,upstream,monkeypatch
):
    """No alias can execute an excluded provider/model tuple."""
    monkeypatch.setenv("PADIEM_GEMINI_API_KEY","synthetic_key_abcdefghij")
    calls=[]
    def unexpected(request):
        calls.append(request)
        raise AssertionError("excluded upstream was called")
    async def invoke():
        return await call_platform_chat_completions(
            model_id="test-fixture/neutral-safe-id",
            upstream_model=upstream,
            provider=provider,
            platform_provider_id=provider,
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(unexpected),
        )
    with pytest.raises(PilotNotConfigured):
        asyncio.run(invoke())
    assert calls==[]


def test_direct_poolside_upstream_not_implicitly_excluded():
    """Separate Poolside provider identity is not covered by Kilo exclusion."""
    from app.pilot.platform import _require_owner_allowed_live_model
    _require_owner_allowed_live_model(
        "poolside/laguna-s-2.1","poolside/laguna-s-2.1","poolside"
    )



def test_canonical_registry_model_tuples_keep_distinct_live_exclusion_gate():
    """Every actual enabled canonical model must be admitted by the OWNER
    exclusion *predicate* for its exact ID + upstream/provider tuple.

    This is NOT a credential, quota, entitlement or live provider readiness
    test. The 11-model set is loaded dynamically to preserve future append-only
    model onboarding and to avoid hardcoding yesterday's 9/10-model snapshots.
    """
    canonical = read_registry()
    assert canonical["models"]
    ids = set()
    for model in canonical["models"]:
        mid = model["id"]
        provider = model["provider_id"]
        upstream = model["upstream_model"]
        assert mid not in ids
        ids.add(mid)
        assert not excluded_from_owner_customer_selection(mid), mid
        _require_owner_allowed_live_model(mid, upstream, provider)


@pytest.mark.parametrize("provider,upstream", [
    ("kilo", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("kilo", "poolside/laguna-s-2.1:free"),
    ("b-ai", "qwen3.8-flash"),
    ("infron", "motif/motif-3"),
    ("experiential", "gpt-5.6-luna"),
    ("kilo", "stepfun/step-3.7-flash"),
])
def test_safe_looking_public_id_cannot_stream_excluded_upstream(provider, upstream):
    """A benign public alias must not bypass the last pre-network SSE guard.

    Every injected transport is fail-on-use and credentials remain untouched.
    """
    hits = []

    def unexpected(request):
        hits.append(request)
        raise AssertionError("excluded upstream sent an SSE network request")

    async def invoke():
        async for _ in stream_platform_chat_completions(
            model_id="test-fixture/neutral-safe-id",
            upstream_model=upstream,
            provider=provider,
            platform_provider_id=provider,
            messages=[{"role": "user", "content": "synthetic fixture"}],
            transport=httpx.MockTransport(unexpected),
        ):
            pass

    with pytest.raises(PilotNotConfigured):
        asyncio.run(invoke())
    assert hits == []


def test_non_excluded_qwen_provider_is_not_the_excluded_b_ai_identity():
    """Owner's B.AI Qwen exclusion must not cross to unrelated Kira Qwen."""
    _require_owner_allowed_live_model(
        "kira/qwen3.8-flash-free", "qwen3.8-flash-free", "kira"
    )
    # Passing this predicate never means the provider is ready or authorized.
