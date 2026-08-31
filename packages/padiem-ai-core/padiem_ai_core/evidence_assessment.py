"""Deterministic claim assessment for Padiem AI Core.

Assessment is a bounded semantic projection over an immutable EvidenceGraph and,
optionally, an independently accepted validator verdict. It never grants trust,
authorization, entitlement, approval, or a universal truth score.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re

from .evidence_graph import ClaimEvidenceRelation, EvidenceGraph, EvidenceGraphError
from .evidence_verification import AcceptedVerification, VerificationDisposition


MAX_ASSESSMENT_EVIDENCE_IDS = 128
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class EvidenceAssessmentError(ValueError):
    """Safe assessment-contract validation failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("assessment error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise EvidenceAssessmentError(
            "invalid_assessment_contract",
            f"{name} must be a bounded safe identifier",
        )
    return value


class ClaimAssessmentState(str, Enum):
    """Deterministic semantic state derived from evidence/verifier inputs."""

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTED = "CONFLICTED"


@dataclass(frozen=True, slots=True)
class ClaimAssessment:
    """Bounded claim assessment with explicit evidence and verification posture."""

    claim_id: str
    state: ClaimAssessmentState
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    contextualizing_evidence_ids: tuple[str, ...]
    missing_supporting_evidence: bool
    verification_disposition: str | None = None
    validator_id: str | None = None
    verification_confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier("claim_id", self.claim_id))
        if not isinstance(self.state, ClaimAssessmentState):
            raise EvidenceAssessmentError(
                "invalid_assessment_contract",
                "state must be ClaimAssessmentState",
            )
        if not isinstance(self.missing_supporting_evidence, bool):
            raise EvidenceAssessmentError(
                "invalid_assessment_contract",
                "missing_supporting_evidence must be boolean",
            )

        for name in (
            "supporting_evidence_ids",
            "contradicting_evidence_ids",
            "contextualizing_evidence_ids",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) for value in values
            ):
                raise EvidenceAssessmentError(
                    "invalid_assessment_contract",
                    f"{name} must be a tuple of evidence identifiers",
                )
            normalized = tuple(_identifier(f"{name} item", value) for value in values)
            if len(normalized) > MAX_ASSESSMENT_EVIDENCE_IDS:
                raise EvidenceAssessmentError(
                    "assessment_budget_exceeded",
                    f"{name} exceeds the bounded evidence limit",
                )
            if len(set(normalized)) != len(normalized):
                raise EvidenceAssessmentError(
                    "invalid_assessment_contract",
                    f"{name} must not contain duplicates",
                )
            object.__setattr__(self, name, normalized)

        if self.verification_disposition is None:
            if self.validator_id is not None or self.verification_confidence is not None:
                raise EvidenceAssessmentError(
                    "invalid_assessment_contract",
                    "validator metadata requires a verification disposition",
                )
        else:
            object.__setattr__(
                self,
                "verification_disposition",
                _identifier("verification_disposition", self.verification_disposition),
            )
            if self.validator_id is None:
                raise EvidenceAssessmentError(
                    "invalid_assessment_contract",
                    "verification disposition requires validator_id",
                )
            object.__setattr__(
                self,
                "validator_id",
                _identifier("validator_id", self.validator_id),
            )
            if self.verification_confidence is not None and (
                isinstance(self.verification_confidence, bool)
                or not isinstance(self.verification_confidence, (int, float))
                or not math.isfinite(float(self.verification_confidence))
                or not 0.0 <= float(self.verification_confidence) <= 1.0
            ):
                raise EvidenceAssessmentError(
                    "invalid_assessment_confidence",
                    "verification confidence must be between 0 and 1 or None",
                )
            object.__setattr__(self, "verification_confidence", float(self.verification_confidence))

    def to_public_dict(self) -> dict[str, object]:
        """Return only bounded semantic evidence; never approval/trust authority."""

        return {
            "claim_id": self.claim_id,
            "state": self.state.value,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "contextualizing_evidence_ids": list(self.contextualizing_evidence_ids),
            "missing_supporting_evidence": self.missing_supporting_evidence,
            "verification": (
                None
                if self.verification_disposition is None
                else {
                    "disposition": self.verification_disposition,
                    "validator_id": self.validator_id,
                    "confidence": self.verification_confidence,
                }
            ),
        }


def _validate_verification(
    claim_id: str,
    verification: AcceptedVerification | None,
) -> tuple[str | None, str | None, float | None]:
    if verification is None:
        return None, None, None
    if not isinstance(verification, AcceptedVerification):
        raise EvidenceAssessmentError(
            "invalid_assessment_contract",
            "verification must be AcceptedVerification or None",
        )
    if (
        verification.request.claim_id != claim_id
        or verification.verdict.claim_id != claim_id
    ):
        raise EvidenceAssessmentError(
            "assessment_verification_mismatch",
            "verification does not belong to the assessed claim",
        )
    return (
        verification.verdict.disposition.value,
        verification.verdict.validator_id,
        verification.verdict.confidence,
    )


def assess_claim(
    graph: EvidenceGraph,
    claim_id: str,
    *,
    verification: AcceptedVerification | None = None,
) -> ClaimAssessment:
    """Assess one claim using only graph relations and an accepted verifier verdict.

    Rules are deliberately conservative: conflicting graph evidence wins over a
    single-sided validator result; evidence presence alone remains unverified.
    """

    if not isinstance(graph, EvidenceGraph):
        raise EvidenceAssessmentError(
            "invalid_assessment_contract",
            "graph must be EvidenceGraph",
        )
    claim_id = _identifier("claim_id", claim_id)
    try:
        graph.claim(claim_id)
        links = graph.links_for_claim(claim_id)
    except EvidenceGraphError as exc:
        raise EvidenceAssessmentError(
            "unknown_assessment_claim",
            "assessment references an unknown claim",
        ) from exc

    support_ids = tuple(
        link.evidence_id
        for link in links
        if link.relation is ClaimEvidenceRelation.SUPPORTS
    )
    contradiction_ids = tuple(
        link.evidence_id
        for link in links
        if link.relation is ClaimEvidenceRelation.CONTRADICTS
    )
    contextual_ids = tuple(
        link.evidence_id
        for link in links
        if link.relation is ClaimEvidenceRelation.CONTEXTUALIZES
    )

    for ids in (support_ids, contradiction_ids, contextual_ids):
        if len(ids) > MAX_ASSESSMENT_EVIDENCE_IDS:
            raise EvidenceAssessmentError(
                "assessment_budget_exceeded",
                "assessment contains too many evidence references",
            )

    disposition, validator_id, confidence = _validate_verification(claim_id, verification)

    if support_ids and contradiction_ids:
        state = ClaimAssessmentState.CONFLICTED
    elif (
        verification is not None
        and verification.verdict.disposition is VerificationDisposition.VERIFIED
        and support_ids
    ):
        state = ClaimAssessmentState.SUPPORTED
    elif (
        verification is not None
        and verification.verdict.disposition is VerificationDisposition.CONTRADICTED
        and contradiction_ids
    ):
        state = ClaimAssessmentState.CONTRADICTED
    else:
        state = ClaimAssessmentState.UNVERIFIED

    return ClaimAssessment(
        claim_id=claim_id,
        state=state,
        supporting_evidence_ids=support_ids,
        contradicting_evidence_ids=contradiction_ids,
        contextualizing_evidence_ids=contextual_ids,
        missing_supporting_evidence=not bool(support_ids),
        verification_disposition=disposition,
        validator_id=validator_id,
        verification_confidence=confidence,
    )
