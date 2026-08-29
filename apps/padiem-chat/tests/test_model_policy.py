from __future__ import annotations

import pytest

from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    DEFAULT_CHAT_PROFILE,
    HIGH_B14_MODEL_ID,
    LOW_B14_MODEL_ID,
    MEDIUM_B14_MODEL_ID,
    MODEL_ALIASES,
    MODEL_CAPABILITIES,
    PROFILE_MODEL_IDS,
    ModelPolicyError,
    model_id_for_profile,
    model_profile_is_assigned,
    model_supports,
    profile_requires_contributor_warning,
    resolve_model_policy,
)


def test_owner_assigned_profile_map_is_exact_and_never_b14_auto():
    assert DEFAULT_CHAT_PROFILE == "medium"
    assert PROFILE_MODEL_IDS == {
        "low": "poolside/laguna-xs-2.1",
        "medium": "poolside/laguna-s-2.1",
        "high": "opencode-zen/muse-spark-1.2-contributor-free",
    }
    assert LOW_B14_MODEL_ID == PROFILE_MODEL_IDS["low"]
    assert MEDIUM_B14_MODEL_ID == PROFILE_MODEL_IDS["medium"]
    assert HIGH_B14_MODEL_ID == PROFILE_MODEL_IDS["high"]
    assert DEFAULT_B14_MODEL_ID == MEDIUM_B14_MODEL_ID
    assert "b14/auto" not in PROFILE_MODEL_IDS.values()


def test_default_policy_executes_medium_poolside_s():
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert policy.profile == "medium"
    assert policy.model_id == MEDIUM_B14_MODEL_ID
    assert model_profile_is_assigned(policy.model_id) is True
    assert policy.messages == [{"role": "user", "content": "안녕하세요"}]
    assert policy.alias is None


def test_profile_lookup_is_product_level_and_high_requires_warning():
    assert model_id_for_profile("LOW") == LOW_B14_MODEL_ID
    assert model_id_for_profile(" medium ") == MEDIUM_B14_MODEL_ID
    assert model_id_for_profile("HIGH") == HIGH_B14_MODEL_ID
    assert profile_requires_contributor_warning("high") is True
    assert profile_requires_contributor_warning("medium") is False
    with pytest.raises(ModelPolicyError) as info:
        model_id_for_profile("ultra")
    assert info.value.code == "unknown_profile"


def test_legacy_poolside_alias_resolves_only_to_medium_and_is_stripped():
    assert MODEL_ALIASES == {"/poolside": MEDIUM_B14_MODEL_ID}
    policy = resolve_model_policy(
        [
            {"role": "assistant", "content": "무엇을 도와드릴까요?"},
            {"role": "user", "content": "  /PoOlSiDe   한국어로 답해 주세요  "},
        ]
    )
    assert policy.profile == "medium"
    assert policy.model_id == MEDIUM_B14_MODEL_ID
    assert policy.alias == "/poolside"
    assert policy.messages[-1] == {"role": "user", "content": "한국어로 답해 주세요"}


def test_low_high_are_not_public_slash_aliases_before_warning_ui():
    for command in ("/low 질문", "/high 질문"):
        with pytest.raises(ModelPolicyError) as info:
            resolve_model_policy([{"role": "user", "content": command}])
        assert info.value.code == "unknown_model_alias"


def test_dormant_agnes_alias_fails_closed():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/agnes 질문"}])
    assert info.value.code == "unknown_model_alias"


def test_unknown_alias_fails_closed_without_provider_hint():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/openrouter 질문"}])
    assert info.value.code == "unknown_model_alias"
    assert "poolside" not in info.value.message.lower()
    assert "agnes" not in info.value.message.lower()


def test_legacy_alias_without_prompt_fails_closed():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/poolside"}])
    assert info.value.code == "model_alias_requires_prompt"


def test_assigned_profiles_claim_bounded_capabilities_not_image():
    assert set(MODEL_CAPABILITIES) == {
        LOW_B14_MODEL_ID,
        MEDIUM_B14_MODEL_ID,
        HIGH_B14_MODEL_ID,
    }
    for model_id in MODEL_CAPABILITIES:
        assert model_supports(model_id, "chat") is True
        assert model_supports(model_id, "coding") is True
        assert model_supports(model_id, "long_context") is True
        assert model_supports(model_id, "image") is False
        assert model_profile_is_assigned(model_id) is True
    assert model_supports("b14/auto", "chat") is False
    assert model_profile_is_assigned("b14/auto") is False
