"""#2505 stage 1: Chat and Claw read and update one shared grade setting.

The owner decision (2026-10-21) makes Chat and Claw two screens of one AI
product. The Free/Plus/Pro/Max assignment is therefore one setting: an
administrator write on either screen lands in the shared row, both surfaces
serve the same model, and an explicit policy OFF applies to both.

Recorder-only: no provider call, no PC call, no network egress.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.central_model_route_d1 import D1CentralModelRouteStore
from app.central_model_route_runtime import (
    chat_request_tier_context,
    resolve_claw_tier_model,
    resolve_tier_route,
)
from app.model_policy import resolve_request_model_policy
from kagent.p01_adapter import _agent_profile
from padiem_control_plane.model_assignment_policy import (
    CatalogModel,
    ModelChange,
    ModelPolicySnapshot,
)
from padiem_control_plane.model_tier_routes import (
    TierRoute,
    TierRouteChange,
    TierRouteSnapshot,
)
from padiem_control_plane.product_tier_routes import ProductTierLabel
from test_4428_central_tier_routes_261019 import (
    ALPHA,
    BETA,
    FakeD1,
    PolicyStore,
    RouteStore,
    built_app,
    call,
    commit,
    request_state,
)

TIERS = ("FREE", "PLUS", "PRO", "MAX")
TIER_IDS = {"FREE": "free", "PLUS": "plus", "PRO": "pro", "MAX": "max"}
MESSAGES = [{"role": "user", "content": "안녕하세요"}]


def _shared_snapshot(tier="FREE", primary=ALPHA, fallback=BETA):
    return TierRouteSnapshot("padiem-global", 3, (
        TierRoute("chat", tier, primary, fallback, True),
    ))


def test_both_surfaces_serve_the_same_model_for_every_grade():
    for tier in TIERS:
        routes = RouteStore(_shared_snapshot(tier))
        state = request_state(routes=routes)
        chat = asyncio.run(resolve_tier_route(
            state, product="chat", tier=tier, static_primary="google/static",
        ))
        claw = asyncio.run(resolve_tier_route(
            state, product="claw", tier=tier, static_primary="google/static",
        ))
        assert (chat.ok, chat.model_id, chat.fallback_model_id) == (True, ALPHA, BETA)
        assert (claw.ok, claw.model_id, claw.fallback_model_id) == (True, ALPHA, BETA)
        assert chat.model_id == claw.model_id


def test_the_chat_dispatch_model_and_the_claw_b14_profile_carry_the_same_model():
    """The shared setting reaches the actual B14 selection on both surfaces."""
    routes = RouteStore(_shared_snapshot("FREE"))
    state = request_state(routes=routes)

    async def _chat_dispatch_model():
        async with chat_request_tier_context(state, "free"):
            return resolve_request_model_policy(MESSAGES)

    policy = asyncio.run(_chat_dispatch_model())
    assert policy.model_id == ALPHA

    claw_route = asyncio.run(resolve_claw_tier_model(state, "free"))
    assert claw_route.ok and claw_route.model_id == ALPHA
    profile = _agent_profile(
        ProductTierLabel.FREE, central_route_model_id=claw_route.model_id,
    )
    assert profile.model_policy["model"] == ALPHA
    assert profile.model_policy["product_tier"] == "free"


def test_an_administrator_write_on_the_claw_screen_serves_the_chat_screen():
    store = D1CentralModelRouteStore(FakeD1())
    commit(store, [TierRouteChange("claw", "FREE", "set", ALPHA, BETA, True)], 0)

    snapshot = asyncio.run(store.snapshot("padiem-global"))
    assert [row.key for row in snapshot.routes] == [("chat", "FREE")]
    assert snapshot.lookup("chat", "FREE").primary_model_id == ALPHA

    state = request_state(routes=RouteStore(snapshot))
    for product in ("chat", "claw"):
        resolution = asyncio.run(resolve_tier_route(
            state, product=product, tier="FREE", static_primary="google/static",
        ))
        assert (resolution.ok, resolution.model_id) == (True, ALPHA)


def test_the_admin_view_reports_one_shared_grade_setting():
    store = D1CentralModelRouteStore(FakeD1())
    commit(store, [TierRouteChange("claw", "FREE", "set", ALPHA, BETA, True)], 0)
    app, settings = built_app(store=store)

    response = call(app, settings, "GET", "/api/admin/models/routes")

    assert response.status_code == 200
    rows = response.json()["routes"]
    assert [(row["product"], row["tier"]) for row in rows] == [("chat", "FREE")]
    assert rows[0]["primary_model_id"] == ALPHA


def test_an_explicit_policy_off_applies_to_both_screens():
    routes = RouteStore(_shared_snapshot("FREE"))
    central_off = PolicyStore(ModelPolicySnapshot("padiem-global", 1, (
        ModelChange("central", "FREE", ALPHA, "block"),
    )))
    for product in ("chat", "claw"):
        resolution = asyncio.run(resolve_tier_route(
            request_state(routes=routes, policy=central_off),
            product=product, tier="FREE", static_primary="google/static",
        ))
        # The blocked primary falls back to the row's own configured fallback,
        # never to a wider model set.
        assert (resolution.ok, resolution.model_id) == (True, BETA)

    # A product-scoped OFF on one screen is an OFF on the shared setting.
    screen_off = PolicyStore(ModelPolicySnapshot("padiem-global", 1, (
        ModelChange("chat", "FREE", ALPHA, "block"),
    )))
    for product in ("chat", "claw"):
        resolution = asyncio.run(resolve_tier_route(
            request_state(routes=routes, policy=screen_off),
            product=product, tier="FREE", static_primary="google/static",
        ))
        assert (resolution.ok, resolution.model_id) == (True, BETA)

    # Lifting the OFF restores the shared model on both screens.
    lifted = PolicyStore(ModelPolicySnapshot("padiem-global", 2, ()))
    for product in ("chat", "claw"):
        resolution = asyncio.run(resolve_tier_route(
            request_state(routes=routes, policy=lifted),
            product=product, tier="FREE", static_primary="google/static",
        ))
        assert (resolution.ok, resolution.model_id) == (True, ALPHA)


def test_another_product_keeps_its_own_independent_grade_setting():
    routes = RouteStore(TierRouteSnapshot("padiem-global", 1, (
        TierRoute("b66", "FREE", ALPHA, None, True),
    )))
    state = request_state(routes=routes)
    b66 = asyncio.run(resolve_tier_route(
        state, product="b66", tier="FREE", static_primary="google/static",
    ))
    shared = asyncio.run(resolve_tier_route(
        state, product="chat", tier="FREE", static_primary="google/static",
    ))
    assert (b66.ok, b66.model_id) == (True, ALPHA)
    assert (shared.ok, shared.model_id, shared.source) == (
        True, "google/static", "static",
    )


def test_a_free_candidate_is_never_bound_to_the_shared_grade():
    free_model = "opencode-go/longcat-2.5-preview-free"
    catalog = dict({
        model_id: CatalogModel(model_id, True, True, True, True, frozenset({"chat"}))
        for model_id in (ALPHA, BETA, free_model)
    })
    from app.central_model_route_d1 import _error
    from padiem_control_plane.contracts import ControlPlaneContractError
    from padiem_control_plane.model_tier_routes import _check_route_changes

    with pytest.raises(ControlPlaneContractError) as exc:
        _check_route_changes(
            (TierRouteChange("chat", "FREE", "set", free_model, None, True),), catalog,
        )
    assert exc.value.code == "model_route_free_candidate"
