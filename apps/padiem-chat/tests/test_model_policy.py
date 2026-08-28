from __future__ import annotations

import pytest

from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    DEFAULT_CHAT_PROFILE,
    MODEL_ALIASES,
    MODEL_CAPABILITIES,
    UNASSIGNED_B14_MODEL_ID,
    ModelPolicyError,
    model_profile_is_assigned,
    model_supports,
    resolve_model_policy,
)


def test_default_policy_is_medium_and_provider_unassigned():
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert DEFAULT_CHAT_PROFILE == "medium"
    assert DEFAULT_B14_MODEL_ID == UNASSIGNED_B14_MODEL_ID
    assert policy.profile == "medium"
    assert policy.model_id == UNASSIGNED_B14_MODEL_ID
    assert model_profile_is_assigned(policy.model_id) is False
    assert policy.messages == [{"role": "user", "content": "안녕하세요"}]
    assert policy.alias is None


def test_legacy_poolside_alias_is_compatibility_noop_not_provider_selection():
    assert MODEL_ALIASES == {"/poolside": UNASSIGNED_B14_MODEL_ID}
    policy = resolve_model_policy(
        [
            {"role": "assistant", "content": "무엇을 도와드릴까요?"},
            {"role": "user", "content": "  /PoOlSiDe   한국어로 답해 주세요  "},
        ]
    )
    assert policy.profile == "medium"
    assert policy.model_id == UNASSIGNED_B14_MODEL_ID
    assert model_profile_is_assigned(policy.model_id) is False
    assert policy.alias == "/poolside"
    assert policy.messages[-1] == {"role": "user", "content": "한국어로 답해 주세요"}


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


def test_unassigned_profile_claims_no_model_capabilities():
    assert MODEL_CAPABILITIES == {UNASSIGNED_B14_MODEL_ID: frozenset()}
    assert model_supports(UNASSIGNED_B14_MODEL_ID, "chat") is False
    assert model_supports(UNASSIGNED_B14_MODEL_ID, "coding") is False
    assert model_supports(UNASSIGNED_B14_MODEL_ID, "long_context") is False
    assert model_supports(UNASSIGNED_B14_MODEL_ID, "free") is False
    assert model_supports(UNASSIGNED_B14_MODEL_ID, "image") is False
    assert model_supports("b14/auto", "chat") is False
