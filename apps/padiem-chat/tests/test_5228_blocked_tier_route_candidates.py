"""#5228: explicit model blocks apply to central, static and outage routes.

This suite is intentionally synthetic: no network, provider dispatch, secrets,
or database mutation. It proves the selected model/fallback candidates are
filtered before the product execution path consumes them.
"""
from __future__ import annotations

import asyncio

import pytest

from app.central_model_route_runtime import resolve_tier_route_view_from_stores
from padiem_control_plane.model_assignment_policy import ModelChange, ModelPolicySnapshot
from padiem_control_plane.model_tier_routes import (
    TierRoute, TierRouteSnapshot, effective_tier_route, static_tier_route,
)

WORKSPACE = "padiem-global"
PRIMARY = "google/test-5228-primary"
FALLBACK = "google/test-5228-fallback"


class Store:
    def __init__(self, value):
        self.value = value

    def snapshot(self, workspace_id):
        assert workspace_id == WORKSPACE
        return self.value


class FailedStore:
    def snapshot(self, workspace_id):
        raise RuntimeError("simulated route ledger read failure")


def block(*ids):
    return ModelPolicySnapshot(
        WORKSPACE, 2,
        tuple(ModelChange("chat", "FREE", model_id, "block") for model_id in ids),
    )


@pytest.mark.parametrize(
    "blocked,expected_primary,expected_fallback",
    [
        (frozenset(), PRIMARY, FALLBACK),
        (frozenset({FALLBACK}), PRIMARY, None),
        (frozenset({PRIMARY}), FALLBACK, None),
        (frozenset({PRIMARY, FALLBACK}), None, None),
    ],
)
def test_central_route_never_returns_a_blocked_candidate(
    blocked, expected_primary, expected_fallback,
):
    snapshot = TierRouteSnapshot(
        WORKSPACE, 4, (TierRoute("chat", "FREE", PRIMARY, FALLBACK, True),),
    )
    result = effective_tier_route(
        snapshot, workspace_id=WORKSPACE, product="chat", tier="FREE",
        static_primary=PRIMARY, static_fallback=FALLBACK,
        blocked_model_ids=blocked,
    )
    assert (result.model_id, result.fallback_model_id) == (
        expected_primary, expected_fallback,
    )
    assert result.ok is (expected_primary is not None)
    assert result.source == "central"
    assert all(candidate not in blocked for candidate in (
        result.model_id, result.fallback_model_id,
    ) if candidate is not None)


@pytest.mark.parametrize(
    "blocked,expected_primary,expected_fallback",
    [
        (frozenset(), PRIMARY, FALLBACK),
        (frozenset({FALLBACK}), PRIMARY, None),
        (frozenset({PRIMARY}), FALLBACK, None),
        (frozenset({PRIMARY, FALLBACK}), None, None),
    ],
)
@pytest.mark.parametrize("snapshot", [
    None,
    TierRouteSnapshot(WORKSPACE, 7, ()),
])
def test_static_route_missing_row_filters_both_candidates(
    blocked, expected_primary, expected_fallback, snapshot,
):
    result = effective_tier_route(
        snapshot, workspace_id=WORKSPACE, product="chat", tier="FREE",
        static_primary=PRIMARY, static_fallback=FALLBACK,
        blocked_model_ids=blocked,
    )
    assert (result.model_id, result.fallback_model_id, result.source) == (
        expected_primary, expected_fallback, "static",
    )
    assert result.ok is (expected_primary is not None)


def test_static_unavailable_stays_unavailable_even_with_fallback():
    result = static_tier_route(
        None, FALLBACK, blocked_model_ids=frozenset(),
    )
    assert result.ok is False
    assert result.model_id is None


@pytest.mark.parametrize(
    "route_state",
    [
        None,
        FailedStore(),
        Store(TierRouteSnapshot(WORKSPACE, 9, ())),
    ],
)
def test_store_resolver_applies_readable_policy_when_route_store_is_missing(route_state):
    route_store = route_state
    result, revision = asyncio.run(resolve_tier_route_view_from_stores(
        route_store, Store(block(FALLBACK)),
        product="chat", tier="FREE",
        static_primary=PRIMARY, static_fallback=FALLBACK,
    ))
    assert result.ok is True
    assert result.model_id == PRIMARY
    assert result.fallback_model_id is None
    assert result.source == "static"
    assert revision == 0


def test_store_resolver_uses_allowed_fallback_if_primary_is_blocked():
    result, revision = asyncio.run(resolve_tier_route_view_from_stores(
        FailedStore(), Store(block(PRIMARY)),
        product="chat", tier="FREE",
        static_primary=PRIMARY, static_fallback=FALLBACK,
    ))
    assert (result.ok, result.model_id, result.fallback_model_id, revision) == (
        True, FALLBACK, None, 0,
    )


def test_store_resolver_blocks_both_candidates_if_policy_is_readable():
    result, revision = asyncio.run(resolve_tier_route_view_from_stores(
        Store(TierRouteSnapshot(WORKSPACE, 8, ())),
        Store(block(PRIMARY, FALLBACK)),
        product="chat", tier="FREE",
        static_primary=PRIMARY, static_fallback=FALLBACK,
    ))
    assert (result.ok, result.model_id, result.fallback_model_id, revision) == (
        False, None, None, 0,
    )


def test_no_policy_store_preserves_existing_static_route():
    result, revision = asyncio.run(resolve_tier_route_view_from_stores(
        None, None, product="chat", tier="FREE",
        static_primary=PRIMARY, static_fallback=FALLBACK,
    ))
    assert (result.ok, result.model_id, result.fallback_model_id, revision) == (
        True, PRIMARY, FALLBACK, 0,
    )
