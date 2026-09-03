from __future__ import annotations

import pytest

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
    UNASSIGNED_B14_MODEL_ID,
    ModelPolicyError,
    model_policy_is_executable,
    model_profile_is_assigned,
    model_supports,
    product_tier_name,
    resolve_model_policy,
)


def test_three_product_tier_identities_remain_known_and_pro_is_default():
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])

    assert DEFAULT_CHAT_PROFILE == "medium"
    assert LOW_B14_MODEL_ID == "kilo/poolside-laguna-s-2.1-free"
    assert MEDIUM_B14_MODEL_ID == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
    assert MAX_HOLD_MODEL_ID == "padiem-profile/max-hold"
    assert HIGH_B14_MODEL_ID == MAX_HOLD_MODEL_ID
    assert "hy3" not in HIGH_B14_MODEL_ID
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
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID})
    assert product_tier_name(HIGH_B14_MODEL_ID) == PADIEM_MAX
    assert model_profile_is_assigned(HIGH_B14_MODEL_ID) is True
    assert model_policy_is_executable(HIGH_B14_MODEL_ID) is False

    assert DEFAULT_B14_MODEL_ID == MEDIUM_B14_MODEL_ID
    assert policy.profile == "medium"
    assert policy.model_id == MEDIUM_B14_MODEL_ID
    assert product_tier_name(policy.model_id) == "Padiem Pro"
    assert model_profile_is_assigned(policy.model_id) is True
    assert model_policy_is_executable(policy.model_id) is True
    assert policy.messages == [{"role": "user", "content": "안녕하세요"}]
    assert policy.alias is None


@pytest.mark.parametrize(
    ("alias", "model_id", "profile", "tier_name"),
    [
        ("/plus", LOW_B14_MODEL_ID, "low", PADIEM_PLUS),
        ("/pro", MEDIUM_B14_MODEL_ID, "medium", PADIEM_PRO),
    ],
)
def test_executable_product_tier_aliases_select_exact_routes_and_are_stripped(
    alias: str,
    model_id: str,
    profile: str,
    tier_name: str,
):
    assert MODEL_ALIASES[alias] == model_id
    policy = resolve_model_policy(
        [
            {"role": "assistant", "content": "무엇을 도와드릴까요?"},
            {"role": "user", "content": f"  {alias.upper()}   테스트 질문입니다  "},
        ]
    )
    assert policy.profile == profile
    assert policy.model_id == model_id
    assert policy.alias == alias
    assert policy.messages[-1] == {"role": "user", "content": "테스트 질문입니다"}
    assert product_tier_name(policy.model_id) == tier_name
    assert model_profile_is_assigned(policy.model_id) is True
    assert model_policy_is_executable(policy.model_id) is True


def test_max_product_identity_is_preserved_but_hold_fails_before_b14():
    assert MODEL_ALIASES["/max"] == HIGH_B14_MODEL_ID
    assert product_tier_name(HIGH_B14_MODEL_ID) == PADIEM_MAX
    assert model_profile_is_assigned(HIGH_B14_MODEL_ID) is True
    assert model_policy_is_executable(HIGH_B14_MODEL_ID) is False
    assert MODEL_CAPABILITIES[HIGH_B14_MODEL_ID] == frozenset()

    original = [{"role": "user", "content": "/max 테스트 질문입니다"}]
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy(original)
    assert info.value.code == "tier_unavailable"
    assert "준비 중" in info.value.message
    assert original == [{"role": "user", "content": "/max 테스트 질문입니다"}]
    for hidden_name in ("hy3", "minimax", "tencent", "kilo", "provider"):
        assert hidden_name not in info.value.message.lower()


def test_legacy_hidden_test_aliases_do_not_change_product_identity():
    assert MODEL_ALIASES["/kilo"] == MEDIUM_B14_MODEL_ID
    assert MODEL_ALIASES["/poolside"] == LOW_B14_MODEL_ID

    kilo = resolve_model_policy([{"role": "user", "content": "/kilo 질문"}])
    poolside = resolve_model_policy([{"role": "user", "content": "/poolside 질문"}])

    assert product_tier_name(kilo.model_id) == PADIEM_PRO
    assert product_tier_name(poolside.model_id) == PADIEM_PLUS


def test_other_provider_aliases_fail_closed_before_b14():
    for alias in ("/agnes", "/openrouter", "/claude", "/gemini"):
        with pytest.raises(ModelPolicyError) as info:
            resolve_model_policy([{"role": "user", "content": f"{alias} 질문"}])
        assert info.value.code == "unknown_model_alias"


def test_unknown_alias_fails_closed_without_provider_hint():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/unknown 질문"}])
    assert info.value.code == "unknown_model_alias"
    message = info.value.message.lower()
    for hidden_name in ("poolside", "nvidia", "tencent", "kilo", "nemotron", "hy3", "laguna", "minimax"):
        assert hidden_name not in message


def test_explicit_alias_without_prompt_fails_closed_before_tier_availability_check():
    for alias in ("/plus", "/pro", "/max", "/poolside", "/kilo"):
        with pytest.raises(ModelPolicyError) as info:
            resolve_model_policy([{"role": "user", "content": alias}])
        assert info.value.code == "model_alias_requires_prompt"


def test_tier_capabilities_are_conservative_and_hold_claims_none():
    assert MODEL_CAPABILITIES[LOW_B14_MODEL_ID] == frozenset({"chat", "coding", "long_context"})
    assert MODEL_CAPABILITIES[MEDIUM_B14_MODEL_ID] == frozenset({"chat", "long_context"})
    assert MODEL_CAPABILITIES[HIGH_B14_MODEL_ID] == frozenset()

    for model_id in (LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID):
        assert model_supports(model_id, "chat") is True
        assert model_supports(model_id, "free") is False
        assert model_supports(model_id, "image") is False

    for model_id in (HIGH_B14_MODEL_ID, AUTO_B14_MODEL_ID, UNASSIGNED_B14_MODEL_ID):
        assert model_supports(model_id, "chat") is False
        assert model_supports(model_id, "free") is False
        assert model_supports(model_id, "image") is False


def test_tier_assignment_is_distinct_from_route_executability():
    for model_id in (LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID, HIGH_B14_MODEL_ID):
        assert model_profile_is_assigned(model_id) is True

    for model_id in (LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID):
        assert model_policy_is_executable(model_id) is True

    assert model_policy_is_executable(HIGH_B14_MODEL_ID) is False

    for model_id in (AUTO_B14_MODEL_ID, UNASSIGNED_B14_MODEL_ID):
        assert model_profile_is_assigned(model_id) is False
        assert model_policy_is_executable(model_id) is False
        assert MODEL_CAPABILITIES[model_id] == frozenset()

    assert AUTO_B14_MODEL_ID == "b14/auto"
