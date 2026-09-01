from __future__ import annotations

import pytest

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.context_permission import (
    BoundaryDisposition,
    ContextCandidate,
    ContextEnvelope,
    ContextFilterReason,
    ContextPermissionError,
    KnowledgeBoundary,
    candidate_from_evidence,
    context_envelope_from_source_selection,
    narrow_knowledge_boundary,
    project_context_permission,
)
from padiem_ai_core.source_quality import SourceQualitySelection


def evidence(evidence_id: str, *, title: str | None = None) -> Evidence:
    return Evidence(
        id=evidence_id,
        title=title or f"Evidence {evidence_id}",
        snippet="bounded source-quality-selected evidence",
        retrieved_at="2026-09-01T00:00:00Z",
        provider="mock",
        source_type="web",
        url=f"https://example.com/{evidence_id}",
    )


def candidate(
    candidate_id: str,
    *,
    scope_id: str = "scope/current",
    resource_ref: str | None = None,
    source_quality_selected: bool = True,
    user_asserted_permission: bool = False,
) -> ContextCandidate:
    ev = evidence(candidate_id.replace("/", "-"))
    return ContextCandidate(
        id=candidate_id,
        scope_id=scope_id,
        resource_ref=resource_ref or f"resource/{candidate_id}",
        evidence=ev,
        provenance=("test",),
        source_quality_selected=source_quality_selected,
        user_asserted_permission=user_asserted_permission,
    )


def envelope(*items: ContextCandidate, source_quality_gate_applied: bool = True) -> ContextEnvelope:
    return ContextEnvelope(
        app_id="p01/core",
        request_id="req/test",
        candidates=tuple(items),
        source_quality_gate_applied=source_quality_gate_applied,
    )


def boundary(**kwargs) -> KnowledgeBoundary:
    defaults = {"allowed_scope_ids": ("scope/current",)}
    defaults.update(kwargs)
    return KnowledgeBoundary(**defaults)


def test_relevant_trusted_evidence_outside_allowed_boundary_is_filtered() -> None:
    item = candidate("ctx/outside", scope_id="scope/future")
    projection = project_context_permission(envelope(item), boundary())

    assert projection.disposition is BoundaryDisposition.OUTSIDE_KNOWLEDGE_BOUNDARY
    assert projection.allowed_context == ()
    assert projection.filtered_context[0].candidate.id == "ctx/outside"
    assert ContextFilterReason.OUTSIDE_ALLOWED_SCOPE in projection.filtered_context[0].reason_codes


def test_relevant_trusted_and_permitted_context_is_retained() -> None:
    item = candidate("ctx/permitted")
    projection = project_context_permission(envelope(item), boundary())

    assert projection.disposition is BoundaryDisposition.PERMITTED
    assert projection.allowed_context == (item,)
    assert projection.filtered_context == ()


def test_source_quality_rejected_context_is_not_resurrected_by_permission_gate() -> None:
    selected = candidate("ctx/selected")
    rejected_by_1308 = candidate("ctx/rejected", source_quality_selected=False)

    projection = project_context_permission(envelope(selected, rejected_by_1308), boundary())

    assert projection.allowed_context == (selected,)
    rejected = projection.filtered_context[0]
    assert rejected.candidate.id == "ctx/rejected"
    assert ContextFilterReason.SOURCE_QUALITY_NOT_SELECTED in rejected.reason_codes


def test_context_envelope_reuses_source_quality_selection_without_reranking() -> None:
    first = evidence("ev1")
    second = evidence("ev2")
    selection = SourceQualitySelection(evidence=(first, second), assessments=(), rejected_count=3)

    prepared = context_envelope_from_source_selection(
        app_id="p01/core",
        request_id="req/source-selection",
        selection=selection,
        scope_id="scope/current",
    )

    assert prepared.source_quality_gate_applied is True
    assert [item.evidence.id for item in prepared.candidates if item.evidence is not None] == ["ev1", "ev2"]
    assert prepared.policy_hints == ("source_quality_selection_accepted",)


def test_user_cannot_self_assert_permission_to_widen_boundary() -> None:
    item = candidate("ctx/self-asserted", scope_id="scope/future", user_asserted_permission=True)
    projection = project_context_permission(envelope(item), boundary())

    assert projection.allowed_context == ()
    reasons = projection.filtered_context[0].reason_codes
    assert ContextFilterReason.USER_SELF_ASSERTED_PERMISSION in reasons
    assert ContextFilterReason.OUTSIDE_ALLOWED_SCOPE in reasons


def test_missing_required_trusted_boundary_fails_closed() -> None:
    item = candidate("ctx/known")
    projection = project_context_permission(envelope(item), boundary(boundary_available=False))

    assert projection.disposition is BoundaryDisposition.BOUNDARY_UNAVAILABLE
    assert projection.allowed_context == ()
    assert projection.filtered_context[0].reason_codes == (ContextFilterReason.BOUNDARY_UNAVAILABLE,)


def test_product_adapter_can_narrow_scope_deterministically() -> None:
    base = KnowledgeBoundary(allowed_scope_ids=("scope/current", "scope/notes"), max_allowed_context=4)
    narrowed = narrow_knowledge_boundary(
        base,
        allowed_scope_ids=("scope/current",),
        denied_resource_refs=("resource/ctx/secret",),
        max_allowed_context=1,
    )

    assert narrowed.allowed_scope_ids == ("scope/current",)
    assert narrowed.max_allowed_context == 1
    assert narrowed.denied_resource_refs == ("resource/ctx/secret",)

    allowed = candidate("ctx/current", scope_id="scope/current")
    outside = candidate("ctx/notes", scope_id="scope/notes")
    projection = project_context_permission(envelope(allowed, outside), narrowed)
    assert projection.allowed_context == (allowed,)
    assert projection.filtered_context[0].candidate == outside


def test_product_adapter_cannot_disable_mandatory_fail_closed_behavior() -> None:
    with pytest.raises(ContextPermissionError, match="cannot be disabled"):
        KnowledgeBoundary(allowed_scope_ids=("scope/current",), require_trusted_boundary=False)


def test_same_inputs_produce_deterministic_projection() -> None:
    first = candidate("ctx/1")
    second = candidate("ctx/2", scope_id="scope/future")
    env = envelope(first, second)
    bound = boundary()

    left = project_context_permission(env, bound).to_public_dict()
    right = project_context_permission(env, bound).to_public_dict()

    assert left == right


def test_bounded_candidate_and_context_limits_are_enforced() -> None:
    with pytest.raises(ContextPermissionError, match="candidates exceed"):
        envelope(*(candidate(f"ctx/{i}") for i in range(33)))

    items = tuple(candidate(f"ctx/limit-{i}") for i in range(3))
    projection = project_context_permission(envelope(*items), boundary(max_allowed_context=2))

    assert [item.id for item in projection.allowed_context] == ["ctx/limit-0", "ctx/limit-1"]
    assert projection.filtered_context[0].candidate.id == "ctx/limit-2"
    assert projection.filtered_context[0].reason_codes == (ContextFilterReason.CONTEXT_LIMIT_EXCEEDED,)


def test_denied_resource_overrides_allowed_scope() -> None:
    item = candidate("ctx/denied", resource_ref="resource/secret")
    projection = project_context_permission(
        envelope(item),
        boundary(denied_resource_refs=("resource/secret",)),
    )

    assert projection.allowed_context == ()
    assert ContextFilterReason.DENIED_RESOURCE in projection.filtered_context[0].reason_codes


def test_public_diagnostics_are_bounded_and_do_not_expose_context_bytes() -> None:
    allowed = candidate("ctx/allowed")
    filtered = candidate("ctx/filtered", scope_id="scope/future")
    projection = project_context_permission(envelope(allowed, filtered), boundary())

    public = projection.to_public_dict()
    assert public["diagnostics"] == {
        "context_candidate_count": 2,
        "context_allowed_count": 1,
        "context_filtered_count": 1,
        "boundary_disposition": "permitted",
        "filter_reason_codes": ["outside_allowed_scope"],
        "policy_version": "context-permission:v1",
        "source_quality_gate_applied": True,
    }
    assert "bounded source-quality-selected evidence" not in repr(public["allowed_context"])


def test_core_contract_remains_product_neutral_without_b61_b62_b14_semantics() -> None:
    item = candidate("ctx/generic", scope_id="scope/current")
    projection = project_context_permission(envelope(item), boundary())

    rendered = repr(projection.to_public_dict())
    assert "StoryMemory" not in rendered
    assert "B61" not in rendered
    assert "B62" not in rendered
    assert "B14" not in rendered
