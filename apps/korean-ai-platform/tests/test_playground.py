"""Tests for the playground deterministic response logic."""

from __future__ import annotations

import pytest

from app.demo_data import (
    MODELS_BY_ID,
    ROUTING_POLICIES,
    generate_demo_response,
)


class TestDemoResponse:
    def test_response_has_all_fields(self):
        result = generate_demo_response("openai-gpt4o", "테스트")
        assert result.model_id == "openai-gpt4o"
        assert result.input_tokens > 0
        assert result.output_tokens > 0
        assert result.cost_krw > 0
        assert result.latency_ms > 0
        assert result.region
        assert result.routing_reason
        assert result.text

    def test_deterministic_same_input(self):
        result1 = generate_demo_response("openai-gpt4o", "안녕하세요")
        result2 = generate_demo_response("openai-gpt4o", "안녕하세요")
        assert result1.text == result2.text
        assert result1.input_tokens == result2.input_tokens
        assert result1.output_tokens == result2.output_tokens
        assert result1.cost_krw == result2.cost_krw

    def test_different_prompt_different_tokens(self):
        short = generate_demo_response("openai-gpt4o", "짧음")
        long = generate_demo_response("openai-gpt4o", "a" * 500)
        assert long.input_tokens > short.input_tokens

    def test_routing_reason_direct(self):
        result = generate_demo_response("openai-gpt4o", "test", "direct")
        assert "직접 선택" in result.routing_reason

    def test_routing_reason_cheapest(self):
        result = generate_demo_response("openai-gpt4o", "test", "cheapest")
        assert "Demo" in result.routing_reason

    def test_routing_reason_fastest(self):
        result = generate_demo_response("openai-gpt4o", "test", "fastest")
        assert "Demo" in result.routing_reason

    def test_routing_reason_korean_first(self):
        result = generate_demo_response("openai-gpt4o", "test", "korean-first")
        assert "Mock" in result.routing_reason

    def test_routing_reason_domestic_first(self):
        result = generate_demo_response("openai-gpt4o", "test", "domestic-first")
        assert "Mock" in result.routing_reason

    def test_response_contains_demo_label(self):
        result = generate_demo_response("openai-gpt4o", "test")
        assert "Demo" in result.text

    def test_cost_calculation(self):
        model = MODELS_BY_ID["openai-gpt4o"]
        result = generate_demo_response("openai-gpt4o", "test prompt here")
        expected = (result.input_tokens / 1000 * model.input_krw_per_1k) + (
            result.output_tokens / 1000 * model.output_krw_per_1k
        )
        assert abs(result.cost_krw - round(expected, 2)) < 0.01


class TestRoutingPolicies:
    def test_all_policies_have_required_fields(self):
        for policy in ROUTING_POLICIES:
            assert policy.id
            assert policy.label
            assert policy.description
            assert policy.selected_model_id
            assert policy.reason
            assert policy.selected_model_id in MODELS_BY_ID

    def test_policy_ids_unique(self):
        ids = [p.id for p in ROUTING_POLICIES]
        assert len(ids) == len(set(ids))

    def test_cheapest_selects_lowest_price_model(self):
        cheapest = next(p for p in ROUTING_POLICIES if p.id == "cheapest")
        model = MODELS_BY_ID[cheapest.selected_model_id]
        all_models = list(MODELS_BY_ID.values())
        min_price = min(m.input_krw_per_1k + m.output_krw_per_1k for m in all_models)
        assert model.input_krw_per_1k + model.output_krw_per_1k == min_price

    def test_fastest_selects_lowest_latency_model(self):
        fastest = next(p for p in ROUTING_POLICIES if p.id == "fastest")
        model = MODELS_BY_ID[fastest.selected_model_id]
        all_models = list(MODELS_BY_ID.values())
        min_latency = min(m.latency_ms for m in all_models)
        assert model.latency_ms == min_latency

    def test_korean_first_selects_highest_korean_score(self):
        korean = next(p for p in ROUTING_POLICIES if p.id == "korean-first")
        model = MODELS_BY_ID[korean.selected_model_id]
        all_models = list(MODELS_BY_ID.values())
        max_score = max(m.korean_score for m in all_models)
        assert model.korean_score == max_score
