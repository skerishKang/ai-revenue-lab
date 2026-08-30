from app.pilot.capability_evidence import ModelCapability
from app.pilot.capability_routing import (
    evaluate_model_capabilities,
    filter_capability_eligible_models,
)
from app.pilot.catalog import CATALOG_MODELS


def _model(model_id: str):
    return next(model for model in CATALOG_MODELS if model.model_id == model_id)


def test_chat_capability_is_eligible_from_configured_legacy_tag():
    result = evaluate_model_capabilities(_model("google/gemini-2.5-flash"), ["chat"])
    assert result.eligible is True
    assert result.requirements.unsupported == ()
    assert result.requirements.unknown == ()


def test_unknown_streaming_capability_is_not_treated_as_supported():
    result = evaluate_model_capabilities(_model("google/gemini-2.5-flash"), ["streaming"])
    assert result.eligible is False
    assert ModelCapability.STREAMING in result.requirements.unknown
    assert ModelCapability.STREAMING not in result.requirements.unsupported


def test_multi_capability_requirement_fails_closed_on_unknown():
    result = evaluate_model_capabilities(
        _model("google/gemini-2.5-flash"),
        ["chat", ModelCapability.VISION, "streaming"],
    )
    assert result.eligible is False
    assert ModelCapability.VISION not in result.requirements.unsupported
    assert ModelCapability.VISION not in result.requirements.unknown
    assert ModelCapability.STREAMING in result.requirements.unknown


def test_empty_requirement_preserves_candidate_order():
    candidates = CATALOG_MODELS[:3]
    assert filter_capability_eligible_models(candidates, None) == candidates
