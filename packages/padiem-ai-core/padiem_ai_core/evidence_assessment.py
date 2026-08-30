"""Deterministic claim assessment for the P01 Evidence/Verification layer.

Assessment is descriptive state derived from the existing provenance graph and
accepted independent validator verdicts. It never grants trust, authorization,
entitlement or human approval, and it never fabricates confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .evidence_graph import ClaimEvidenceRelation, EvidenceGraph
from .evidence_verification import AcceptedVerification, VerificationDisposition


class ClaimAssessmentState(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"
    CONFLICTED = "conflicted"


@dataclass(frozen=True, slots=True)
class ClaimAssessment:
    claim_id: str
    state: ClaimAssessmentState
    supporting_evidence_ids: tuple[str, ...] = ()
    contradicting_evidence_ids: tuple[str, ...] = ()
    checked_evidence_ids: tuple[str, ...] = ()
    missing_evidence: bool = False
    confidence: float | None = None
    validator_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not self.claim_id:
            raise ValueError("claim_id must be non-empty")
        if not isinstance(self.state, ClaimAssessmentState):
            raise ValueError("state must be ClaimAssessmentState")
        for name in (
            "supporting_evidence_ids",
            "contradicting_evidence_ids",
            "checked_evidence_ids",
            "validator_ids",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise ValueError(f"{name} must be a tuple")
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{name} must contain non-empty identifiers")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must not contain duplicates")
        if not isinstance(self.missing_evidence, bool):
            raise ValueError("missing_evidence must be boolean")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1 or None")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "state": self.state.value,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "checked_evidence_ids": list(self.checked_evidence_ids),
            "missing_evidence": self.missing_evidence,
            "confidence": self.confidence,
            "validator_ids": list(self.validator_ids),
        }


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def assess_claim(
    graph: EvidenceGraph,
    claim_id: str,
    *,
    accepted_verifications: Sequence[AcceptedVerification] = (),
) -> ClaimAssessment:
    """Derive a deterministic descriptive state for one claim.

    Rules, in precedence order:
    - an accepted validator saying CONTRADICTED contributes contradiction;
    - an accepted validator saying VERIFIED contributes support;
    - graph support/contradiction links remain visible even without a verdict;
    - both checked support and checked contradiction yield CONFLICTED;
    - otherwise VERIFIED yields SUPPORTED and CONTRADICTED yields CONTRADICTED;
    - no accepted verdict and no direct source link yields UNVERIFIED.

    Numeric confidence is copied only when every accepted verdict contributing to
    the selected disposition agrees on the same explicit value; otherwise it stays
    unknown. Human approval is intentionally outside this function.
    """
    if not isinstance(graph, EvidenceGraph):
        raise ValueError("graph must be EvidenceGraph")
    claim = graph.claim(claim_id)
    links = graph.links_for_claim(claim.id)
    supporting = _unique(tuple(link.evidence_id for link in links if link.relation is ClaimEvidenceRelation.SUPPORTS))
    contradicting = _unique(tuple(link.evidence_id for link in links if link.relation is ClaimEvidenceRelation.CONTRADICTS))

    relevant = tuple(
        verification
        for verification in accepted_verifications
        if verification.request.claim_id == claim.id
    )
    checked = _unique(tuple(evidence_id for verification in relevant for evidence_id in verification.verdict.checked_evidence_ids))
    validator_ids = _unique(tuple(verification.verdict.validator_id for verification in relevant))

    verified_verdicts = tuple(v for v in relevant if v.verdict.disposition is VerificationDisposition.VERIFIED)
    contradicted_verdicts = tuple(v for v in relevant if v.verdict.disposition is VerificationDisposition.CONTRADICTED)

    has_verified = bool(verified_verdicts)
    has_contradicted = bool(contradicted_verdicts)
    checked_support = any(
        evidence_id in supporting
        for evidence_id in checked
    )
    checked_contradiction = any(
        evidence_id in contradicting
        for evidence_id in checked
    )

    if (has_verified or checked_support) and (has_contradicted or checked_contradiction):
        state = ClaimAssessmentState.CONFLICTED
    elif has_contradicted:
        state = ClaimAssessmentState.CONTRADICTED
    elif has_verified:
        state = ClaimAssessmentState.SUPPORTED
    elif contradicting and not supporting:
        state = ClaimAssessmentState.CONTRADICTED
    elif supporting:
        state = ClaimAssessmentState.SUPPORTED
    else:
        state = ClaimAssessmentState.UNVERIFIED

    explicit_confidences = {
        float(v.verdict.confidence)
        for v in relevant
        if v.verdict.confidence is not None
    }
    confidence = explicit_confidences.pop() if len(explicit_confidences) == 1 else None
    if state is ClaimAssessmentState.CONFLICTED:
        confidence = None

    missing_evidence = not supporting and not contradicting and not checked

    return ClaimAssessment(
        claim_id=claim.id,
        state=state,
        supporting_evidence_ids=supporting,
        contradicting_evidence_ids=contradicting,
        checked_evidence_ids=checked,
        missing_evidence=missing_evidence,
        confidence=confidence,
        validator_ids=validator_ids,
    )
