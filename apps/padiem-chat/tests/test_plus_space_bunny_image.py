"""Padiem Plus successor-pending hold contract (#3568).

Space Bunny remains historical provider metadata only. Padiem Plus keeps its
product identity but has no executable text/image model until the owner selects
and proves a successor.
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


def test_plus_identity_is_hold_and_space_bunny_is_historical_only() -> None:
    assert active_route_for(ProductTierLabel.PLUS) is None
    assert LOW_B14_MODEL_ID == DEFAULT_B14_MODEL_ID == PLUS_HOLD_MODEL_ID
    assert EXECUTABLE_B14_MODEL_IDS == frozenset()

    plus_routes = get_tier(ProductTierLabel.PLUS).routes
    bunny = next(
        route for route in plus_routes
        if route.model_id == "kilo/stealth-space-bunny-alpha"
    )
    assert bunny.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
    assert bunny.hold_reason and "#3568" in bunny.hold_reason


def test_plus_chat_and_image_fail_before_b14_until_successor_selection() -> None:
    assert MODEL_CAPABILITIES[LOW_B14_MODEL_ID] == frozenset()
    assert model_supports(LOW_B14_MODEL_ID, "chat") is False
    assert model_supports(LOW_B14_MODEL_ID, "image") is False

    with pytest.raises(ModelPolicyError) as chat:
        resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert chat.value.code == "tier_unavailable"

    with pytest.raises(ModelPolicyError) as tier:
        resolve_tier_policy(
            [{"role": "user", "content": "브라우저 등급 테스트"}],
            "plus",
        )
    assert tier.value.code == "tier_unavailable"


def test_plus_product_identity_can_be_resolved_without_execution() -> None:
    policy = resolve_model_policy(
        [{"role": "user", "content": "안녕하세요"}],
        require_executable=False,
    )
    assert policy.model_id == PLUS_HOLD_MODEL_ID
    assert model_policy_is_executable(policy.model_id) is False
