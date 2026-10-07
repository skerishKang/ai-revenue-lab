"""Padiem Plus successor contract (#3568 -> #3579 policy v2).

Space Bunny remains historical provider metadata only. The owner selected the
Ling 3.1 Flash successor for the Plus text lane; vision/image remains without
an executable route and capability claims stay conservative until proven.
"""

from __future__ import annotations

import pytest

from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    EXECUTABLE_B14_MODEL_IDS,
    LOW_B14_MODEL_ID,
    MODEL_CAPABILITIES,
    ModelPolicyError,
    model_policy_is_executable,
    model_supports,
    resolve_model_policy,
    resolve_tier_policy,
)
from padiem_control_plane.product_tier_routes import (
    PLUS_HOLD_MODEL_ID,
    ProductRouteStatus,
    ProductTierLabel,
    active_route_for,
    get_tier,
)


def test_plus_identity_is_executable_successor_and_bunny_is_historical() -> None:
    plus_route = active_route_for(ProductTierLabel.PLUS)
    assert plus_route is not None
    assert plus_route.model_id == LOW_B14_MODEL_ID == DEFAULT_B14_MODEL_ID
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({LOW_B14_MODEL_ID})

    plus_routes = get_tier(ProductTierLabel.PLUS).routes
    bunny = next(
        route for route in plus_routes
        if route.model_id == "kilo/stealth-space-bunny-alpha"
    )
    assert bunny.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
    assert bunny.hold_reason and "#3568" in bunny.hold_reason


def test_plus_capability_claims_stay_conservative_and_held_tiers_fail_closed() -> None:
    assert MODEL_CAPABILITIES[LOW_B14_MODEL_ID] == frozenset()
    assert model_supports(LOW_B14_MODEL_ID, "chat") is False
    assert model_supports(LOW_B14_MODEL_ID, "image") is False

    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert policy.model_id == LOW_B14_MODEL_ID
    assert model_policy_is_executable(policy.model_id) is True

    with pytest.raises(ModelPolicyError) as tier:
        resolve_tier_policy(
            [{"role": "user", "content": "브라우저 등급 테스트"}],
            "pro",
        )
    assert tier.value.code == "tier_unavailable"


def test_plus_product_identity_resolves_to_executable_successor() -> None:
    policy = resolve_model_policy(
        [{"role": "user", "content": "안녕하세요"}],
        require_executable=False,
    )
    assert policy.model_id == LOW_B14_MODEL_ID
    assert model_policy_is_executable(policy.model_id) is True
