import pytest

from app.pilot.capability_evidence import (
    CapabilityEvidenceError,
    CapabilityEvidenceKind,
    CapabilitySupport,
    ModelCapability,
    ModelCapabilityEvidence,
    capability_profile_from_catalog_model,
    evaluate_capability_requirements,
)
from app.pilot.catalog import get_catalog_by_id


def model(model_id: str):
    result = get_catalog_by_id(model_id)
    assert result is not None
    return result


def test_legacy_supported_tags_map_to_canonical_configured_support() -> None:
    profile = capability_profile_from_catalog_model(
        model("google/gemini-2.5-flash")
    )

    assert profile.evidence_for(ModelCapability.CHAT).support is CapabilitySupport.SUPPORTED
    assert profile.evidence_for(ModelCapability.CHAT).evidence_kind is CapabilityEvidenceKind.CONFIGURED
    assert profile.evidence_for(ModelCapability.VISION).support is CapabilitySupport.SUPPORTED
    assert profile.evidence_for(ModelCapability.CODING).support is CapabilitySupport.SUPPORTED
    assert profile.evidence_for(ModelCapability.LONG_CONTEXT).support is CapabilitySupport.SUPPORTED


def test_absent_legacy_tag_is_unknown_not_unsupported() -> None:
    profile = capability_profile_from_catalog_model(
        model("google/gemini-2.5-flash")
    )

    for capability in (
        ModelCapability.STREAMING,
        ModelCapability.FILE_DOCUMENT,
        ModelCapability.STRUCTURED_OUTPUT,
        ModelCapability.TOOL_CALLING,
        ModelCapability.REASONING,
    ):
        evidence = profile.evidence_for(capability)
        assert evidence.support is CapabilitySupport.UNKNOWN
        assert evidence.evidence_kind is CapabilityEvidenceKind.NONE


def test_free_legacy_tag_is_not_execution_capability() -> None:
    profile = capability_profile_from_catalog_model(model("openrouter/free"))

    assert all(entry.capability.value != "free" for entry in profile.entries)
    assert profile.evidence_for(ModelCapability.CHAT).support is CapabilitySupport.SUPPORTED
    assert profile.evidence_for(ModelCapability.STREAMING).support is CapabilitySupport.UNKNOWN


def test_requirement_evaluation_distinguishes_unknown_from_unsupported() -> None:
    base = model("google/gemini-2.5-flash")
    profile = capability_profile_from_catalog_model(
        base,
        explicit_evidence=(
            ModelCapabilityEvidence(
                capability=ModelCapability.TOOL_CALLING,
                support=CapabilitySupport.UNSUPPORTED,
                evidence_kind=CapabilityEvidenceKind.UPSTREAM_REPORTED,
                evidence_ref="upstream:openrouter:model-capabilities",
                observed_at="2026-08-30T15:00:00Z",
            ),
        ),
    )

    result = evaluate_capability_requirements(
        profile,
        (
            ModelCapability.CHAT,
            ModelCapability.STREAMING,
            ModelCapability.TOOL_CALLING,
        ),
    )

    assert result.satisfied is False
    assert result.unknown == (ModelCapability.STREAMING,)
    assert result.unsupported == (ModelCapability.TOOL_CALLING,)


def test_explicit_supported_evidence_can_fill_unknown_without_changing_catalog() -> None:
    base = model("google/gemini-2.5-flash")
    assert "streaming" not in base.capabilities

    profile = capability_profile_from_catalog_model(
        base,
        explicit_evidence=(
            ModelCapabilityEvidence(
                capability=ModelCapability.STREAMING,
                support=CapabilitySupport.SUPPORTED,
                evidence_kind=CapabilityEvidenceKind.MEASURED,
                evidence_ref="probe:streaming:gemini-flash",
                observed_at="2026-08-30T15:10:00+00:00",
            ),
        ),
    )

    assert profile.evidence_for(ModelCapability.STREAMING).support is CapabilitySupport.SUPPORTED
    assert "streaming" not in base.capabilities


def test_known_capability_state_requires_provenance() -> None:
    with pytest.raises(CapabilityEvidenceError) as exc_info:
        ModelCapabilityEvidence(
            capability=ModelCapability.STREAMING,
            support=CapabilitySupport.SUPPORTED,
            evidence_kind=CapabilityEvidenceKind.NONE,
        )
    assert exc_info.value.code == "invalid_capability_evidence"


def test_unknown_capability_must_not_carry_fake_evidence() -> None:
    with pytest.raises(CapabilityEvidenceError) as exc_info:
        ModelCapabilityEvidence(
            capability=ModelCapability.STREAMING,
            support=CapabilitySupport.UNKNOWN,
            evidence_kind=CapabilityEvidenceKind.CONFIGURED,
            evidence_ref="catalog:fake",
        )
    assert exc_info.value.code == "invalid_capability_evidence"


def test_upstream_and_measured_evidence_require_timezone_aware_timestamp() -> None:
    with pytest.raises(CapabilityEvidenceError):
        ModelCapabilityEvidence(
            capability=ModelCapability.STREAMING,
            support=CapabilitySupport.SUPPORTED,
            evidence_kind=CapabilityEvidenceKind.MEASURED,
            evidence_ref="probe:stream",
            observed_at="2026-08-30T15:10:00",
        )

    evidence = ModelCapabilityEvidence(
        capability=ModelCapability.STREAMING,
        support=CapabilitySupport.SUPPORTED,
        evidence_kind=CapabilityEvidenceKind.MEASURED,
        evidence_ref="probe:stream",
        observed_at="2026-08-30T15:10:00Z",
    )
    assert evidence.observed_at == "2026-08-30T15:10:00Z"


def test_duplicate_explicit_capability_evidence_fails_closed() -> None:
    entry = ModelCapabilityEvidence(
        capability=ModelCapability.STREAMING,
        support=CapabilitySupport.UNSUPPORTED,
        evidence_kind=CapabilityEvidenceKind.UPSTREAM_REPORTED,
        evidence_ref="upstream:streaming",
        observed_at="2026-08-30T15:00:00Z",
    )

    with pytest.raises(CapabilityEvidenceError) as exc_info:
        capability_profile_from_catalog_model(
            model("openrouter/free"),
            explicit_evidence=(entry, entry),
        )
    assert exc_info.value.code == "duplicate_capability_evidence"
