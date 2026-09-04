"""Product-neutral normalized document contract for Padiem AI Core.

This module defines the shape of a successfully normalized document that a
trusted product adapter hands to Core. It deliberately contains no parser, no
file-format logic, no transport, and no storage authority: products own
reading bytes and resolving references, and Core owns only the bounded,
validated semantics of the normalized result.

Content inside a ``NormalizedDocument`` is untrusted reference data. It is
never an instruction source, and the display name is sanitized metadata, not
an authority. A rejected extraction is represented by the adapter raising
``DocumentContractError``; it never becomes a ``NormalizedDocument``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


# Structural bounds for the contract itself. These are Core-wide ceilings,
# not per-product content policy; products choose smaller budgets upstream.
MAX_SEGMENT_TEXT_CHARS = 12_000
MAX_DOCUMENT_SEGMENTS = 512
MAX_NORMALIZED_TEXT_CHARS = 200_000
MAX_DISPLAY_NAME_CHARS = 256
MAX_DOCUMENT_WARNINGS = 32

# The single trust class for every document body carried by this contract.
DOCUMENT_CONTENT_TRUST_CLASS = "untrusted_reference_data"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHORT_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$")
_WARNING_RE = re.compile(r"^[a-z][a-z0-9._:-]{0,63}$")


class DocumentContractError(ValueError):
    """Safe validation failure at the Core document-normalization boundary.

    Messages identify only the offending field; they never echo document
    content, storage references, or adapter exception text.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("document error code must be a safe identifier")
        self.code = code
        self.safe_message = message


def _identifier(name: str, value: str, *, short: bool = False) -> str:
    pattern = _SHORT_IDENTIFIER_RE if short else _IDENTIFIER_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        limit = 48 if short else 128
        raise DocumentContractError(
            "invalid_document_contract",
            f"{name} must be a safe identifier of at most {limit} characters",
        )
    return value


def _bounded_text(name: str, value: str, *, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DocumentContractError(
            "invalid_document_contract",
            f"{name} must be a non-empty string",
        )
    text = value.strip()
    if len(text) > limit:
        raise DocumentContractError(
            "document_budget_exceeded",
            f"{name} exceeds the bounded document limit",
        )
    return text


def _sanitize_display_name(value: str) -> str:
    if not isinstance(value, str):
        raise DocumentContractError(
            "invalid_document_contract",
            "display_name must be a string",
        )
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise DocumentContractError(
            "invalid_document_contract",
            "display_name must contain visible characters",
        )
    if len(cleaned) > MAX_DISPLAY_NAME_CHARS:
        raise DocumentContractError(
            "document_budget_exceeded",
            "display_name exceeds the bounded document limit",
        )
    return cleaned


def _warning_tuple(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise DocumentContractError(
            "invalid_document_contract",
            f"{name} must be a sequence of warning identifiers",
        )
    checked: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _WARNING_RE.fullmatch(value):
            raise DocumentContractError(
                "invalid_document_contract",
                f"{name} entries must be bounded lowercase warning identifiers",
            )
        checked.append(value)
    if len(checked) > MAX_DOCUMENT_WARNINGS:
        raise DocumentContractError(
            "document_budget_exceeded",
            f"{name} exceeds the bounded item count",
        )
    if len(set(checked)) != len(checked):
        raise DocumentContractError(
            "invalid_document_contract",
            f"{name} must not contain duplicates",
        )
    return tuple(checked)


class DocumentKind(str, Enum):
    """Product-neutral normalized content kinds accepted by Core."""

    TEXT = "text"
    MARKDOWN = "markdown"
    CSV = "csv"
    JSON = "json"
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"


class ExtractionStatus(str, Enum):
    """Adapter-reported outcome of a normalization attempt.

    ``REJECTED`` exists so adapters can classify a failure, but a rejected
    extraction never becomes a ``NormalizedDocument``.
    """

    COMPLETE = "complete"
    TRUNCATED = "truncated"
    REJECTED = "rejected"


class LocatorKind(str, Enum):
    """Bounded address space a segment can point back into."""

    PAGE = "page"
    SHEET = "sheet"
    ROW = "row"
    CELL = "cell"
    PARAGRAPH = "paragraph"
    LINE = "line"
    HEADING = "heading"
    OFFSET = "offset"
    BLOCK = "block"
    ITEM = "item"


class LocatorPrecision(str, Enum):
    """How exact a locator claim is for the segment it annotates."""

    EXACT = "exact"
    APPROXIMATE = "approximate"


@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """A bounded, non-authoritative back-reference for one segment.

    The value is a safe identifier such as a page number, sheet name, or
    offset token. It never carries a path, URL, bucket key, or storage ref.
    """

    kind: LocatorKind
    value: str
    precision: LocatorPrecision

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LocatorKind):
            raise DocumentContractError(
                "invalid_document_contract",
                "locator kind must be LocatorKind",
            )
        if not isinstance(self.precision, LocatorPrecision):
            raise DocumentContractError(
                "invalid_document_contract",
                "locator precision must be LocatorPrecision",
            )
        object.__setattr__(self, "value", _identifier("locator value", self.value))

    def to_public_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "value": self.value,
            "precision": self.precision.value,
        }


@dataclass(frozen=True, slots=True)
class DocumentSegment:
    """One bounded piece of normalized document text with optional locator."""

    text: str
    order: int
    locator: DocumentLocator | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            _bounded_text("segment text", self.text, limit=MAX_SEGMENT_TEXT_CHARS),
        )
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise DocumentContractError(
                "invalid_document_contract",
                "segment order must be an integer",
            )
        if self.order < 0:
            raise DocumentContractError(
                "invalid_document_contract",
                "segment order must not be negative",
            )
        if self.locator is not None and not isinstance(self.locator, DocumentLocator):
            raise DocumentContractError(
                "invalid_document_contract",
                "segment locator must be DocumentLocator or None",
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


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    """A successfully normalized, bounded, untrusted document body.

    Only ``COMPLETE`` and ``TRUNCATED`` extractions may be constructed here.
    ``display_name`` is sanitized metadata with no authority, and ``warnings``
    are bounded machine identifiers, never exception text.
    """

    document_id: str
    kind: DocumentKind
    display_name: str
    segments: tuple[DocumentSegment, ...]
    status: ExtractionStatus
    warnings: tuple[str, ...] = ()

    content_trust_class: str = DOCUMENT_CONTENT_TRUST_CLASS
    display_name_is_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", _identifier("document_id", self.document_id))
        if not isinstance(self.kind, DocumentKind):
            raise DocumentContractError(
                "invalid_document_contract",
                "kind must be DocumentKind",
            )
        object.__setattr__(self, "display_name", _sanitize_display_name(self.display_name))
        if not isinstance(self.segments, tuple):
            object.__setattr__(self, "segments", tuple(self.segments))
        if not isinstance(self.segments, tuple) or any(
            not isinstance(item, DocumentSegment) for item in self.segments
        ):
            raise DocumentContractError(
                "invalid_document_contract",
                "segments must be a tuple of DocumentSegment values",
            )
        if len(self.segments) == 0:
            raise DocumentContractError(
                "invalid_document_contract",
                "a normalized document requires at least one segment",
            )
        if len(self.segments) > MAX_DOCUMENT_SEGMENTS:
            raise DocumentContractError(
                "document_budget_exceeded",
                "segments exceed the bounded document limit",
            )
        orders = tuple(segment.order for segment in self.segments)
        if len(set(orders)) != len(orders):
            raise DocumentContractError(
                "invalid_document_contract",
                "segment orders must be unique",
            )
        if sum(segment.char_count for segment in self.segments) > MAX_NORMALIZED_TEXT_CHARS:
            raise DocumentContractError(
                "document_budget_exceeded",
                "normalized text exceeds the bounded document limit",
            )
        if not isinstance(self.status, ExtractionStatus):
            raise DocumentContractError(
                "invalid_document_contract",
                "status must be ExtractionStatus",
            )
        if self.status is ExtractionStatus.REJECTED:
            raise DocumentContractError(
                "rejected_document_not_normalizable",
                "a rejected extraction cannot be represented as a normalized document",
            )
        object.__setattr__(self, "warnings", _warning_tuple("warnings", self.warnings))
        if self.status is ExtractionStatus.TRUNCATED and not self.warnings:
            raise DocumentContractError(
                "truncation_requires_warning",
                "a truncated document must carry at least one warning identifier",
            )
        if self.content_trust_class != DOCUMENT_CONTENT_TRUST_CLASS:
            raise DocumentContractError(
                "invalid_document_contract",
                "document content trust class is fixed by Core",
            )
        if self.display_name_is_authority is not False:
            raise DocumentContractError(
                "invalid_document_contract",
                "display_name can never be an authority",
            )

    @property
    def text_chars(self) -> int:
        """Total normalized characters across all segments."""

        return sum(segment.char_count for segment in self.segments)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def truncated(self) -> bool:
        return self.status is ExtractionStatus.TRUNCATED

    def to_public_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "kind": self.kind.value,
            "display_name": self.display_name,
            "status": self.status.value,
            "segment_count": self.segment_count,
            "text_chars": self.text_chars,
            "truncated": self.truncated,
            "warnings": list(self.warnings),
            "content_trust_class": self.content_trust_class,
            "display_name_is_authority": self.display_name_is_authority,
        }


__all__ = [
    "DOCUMENT_CONTENT_TRUST_CLASS",
    "MAX_DISPLAY_NAME_CHARS",
    "MAX_DOCUMENT_SEGMENTS",
    "MAX_DOCUMENT_WARNINGS",
    "MAX_NORMALIZED_TEXT_CHARS",
    "MAX_SEGMENT_TEXT_CHARS",
    "DocumentContractError",
    "DocumentKind",
    "DocumentLocator",
    "DocumentSegment",
    "ExtractionStatus",
    "LocatorKind",
    "LocatorPrecision",
    "NormalizedDocument",
]
