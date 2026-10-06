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


def test_three_product_tier_identities_remain_known_while_all_routes_hold() -> None:
    policy = resolve_model_policy(
        [{"role": "user", "content": "안녕하세요"}],
        require_executable=False,
    )

    assert DEFAULT_CHAT_PROFILE == "low"
    assert LOW_B14_MODEL_ID == "kilo/inclusionai-ling-3.1-flash"
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


def test_ordinary_chat_resolves_executable_successor_route() -> None:
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert policy.model_id == LOW_B14_MODEL_ID
    assert model_policy_is_executable(policy.model_id) is True


def test_plus_alias_preserves_product_identity_without_becoming_executable() -> None:
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


@pytest.mark.parametrize("alias", ["/pro", "/max"])
def test_held_tier_aliases_fail_closed_before_b14(alias: str) -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": f"{alias} 질문"}])
    assert info.value.code == "tier_unavailable"
    assert "준비 중" in info.value.message


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


def test_hold_identities_claim_no_model_capabilities() -> None:
    for model_id in (
        LOW_B14_MODEL_ID,
        MEDIUM_B14_MODEL_ID,
        HIGH_B14_MODEL_ID,
        AUTO_B14_MODEL_ID,
        UNASSIGNED_B14_MODEL_ID,
    ):
        assert MODEL_CAPABILITIES[model_id] == frozenset()
        assert model_supports(model_id, "chat") is False
        assert model_supports(model_id, "image") is False
        assert model_supports(model_id, "free") is False


def test_tier_assignment_is_distinct_from_route_executability() -> None:
    for model_id in (LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID, HIGH_B14_MODEL_ID):
        assert model_profile_is_assigned(model_id) is True
    assert model_policy_is_executable(LOW_B14_MODEL_ID) is True
    for model_id in (MEDIUM_B14_MODEL_ID, HIGH_B14_MODEL_ID):
        assert model_policy_is_executable(model_id) is False

    for model_id in (AUTO_B14_MODEL_ID, UNASSIGNED_B14_MODEL_ID):
        assert model_profile_is_assigned(model_id) is False
        assert model_policy_is_executable(model_id) is False


def test_route_identities_are_derived_from_shared_contract() -> None:
    assert active_route_for(ProductTierLabel.PLUS) is not None
    assert active_route_for(ProductTierLabel.PLUS).model_id == LOW_B14_MODEL_ID
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


def test_successor_selection_makes_default_profile_executable() -> None:
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({LOW_B14_MODEL_ID})
    assert model_policy_is_executable(DEFAULT_B14_MODEL_ID) is True
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
def test_browser_held_tiers_fail_closed(tier_id: str) -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_tier_policy([{"role": "user", "content": "HOLD 등급 테스트"}], tier_id)
    assert info.value.code == "tier_unavailable"


@pytest.mark.parametrize("tier_id", ["", "auto", "fast", "balanced", "deep", "unknown"])
def test_browser_tier_rejects_non_product_values(tier_id: str) -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_tier_policy([{"role": "user", "content": "질문"}], tier_id)
    assert info.value.code == "unknown_product_tier"


def test_request_tier_context_scoping_with_executable_plus() -> None:
    messages = [{"role": "user", "content": "등급 컨텍스트 테스트"}]

    identity = resolve_request_model_policy(messages, require_executable=False)
    assert identity.model_id == LOW_B14_MODEL_ID

    with request_tier_context("plus"):
        plus_identity = resolve_request_model_policy(messages, require_executable=False)
        assert plus_identity.model_id == LOW_B14_MODEL_ID
        executable = resolve_request_model_policy(messages)
        assert executable.model_id == LOW_B14_MODEL_ID

    with request_tier_context("pro"):
        with pytest.raises(ModelPolicyError) as info:
            resolve_request_model_policy(messages)
        assert info.value.code == "tier_unavailable"

    identity = resolve_request_model_policy(messages, require_executable=False)
    assert identity.model_id == LOW_B14_MODEL_ID
