from __future__ import annotations

import pytest

from app.model_policy import (
    AUTO_B14_MODEL_ID,
    DEFAULT_B14_MODEL_ID,
    DEFAULT_CHAT_PROFILE,
    HIGH_B14_MODEL_ID,
    LOW_B14_MODEL_ID,
    MEDIUM_B14_MODEL_ID,
    MODEL_ALIASES,
    MODEL_CAPABILITIES,
    PROFILE_MODEL_IDS,
    UNASSIGNED_B14_MODEL_ID,
    ModelPolicyError,
    model_policy_is_executable,
    model_profile_is_assigned,
    model_supports,
    resolve_model_policy,
)


def test_profile_mapping_keeps_only_medium_executable_and_defaults_to_laguna():
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])

    assert DEFAULT_CHAT_PROFILE == "medium"
    assert PROFILE_MODEL_IDS == {
        "low": LOW_B14_MODEL_ID,
        "medium": MEDIUM_B14_MODEL_ID,
        "high": HIGH_B14_MODEL_ID,
    }
    assert LOW_B14_MODEL_ID == "padiem-profile/low-unassigned"
    assert MEDIUM_B14_MODEL_ID == "poolside/laguna-s-2.1"
    assert HIGH_B14_MODEL_ID == "padiem-profile/high-paid-unassigned"
    assert DEFAULT_B14_MODEL_ID == MEDIUM_B14_MODEL_ID
    assert policy.profile == "medium"
    assert policy.model_id == MEDIUM_B14_MODEL_ID
    assert model_profile_is_assigned(policy.model_id) is True
    assert model_policy_is_executable(policy.model_id) is True
    assert policy.messages == [{"role": "user", "content": "안녕하세요"}]
    assert policy.alias is None


def test_poolside_alias_selects_exact_medium_laguna_and_is_stripped():
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


def test_other_provider_aliases_fail_closed_before_b14():
    for alias in ("/agnes", "/openrouter", "/claude", "/gemini", "/kilo"):
        with pytest.raises(ModelPolicyError) as info:
            resolve_model_policy([{"role": "user", "content": f"{alias} 질문"}])
        assert info.value.code == "unknown_model_alias"


def test_unknown_alias_fails_closed_without_provider_hint():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/unknown 질문"}])
    assert info.value.code == "unknown_model_alias"
    assert "poolside" not in info.value.message.lower()
    assert "agnes" not in info.value.message.lower()


def test_poolside_alias_without_prompt_fails_closed():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/poolside"}])
    assert info.value.code == "model_alias_requires_prompt"


def test_medium_capabilities_are_conservative_and_do_not_claim_durable_free_or_image():
    assert MODEL_CAPABILITIES[MEDIUM_B14_MODEL_ID] == frozenset(
        {"chat", "coding", "long_context"}
    )
    assert model_supports(MEDIUM_B14_MODEL_ID, "chat") is True
    assert model_supports(MEDIUM_B14_MODEL_ID, "coding") is True
    assert model_supports(MEDIUM_B14_MODEL_ID, "long_context") is True
    assert model_supports(MEDIUM_B14_MODEL_ID, "free") is False
    assert model_supports(MEDIUM_B14_MODEL_ID, "image") is False


def test_low_high_auto_and_legacy_unassigned_are_not_executable():
    for model_id in (
        LOW_B14_MODEL_ID,
        HIGH_B14_MODEL_ID,
        AUTO_B14_MODEL_ID,
        UNASSIGNED_B14_MODEL_ID,
    ):
        assert model_profile_is_assigned(model_id) is False
        assert model_policy_is_executable(model_id) is False
        assert MODEL_CAPABILITIES[model_id] == frozenset()

    assert AUTO_B14_MODEL_ID == "b14/auto"
