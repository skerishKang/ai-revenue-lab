from app.pilot.capability_evidence import ModelCapability
from app.pilot.capability_routing import (
    evaluate_model_capabilities,
    filter_capability_eligible_models,
)
from app.pilot import catalog as _catalog

def _model(model_id: str):
    # Existing exact JSON models are authoritative; test-only Gemini fixtures
    # may still be scoped into the legacy scorer list.
    return next(
        (model for model in _catalog.CATALOG_MODELS if model.model_id == model_id),
        _catalog.get_catalog_by_id(model_id),
    )

def _chat_only_subject() -> str:
    """A catalog identity the legacy tag routes for chat but not streaming.

    #7241 3a: the subject model the legacy-tag cases drive is a deployment
    value, so it is read from the live catalog rather than written here. The
    selector asks the scorer itself which rows are chat-eligible while leaving
    streaming unknown — exactly the row these contracts describe — and takes
    the first by catalog order so the choice is deterministic.
    """
    seen: list[str] = []
    for row in _catalog.CATALOG_MODELS:
        if row.model_id not in seen:
            seen.append(row.model_id)
    for model_id in list(_catalog.CATALOG_BY_ID):
        if model_id not in seen:
            seen.append(model_id)
    for model_id in seen:
        model = _model(model_id)
        if model is None or not model.enabled:
            continue
        chat = evaluate_model_capabilities(model, ["chat"])
        streaming = evaluate_model_capabilities(model, ["streaming"])
        if chat.eligible and not streaming.eligible:
            return model_id
    raise AssertionError("no catalog identity routes chat but leaves streaming unknown")


def test_chat_capability_is_eligible_from_configured_legacy_tag():
    result = evaluate_model_capabilities(_model(_chat_only_subject()), ["chat"])
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
    result = evaluate_model_capabilities(_model(_chat_only_subject()), ["streaming"])
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
