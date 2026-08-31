"""Product-safe grounded citation projection for Padiem AI Core.

Citations are projections of already-linked ``EvidenceGraph`` sources. They do
not expose raw Evidence snippets and do not turn a citation into a verification
or human-approval claim. When an independently accepted validator verdict is
available, its disposition is attached at the claim bundle level while each
source separately records whether that validator actually checked it.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .evidence_graph import (
    ClaimEvidenceRelation,
    EvidenceGraph,
    EvidenceGraphError,
)
from .evidence_verification import AcceptedVerification


MAX_CITATIONS_PER_CLAIM = 64
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class EvidenceCitationError(ValueError):
    """Safe citation-projection validation failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("citation error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise EvidenceCitationError(
            "invalid_citation_contract",
            f"{name} must be a bounded safe identifier",
        )
    return value


@dataclass(frozen=True, slots=True)
class GroundedCitation:
    """One product-safe source reference attached to a claim."""

    citation_id: str
    claim_id: str
    evidence_id: str
    title: str
    url: str | None
    provider: str
    source_type: str
    relation: ClaimEvidenceRelation
    checked_by_validator: bool = False

    def __post_init__(self) -> None:
        for name in ("citation_id", "claim_id", "evidence_id", "provider", "source_type"):
            object.__setattr__(self, name, _identifier(name, getattr(self, name)))
        if not isinstance(self.title, str) or not self.title.strip():
            raise EvidenceCitationError(
                "invalid_citation_contract",
                "citation title must be a non-empty string",
            )
        object.__setattr__(self, "title", self.title.strip())
        if self.url is not None and not isinstance(self.url, str):
            raise EvidenceCitationError(
                "invalid_citation_contract",
                "citation url must be a string or None",
            )
        if not isinstance(self.relation, ClaimEvidenceRelation):
            raise EvidenceCitationError(
                "invalid_citation_contract",
                "citation relation must be ClaimEvidenceRelation",
            )
        if not isinstance(self.checked_by_validator, bool):
            raise EvidenceCitationError(
                "invalid_citation_contract",
                "checked_by_validator must be boolean",
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "citation_id": self.citation_id,
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "title": self.title,
            "url": self.url,
            "provider": self.provider,
            "source_type": self.source_type,
            "relation": self.relation.value,
            "checked_by_validator": self.checked_by_validator,
        }


@dataclass(frozen=True, slots=True)
class GroundedCitationBundle:
    """Claim-level citation bundle with optional independent-verdict metadata."""

    claim_id: str
    claim_text: str
    citations: tuple[GroundedCitation, ...]
    verification_disposition: str | None = None
    validator_id: str | None = None
    verification_confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier("claim_id", self.claim_id))
        if not isinstance(self.claim_text, str) or not self.claim_text.strip():
            raise EvidenceCitationError(
                "invalid_citation_contract",
                "claim_text must be a non-empty string",
            )
        object.__setattr__(self, "claim_text", self.claim_text.strip())
        if not isinstance(self.citations, tuple) or not self.citations:
            raise EvidenceCitationError(
                "no_grounded_citations",
                "citation bundle requires at least one grounded source",
            )
        if len(self.citations) > MAX_CITATIONS_PER_CLAIM:
            raise EvidenceCitationError(
                "citation_budget_exceeded",
                "citation bundle exceeds the bounded source count",
            )
        if any(not isinstance(citation, GroundedCitation) for citation in self.citations):
            raise EvidenceCitationError(
                "invalid_citation_contract",
                "citations must contain GroundedCitation values",
            )
        if any(citation.claim_id != self.claim_id for citation in self.citations):
            raise EvidenceCitationError(
                "citation_claim_mismatch",
                "all citations must belong to the bundle claim",
            )
        if self.verification_disposition is None:
            if self.validator_id is not None or self.verification_confidence is not None:
                raise EvidenceCitationError(
                    "invalid_citation_contract",
                    "validator metadata requires a verification disposition",
                )
        else:
            object.__setattr__(
                self,
                "verification_disposition",
                _identifier("verification_disposition", self.verification_disposition),
            )
            if self.validator_id is None:
                raise EvidenceCitationError(
                    "invalid_citation_contract",
                    "verification disposition requires validator_id",
                )
            object.__setattr__(
                self,
                "validator_id",
                _identifier("validator_id", self.validator_id),
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "citations": [citation.to_public_dict() for citation in self.citations],
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


def project_grounded_citations(
    graph: EvidenceGraph,
    claim_id: str,
    *,
    verification: AcceptedVerification | None = None,
) -> GroundedCitationBundle:
    """Project graph-linked Evidence into product-safe citations.

    All graph relations are preserved, including contradictory/contextualizing
    sources. A caller may render them differently, but Core does not hide
    contradictions merely because supporting evidence also exists.
    """

    if not isinstance(graph, EvidenceGraph):
        raise EvidenceCitationError(
            "invalid_citation_contract",
            "graph must be EvidenceGraph",
        )
    claim_id = _identifier("claim_id", claim_id)
    try:
        claim = graph.claim(claim_id)
        links = graph.links_for_claim(claim_id)
    except EvidenceGraphError as exc:
        raise EvidenceCitationError(
            "unknown_citation_claim",
            "citation projection references an unknown claim",
        ) from exc

    if not links:
        raise EvidenceCitationError(
            "no_grounded_citations",
            "claim has no Evidence links to project",
        )
    if len(links) > MAX_CITATIONS_PER_CLAIM:
        raise EvidenceCitationError(
            "citation_budget_exceeded",
            "claim has too many Evidence links to project safely",
        )

    checked_ids: frozenset[str] = frozenset()
    verification_disposition: str | None = None
    validator_id: str | None = None
    verification_confidence: float | None = None
    if verification is not None:
        if not isinstance(verification, AcceptedVerification):
            raise EvidenceCitationError(
                "invalid_citation_contract",
                "verification must be AcceptedVerification or None",
            )
        if verification.request.claim_id != claim_id or verification.verdict.claim_id != claim_id:
            raise EvidenceCitationError(
                "citation_verification_mismatch",
                "verification does not belong to the citation claim",
            )
        checked_ids = frozenset(verification.verdict.checked_evidence_ids)
        verification_disposition = verification.verdict.disposition.value
        validator_id = verification.verdict.validator_id
        verification_confidence = verification.verdict.confidence

    citations: list[GroundedCitation] = []
    for index, link in enumerate(links, start=1):
        source = graph.source(link.evidence_id)
        citation_id = f"citation:{index}"
        citations.append(
            GroundedCitation(
                citation_id=citation_id,
                claim_id=claim_id,
                evidence_id=source.id,
                title=source.title,
                url=source.url,
                provider=source.provider,
                source_type=source.source_type,
                relation=link.relation,
                checked_by_validator=source.id in checked_ids,
            )
        )

    return GroundedCitationBundle(
        claim_id=claim_id,
        claim_text=claim.text,
        citations=tuple(citations),
        verification_disposition=verification_disposition,
        validator_id=validator_id,
        verification_confidence=verification_confidence,
    )
