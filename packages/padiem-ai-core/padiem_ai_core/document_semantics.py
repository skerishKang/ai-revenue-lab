"""Product-neutral document semantics for Padiem AI Core.

This module owns the reusable semantic vocabulary for normalized documents:
content kinds, extraction statuses, locators, segments, and the fixed content
trust class. It deliberately contains no parser, transport, or storage logic.

The canonical normalized-document object lives in
``padiem_ai_core.document_normalization`` and is enriched by these semantics.
A reference to an opaque resolver/attachment token is Engine-side resolution
authority and must never appear in, or be equated with, any field here.

Document bodies are untrusted reference data. They can never grant system,
agent, tool, connector, tenant, memory-write, or provider-routing authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re


# Structural bounds shared with document normalization. These mirror the
# canonical normalization ceilings so a whole document body can always be
# projected as one document-level segment.
MAX_SEGMENT_TEXT_CHARS = 40_000
MAX_DOCUMENT_SEGMENTS = 512
MAX_DOCUMENT_WARNINGS = 32

# The single fixed trust class for every document body in Core.
DOCUMENT_CONTENT_TRUST_CLASS = "untrusted_reference_data"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_WARNING_RE = re.compile(r"^[a-z][a-z0-9._:-]{0,63}$")


class DocumentNormalizationError(ValueError):
    """Safe validation/policy failure at the Core document boundary.

    Messages identify only the offending concern; they never echo document
    body content, payloads, or resolver data.
    """

    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


def validate_locator_value(value: object) -> str:
    """Validate a bounded, safe document-internal locator value."""

    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise DocumentNormalizationError(
            "invalid_locator_value",
            "Locator value must be a safe identifier of at most 128 characters.",
        )
    return value


def normalize_document_warnings(values: object) -> tuple[str, ...]:
    """Validate bounded, machine-only warning identifiers."""

    if isinstance(values, (str, bytes)):
        raise DocumentNormalizationError(
            "invalid_document_warnings",
            "Document warnings must be a sequence of identifiers.",
        )
    checked: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _WARNING_RE.fullmatch(value):
            raise DocumentNormalizationError(
                "invalid_document_warnings",
                "Document warning identifiers must be bounded lowercase tokens.",
            )
        checked.append(value)
    if len(checked) > MAX_DOCUMENT_WARNINGS:
        raise DocumentNormalizationError(
            "document_warnings_limit",
            "Document warnings exceed the bounded item count.",
        )
    if len(set(checked)) != len(checked):
        raise DocumentNormalizationError(
            "duplicate_document_warnings",
            "Document warnings must not contain duplicates.",
        )
    return tuple(checked)


class DocumentKind(str, Enum):
    """Product-neutral normalized content kinds supported by Core."""

    TEXT = "text"
    MARKDOWN = "markdown"
    CSV = "csv"
    JSON = "json"
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"


class ExtractionStatus(str, Enum):
    """Status of a successfully constructed normalized document.

    A rejected or failed extraction is always an exception, never a document,
    so no rejected member exists here by design.
    """

    COMPLETE = "complete"
    TRUNCATED = "truncated"


class LocatorKind(str, Enum):
    """Bounded document-internal address spaces for segment provenance."""

    PAGE = "page"
    SLIDE = "slide"
    SHEET = "sheet"
    CELL = "cell"
    RANGE = "range"
    ROW = "row"
    COLUMN = "column"
    LINE = "line"
    PARAGRAPH = "paragraph"
    SECTION = "section"
    HEADING = "heading"
    MEMBER = "member"
    OFFSET = "offset"


class LocatorPrecision(str, Enum):
    """Explicit honesty level of a locator claim."""

    EXACT = "exact"
    APPROXIMATE = "approximate"


_MEDIA_TYPE_BY_KIND: dict[DocumentKind, str] = {
    DocumentKind.TEXT: "text/plain",
    DocumentKind.MARKDOWN: "text/markdown",
    DocumentKind.CSV: "text/csv",
    DocumentKind.JSON: "application/json",
    DocumentKind.PDF: "application/pdf",
    DocumentKind.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    DocumentKind.PPTX: (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    DocumentKind.XLSX: (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
}

KIND_BY_MEDIA_TYPE: dict[str, DocumentKind] = {
    media: kind for kind, media in _MEDIA_TYPE_BY_KIND.items()
}


def document_kind_for_media(media_type: str, *, default: DocumentKind | None = None) -> DocumentKind | None:
    """Map a canonical media identity onto its document kind."""

    return KIND_BY_MEDIA_TYPE.get(media_type, default)


@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """A bounded, document-internal back-reference for one segment.

    The value is a safe identifier such as a page number or sheet coordinate.
    It is never a storage location, archive member reference, or resolver token.
    """

    kind: LocatorKind
    value: str
    precision: LocatorPrecision

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LocatorKind):
            raise DocumentNormalizationError(
                "invalid_locator_kind",
                "Locator kind must be a LocatorKind value.",
            )
        if not isinstance(self.precision, LocatorPrecision):
            raise DocumentNormalizationError(
                "invalid_locator_precision",
                "Locator precision must be a LocatorPrecision value.",
            )
        object.__setattr__(self, "value", validate_locator_value(self.value))

    def to_public_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "value": self.value,
            "precision": self.precision.value,
        }


@dataclass(frozen=True, slots=True, repr=False)
class DocumentSegment:
    """One bounded piece of document text with optional locator provenance.

    The body text is excluded from ``repr`` and from the public projection;
    only character count and ordering are safe to surface.
    """

    text: str = field(repr=False)
    order: int = 0
    locator: DocumentLocator | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise DocumentNormalizationError(
                "invalid_segment_text",
                "Segment text must be a non-empty string.",
            )
        if len(self.text) > MAX_SEGMENT_TEXT_CHARS:
            raise DocumentNormalizationError(
                "segment_text_limit",
                "Segment text exceeds the bounded character limit.",
            )
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise DocumentNormalizationError(
                "invalid_segment_order",
                "Segment order must be an integer.",
            )
        if self.order < 0:
            raise DocumentNormalizationError(
                "invalid_segment_order",
                "Segment order must not be negative.",
            )
        if self.locator is not None and not isinstance(self.locator, DocumentLocator):
            raise DocumentNormalizationError(
                "invalid_segment_locator",
                "Segment locator must be a DocumentLocator or None.",
            )

    def __repr__(self) -> str:
        return (
            "DocumentSegment("
            f"order={self.order}, char_count={self.char_count}, "
            f"has_locator={self.locator is not None})"
        )

    @property
    def char_count(self) -> int:
        return len(self.text)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "order": self.order,
            "char_count": self.char_count,
            "locator": self.locator.to_public_dict() if self.locator is not None else None,
        }


__all__ = [
    "DOCUMENT_CONTENT_TRUST_CLASS",
    "KIND_BY_MEDIA_TYPE",
    "MAX_DOCUMENT_SEGMENTS",
    "MAX_DOCUMENT_WARNINGS",
    "MAX_SEGMENT_TEXT_CHARS",
    "DocumentKind",
    "DocumentLocator",
    "DocumentNormalizationError",
    "DocumentSegment",
    "ExtractionStatus",
    "LocatorKind",
    "LocatorPrecision",
    "document_kind_for_media",
    "normalize_document_warnings",
    "validate_locator_value",
]
