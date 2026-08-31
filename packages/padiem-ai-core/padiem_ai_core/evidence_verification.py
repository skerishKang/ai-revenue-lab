"""Independent, product-neutral verification hook for Padiem AI Core.

This module layers a validator verdict over ``EvidenceGraph`` without turning
Core into Business 48's verification product. It deliberately separates:

- claim provenance from verification;
- producer identity from validator identity;
- validator verdict from any later human approval;
- unknown confidence from numeric confidence.

A validator may be implemented by a product, service, human-assisted workflow,
or bounded model-backed adapter, but trusted server policy must identify it as
independent from the claim producer before Core accepts the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Protocol

from .evidence_graph import (
    ClaimEvidenceRelation,
    EvidenceGraph,
    EvidenceGraphError,
)


MAX_VERIFICATION_EVIDENCE_IDS = 64
MAX_VERIFICATION_SUMMARY_CHARS = 2_000
MAX_ALLOWED_VALIDATORS = 64

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class EvidenceVerificationError(ValueError):
    """Safe verification-contract validation failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("verification error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise EvidenceVerificationError(
            "invalid_verification_contract",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _identifier_tuple(
    name: str,
    values: tuple[str, ...],
    *,
    maximum: int,
    require_non_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise EvidenceVerificationError(
            "invalid_verification_contract",
            f"{name} must be a tuple of identifiers",
        )
    checked = tuple(_identifier(name, value) for value in values)
    if require_non_empty and not checked:
        raise EvidenceVerificationError(
            "invalid_verification_contract",
            f"{name} must not be empty",
        )
    if len(checked) > maximum:
        raise EvidenceVerificationError(
            "verification_budget_exceeded",
            f"{name} exceeds the bounded verification limit",
        )
    if len(set(checked)) != len(checked):
        raise EvidenceVerificationError(
            "invalid_verification_contract",
            f"{name} must not contain duplicates",
        )
    return checked


class VerificationDisposition(str, Enum):
    """Independent validator result; never a human approval state."""

    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    """One claim submitted for an independent validator decision."""

    claim_id: str
    producer_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier("claim_id", self.claim_id))
        object.__setattr__(
            self,
            "producer_id",
            _identifier("producer_id", self.producer_id),
        )


@dataclass(frozen=True, slots=True)
class VerificationVerdict:
    """Bounded validator verdict with explicit evidence inspection record.

    ``confidence`` is optional. ``None`` means the validator did not provide a
    defensible numeric confidence and Core preserves that unknown state rather
    than fabricating one.
    """

    verdict_id: str
    claim_id: str
    validator_id: str
    disposition: VerificationDisposition
    checked_evidence_ids: tuple[str, ...] = ()
    confidence: float | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "verdict_id",
            _identifier("verdict_id", self.verdict_id),
        )
        object.__setattr__(self, "claim_id", _identifier("claim_id", self.claim_id))
        object.__setattr__(
            self,
            "validator_id",
            _identifier("validator_id", self.validator_id),
        )
        if not isinstance(self.disposition, VerificationDisposition):
            raise EvidenceVerificationError(
                "invalid_verification_contract",
                "disposition must be VerificationDisposition",
            )
        checked = _identifier_tuple(
            "checked evidence id",
            self.checked_evidence_ids,
            maximum=MAX_VERIFICATION_EVIDENCE_IDS,
            require_non_empty=(
                self.disposition
                in {
                    VerificationDisposition.VERIFIED,
                    VerificationDisposition.CONTRADICTED,
                }
            ),
        )
        object.__setattr__(self, "checked_evidence_ids", checked)

        if self.confidence is not None:
            if (
                isinstance(self.confidence, bool)
                or not isinstance(self.confidence, (int, float))
                or not math.isfinite(float(self.confidence))
                or not 0.0 <= float(self.confidence) <= 1.0
            ):
                raise EvidenceVerificationError(
                    "invalid_verification_confidence",
                    "confidence must be a finite number from 0 to 1 or None",
                )
            object.__setattr__(self, "confidence", float(self.confidence))

        if self.summary is not None:
            if not isinstance(self.summary, str) or not self.summary.strip():
                raise EvidenceVerificationError(
                    "invalid_verification_contract",
                    "summary must be a non-empty string or None",
                )
            summary = self.summary.strip()
            if len(summary) > MAX_VERIFICATION_SUMMARY_CHARS:
                raise EvidenceVerificationError(
                    "verification_budget_exceeded",
                    "summary exceeds the bounded verification limit",
                )
            object.__setattr__(self, "summary", summary)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "verdict_id": self.verdict_id,
            "claim_id": self.claim_id,
            "validator_id": self.validator_id,
            "disposition": self.disposition.value,
            "checked_evidence_ids": list(self.checked_evidence_ids),
            "confidence": self.confidence,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class TrustedVerificationPolicy:
    """Server-owned validator allowlist; model/browser input cannot widen it."""

    allowed_validator_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        allowed = _identifier_tuple(
            "allowed validator id",
            self.allowed_validator_ids,
            maximum=MAX_ALLOWED_VALIDATORS,
            require_non_empty=True,
        )
        object.__setattr__(self, "allowed_validator_ids", allowed)


@dataclass(frozen=True, slots=True)
class AcceptedVerification:
    """A verdict accepted by Core's independence/evidence conformance gates."""

    request: VerificationRequest
    verdict: VerificationVerdict

    def __post_init__(self) -> None:
        if not isinstance(self.request, VerificationRequest):
            raise EvidenceVerificationError(
                "invalid_verification_contract",
                "request must be VerificationRequest",
            )
        if not isinstance(self.verdict, VerificationVerdict):
            raise EvidenceVerificationError(
                "invalid_verification_contract",
                "verdict must be VerificationVerdict",
            )

    def to_public_dict(self) -> dict[str, object]:
        # Human approval is intentionally absent. A B48-style product may layer
        # a separate approval decision over this accepted validator verdict.
        return self.verdict.to_public_dict()


class EvidenceValidator(Protocol):
    """Product-neutral independent validator seam."""

    async def verify(
        self,
        *,
        graph: EvidenceGraph,
        request: VerificationRequest,
    ) -> VerificationVerdict: ...


def accept_verification_verdict(
    graph: EvidenceGraph,
    request: VerificationRequest,
    verdict: VerificationVerdict,
    *,
    policy: TrustedVerificationPolicy,
) -> AcceptedVerification:
    """Accept an independent verdict only when identities and evidence conform.

    This function does not execute a validator and never grants human approval.
    It validates a verdict produced by an external trusted validator adapter.
    """

    if not isinstance(graph, EvidenceGraph):
        raise EvidenceVerificationError(
            "invalid_verification_contract",
            "graph must be EvidenceGraph",
        )
    if not isinstance(request, VerificationRequest):
        raise EvidenceVerificationError(
            "invalid_verification_contract",
            "request must be VerificationRequest",
        )
    if not isinstance(verdict, VerificationVerdict):
        raise EvidenceVerificationError(
            "invalid_verification_contract",
            "verdict must be VerificationVerdict",
        )
    if not isinstance(policy, TrustedVerificationPolicy):
        raise EvidenceVerificationError(
            "invalid_verification_contract",
            "policy must be TrustedVerificationPolicy",
        )

    try:
        graph.claim(request.claim_id)
    except EvidenceGraphError as exc:
        raise EvidenceVerificationError(
            "unknown_verification_claim",
            "verification request references an unknown claim",
        ) from exc

    if verdict.claim_id != request.claim_id:
        raise EvidenceVerificationError(
            "verification_claim_mismatch",
            "validator verdict does not belong to the requested claim",
        )
    if verdict.validator_id == request.producer_id:
        raise EvidenceVerificationError(
            "self_verification_forbidden",
            "claim producer cannot act as its own independent validator",
        )
    if verdict.validator_id not in policy.allowed_validator_ids:
        raise EvidenceVerificationError(
            "validator_not_authorized",
            "validator is not allowed by trusted verification policy",
        )

    claim_links = graph.links_for_claim(request.claim_id)
    links_by_evidence = {link.evidence_id: link for link in claim_links}
    for evidence_id in verdict.checked_evidence_ids:
        try:
            graph.source(evidence_id)
        except EvidenceGraphError as exc:
            raise EvidenceVerificationError(
                "unknown_checked_evidence",
                "validator referenced Evidence outside the graph",
            ) from exc
        if evidence_id not in links_by_evidence:
            raise EvidenceVerificationError(
                "unlinked_checked_evidence",
                "validator checked Evidence not linked to the requested claim",
            )

    checked_relations = {
        links_by_evidence[evidence_id].relation
        for evidence_id in verdict.checked_evidence_ids
    }
    if (
        verdict.disposition is VerificationDisposition.VERIFIED
        and ClaimEvidenceRelation.SUPPORTS not in checked_relations
    ):
        raise EvidenceVerificationError(
            "verified_without_support",
            "verified verdict requires checked supporting Evidence",
        )
    if (
        verdict.disposition is VerificationDisposition.CONTRADICTED
        and ClaimEvidenceRelation.CONTRADICTS not in checked_relations
    ):
        raise EvidenceVerificationError(
            "contradicted_without_contradiction",
            "contradicted verdict requires checked contradictory Evidence",
        )

    return AcceptedVerification(request=request, verdict=verdict)
