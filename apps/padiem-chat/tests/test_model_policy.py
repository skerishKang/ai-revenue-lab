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
    resolve_model_policy,
    resolve_request_model_policy,
    resolve_tier_policy,
    request_tier_context,
)


def test_three_product_tier_identities_remain_known_and_plus_is_default():
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])

    assert DEFAULT_CHAT_PROFILE == "low"
    assert LOW_B14_MODEL_ID == "sensenova/sensenova-6.8-flash-lite"
    assert MEDIUM_B14_MODEL_ID == "padiem-profile/pro-hold"
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
    assert EXECUTABLE_B14_MODEL_IDS == frozenset({LOW_B14_MODEL_ID})
    assert product_tier_name(HIGH_B14_MODEL_ID) == PADIEM_MAX
    assert model_profile_is_assigned(HIGH_B14_MODEL_ID) is True
    assert model_policy_is_executable(HIGH_B14_MODEL_ID) is False

    assert DEFAULT_B14_MODEL_ID == LOW_B14_MODEL_ID
    assert policy.profile == "low"
    assert policy.model_id == LOW_B14_MODEL_ID
    assert product_tier_name(policy.model_id) == "Padiem Plus"
    assert model_profile_is_assigned(policy.model_id) is True
    assert model_policy_is_executable(policy.model_id) is True
    assert policy.messages == [{"role": "user", "content": "안녕하세요"}]
    assert policy.alias is None


@pytest.mark.parametrize(
    ("alias", "model_id", "profile", "tier_name"),
    [
        ("/plus", LOW_B14_MODEL_ID, "low", PADIEM_PLUS),
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


def test_pro_and_max_product_identities_are_preserved_but_hold_fails_before_b14():
    assert MODEL_ALIASES["/pro"] == MEDIUM_B14_MODEL_ID
    assert product_tier_name(MEDIUM_B14_MODEL_ID) == PADIEM_PRO
    assert model_policy_is_executable(MEDIUM_B14_MODEL_ID) is False
    with pytest.raises(ModelPolicyError) as pro_info:
        resolve_model_policy([{"role": "user", "content": "/pro 테스트 질문입니다"}])
    assert pro_info.value.code == "tier_unavailable"


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

    with pytest.raises(ModelPolicyError) as kilo_info:
        resolve_model_policy([{"role": "user", "content": "/kilo 질문"}])
    assert kilo_info.value.code == "tier_unavailable"
    poolside = resolve_model_policy([{"role": "user", "content": "/poolside 질문"}])
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
    assert MODEL_CAPABILITIES[MEDIUM_B14_MODEL_ID] == frozenset()
    assert MODEL_CAPABILITIES[HIGH_B14_MODEL_ID] == frozenset()

    assert model_supports(LOW_B14_MODEL_ID, "chat") is True
    assert model_supports(LOW_B14_MODEL_ID, "free") is False
    assert model_supports(LOW_B14_MODEL_ID, "image") is False

    for model_id in (MEDIUM_B14_MODEL_ID, HIGH_B14_MODEL_ID, AUTO_B14_MODEL_ID, UNASSIGNED_B14_MODEL_ID):
        assert model_supports(model_id, "chat") is False
        assert model_supports(model_id, "free") is False
        assert model_supports(model_id, "image") is False


def test_tier_assignment_is_distinct_from_route_executability():
    for model_id in (LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID, HIGH_B14_MODEL_ID):
        assert model_profile_is_assigned(model_id) is True

    assert model_policy_is_executable(LOW_B14_MODEL_ID) is True
    assert model_policy_is_executable(MEDIUM_B14_MODEL_ID) is False
    assert model_policy_is_executable(HIGH_B14_MODEL_ID) is False

    for model_id in (AUTO_B14_MODEL_ID, UNASSIGNED_B14_MODEL_ID):
        assert model_profile_is_assigned(model_id) is False
        assert model_policy_is_executable(model_id) is False
        assert MODEL_CAPABILITIES[model_id] == frozenset()

    assert AUTO_B14_MODEL_ID == "b14/auto"


def test_route_identities_are_derived_from_shared_contract():
    """#2099 STEP-2: Chat no longer owns duplicate route literals."""
    from padiem_control_plane.product_tier_routes import (
        MAX_HOLD_MODEL_ID as CONTRACT_MAX_HOLD_MODEL_ID,
        PRO_HOLD_MODEL_ID as CONTRACT_PRO_HOLD_MODEL_ID,
    )
    from padiem_control_plane.product_tier_routes import (
        RETIRED_PRODUCT_MODEL_IDS as CONTRACT_RETIRED_MODEL_IDS,
    )
    from padiem_control_plane.product_tier_routes import (
        ProductTierLabel as ContractTierLabel,
    )
    from padiem_control_plane.product_tier_routes import (
        active_route_for as contract_active_route_for,
    )

    assert LOW_B14_MODEL_ID == contract_active_route_for(ContractTierLabel.PLUS).model_id
    assert contract_active_route_for(ContractTierLabel.PRO) is None
    assert MEDIUM_B14_MODEL_ID == CONTRACT_PRO_HOLD_MODEL_ID
    assert MAX_HOLD_MODEL_ID == CONTRACT_MAX_HOLD_MODEL_ID
    assert RETIRED_B14_MODEL_IDS == frozenset(CONTRACT_RETIRED_MODEL_IDS)


def test_model_policy_source_contains_no_route_id_literals_after_derivation():
    source = Path(model_policy_module.__file__).read_text(encoding="utf-8")
    assert '"kilo/' not in source
    assert "'kilo/" not in source
    assert '"padiem-profile/max-hold"' not in source
    assert '"padiem-profile/pro-hold"' not in source
    assert "RETIRED_B14_MODEL_IDS = frozenset(RETIRED_PRODUCT_MODEL_IDS)" in source


def test_executable_profile_routes_are_explicit_registered_and_not_retired():
    """#2094 contract: no product tier may ever point at a retired free lane."""
    assert RETIRED_B14_MODEL_IDS == frozenset(
        {
            "kilo/minimax-minimax-m3-free",
            "kilo/tencent-hy3-free",
        }
    )

    for executable_id in (LOW_B14_MODEL_ID,):
        assert executable_id not in RETIRED_B14_MODEL_IDS

    expected_routes = {
        "low": "sensenova/sensenova-6.8-flash-lite",
    }
    for profile_id, expected_model in expected_routes.items():
        model_id = PROFILE_MODEL_IDS[profile_id]
        assert model_policy_is_executable(model_id) is True
        assert model_id not in RETIRED_B14_MODEL_IDS
        assert model_id == expected_model
        assert model_id.count("/") == 1
        assert model_id != AUTO_B14_MODEL_ID

    assert PROFILE_MODEL_IDS["medium"] == MEDIUM_B14_MODEL_ID
    assert model_policy_is_executable(MEDIUM_B14_MODEL_ID) is False
    assert PROFILE_MODEL_IDS["high"] == MAX_HOLD_MODEL_ID
    assert model_policy_is_executable(MAX_HOLD_MODEL_ID) is False

    assert DEFAULT_B14_MODEL_ID == PROFILE_MODEL_IDS[DEFAULT_CHAT_PROFILE]
    assert model_policy_is_executable(DEFAULT_B14_MODEL_ID) is True
    assert DEFAULT_B14_MODEL_ID not in RETIRED_B14_MODEL_IDS


@pytest.mark.parametrize(
    ("tier_id", "expected_model", "expected_profile"),
    [
        ("plus", LOW_B14_MODEL_ID, "low"),
    ],
)
def test_explicit_browser_tier_resolves_through_shared_contract(
    tier_id: str,
    expected_model: str,
    expected_profile: str,
) -> None:
    messages = [{"role": "user", "content": "브라우저 등급 선택 테스트"}]
    policy = resolve_tier_policy(messages, tier_id)

    assert policy.model_id == expected_model
    assert policy.profile == expected_profile
    assert policy.messages == messages
    assert policy.alias is None


@pytest.mark.parametrize("tier_id", ["pro", "max"])
def test_explicit_browser_held_tiers_fail_closed(tier_id: str) -> None:
    messages = [{"role": "user", "content": "HOLD 등급 테스트"}]
    with pytest.raises(ModelPolicyError) as info:
        resolve_tier_policy(messages, tier_id)
    assert info.value.code == "tier_unavailable"


@pytest.mark.parametrize("tier_id", ["", "auto", "fast", "balanced", "deep", "unknown"])
def test_browser_tier_rejects_non_product_values(tier_id: str) -> None:
    with pytest.raises(ModelPolicyError) as info:
        resolve_tier_policy([{"role": "user", "content": "질문"}], tier_id)
    assert info.value.code == "unknown_product_tier"


def test_request_tier_context_is_request_scoped_and_resets_to_default() -> None:
    messages = [{"role": "user", "content": "등급 컨텍스트 테스트"}]

    assert resolve_request_model_policy(messages).model_id == LOW_B14_MODEL_ID
    with request_tier_context("plus"):
        assert resolve_request_model_policy(messages).model_id == LOW_B14_MODEL_ID
    assert resolve_request_model_policy(messages).model_id == LOW_B14_MODEL_ID
