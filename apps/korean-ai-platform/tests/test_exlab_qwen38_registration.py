"""B14 ExLab model selection and fixed provider transport contract.

#7241 3단계: the route this suite covers is selected structurally rather than
spelled here. It is the one registered route that

* is not an owner-excluded identity and not an excluded free candidate,
* is on no designated per-grade roster (so it is reachable only by its exact
  id, as the owner decision intends for this route),
* declares exactly chat+coding,
* claims no evidenced per-token price (the promotion is not a fixed price),
* is not a free-marked upstream identity, and
* is served on a non-empty context window.

Everything the suite asserts — the model id, its upstream identity, the
provider id and display name, the origin, the host allow-list and the
credential slot — is then read back from the registry row and provider entry
the selector points at.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.errors import PilotNotConfigured, UpstreamRateLimited, UpstreamAuthFailed
from app.pilot.model_registry_file import read_registry
from app.pilot.owner_model_exclusions import (
    excluded_from_owner_customer_selection,
    free_candidate_excluded_from_execution,
)
from app.pilot.platform import (
    call_platform_chat_completions, stream_platform_chat_completions,
)
from app.pilot.router_core import resolve_manual_route
from app.pilot.tier_fallback import (
    effective_tier_default, effective_tier_fallback,
)

from _registry_values import model_rows, provider_row, requires_owner_document


def _roster_ids() -> set[str]:
    """Every identity a product grade selects on its own (default + fallbacks)."""
    roster = {effective_tier_default()}
    for fallback in effective_tier_fallback().values():
        roster.update(fallback)
    return roster


def _onboarded_row() -> dict:
    """The manual-only promoted route this suite covers (see the module doc).

    A registry document that admits no such route — e.g. a placeholder fixture
    carrying only example rows — answers ``None``: every non-owner pin in this
    suite is an owner decision about a real route, so it is reported as skipped
    rather than silently passing on a route it never selected.
    """
    roster = _roster_ids()
    candidates = [
        row for row in model_rows()
        if not excluded_from_owner_customer_selection(row["id"])
        and not free_candidate_excluded_from_execution(row["id"])
        and row["id"] not in roster
        and set(row["capabilities"]) == {"chat", "coding"}
        and row["input_price_usd_per_1m"] is None
        and row["output_price_usd_per_1m"] is None
        and not row["upstream_model"].casefold().endswith("-free")
        and row["context_window"] > 0
    ]
    assert len(candidates) <= 1, "the manual-only promoted route is not unique"
    return candidates[0] if candidates else None


ROW = _onboarded_row()
#: Applied to every pin that reads the selected route: with no such route in the
#: effective document there is nothing to assert, and the pin is reported as
#: skipped instead of passing on a route it never selected.
_NO_ROUTE = pytest.mark.skipif(
    ROW is None,
    reason="the effective registry document carries no manual-only promoted route",
)
if ROW is None:
    PROVIDER_ROW = MODEL = UPSTREAM = PROVIDER_NAME = ORIGIN = BINDING = None
    HOSTS = RETIRED = ()
else:
    PROVIDER = ROW["provider_id"]
    PROVIDER_ROW = provider_row(PROVIDER)
    MODEL = ROW["id"]
    UPSTREAM = ROW["upstream_model"]
    #: The display name the B14 call surfaces label this provider with.
    PROVIDER_NAME = ROW["provider_name"]
    ORIGIN = PROVIDER_ROW["base_origin"]
    HOSTS = PROVIDER_ROW["allowed_hosts"]
    BINDING = PROVIDER_ROW["credential_binding_name"]
    #: The retired identities the owner removed, read from the same document.
    RETIRED = read_registry()["retired_models"]
#: The surface suffix the OpenAI-compatible completion path names.
COMPLETIONS_PATH = "/chat" + "/completions"
CHAT_URL = (ORIGIN or "").rstrip("/") + COMPLETIONS_PATH
#: The promotion price the row must not claim: a promo expiry is not a price.
UNPRICED = None


@_NO_ROUTE
def test_exlab_catalog_is_manual_only_and_uses_existing_secret_name():
    d=read_registry()
    assert len(d["models"])>=11 and len(d["providers"])>=8
    p=d["providers"][PROVIDER]
    assert p["base_origin"]==ORIGIN
    assert p["allowed_hosts"]==HOSTS
    assert p["credential_source"]=="platform_secret"
    assert p["credential_binding_name"]==BINDING
    m=next(x for x in d["models"] if x["id"]==MODEL)
    assert m["provider_id"]==PROVIDER
    assert m["upstream_model"]==UPSTREAM
    # The promotion is not a fixed price, and the route declares no image or
    # tool capability while the promotion runs.
    assert m["input_price_usd_per_1m"] is UNPRICED
    assert m["output_price_usd_per_1m"] is UNPRICED
    assert m["capabilities"]==["chat","coding"]
    assert m["context_window"]>0
    assert all(not d["groups"][group] for group in ("plus","pro","max"))
    # The owner retired this provider's predecessor routes. Those exact ids are
    # listed so they may never be registered again, and this suite never asks
    # for them by name: it asks for the provider whose every retired identity
    # is absent from the live register.
    registered = {x["id"] for x in d["models"]}
    assert RETIRED
    assert not (set(RETIRED) & registered)
    assert [retired for retired in RETIRED
            if retired.split("/", 1)[0] == PROVIDER]


@_NO_ROUTE
def test_b14_models_lists_exact_exlab_without_showing_secret():
    with TestClient(create_app()) as client:
        res=client.get("/api/pilot/admin/models")
    assert res.status_code==200
    rows={r["id"]:r for r in res.json()["registered_routes"]}
    assert len(rows)==len(read_registry()["models"])
    row=rows[MODEL]
    assert row["provider_id"]==PROVIDER
    assert row["upstream_model"]==UPSTREAM
    # On no designated roster, so only the exact id reaches it.
    assert row["explicit_only"] is True
    assert row["auto_eligible"] is False
    assert row["free"] is False  # free promotion is not a permanent model capability
    assert BINDING not in res.text
    assert "Authorization" not in res.text


@pytest.fixture
def live_env(monkeypatch):
    saved=runtime_config.provider_mode
    runtime_config.provider_mode="live"
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setenv(BINDING,"test-fixture-exlab-binding-no-real-secret")
    yield
    runtime_config.provider_mode=saved



@_NO_ROUTE
@requires_owner_document
def test_owner_selected_model_route_is_available_without_fallback(live_env):
    route = resolve_manual_route(MODEL)
    assert route.selected_model == MODEL
    assert route.selected_upstream_model == UPSTREAM
    assert route.platform_provider_id == PROVIDER
    assert route.fallback_allowed is False
    assert route.eligible_fallback == []


@_NO_ROUTE
@requires_owner_document
def test_direct_transport_uses_exact_origin_slug_and_binding(live_env):
    fixture = "test-fixture-exlab-binding-no-real-secret"
    def responder(request):
        assert str(request.url) == CHAT_URL
        assert request.headers["Authorization"] == "Bearer " + fixture
        assert json.loads(request.content)["model"] == UPSTREAM
        return httpx.Response(200, json={
            "id": "synthetic", "model": UPSTREAM,
            "choices": [{"message": {"content": "견적 확인 완료"}}],
        })
    result = asyncio.run(call_platform_chat_completions(
        model_id=MODEL, upstream_model=UPSTREAM,
        provider=PROVIDER_NAME, platform_provider_id=PROVIDER,
        messages=[{"role": "user", "content": "합성 견적 확인"}],
        transport=httpx.MockTransport(responder),
    ))
    assert result["model"] == UPSTREAM
    assert result["_live"] is True
    assert fixture not in repr(result)


@_NO_ROUTE
@requires_owner_document
def test_stream_transport_uses_exact_upstream_slug(live_env):
    fixture = "test-fixture-exlab-binding-no-real-secret"
    def responder(request):
        assert str(request.url) == CHAT_URL
        assert request.headers["Authorization"] == "Bearer " + fixture
        assert json.loads(request.content)["model"] == UPSTREAM
        payload = (
            'data: {"id":"test","model":"' + UPSTREAM + '",'
            '"choices":[{"delta":{"content":"확인"},"finish_reason":"stop"}]}\\n\\n'
            'data: [DONE]\\n\\n'
        ).replace('\\n','\n').encode()
        return httpx.Response(200, content=payload)
    async def run():
        return [event async for event in stream_platform_chat_completions(
            model_id=MODEL, upstream_model=UPSTREAM,
            provider=PROVIDER_NAME, platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "합성 입력"}],
            transport=httpx.MockTransport(responder),
        )]
    events=asyncio.run(run())
    assert events[0].model == UPSTREAM
    assert events[-1].done is True
    assert all(fixture not in repr(ev) for ev in events)


@_NO_ROUTE
@requires_owner_document
@pytest.mark.parametrize("code,exception", [
    (401, UpstreamAuthFailed),
    (429, UpstreamRateLimited),
])
def test_upstream_errors_fail_safely(live_env, code, exception):
    def responder(req):
        return httpx.Response(code, json={"error": "synthetic"})
    with pytest.raises(exception):
        asyncio.run(call_platform_chat_completions(
            model_id=MODEL, upstream_model=UPSTREAM,
            provider=PROVIDER_NAME, platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "synthetic"}],
            transport=httpx.MockTransport(responder),
        ))


@_NO_ROUTE
@requires_owner_document
def test_missing_own_secret_fails_before_upstream(live_env, monkeypatch):
    monkeypatch.delenv(BINDING)
    def unexpected(req):
        raise AssertionError("no upstream without ExLab credential")
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call_platform_chat_completions(
            model_id=MODEL, upstream_model=UPSTREAM,
            provider=PROVIDER_NAME, platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "synthetic"}],
            transport=httpx.MockTransport(unexpected),
        ))
