"""B14 per-model official parameter profile contract (#3977).

Covers the profile registry itself: registry drift, fail-closed validation,
exact upstream shape mapping, and the separation of the B14 service output
ceiling from any model's documented maximum output.
"""

from __future__ import annotations

import pytest

from app.pilot.catalog import CATALOG_BY_ID
from app.pilot.errors import InvalidParameterValue, UnsupportedParameter
from app.pilot.model_parameter_profiles import (
    B14_OPERATIONAL_REQUEST_TOKEN_CEILING,
    CANONICAL_OPTIONAL_FIELDS,
    PROFILES,
    build_upstream_parameters,
    describe_profile,
    get_profile,
    supported_optional_fields,
    validate_optional_parameters,
)


def _enabled_registered_ids() -> set[str]:
    return {m.model_id for m in CATALOG_BY_ID.values() if m.enabled}


def test_every_enabled_registered_model_has_a_profile() -> None:
    missing = sorted(_enabled_registered_ids() - set(PROFILES))
    assert not missing, f"registered models without a parameter profile: {missing}"


def test_profile_ids_match_the_registry_exactly() -> None:
    # No orphan profile may claim a model that is not registered.
    assert set(PROFILES) == _enabled_registered_ids()


def test_unknown_model_has_no_profile_and_no_supported_fields() -> None:
    assert get_profile("does/not-exist") is None
    assert supported_optional_fields("does/not-exist") == ()


def test_canonical_optional_fields_are_the_only_accepted_names() -> None:
    assert set(CANONICAL_OPTIONAL_FIELDS) == {
        "top_p",
        "top_k",
        "reasoning_effort",
        "thinking",
    }


def test_describe_profile_records_the_required_authority_fields() -> None:
    record = describe_profile("google/gemini-3.5-flash-lite")
    for key in (
        "b14_id",
        "serving_provider_id",
        "serving_api_origin",
        "upstream_model",
        "model_developer",
        "base_model_id",
        "variant_kind",
        "variant_evidence",
        "manufacturer_doc_url",
        "manufacturer_doc_checked_at",
        "provider_doc_url",
        "provider_doc_checked_at",
        "provider_authenticated_models_evidence",
        "supported_optional_fields",
        "supported_request_fields",
        "native_defaults",
        "max_input_context",
        "model_max_output",
        "serving_max_output",
        "request_budget_contract",
        "evidence_level",
        "passthrough_test",
    ):
        assert key in record, f"missing authority field: {key}"


def test_unknown_model_describe_is_explicitly_unknown() -> None:
    record = describe_profile("does/not-exist")
    assert record["profile_status"] == "UNKNOWN"
    assert record["supported_optional_fields"] == []
    assert record["passthrough_test"] == "NOT_TESTED"


def test_unknown_capability_is_never_fabricated() -> None:
    # Model maximum output is UNKNOWN for every registered model: it must stay
    # None, never a made-up number (authority doc §4/§8).
    for profile in PROFILES.values():
        assert profile.model_max_output is None


def test_provider_variant_is_not_conflated_with_a_manufacturer_model() -> None:
    exlab = get_profile("experiential/qwen3.8-flash-next-uncensored")
    assert exlab is not None
    assert exlab.variant_kind == "provider_variant"
    assert exlab.serving_provider_id == "experiential"
    assert exlab.base_model_id == "qwen3.8-flash-next"


def test_agnes_unknown_provenance_stays_unknown() -> None:
    agnes = get_profile("agnes-ai/agnes-3.0-flash")
    assert agnes is not None
    assert agnes.variant_kind == "unknown"
    assert agnes.model_developer == "UNKNOWN"


def test_validate_omits_absent_and_null_values() -> None:
    assert validate_optional_parameters("google/gemini-3.5-flash-lite", {}) == {}
    # An explicit null is treated as "not provided" and stays omitted.
    assert validate_optional_parameters("google/gemini-3.5-flash-lite", {"top_p": None}) == {}


def test_validate_preserves_explicit_supported_values() -> None:
    validated = validate_optional_parameters(
        "google/gemini-3.5-flash-lite",
        {"top_p": 0.95, "reasoning_effort": "minimal"},
    )
    assert validated == {"top_p": 0.95, "reasoning_effort": "minimal"}


def test_validate_rejects_a_field_the_exact_model_does_not_document() -> None:
    with pytest.raises(UnsupportedParameter) as info:
        validate_optional_parameters("inception/mercury-2.5", {"top_p": 0.5})
    assert info.value.status_code == 422
    assert info.value.field == "top_p"
    assert info.value.model_id == "inception/mercury-2.5"


def test_validate_rejects_any_model_specific_field_on_unknown_profile() -> None:
    with pytest.raises(UnsupportedParameter):
        validate_optional_parameters("does/not-exist", {"thinking": True})


def test_validate_rejects_out_of_range_and_unknown_enum_values() -> None:
    with pytest.raises(InvalidParameterValue):
        validate_optional_parameters("google/gemini-3.5-flash-lite", {"top_p": 1.5})
    with pytest.raises(InvalidParameterValue):
        validate_optional_parameters(
            "google/gemini-3.5-flash-lite", {"reasoning_effort": "none"}
        )
    # Atria's direct observation returned HTTP 422 for "none", so it is not a
    # supported value even though low/medium/high are.
    with pytest.raises(InvalidParameterValue):
        validate_optional_parameters("atria/Atria-Dawn-Preview", {"reasoning_effort": "none"})


def test_validate_rejects_wrong_value_kind() -> None:
    with pytest.raises(InvalidParameterValue):
        validate_optional_parameters("poolside/laguna-s-2.1", {"thinking": "on"})
    with pytest.raises(InvalidParameterValue):
        validate_optional_parameters("google/gemma-4-31b-it", {"top_k": "many"})


def test_build_upstream_parameters_maps_the_exact_shape() -> None:
    assert build_upstream_parameters(
        "google/gemini-3.5-flash-lite", {"reasoning_effort": "minimal"}
    ) == {"reasoning_effort": "minimal"}
    # Poolside/Agnes thinking maps onto the nested chat_template_kwargs shape.
    assert build_upstream_parameters("poolside/laguna-s-2.1", {"thinking": True}) == {
        "chat_template_kwargs": {"enable_thinking": True}
    }
    assert build_upstream_parameters("agnes-ai/agnes-3.0-flash", {"thinking": False}) == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_build_upstream_parameters_never_invents_fields() -> None:
    assert build_upstream_parameters("does/not-exist", {"thinking": True}) == {}
    assert build_upstream_parameters("inception/mercury-2.5", {"top_p": 0.5}) == {}


def test_service_ceiling_is_separate_from_model_maximum_output() -> None:
    # The B14 operational ceiling is a resource guard, not a model capability.
    assert B14_OPERATIONAL_REQUEST_TOKEN_CEILING == 4096
    for profile in PROFILES.values():
        assert profile.request_budget_contract == "explicit_only_bounded_by_b14_service_ceiling"
        # No profile claims the service ceiling as the model's own maximum.
        assert profile.model_max_output != B14_OPERATIONAL_REQUEST_TOKEN_CEILING


def test_generated_profile_document_matches_the_registry() -> None:
    """The checked-in per-model record must not drift from the code."""
    from pathlib import Path

    from app.pilot.model_parameter_profiles import render_markdown

    doc = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "B14_MODEL_PARAMETER_PROFILES.md"
    )
    assert doc.exists(), "generated profile document is missing"
    assert doc.read_text(encoding="utf-8") == render_markdown()
