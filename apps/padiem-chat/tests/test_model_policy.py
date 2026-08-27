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


AGNES_MODEL = "agnes-ai/agnes-2.5-flash"


def test_default_model_is_exact_agnes_and_never_b14_auto():
    policy = resolve_model_policy([{"role": "user", "content": "안녕하세요"}])
    assert DEFAULT_B14_MODEL_ID == AGNES_MODEL
    assert policy.model_id == AGNES_MODEL
    assert policy.model_id != "b14/auto"
    assert policy.messages == [{"role": "user", "content": "안녕하세요"}]
    assert policy.alias is None


def test_agnes_alias_is_the_only_initial_model_alias_and_is_stripped():
    assert MODEL_ALIASES == {"/agnes": AGNES_MODEL}
    policy = resolve_model_policy(
        [
            {"role": "assistant", "content": "무엇을 도와드릴까요?"},
            {"role": "user", "content": "  /AgNeS   한국어로 답해 주세요  "},
        ]
    )
    assert policy.model_id == AGNES_MODEL
    assert policy.alias == "/agnes"
    assert policy.messages[-1] == {"role": "user", "content": "한국어로 답해 주세요"}


def test_unknown_alias_fails_closed():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/openrouter 질문"}])
    assert info.value.code == "unknown_model_alias"


def test_alias_without_prompt_fails_closed():
    with pytest.raises(ModelPolicyError) as info:
        resolve_model_policy([{"role": "user", "content": "/agnes"}])
    assert info.value.code == "model_alias_requires_prompt"


def test_agnes_policy_claims_chat_only_not_free_or_image():
    assert MODEL_CAPABILITIES == {AGNES_MODEL: frozenset({"chat"})}
    assert model_supports(AGNES_MODEL, "chat") is True
    assert model_supports(AGNES_MODEL, "free") is False
    assert model_supports(AGNES_MODEL, "image") is False
    assert model_supports("b14/auto", "chat") is False
