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
