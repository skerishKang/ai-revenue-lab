"""Padiem Plus split-role contract (#3568 hold, #3554 text selection).

Space Bunny remains historical provider metadata only and is never executable.
Owner decision 2026-10-07 (#3554) selected Agnes 3.0 Flash for the Plus TEXT
role, so text dispatches while the VISION role stays unselected: image work must
keep failing closed on capability, not on the absence of any model.
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


def test_plus_identity_is_text_selected_and_space_bunny_is_historical_only() -> None:
    route = active_route_for(ProductTierLabel.PLUS)
    assert route is not None
    assert route.model_id == DEFAULT_B14_MODEL_ID == LOW_B14_MODEL_ID
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({LOW_B14_MODEL_ID})

    plus_routes = get_tier(ProductTierLabel.PLUS).routes
    bunny = next(
        route for route in plus_routes
        if route.model_id == "kilo/stealth-space-bunny-alpha"
    )
    assert bunny.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
    assert bunny.hold_reason and "#3568" in bunny.hold_reason
    # The Plus hold sentinel survives as data-only history for the unselected
    # vision role; it is no longer what Plus text resolves to.
    sentinel = next(r for r in plus_routes if r.model_id == PLUS_HOLD_MODEL_ID)
    assert sentinel.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
    assert LOW_B14_MODEL_ID != PLUS_HOLD_MODEL_ID


def test_plus_text_dispatches_while_image_stays_held() -> None:
    assert MODEL_CAPABILITIES[LOW_B14_MODEL_ID] == frozenset({"chat"})
    assert model_supports(LOW_B14_MODEL_ID, "chat") is True
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert policy.model_id == LOW_B14_MODEL_ID

    # VISION is still unselected: the lane claims no image capability, so the
    # image path fails closed on capability rather than on an unselected model.
    assert model_supports(LOW_B14_MODEL_ID, "image") is False
    with pytest.raises(ModelPolicyError) as tier:
        resolve_tier_policy(
            [{"role": "user", "content": "브라우저 등급 테스트"}],
            "pro",
        )
    assert tier.value.code == "tier_unavailable"


def test_plus_product_identity_resolves_from_the_selected_text_route() -> None:
    policy = resolve_model_policy(
        [{"role": "user", "content": "안녕하세요"}],
        require_executable=False,
    )
    assert policy.model_id == LOW_B14_MODEL_ID
    assert model_policy_is_executable(policy.model_id) is True
