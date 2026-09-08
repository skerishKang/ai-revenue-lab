from app.pilot.capability_evidence import ModelCapability
from app.pilot.capability_routing import (
    evaluate_model_capabilities,
    filter_capability_eligible_models,
)
from app.pilot import catalog as _catalog

def _model(model_id: str):
    return next(
        model for model in _catalog.CATALOG_MODELS if model.model_id == model_id
    )

def test_chat_capability_is_eligible_from_configured_legacy_tag():
    result = evaluate_model_capabilities(_model("kilo/nvidia-nemotron-3-ultra-550b-a55b-free"), ["chat"])
    assert result.eligible is True
    assert result.requirements.unsupported == ()
    assert result.requirements.unknown == ()

def test_legacy_image_requirement_maps_to_canonical_vision(gemini_catalog_entry):
    result = evaluate_model_capabilities(_model(gemini_catalog_entry.model_id), ["image"])
    assert result.eligible is True
    assert result.requirements.required == (ModelCapability.VISION,)
    assert result.requirements.unsupported == ()
    assert result.requirements.unknown == ()

def test_unknown_streaming_capability_is_not_treated_as_supported():
    result = evaluate_model_capabilities(_model("kilo/nvidia-nemotron-3-ultra-550b-a55b-free"), ["streaming"])
    assert result.eligible is False
    assert ModelCapability.STREAMING in result.requirements.unknown
    assert ModelCapability.STREAMING not in result.requirements.unsupported

def test_multi_capability_requirement_fails_closed_on_unknown(gemini_catalog_entry):
    result = evaluate_model_capabilities(
        _model(gemini_catalog_entry.model_id),
        ["chat", ModelCapability.VISION, "streaming"],
    )
    assert result.eligible is False
    assert ModelCapability.VISION not in result.requirements.unsupported
    assert ModelCapability.VISION not in result.requirements.unknown
    assert ModelCapability.STREAMING in result.requirements.unknown

def test_empty_requirement_preserves_candidate_order(gemini_catalog_entry):
    candidates = _catalog.CATALOG_MODELS[:3]
    assert filter_capability_eligible_models(candidates, None) == candidates
