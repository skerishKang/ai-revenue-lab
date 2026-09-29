"""Padiem Plus text+image primary is Space Bunny Alpha (#3209).

Source-only contract:

- ordinary chat resolves to Padiem Plus -> kilo/stealth-space-bunny-alpha
  (Agnes and SenseNova are not the default).
- the Plus route carries the image capability, so an image request takes the
  existing MultimodalExecutionRuntime path (no second stack, no new gateway).
- provider/model identity stays out of user-facing errors.
"""

from __future__ import annotations

from pathlib import Path

from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    LOW_B14_MODEL_ID,
    MODEL_CAPABILITIES,
    model_supports,
    resolve_model_policy,
    resolve_tier_policy,
)
from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    active_route_for,
)

CLIENT_SOURCE = (Path(__file__).resolve().parents[1] / "app" / "b14_client.py").read_text(
    encoding="utf-8"
)


def test_plus_default_text_is_space_bunny() -> None:
    plus = active_route_for(ProductTierLabel.PLUS)
    assert plus is not None
    assert plus.model_id == "kilo/stealth-space-bunny-alpha"
    assert plus.provider_id == "kilo"
    assert plus.upstream_model == "stealth/space-bunny-alpha"

    assert LOW_B14_MODEL_ID == "kilo/stealth-space-bunny-alpha"
    assert DEFAULT_B14_MODEL_ID == "kilo/stealth-space-bunny-alpha"

    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert policy.model_id == "kilo/stealth-space-bunny-alpha"

    tier_policy = resolve_tier_policy(
        [{"role": "user", "content": "브라우저 등급 테스트"}], "plus"
    )
    assert tier_policy.model_id == "kilo/stealth-space-bunny-alpha"


def test_agnes_and_sensenova_are_not_the_default() -> None:
    assert LOW_B14_MODEL_ID != "agnes-ai/agnes-3.0-flash"
    assert LOW_B14_MODEL_ID != "sensenova/sensenova-6.8-flash-lite"
    assert DEFAULT_B14_MODEL_ID != "agnes-ai/agnes-3.0-flash"
    assert DEFAULT_B14_MODEL_ID != "sensenova/sensenova-6.8-flash-lite"


def test_plus_image_uses_the_existing_multimodal_stack() -> None:
    assert model_supports(LOW_B14_MODEL_ID, "image") is True
    assert "image" in MODEL_CAPABILITIES[LOW_B14_MODEL_ID]
    assert model_supports(LOW_B14_MODEL_ID, "video") is False

    # The existing Chat attachment path is reused: capability gate,
    # multimodal request/runtime, and the shared Core facade.
    assert 'if not model_supports(model, "image"):' in CLIENT_SOURCE
    assert "MultimodalExecutionRequest" in CLIENT_SOURCE
    assert "MultimodalExecutionRuntime" in CLIENT_SOURCE
    assert "_messages_with_attachment(" in CLIENT_SOURCE
    assert "B14MultimodalChatRequest" not in CLIENT_SOURCE

    # No second multimodal stack / gateway / transport is introduced here.
    for forbidden in (
        "SecondMultimodal",
        "NewImageGateway",
        "NewImageTransport",
        "image_gateway",
    ):
        assert forbidden not in CLIENT_SOURCE
