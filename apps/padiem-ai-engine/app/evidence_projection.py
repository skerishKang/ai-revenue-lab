"""The single Engine-safe Evidence/Citation projection for every Engine transport.

Core owns Evidence semantics: source trust, grounding, verification, filtering,
deduplication and settled ordering (``padiem_ai_core.source_quality``,
``padiem_ai_core.grounding_runtime``, ``padiem_ai_core.evidence_graph``,
``padiem_ai_core.evidence_citation``, ``padiem_ai_core.evidence_verification``).
The Engine owns only this bounded transport projection:

* it accepts Core authority values and reuses Core public serialization
  verbatim, so no second Engine Evidence model exists;
* it preserves the Core-settled order and membership exactly; the Engine never
  re-sorts, re-filters, re-scores or re-deduplicates Evidence;
* it fails closed on any non-Core value, so private provider/runtime objects
  can never be serialized into public output;
* it normalizes absence: a run whose Core contract carries no grounded Evidence
  projects no Evidence fields at all rather than a fabricated empty verified set.

``execute``, ``stream`` and ``research`` terminal outputs must all be built
through :func:`project_terminal_evidence`, which is the parity chokepoint for
#1745. The orchestration path already returns Core's own
``OrchestrationResult.to_public_dict()`` evidence block; Engine passes that
Core-owned block through unmodified and must not double-project or fork it.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from padiem_ai_core import (
    AcceptedVerification,
    Evidence,
    EvidenceGraph,
    ExecutionResult,
    GroundedResearchResult,
    GroundedSynthesisResult,
    OrchestrationResult,
    StreamingExecutionEvent,
    project_grounded_citations,
)
from padiem_ai_core.evidence_citation import EvidenceCitationError

# Bounded public vocabulary mirrors of the Core-owned projections. The
# conformance tests re-derive these sets from live Core serialization so any
# Core-side schema drift fails loudly instead of silently widening the wire.
ENGINE_EVIDENCE_SOURCE_FIELDS = frozenset(
    {"id", "title", "url", "snippet", "retrieved_at", "provider", "source_type"}
)
ENGINE_EVIDENCE_CITATION_FIELDS = frozenset(
    {
        "citation_id",
        "claim_id",
        "evidence_id",
        "title",
        "url",
        "provider",
        "source_type",
        "relation",
        "checked_by_validator",
    }
)


class EngineEvidenceProjectionError(ValueError):
    """Fail-closed projection failure carrying only safe, bounded information."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def project_engine_evidence(evidence: Sequence[Any]) -> list[dict[str, Any]]:
    """Normalize one settled Core Evidence sequence for any Engine transport.

    Membership, ordering and deduplication are already Core authority (source
    trust selection, URL deduplication and context budget ran in Core). The
    Engine preserves them exactly and reuses ``Evidence.to_public_dict()``
    verbatim. Any non-Core value is rejected so private provider objects,
    raw responses or hidden context can never reach public output.
    """
    if isinstance(evidence, (str, bytes, bytearray)) or not isinstance(evidence, Sequence):
        raise EngineEvidenceProjectionError(
            "invalid_evidence_projection",
            "Engine evidence must be a sequence of Core evidence.",
        )
    projected: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, Evidence):
            raise EngineEvidenceProjectionError(
                "invalid_evidence_projection",
                "Engine evidence must be a sequence of Core evidence.",
            )
        projected.append(item.to_public_dict())
    return projected


def project_engine_citation_bundles(
    graph: EvidenceGraph,
    claim_ids: Sequence[str],
    *,
    verifications: Mapping[str, AcceptedVerification] | None = None,
) -> list[dict[str, Any]]:
    """Project claim-level citations through the single Core citation authority.

    Delegates to ``project_grounded_citations`` so a citation can only ever
    reference Evidence that is still present in the graph: evidence removed by
    Core trust/context policy cannot be cited, and a verification disposition
    is attached only from an independently accepted validator verdict.
    """
    if not isinstance(graph, EvidenceGraph):
        raise EngineEvidenceProjectionError(
            "invalid_citation_projection",
            "Engine citations require a Core evidence graph.",
        )
    if isinstance(claim_ids, (str, bytes, bytearray)) or not isinstance(claim_ids, Sequence):
        raise EngineEvidenceProjectionError(
            "invalid_citation_projection",
            "Engine citation claim ids must be a sequence.",
        )
    bundles: list[dict[str, Any]] = []
    for claim_id in claim_ids:
        verification = (
            None if verifications is None else verifications.get(claim_id)
        )
        try:
            bundle = project_grounded_citations(
                graph,
                claim_id,
                verification=verification,
            )
        except EvidenceCitationError as exc:
            raise EngineEvidenceProjectionError(exc.code, exc.safe_message) from None
        bundles.append(bundle.to_public_dict())
    return bundles


def project_terminal_evidence(result: Any) -> dict[str, Any]:
    """Return the canonical Engine evidence fields for one settled terminal value.

    This is the single chokepoint every Engine transport uses when it builds a
    terminal output, so transports cannot invent their own Evidence shape:

    * ``GroundedSynthesisResult`` / ``GroundedResearchResult``: Core's settled
      prepared Evidence tuple is projected as ``sources``.
    * ``ExecutionResult`` / ``StreamingExecutionEvent``: the Core contract for a
      plain model run carries no grounded Evidence, so nothing is projected.
      Absence is the normalized unavailable state; it is never a claim that the
      answer was verified, and no citations are fabricated mid-stream.
    * ``OrchestrationResult``: Core already owns the public evidence block in
      ``to_public_dict()``; Engine forwards it unmodified and adds nothing.

    Unknown values fail closed.
    """
    if isinstance(result, (GroundedSynthesisResult, GroundedResearchResult)):
        return {"sources": project_engine_evidence(result.prepared.evidence)}
    if isinstance(result, (ExecutionResult, StreamingExecutionEvent, OrchestrationResult)):
        return {}
    raise EngineEvidenceProjectionError(
        "invalid_evidence_projection",
        "Engine terminal result is not a Core authority value.",
    )
