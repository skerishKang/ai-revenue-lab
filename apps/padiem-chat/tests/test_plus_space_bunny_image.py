"""Current owner four-tier routes with historic Space Bunny metadata.

Original Plus-hold tests predated the owner decisions that made Beam Free the
Free primary and Muse Spark the Plus/Pro/Max primary.
Do not re-enable historical Space Bunny or image execution.
"""
from __future__ import annotations

from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    EXECUTABLE_B14_MODEL_IDS,
    LOW_B14_MODEL_ID,
    MODEL_CAPABILITIES,
    model_policy_is_executable,
    model_supports,
    resolve_model_policy,
    resolve_tier_policy,
)
from padiem_control_plane.product_tier_routes import (
    ProductRouteStatus,
    ProductTierLabel,
    active_route_for,
    get_tier,
)

BEAM = "opencode-go/beam-free"
MUSE = "opencode-go/muse-spark-1.3-contributor"


def test_plus_identity_is_executable_muse_and_space_bunny_is_historical_only() -> None:
    plus = active_route_for(ProductTierLabel.PLUS)
    assert plus is not None
    assert plus.status is ProductRouteStatus.EXECUTABLE
    assert plus.model_id == LOW_B14_MODEL_ID == MUSE
    assert DEFAULT_B14_MODEL_ID == BEAM
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({BEAM, MUSE})
    bunny = next(
        route for route in get_tier(ProductTierLabel.PLUS).routes
        if route.model_id == "kilo/stealth-space-bunny-alpha"
    )
    assert bunny.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
    assert bunny.hold_reason and "#3568" in bunny.hold_reason


def test_plus_chat_executes_muse_and_image_remains_unavailable() -> None:
    assert MODEL_CAPABILITIES[LOW_B14_MODEL_ID] == frozenset({"chat", "coding"})
    assert model_supports(LOW_B14_MODEL_ID, "chat")
    assert not model_supports(LOW_B14_MODEL_ID, "image")
    default = resolve_model_policy([{"role": "user", "content": "hello"}])
    plus = resolve_tier_policy([{"role": "user", "content": "hello"}], "plus")
    assert default.model_id == BEAM and default.profile == "free"
    assert plus.model_id == MUSE and plus.profile == "low"


def test_plus_product_identity_matches_current_executable_route() -> None:
    policy = resolve_model_policy(
        [{"role": "user", "content": "hello"}],
        require_executable=False,
    )
    assert policy.model_id == BEAM
    assert model_policy_is_executable(policy.model_id)
