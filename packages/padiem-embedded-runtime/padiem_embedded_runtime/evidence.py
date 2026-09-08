"""Public-safe evidence/citation presentation for IP-SIDECAR (S4).

Evidence and citation input arrives from untrusted host/tooling surfaces.
This module performs bounded normalization, deterministic ordering and
deduplication, and stable reference labels, then projects only allowlisted
presentation fields. It never renders HTML, never fetches URLs, and never
carries raw provider/tool/terminal material: values matching guarded
patterns fail the item, and malformed items degrade the presentation
instead of raising, so the host primary journey keeps working.

Pipeline:

    public-safe evidence/citation input
      -> bounded normalization
      -> stable presentation projection
      -> deterministic order/dedup/reference labels
      -> host-safe empty/degraded state
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .errors import SidecarContractError

STATUS_READY = "ready"
STATUS_EMPTY = "empty"
STATUS_DEGRADED = "degraded"
PRESENTATION_STATUSES = frozenset({STATUS_READY, STATUS_EMPTY, STATUS_DEGRADED})

DROP_REASON_MALFORMED_ITEM = "MALFORMED_ITEM"
DROP_REASON_INVALID_FIELD = "INVALID_FIELD"

ALLOWED_CITATION_FIELDS = frozenset({"source_id", "title", "locator"})

MAX_CITATIONS = 12
MAX_SOURCE_ID_CHARS = 64
MAX_TITLE_CHARS = 120
MAX_LOCATOR_CHARS = 80

_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_GUARDED_VALUE_RE = re.compile(
    r"secret|passwd|password|credential|api[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|bearer|authorization|"
    r"reasoning|chain[_-]of[_-]thought|tool[_-]?arg|stdout|stderr|traceback|"
    r"<\s*/?\s*[a-z]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CitationRef:
    """One normalized, bounded, public-safe citation."""

    source_id: str
    title: str
    locator: str = ""

    def to_public_dict(self) -> dict[str, object]:
        return {"source_id": self.source_id, "title": self.title, "locator": self.locator}


@dataclass(frozen=True)
class PresentedCitation:
    """A citation with its deterministic presentation label."""

    label: str
    citation: CitationRef

    def to_public_dict(self) -> dict[str, object]:
        return {"label": self.label, **self.citation.to_public_dict()}


@dataclass(frozen=True)
class CitationPresentation:
    """Immutable host-safe presentation result. Never carries raw input."""

    status: str
    citations: tuple[PresentedCitation, ...] = field(default_factory=tuple)
    dropped_count: int = 0
    drop_reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in PRESENTATION_STATUSES:
            raise SidecarContractError("presentation status is not an allowlisted code")
        for reason in self.drop_reasons:
            if reason not in (DROP_REASON_MALFORMED_ITEM, DROP_REASON_INVALID_FIELD):
                raise SidecarContractError("drop reason is not an allowlisted code")
        if self.dropped_count < 0:
            raise SidecarContractError("dropped_count must be >= 0")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "citations": [c.to_public_dict() for c in self.citations],
            "dropped_count": self.dropped_count,
            "drop_reasons": list(self.drop_reasons),
        }


def _check_bounded_text(value: object, limit: int, field_name: str) -> str:
    if not isinstance(value, str):
        raise SidecarContractError(f"citation {field_name} must be text")
    if len(value) > limit:
        raise SidecarContractError(f"citation {field_name} exceeds the bound")
    if _GUARDED_VALUE_RE.search(value):
        raise SidecarContractError(f"citation {field_name} resembles non-public material")
    return value


def normalize_citation(raw: Mapping[str, object]) -> CitationRef:
    """Validate one untrusted citation into a :class:`CitationRef` or fail closed."""
    if not isinstance(raw, Mapping):
        raise SidecarContractError("citation must be a mapping")
    unknown = sorted(k for k in raw if k not in ALLOWED_CITATION_FIELDS)
    if unknown:
        raise SidecarContractError(f"unknown citation fields: {', '.join(unknown)}")
    if "source_id" not in raw:
        raise SidecarContractError("citation requires source_id")
    source_id = _check_bounded_text(raw["source_id"], MAX_SOURCE_ID_CHARS, "source_id")
    if _SOURCE_ID_RE.fullmatch(source_id) is None:
        raise SidecarContractError("citation source_id must be a bounded identifier")
    title = _check_bounded_text(raw.get("title", ""), MAX_TITLE_CHARS, "title")
    locator = _check_bounded_text(raw.get("locator", ""), MAX_LOCATOR_CHARS, "locator")
    return CitationRef(source_id=source_id, title=title, locator=locator)


def present_citations(raw_items: Sequence[object]) -> CitationPresentation:
    """Project untrusted citation input into a deterministic host-safe view.

    Malformed items are dropped (counted, reason-coded, values never
    retained). Surviving items are deduplicated on ``(source_id, locator)``,
    ordered by ``(source_id, locator, first-seen index)``, and labeled
    ``[1]..[n]`` in that order. Empty input yields an ``empty`` presentation;
    any dropped item yields ``degraded``. This function never raises for
    untrusted data.
    """
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return CitationPresentation(
            status=STATUS_DEGRADED,
            drop_reasons=(DROP_REASON_MALFORMED_ITEM,),
            dropped_count=1,
        )

    normalized: list[tuple[int, CitationRef]] = []
    drop_reasons: set[str] = set()
    dropped = 0
    for index, raw in enumerate(raw_items):
        if len(normalized) >= MAX_CITATIONS:
            dropped += 1
            drop_reasons.add(DROP_REASON_MALFORMED_ITEM)
            continue
        try:
            normalized.append((index, normalize_citation(raw)))
        except SidecarContractError:
            dropped += 1
            drop_reasons.add(
                DROP_REASON_INVALID_FIELD
                if isinstance(raw, Mapping)
                else DROP_REASON_MALFORMED_ITEM
            )

    seen: dict[tuple[str, str], tuple[int, CitationRef]] = {}
    for index, citation in normalized:
        key = (citation.source_id, citation.locator)
        if key not in seen:
            seen[key] = (index, citation)

    ordered = sorted(seen.values(), key=lambda pair: (pair[1].source_id, pair[1].locator, pair[0]))
    presented = tuple(
        PresentedCitation(label=f"[{position}]", citation=citation)
        for position, (_, citation) in enumerate(ordered, start=1)
    )

    if dropped:
        status = STATUS_DEGRADED
    elif not presented:
        status = STATUS_EMPTY
    else:
        status = STATUS_READY
    return CitationPresentation(
        status=status,
        citations=presented,
        dropped_count=dropped,
        drop_reasons=tuple(sorted(drop_reasons)),
    )
