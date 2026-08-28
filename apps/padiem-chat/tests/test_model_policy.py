from __future__ import annotations

import pytest

from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    MODEL_ALIASES,
    MODEL_CAPABILITIES,
    ModelPolicyError,
    model_supports,
    resolve_model_policy,
)


POOLSIDE_MODEL = "poolside/laguna-s-2.1"


def test_default_model_is_exact_poolside_and_never_b14_auto():
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert DEFAULT_B14_MODEL_ID == POOLSIDE_MODEL
    assert policy.model_id == POOLSIDE_MODEL
    assert policy.model_id != "b14/auto"
    assert policy.messages == [{"role": "user", "content": "안녕하세요"}]
    assert policy.alias is None


def test_poolside_alias_is_the_only_active_model_alias_and_is_stripped():
    assert MODEL_ALIASES == {"/poolside": POOLSIDE_MODEL}
    policy = resolve_model_policy(
        [
            {"role": "assistant", "content": "무엇을 도와드릴까요?"},
            {"role": "user", "content": "  /PoOlSiDe   한국어로 답해 주세요  "},
        ]
    )
    assert policy.model_id == POOLSIDE_MODEL
    assert policy.alias == "/poolside"
    assert policy.messages[-1] == {"role": "user", "content": "한국어로 답해 주세요"}


def test_dormant_agnes_alias_fails_closed():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/agnes 질문"}])
    assert info.value.code == "unknown_model_alias"


def test_unknown_alias_fails_closed():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/openrouter 질문"}])
    assert info.value.code == "unknown_model_alias"


def test_alias_without_prompt_fails_closed():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/poolside"}])
    assert info.value.code == "model_alias_requires_prompt"


def test_poolside_policy_claims_approved_capabilities_not_free_or_image():
    assert MODEL_CAPABILITIES == {
        POOLSIDE_MODEL: frozenset({"chat", "coding", "long_context"})
    }
    assert model_supports(POOLSIDE_MODEL, "chat") is True
    assert model_supports(POOLSIDE_MODEL, "coding") is True
    assert model_supports(POOLSIDE_MODEL, "long_context") is True
    assert model_supports(POOLSIDE_MODEL, "free") is False
    assert model_supports(POOLSIDE_MODEL, "image") is False
    assert model_supports("b14/auto", "chat") is False
