"""Tests for synthetic demo data integrity."""

from __future__ import annotations

import re

from app.demo_data import (
    ACCESS_MODES,
    DEMO_API_KEYS,
    DEMO_USAGE_RECORDS,
    MODELS,
    MODELS_BY_ID,
    compute_usage_summary,
    get_integration_examples,
)


class TestModelData:
    def test_models_not_empty(self):
        assert len(MODELS) >= 5

    def test_models_by_id_consistent(self):
        for model in MODELS:
            assert model.id in MODELS_BY_ID
            assert MODELS_BY_ID[model.id] is model

    def test_model_ids_unique(self):
        ids = [m.id for m in MODELS]
        assert len(ids) == len(set(ids))

    def test_model_has_required_fields(self):
        for model in MODELS:
            assert model.id
            assert model.provider
            assert model.provider_type in ("external", "domestic", "open-model")
            assert model.name
            assert model.input_krw_per_1k >= 0
            assert model.output_krw_per_1k >= 0
            assert model.region
            assert 1 <= model.korean_score <= 5
            assert 1 <= model.coding_score <= 5
            assert model.latency_ms > 0
            assert model.context_window > 0

    def test_has_external_models(self):
        external = [m for m in MODELS if m.provider_type == "external"]
        assert len(external) >= 2

    def test_has_domestic_models(self):
        domestic = [m for m in MODELS if m.provider_type == "domestic"]
        assert len(domestic) >= 2

    def test_has_open_model_models(self):
        open_models = [m for m in MODELS if m.provider_type == "open-model"]
        assert len(open_models) >= 1

    def test_tags_not_empty(self):
        for model in MODELS:
            assert len(model.tags) > 0


class TestApiKeyData:
    def test_keys_not_empty(self):
        assert len(DEMO_API_KEYS) >= 1

    def test_keys_have_required_fields(self):
        for key in DEMO_API_KEYS:
            assert key.id
            assert key.label
            assert key.masked_key
            assert key.created_at
            assert key.status in ("active", "revoked")
            assert key.access_mode

    def test_keys_are_masked(self):
        for key in DEMO_API_KEYS:
            assert "****" in key.masked_key
            assert len(key.masked_key) < 40

    def test_no_real_secret_patterns(self):
        secret_patterns = [
            r"sk-[a-zA-Z0-9]{20,}",
            r"AKIA[A-Z0-9]{16}",
            r"ghp_[a-zA-Z0-9]{36}",
            r"eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*",
        ]
        for key in DEMO_API_KEYS:
            for pattern in secret_patterns:
                assert not re.search(pattern, key.masked_key), (
                    f"Potential secret pattern found in key: {key.masked_key}"
                )


class TestAccessModeData:
    def test_modes_not_empty(self):
        assert len(ACCESS_MODES) >= 4

    def test_modes_have_required_fields(self):
        for mode in ACCESS_MODES:
            assert mode.id
            assert mode.label
            assert mode.description
            assert mode.status

    def test_modes_cover_all_types(self):
        mode_ids = [m.id for m in ACCESS_MODES]
        assert "gateway" in mode_ids
        assert "byok" in mode_ids
        assert "business14-credit" in mode_ids
        assert "self-hosted" in mode_ids


class TestUsageData:
    def test_records_not_empty(self):
        assert len(DEMO_USAGE_RECORDS) >= 3

    def test_records_have_required_fields(self):
        for record in DEMO_USAGE_RECORDS:
            assert record.timestamp
            assert record.model_id
            assert record.model_name
            assert record.provider
            assert record.input_tokens >= 0
            assert record.output_tokens >= 0
            assert record.cost_krw >= 0
            assert record.status in ("success", "error")
            assert record.latency_ms >= 0

    def test_summary_computed_correctly(self):
        summary = compute_usage_summary()
        assert summary.remaining_credit_krw > 0
        assert summary.monthly_requests == len(DEMO_USAGE_RECORDS)
        assert summary.monthly_cost_krw > 0
        assert summary.total_input_tokens > 0
        assert summary.total_output_tokens > 0
        assert 0 <= summary.success_rate <= 100
        assert len(summary.by_provider) > 0
        assert len(summary.by_model) > 0

    def test_summary_provider_breakdown(self):
        summary = compute_usage_summary()
        total_requests = sum(p["requests"] for p in summary.by_provider)
        assert total_requests == len(DEMO_USAGE_RECORDS)

    def test_summary_model_breakdown(self):
        summary = compute_usage_summary()
        total_requests = sum(m["requests"] for m in summary.by_model)
        assert total_requests == len(DEMO_USAGE_RECORDS)


class TestIntegrationExamples:
    def test_examples_returned(self):
        examples = get_integration_examples()
        assert len(examples) >= 4

    def test_examples_have_required_fields(self):
        for example in get_integration_examples():
            assert example.id
            assert example.label
            assert example.language
            assert example.code

    def test_examples_include_curl(self):
        examples = get_integration_examples()
        labels = [e.label.lower() for e in examples]
        assert "curl" in labels

    def test_examples_include_python(self):
        examples = get_integration_examples()
        labels = [e.label.lower() for e in examples]
        assert "python" in labels

    def test_examples_include_javascript(self):
        examples = get_integration_examples()
        labels = [e.label.lower() for e in examples]
        assert "javascript" in labels

    def test_examples_use_placeholder_key(self):
        examples = get_integration_examples()
        for example in examples:
            assert "$KAP_API_KEY" in example.code

    def test_examples_use_demo_endpoint(self):
        examples = get_integration_examples()
        for example in examples:
            assert "example-kap.demo" in example.code

    def test_no_real_secret_in_examples(self):
        secret_patterns = [
            r"sk-[a-zA-Z0-9]{20,}",
            r"AKIA[A-Z0-9]{16}",
            r"ghp_[a-zA-Z0-9]{36}",
        ]
        examples = get_integration_examples()
        for example in examples:
            for pattern in secret_patterns:
                assert not re.search(pattern, example.code), (
                    f"Potential secret pattern found in example: {example.label}"
                )

    def test_examples_for_different_models(self):
        examples1 = get_integration_examples("openai-gpt4o")
        examples2 = get_integration_examples("naver-hyperclova-x")
        assert examples1[0].code != examples2[0].code
