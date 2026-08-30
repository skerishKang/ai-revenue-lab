"""Product-neutral evidence provenance graph for Padiem AI Core.

The existing :class:`Evidence` contract remains the source-record authority.
This module adds only relationships between claims and those source records.
It deliberately does not declare a claim "verified", assign a universal truth
score, or make model output an authority. Independent verification is a
separate contract layered on top of this graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Sequence

from .contracts import Evidence


MAX_EVIDENCE_GRAPH_SOURCES = 128
MAX_EVIDENCE_GRAPH_CLAIMS = 128
MAX_EVIDENCE_GRAPH_LINKS = 512
MAX_CLAIM_TEXT_CHARS = 4_000
MAX_CLAIM_DERIVATION_INPUTS = 32

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class EvidenceGraphError(ValueError):
    """Safe graph-contract validation failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("evidence graph error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise EvidenceGraphError(
            "invalid_evidence_graph",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _bounded_text(name: str, value: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceGraphError(
            "invalid_evidence_graph",
            f"{name} must be a non-empty string",
        )
    text = value.strip()
    if len(text) > maximum:
        raise EvidenceGraphError(
            "evidence_graph_budget_exceeded",
            f"{name} exceeds the bounded graph limit",
        )
    return text


class ClaimDerivation(str, Enum):
    """How a claim entered the graph; not a verification verdict."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    GENERATED = "generated"
    IMPORTED = "imported"


class ClaimEvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXTUALIZES = "contextualizes"


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """One bounded claim with explicit derivation provenance.

    ``derived_from_claim_ids`` identifies prior claims used to derive this claim.
    It does not assert correctness. An observed claim still needs at least one
    direct supporting Evidence link at graph-validation time.
    """

    id: str
    text: str
    derivation: ClaimDerivation
    derived_from_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier("claim id", self.id))
        object.__setattr__(
            self,
            "text",
            _bounded_text("claim text", self.text, maximum=MAX_CLAIM_TEXT_CHARS),
        )
        if not isinstance(self.derivation, ClaimDerivation):
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "claim derivation must be ClaimDerivation",
            )
        if isinstance(self.derived_from_claim_ids, (str, bytes)):
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "derived_from_claim_ids must be a tuple of claim identifiers",
            )
        derived = tuple(
            _identifier("derived claim id", item)
            for item in self.derived_from_claim_ids
        )
        if len(derived) > MAX_CLAIM_DERIVATION_INPUTS:
            raise EvidenceGraphError(
                "evidence_graph_budget_exceeded",
                "claim has too many derivation inputs",
            )
        if len(set(derived)) != len(derived):
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "derived claim identifiers must not contain duplicates",
            )
        if self.id in derived:
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "claim cannot derive from itself",
            )
        if self.derivation is ClaimDerivation.OBSERVED and derived:
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "observed claim cannot derive from another claim",
            )
        object.__setattr__(self, "derived_from_claim_ids", derived)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "derivation": self.derivation.value,
            "derived_from_claim_ids": list(self.derived_from_claim_ids),
        }


@dataclass(frozen=True, slots=True)
class ClaimEvidenceLink:
    claim_id: str
    evidence_id: str
    relation: ClaimEvidenceRelation

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier("claim id", self.claim_id))
        object.__setattr__(
            self,
            "evidence_id",
            _identifier("evidence id", self.evidence_id),
        )
        if not isinstance(self.relation, ClaimEvidenceRelation):
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "relation must be ClaimEvidenceRelation",
            )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "relation": self.relation.value,
        }


@dataclass(frozen=True, slots=True)
class EvidenceGraph:
    """Immutable claim/source graph with deterministic acyclic derivation order."""

    sources: tuple[Evidence, ...]
    claims: tuple[EvidenceClaim, ...]
    links: tuple[ClaimEvidenceLink, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.sources, tuple) or any(
            not isinstance(source, Evidence) for source in self.sources
        ):
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "sources must be a tuple of Evidence values",
            )
        if not isinstance(self.claims, tuple) or any(
            not isinstance(claim, EvidenceClaim) for claim in self.claims
        ):
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "claims must be a tuple of EvidenceClaim values",
            )
        if not isinstance(self.links, tuple) or any(
            not isinstance(link, ClaimEvidenceLink) for link in self.links
        ):
            raise EvidenceGraphError(
                "invalid_evidence_graph",
                "links must be a tuple of ClaimEvidenceLink values",
            )

        if len(self.sources) > MAX_EVIDENCE_GRAPH_SOURCES:
            raise EvidenceGraphError(
                "evidence_graph_budget_exceeded",
                "graph contains too many Evidence sources",
            )
        if not 1 <= len(self.claims) <= MAX_EVIDENCE_GRAPH_CLAIMS:
            raise EvidenceGraphError(
                "evidence_graph_budget_exceeded",
                "graph must contain a bounded non-empty claim set",
            )
        if len(self.links) > MAX_EVIDENCE_GRAPH_LINKS:
            raise EvidenceGraphError(
                "evidence_graph_budget_exceeded",
                "graph contains too many claim/evidence links",
            )

        evidence_ids = tuple(source.id for source in self.sources)
        claim_ids = tuple(claim.id for claim in self.claims)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise EvidenceGraphError(
                "duplicate_evidence_source",
                "Evidence source ids must be unique",
            )
        if len(set(claim_ids)) != len(claim_ids):
            raise EvidenceGraphError(
                "duplicate_evidence_claim",
                "claim ids must be unique",
            )

        evidence_id_set = frozenset(evidence_ids)
        claim_id_set = frozenset(claim_ids)
        seen_link_keys: set[tuple[str, str, ClaimEvidenceRelation]] = set()
        for link in self.links:
            if link.claim_id not in claim_id_set:
                raise EvidenceGraphError(
                    "unknown_evidence_claim",
                    "claim/evidence link references an unknown claim",
                )
            if link.evidence_id not in evidence_id_set:
                raise EvidenceGraphError(
                    "unknown_evidence_source",
                    "claim/evidence link references an unknown Evidence source",
                )
            key = (link.claim_id, link.evidence_id, link.relation)
            if key in seen_link_keys:
                raise EvidenceGraphError(
                    "duplicate_evidence_link",
                    "claim/evidence links must not contain exact duplicates",
                )
            seen_link_keys.add(key)

        # Claims may derive only from earlier claims. This gives a deterministic,
        # trivially acyclic provenance graph without a separate graph algorithm.
        earlier: set[str] = set()
        links_by_claim: dict[str, list[ClaimEvidenceLink]] = {}
        for link in self.links:
            links_by_claim.setdefault(link.claim_id, []).append(link)
        for claim in self.claims:
            if any(parent not in earlier for parent in claim.derived_from_claim_ids):
                raise EvidenceGraphError(
                    "invalid_claim_derivation",
                    "claim derivation may reference only earlier claims",
                )
            if claim.derivation is ClaimDerivation.OBSERVED:
                direct = links_by_claim.get(claim.id, ())
                if not any(
                    link.relation is ClaimEvidenceRelation.SUPPORTS
                    for link in direct
                ):
                    raise EvidenceGraphError(
                        "observed_claim_missing_source",
                        "observed claim requires at least one direct supporting Evidence source",
                    )
            earlier.add(claim.id)

    def source(self, evidence_id: str) -> Evidence:
        evidence_id = _identifier("evidence id", evidence_id)
        for source in self.sources:
            if source.id == evidence_id:
                return source
        raise EvidenceGraphError(
            "unknown_evidence_source",
            "Evidence source does not exist in this graph",
        )

    def claim(self, claim_id: str) -> EvidenceClaim:
        claim_id = _identifier("claim id", claim_id)
        for claim in self.claims:
            if claim.id == claim_id:
                return claim
        raise EvidenceGraphError(
            "unknown_evidence_claim",
            "claim does not exist in this graph",
        )

    def links_for_claim(self, claim_id: str) -> tuple[ClaimEvidenceLink, ...]:
        self.claim(claim_id)
        return tuple(link for link in self.links if link.claim_id == claim_id)

    def to_public_dict(self) -> dict[str, object]:
        """Project graph structure without raw Evidence snippets.

        ``Evidence.snippet`` may contain private or lengthy retrieved content.
        The generic graph contract therefore exposes only bounded source
        metadata. Product-specific surfaces may separately choose what source
        text to reveal under their own policy.
        """

        return {
            "sources": [
                {
                    "id": source.id,
                    "title": source.title,
                    "url": source.url,
                    "retrieved_at": source.retrieved_at,
                    "provider": source.provider,
                    "source_type": source.source_type,
                }
                for source in self.sources
            ],
            "claims": [claim.to_public_dict() for claim in self.claims],
            "links": [link.to_public_dict() for link in self.links],
        }


def evidence_graph(
    *,
    sources: Sequence[Evidence],
    claims: Sequence[EvidenceClaim],
    links: Sequence[ClaimEvidenceLink],
) -> EvidenceGraph:
    """Copy arbitrary sequences into the immutable canonical graph contract."""

    if isinstance(sources, (str, bytes)) or isinstance(claims, (str, bytes)) or isinstance(links, (str, bytes)):
        raise EvidenceGraphError(
            "invalid_evidence_graph",
            "graph inputs must be sequences of contract values",
        )
    return EvidenceGraph(
        sources=tuple(sources),
        claims=tuple(claims),
        links=tuple(links),
    )
