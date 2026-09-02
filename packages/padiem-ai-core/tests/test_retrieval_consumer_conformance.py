"""Cross-primitive conformance for product retrieval consumers.

This suite deliberately contains no product locator grammar, storage schema, model
route, provider credential, or network call.  It locks the reusable composition
proved by a real product consumer: product-owned candidate meaning -> Core
permission projection -> resolve only allowed bytes -> Core bounded retrieval
context.
"""

from __future__ import annotations

import pytest

from padiem_ai_core.context_permission import (
    BoundaryDisposition,
    ContextCandidate,
    ContextEnvelope,
    ContextFilterReason,
    KnowledgeBoundary,
    narrow_knowledge_boundary,
    project_context_permission,
)
from padiem_ai_core.context_policy import ContextTrust
from padiem_ai_core.retrieval import (
    RetrievalContractError,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievedItem,
    prepare_retrieval_context,
)


NAMESPACE = "product.reader"
CURRENT_SCOPE = "scope/current"
FUTURE_SCOPE = "scope/future"
NOTES_SCOPE = "scope/notes"


def _request(*, max_results: int = 8) -> RetrievalRequest:
    return RetrievalRequest(
        query="Explain the relevant supplied material",
        namespaces=(NAMESPACE,),
        max_results=max_results,
    )


def _item(
    item_id: str,
    *,
    content: str,
    namespace: str = NAMESPACE,
) -> RetrievedItem:
    return RetrievedItem(
        id=item_id,
        namespace=namespace,
        source_type="product_corpus",
        provider="product_adapter",
        source_ref=f"source:{item_id}",
        title=f"Reference {item_id}",
        content=content,
    )


def _candidate(
    item: RetrievedItem,
    *,
    scope_id: str,
    user_asserted_permission: bool = False,
) -> ContextCandidate:
    return ContextCandidate(
        id=f"ctx/{item.id}",
        scope_id=scope_id,
        resource_ref=f"retrieval/{item.id}",
        provenance=("retrieval", "product_adapter"),
        source_quality_selected=True,
        user_asserted_permission=user_asserted_permission,
    )


def _envelope(*candidates: ContextCandidate) -> ContextEnvelope:
    return ContextEnvelope(
        app_id="product-reference",
        request_id="req/retrieval-conformance",
        candidates=tuple(candidates),
        source_quality_gate_applied=True,
        policy_hints=("product_domain_projection_complete",),
    )


def _boundary(*, available: bool = True) -> KnowledgeBoundary:
    return KnowledgeBoundary(
        allowed_scope_ids=(CURRENT_SCOPE,),
        boundary_available=available,
        require_trusted_boundary=True,
        max_allowed_context=8,
    )


def _resolve_allowed_items(
    projection,
    item_by_candidate_id: dict[str, RetrievedItem],
) -> tuple[RetrievedItem, ...]:
    """Test-only resolver: reference bytes are resolved *after* permission."""

    return tuple(item_by_candidate_id[candidate.id] for candidate in projection.allowed_context)


def test_allowed_ids_are_the_only_reference_bytes_prepared_for_model_context() -> None:
    allowed_text = "allowed reference bytes"
    future_text = "filtered future reference bytes must never be model visible"
    allowed = _item("allowed_1", content=allowed_text)
    future = _item("future_1", content=future_text)
    allowed_candidate = _candidate(allowed, scope_id=CURRENT_SCOPE)
    future_candidate = _candidate(future, scope_id=FUTURE_SCOPE)

    projection = project_context_permission(
        _envelope(allowed_candidate, future_candidate),
        _boundary(),
    )

    assert projection.disposition is BoundaryDisposition.PERMITTED
    assert projection.allowed_context == (allowed_candidate,)
    assert projection.filtered_context[0].candidate == future_candidate
    assert ContextFilterReason.OUTSIDE_ALLOWED_SCOPE in projection.filtered_context[0].reason_codes

    by_candidate = {
        allowed_candidate.id: allowed,
        future_candidate.id: future,
    }
    resolved = _resolve_allowed_items(projection, by_candidate)
    assert tuple(item.id for item in resolved) == ("allowed_1",)

    prepared = prepare_retrieval_context(
        _request(max_results=2),
        resolved,
        policy=RetrievalPolicy(max_results=2),
    )

    assert prepared.context.reference_context is not None
    assert allowed_text in prepared.context.reference_context
    assert future_text not in prepared.context.reference_context
    assert prepared.context.trusted_system_context is None
    assert all(
        fragment.trust is ContextTrust.UNTRUSTED_REFERENCE
        for fragment in prepared.context.references
    )


def test_all_filtered_candidates_create_no_execution_eligible_reference_context() -> None:
    future = _item("future_only", content="future-only bytes")
    candidate = _candidate(future, scope_id=FUTURE_SCOPE)

    projection = project_context_permission(_envelope(candidate), _boundary())

    assert projection.disposition is BoundaryDisposition.OUTSIDE_KNOWLEDGE_BOUNDARY
    assert projection.allowed_context == ()
    assert _resolve_allowed_items(projection, {candidate.id: future}) == ()


def test_missing_required_boundary_fails_closed_before_reference_resolution() -> None:
    item = _item("known_1", content="known but not authorized without a boundary")
    candidate = _candidate(item, scope_id=CURRENT_SCOPE)

    projection = project_context_permission(
        _envelope(candidate),
        _boundary(available=False),
    )

    assert projection.disposition is BoundaryDisposition.BOUNDARY_UNAVAILABLE
    assert projection.allowed_context == ()
    assert projection.filtered_context[0].reason_codes == (
        ContextFilterReason.BOUNDARY_UNAVAILABLE,
    )
    assert _resolve_allowed_items(projection, {candidate.id: item}) == ()


def test_user_self_asserted_permission_cannot_rescue_candidate() -> None:
    item = _item("self_asserted", content="caller cannot make this trusted")
    candidate = _candidate(
        item,
        scope_id=CURRENT_SCOPE,
        user_asserted_permission=True,
    )

    projection = project_context_permission(_envelope(candidate), _boundary())

    assert projection.allowed_context == ()
    assert ContextFilterReason.USER_SELF_ASSERTED_PERMISSION in (
        projection.filtered_context[0].reason_codes
    )


def test_product_narrowing_removes_otherwise_permitted_scope() -> None:
    current = _item("current_1", content="current")
    note = _item("note_1", content="note")
    current_candidate = _candidate(current, scope_id=CURRENT_SCOPE)
    note_candidate = _candidate(note, scope_id=NOTES_SCOPE)
    broad = KnowledgeBoundary(
        allowed_scope_ids=(CURRENT_SCOPE, NOTES_SCOPE),
        max_allowed_context=8,
    )
    narrowed = narrow_knowledge_boundary(
        broad,
        allowed_scope_ids=(CURRENT_SCOPE,),
    )

    projection = project_context_permission(
        _envelope(current_candidate, note_candidate),
        narrowed,
    )

    assert projection.allowed_context == (current_candidate,)
    assert projection.filtered_context[0].candidate == note_candidate
    assert ContextFilterReason.OUTSIDE_ALLOWED_SCOPE in projection.filtered_context[0].reason_codes


def test_out_of_namespace_item_fails_closed_when_resolved_for_context() -> None:
    outside = _item(
        "outside_ns",
        content="wrong namespace",
        namespace="private.other",
    )
    candidate = _candidate(outside, scope_id=CURRENT_SCOPE)
    projection = project_context_permission(_envelope(candidate), _boundary())
    resolved = _resolve_allowed_items(projection, {candidate.id: outside})

    with pytest.raises(RetrievalContractError) as exc_info:
        prepare_retrieval_context(_request(), resolved)

    assert exc_info.value.code == "retrieval_scope_violation"


def test_duplicate_retrieval_ids_cannot_multiply_model_visible_context() -> None:
    first = _item("duplicate", content="first copy")
    second = _item("duplicate", content="second copy")
    first_candidate = ContextCandidate(
        id="ctx/duplicate/1",
        scope_id=CURRENT_SCOPE,
        resource_ref="retrieval/duplicate/1",
        provenance=("retrieval",),
    )
    second_candidate = ContextCandidate(
        id="ctx/duplicate/2",
        scope_id=CURRENT_SCOPE,
        resource_ref="retrieval/duplicate/2",
        provenance=("retrieval",),
    )
    projection = project_context_permission(
        _envelope(first_candidate, second_candidate),
        _boundary(),
    )
    resolved = _resolve_allowed_items(
        projection,
        {
            first_candidate.id: first,
            second_candidate.id: second,
        },
    )

    with pytest.raises(RetrievalContractError) as exc_info:
        prepare_retrieval_context(_request(max_results=2), resolved)

    assert exc_info.value.code == "duplicate_retrieval_item"


def test_public_diagnostics_never_contain_reference_content_or_provider_secret_material() -> None:
    secret_like = "private-reference-content-should-not-appear"
    allowed = _item("safe_meta", content=secret_like)
    future = _item("filtered_meta", content="future-private-reference")
    allowed_candidate = _candidate(allowed, scope_id=CURRENT_SCOPE)
    future_candidate = _candidate(future, scope_id=FUTURE_SCOPE)

    projection = project_context_permission(
        _envelope(allowed_candidate, future_candidate),
        _boundary(),
    )
    public_projection = projection.to_public_dict()
    prepared = prepare_retrieval_context(
        _request(max_results=2),
        _resolve_allowed_items(
            projection,
            {
                allowed_candidate.id: allowed,
                future_candidate.id: future,
            },
        ),
    )
    public_retrieval = prepared.to_public_dict()
    rendered = repr((public_projection, public_retrieval))

    assert secret_like not in rendered
    assert "future-private-reference" not in rendered
    assert "authorization" not in rendered.lower()
    assert "credential" not in rendered.lower()
    assert public_projection["diagnostics"]["context_allowed_count"] == 1
    assert public_projection["diagnostics"]["context_filtered_count"] == 1
