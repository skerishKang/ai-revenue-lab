from __future__ import annotations

from pathlib import Path

import pytest

from app import model_policy as model_policy_module
from app.model_policy import (
    AUTO_B14_MODEL_ID,
    DEFAULT_B14_MODEL_ID,
    DEFAULT_CHAT_PROFILE,
    EXECUTABLE_B14_MODEL_IDS,
    HIGH_B14_MODEL_ID,
    KILO_B14_MODEL_ID,
    LOW_B14_MODEL_ID,
    MAX_HOLD_MODEL_ID,
    MEDIUM_B14_MODEL_ID,
    MODEL_ALIASES,
    MODEL_CAPABILITIES,
    PADIEM_MAX,
    PADIEM_PLUS,
    PADIEM_PRO,
    PRODUCT_TIER_NAMES,
    PROFILE_MODEL_IDS,
    RETIRED_B14_MODEL_IDS,
    UNASSIGNED_B14_MODEL_ID,
    ModelPolicyError,
    model_policy_is_executable,
    model_profile_is_assigned,
    model_supports,
    product_tier_name,
    request_tier_context,
    resolve_model_policy,
    resolve_request_model_policy,
    resolve_tier_policy,
)
from padiem_control_plane.product_tier_routes import (
    MAX_HOLD_MODEL_ID as CONTRACT_MAX_HOLD_MODEL_ID,
    PLUS_HOLD_MODEL_ID as CONTRACT_PLUS_HOLD_MODEL_ID,
    PRO_HOLD_MODEL_ID as CONTRACT_PRO_HOLD_MODEL_ID,
    ProductTierLabel,
    active_route_for,
)


def test_three_product_tier_identities_with_plus_text_selected_and_others_holding() -> None:
    policy = resolve_model_policy(
        [{"role": "user", "content": "안녕하세요"}],
        require_executable=False,
    )
    plus_route = active_route_for(ProductTierLabel.PLUS)
    assert plus_route is not None

    assert DEFAULT_CHAT_PROFILE == "low"
    assert LOW_B14_MODEL_ID == plus_route.model_id
    assert MEDIUM_B14_MODEL_ID == CONTRACT_PRO_HOLD_MODEL_ID
    assert MAX_HOLD_MODEL_ID == CONTRACT_MAX_HOLD_MODEL_ID
    assert HIGH_B14_MODEL_ID == MAX_HOLD_MODEL_ID
    assert KILO_B14_MODEL_ID == MEDIUM_B14_MODEL_ID
    assert PROFILE_MODEL_IDS == {
        "low": LOW_B14_MODEL_ID,
        "medium": MEDIUM_B14_MODEL_ID,
        "high": HIGH_B14_MODEL_ID,
    }
    assert PRODUCT_TIER_NAMES == {
        LOW_B14_MODEL_ID: PADIEM_PLUS,
        MEDIUM_B14_MODEL_ID: PADIEM_PRO,
        HIGH_B14_MODEL_ID: PADIEM_MAX,
    }
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({LOW_B14_MODEL_ID})
    assert DEFAULT_B14_MODEL_ID == LOW_B14_MODEL_ID
    assert policy.model_id == LOW_B14_MODEL_ID
    assert policy.profile == "low"
    assert product_tier_name(policy.model_id) == PADIEM_PLUS
    assert model_profile_is_assigned(policy.model_id) is True
    assert model_policy_is_executable(policy.model_id) is True


def test_ordinary_chat_resolves_the_selected_plus_text_route() -> None:
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert policy.model_id == LOW_B14_MODEL_ID
    assert policy.profile == "low"


def test_plus_alias_preserves_product_identity_and_is_now_executable() -> None:
    policy = resolve_model_policy(
        [{"role": "user", "content": "/plus 테스트 질문입니다"}],
        require_executable=False,
    )
    assert MODEL_ALIASES["/plus"] == LOW_B14_MODEL_ID
    assert policy.model_id == LOW_B14_MODEL_ID
    assert policy.profile == "low"
    assert policy.alias == "/plus"
    assert policy.messages[-1] == {"role": "user", "content": "테스트 질문입니다"}
    assert product_tier_name(policy.model_id) == PADIEM_PLUS
    assert model_policy_is_executable(policy.model_id) is True


def test_unselected_tier_aliases_still_fail_closed_before_b14() -> None:
    for alias in ("/pro", "/max"):
        with pytest.raises(ModelPolicyError) as info:
            resolve_model_policy([{"role": "user", "content": f"{alias} 질문"}])
        assert info.value.code == "tier_unavailable", alias
        assert "준비 중" in info.value.message, alias


def test_legacy_kilo_alias_remains_non_executable_compatibility_identity() -> None:
    assert MODEL_ALIASES["/kilo"] == MEDIUM_B14_MODEL_ID
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/kilo 질문"}])
    assert info.value.code == "tier_unavailable"


def test_poolside_alias_is_not_a_fallback() -> None:
    assert "/poolside" not in MODEL_ALIASES
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/poolside 질문"}])
    assert info.value.code == "unknown_model_alias"
    # The Plus text selection must not silently widen the executable set: only
    # the selected Plus lane is dispatchable, and Poolside stays outside it.
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({LOW_B14_MODEL_ID})
    assert model_policy_is_executable("poolside/laguna-s-2.1") is False


@pytest.mark.parametrize("alias", ["/agnes", "/openrouter", "/claude", "/gemini"])
def test_other_provider_aliases_fail_closed_before_b14(alias: str) -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": f"{alias} 질문"}])
    assert info.value.code == "unknown_model_alias"


def test_unknown_alias_fails_closed_without_provider_hint() -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/unknown 질문"}])
    assert info.value.code == "unknown_model_alias"
    message = info.value.message.lower()
    for hidden_name in ("poolside", "nvidia", "tencent", "kilo", "nemotron", "hy3", "laguna"):
        assert hidden_name not in message


def test_explicit_alias_without_prompt_fails_before_availability_check() -> None:
    for alias in ("/plus", "/pro", "/max", "/kilo"):
        with pytest.raises(ModelPolicyError) as info:
            resolve_model_policy([{"role": "user", "content": alias}])
        assert info.value.code == "model_alias_requires_prompt"


def test_hold_identities_claim_no_capabilities_and_plus_claims_text_only() -> None:
    for model_id in (
        MEDIUM_B14_MODEL_ID,
        HIGH_B14_MODEL_ID,
        AUTO_B14_MODEL_ID,
        UNASSIGNED_B14_MODEL_ID,
    ):
        assert MODEL_CAPABILITIES[model_id] == frozenset()
        assert model_supports(model_id, "chat") is False
        assert model_supports(model_id, "image") is False
        assert model_supports(model_id, "free") is False

    # #3554 fills the TEXT role only. The Plus lane must therefore claim "chat"
    # and must never claim "image": the unselected vision role stays enforced by
    # this capability absence, not by an empty model id.
    assert MODEL_CAPABILITIES[LOW_B14_MODEL_ID] == frozenset({"chat"})
    assert model_supports(LOW_B14_MODEL_ID, "chat") is True
    assert model_supports(LOW_B14_MODEL_ID, "image") is False


def test_tier_assignment_is_distinct_from_route_executability() -> None:
    for model_id in (LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID, HIGH_B14_MODEL_ID):
        assert model_profile_is_assigned(model_id) is True
    # Assignment still does not imply execution: Pro and Max are assigned tiers
    # whose routes stay held, while Plus became executable through #3554 only.
    assert model_policy_is_executable(LOW_B14_MODEL_ID) is True
    assert model_policy_is_executable(MEDIUM_B14_MODEL_ID) is False
    assert model_policy_is_executable(HIGH_B14_MODEL_ID) is False

    for model_id in (AUTO_B14_MODEL_ID, UNASSIGNED_B14_MODEL_ID):
        assert model_profile_is_assigned(model_id) is False
        assert model_policy_is_executable(model_id) is False


def test_route_identities_are_derived_from_shared_contract() -> None:
    plus_route = active_route_for(ProductTierLabel.PLUS)
    assert plus_route is not None
    assert LOW_B14_MODEL_ID == plus_route.model_id
    assert active_route_for(ProductTierLabel.PRO) is None
    assert active_route_for(ProductTierLabel.MAX) is None
    assert MEDIUM_B14_MODEL_ID == CONTRACT_PRO_HOLD_MODEL_ID
    assert HIGH_B14_MODEL_ID == CONTRACT_MAX_HOLD_MODEL_ID


def test_model_policy_source_contains_no_provider_route_literals() -> None:
    source = Path(model_policy_module.__file__).read_text(encoding="utf-8")
    assert '"kilo/' not in source
    assert "'kilo/" not in source
    assert '"padiem-profile/plus-hold"' not in source
    assert '"padiem-profile/pro-hold"' not in source
    assert '"padiem-profile/max-hold"' not in source
    assert "EXECUTABLE_B14_MODEL_IDS = _contract_executable_ids()" in source


def test_only_the_selected_plus_text_profile_is_executable() -> None:
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({DEFAULT_B14_MODEL_ID})
    assert model_policy_is_executable(DEFAULT_B14_MODEL_ID) is True
    assert model_policy_is_executable(PROFILE_MODEL_IDS["medium"]) is False
    assert model_policy_is_executable(PROFILE_MODEL_IDS["high"]) is False
    assert DEFAULT_B14_MODEL_ID == PROFILE_MODEL_IDS[DEFAULT_CHAT_PROFILE]
    assert RETIRED_B14_MODEL_IDS == frozenset(
        {
            "kilo/minimax-minimax-m3-free",
            "kilo/tencent-hy3-free",
        }
    )


@pytest.mark.parametrize(
    ("tier_id", "expected_model", "expected_profile"),
    [
        ("plus", LOW_B14_MODEL_ID, "low"),
        ("pro", MEDIUM_B14_MODEL_ID, "medium"),
        ("max", HIGH_B14_MODEL_ID, "high"),
    ],
)
def test_browser_tier_identity_resolves_without_execution(
    tier_id: str,
    expected_model: str,
    expected_profile: str,
) -> None:
    messages = [{"role": "user", "content": "브라우저 등급 선택 테스트"}]
    policy = resolve_tier_policy(messages, tier_id, require_executable=False)
    assert policy.model_id == expected_model
    assert policy.profile == expected_profile
    assert policy.messages == messages


@pytest.mark.parametrize("tier_id", ["pro", "max"])
def test_browser_tiers_without_a_selected_route_fail_closed(tier_id: str) -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_tier_policy([{"role": "user", "content": "HOLD 등급 테스트"}], tier_id)
    assert info.value.code == "tier_unavailable"


@pytest.mark.parametrize("tier_id", ["", "auto", "fast", "balanced", "deep", "unknown"])
def test_browser_tier_rejects_non_product_values(tier_id: str) -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_tier_policy([{"role": "user", "content": "질문"}], tier_id)
    assert info.value.code == "unknown_product_tier"


def test_request_tier_context_stays_scoped_per_tier_executability() -> None:
    messages = [{"role": "user", "content": "등급 컨텍스트 테스트"}]

    identity = resolve_request_model_policy(messages, require_executable=False)
    assert identity.model_id == LOW_B14_MODEL_ID

    with request_tier_context("plus"):
        plus_identity = resolve_request_model_policy(messages, require_executable=False)
        assert plus_identity.model_id == LOW_B14_MODEL_ID
        # Plus now has a selected text route, so the scoped call resolves.
        assert resolve_request_model_policy(messages).model_id == LOW_B14_MODEL_ID

    with request_tier_context("pro"):
        with pytest.raises(ModelPolicyError) as info:
            resolve_request_model_policy(messages)
        assert info.value.code == "tier_unavailable"

    # Outside any context the default tier applies and stays dispatchable.
    assert resolve_request_model_policy(messages).model_id == DEFAULT_B14_MODEL_ID
