"""Bounded native PDF merge/split operations over the canonical pypdf authority."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from .document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_PDF_PAGES,
    DocumentNormalizationError,
    _open_pdf_reader,
)

MAX_MERGE_INPUT_FILES = 8
MAX_INPUT_BYTES_PER_FILE = MAX_BINARY_DOCUMENT_BYTES
MAX_AGGREGATE_INPUT_BYTES = MAX_INPUT_BYTES_PER_FILE * MAX_MERGE_INPUT_FILES
MAX_PDF_PAGES_PER_INPUT = MAX_PDF_PAGES
MAX_OUTPUT_PAGES = MAX_PDF_PAGES
MAX_OUTPUT_BYTES = MAX_BINARY_DOCUMENT_BYTES
MAX_SPLIT_RANGES = 16
MAX_RANGE_WIDTH = MAX_PDF_PAGES
MAX_TOTAL_SELECTED_PAGES = MAX_PDF_PAGES
USER_PAGE_NUMBERING = "one_based"
ACTIVE_CONTENT_POLICY = "fail_closed"
EXTERNAL_URI_FETCH = 0
EMBEDDED_SCRIPT_EXECUTION = 0
BYTE_IDENTICAL_DETERMINISM = "NOT_CLAIMED"
SEMANTIC_DETERMINISM = "YES"


@dataclass(frozen=True, slots=True)
class PdfPageProvenance:
    output_page_number: int
    source_document_index: int
    source_page_number: int

    def __post_init__(self) -> None:
        for value in (
            self.output_page_number,
            self.source_page_number,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise DocumentNormalizationError(
                    "pdf_provenance_page",
                    "PDF provenance page numbers must be positive integers.",
                )
        if (
            isinstance(self.source_document_index, bool)
            or not isinstance(self.source_document_index, int)
            or self.source_document_index < 0
        ):
            raise DocumentNormalizationError(
                "pdf_provenance_document",
                "PDF provenance document index must be a non-negative integer.",
            )

    def safe_dict(self) -> dict[str, int]:
        return {
            "output_page_number": self.output_page_number,
            "source_document_index": self.source_document_index,
            "source_page_number": self.source_page_number,
        }


@dataclass(frozen=True, slots=True)
class PdfOperationResult:
    operation: str
    payload: bytes = field(repr=False)
    page_count: int
    provenance: tuple[PdfPageProvenance, ...]
    source_document_count: int
    source_page_count: int

    def __post_init__(self) -> None:
        if self.operation not in {"merge", "split"}:
            raise DocumentNormalizationError(
                "pdf_operation_kind", "PDF operation kind is unsupported."
            )
        if not isinstance(self.payload, bytes) or not self.payload:
            raise DocumentNormalizationError(
                "pdf_output_empty", "PDF operation output is empty."
            )
        if self.page_count < 1 or self.page_count > MAX_OUTPUT_PAGES:
            raise DocumentNormalizationError(
                "pdf_output_page_limit", "PDF output page count is out of bounds."
            )
        if len(self.payload) > MAX_OUTPUT_BYTES:
            raise DocumentNormalizationError(
                "pdf_output_bytes_limit", "PDF output byte count is out of bounds."
            )
        if len(self.provenance) != self.page_count:
            raise DocumentNormalizationError(
                "pdf_provenance_count",
                "PDF provenance count does not match output pages.",
            )
        if self.source_document_count < 1 or self.source_page_count < 1:
            raise DocumentNormalizationError(
                "pdf_source_empty", "PDF source has no pages."
            )

    def safe_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "page_count": self.page_count,
            "source_document_count": self.source_document_count,
            "source_page_count": self.source_page_count,
            "page_provenance": [item.safe_dict() for item in self.provenance],
            "user_page_numbering": USER_PAGE_NUMBERING,
        }


def _writer() -> Any:
    try:
        from pypdf import PdfWriter
    except ModuleNotFoundError as exc:
        raise DocumentNormalizationError(
            "document_dependency_unavailable",
            "PDF operation dependency is unavailable.",
        ) from exc
    return PdfWriter()


def _payload_bytes(payload: object) -> bytes:
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise DocumentNormalizationError(
            "pdf_input_empty", "PDF input must be non-empty bytes."
        )
    binary = bytes(payload)
    if len(binary) > MAX_INPUT_BYTES_PER_FILE:
        raise DocumentNormalizationError(
            "pdf_input_bytes_limit", "PDF input byte count is out of bounds."
        )
    return binary


def _close_reader(reader: Any) -> None:
    close = getattr(reader, "close", None)
    if callable(close):
        close()


def _reject_active_content(reader: Any) -> None:
    root = getattr(reader, "trailer", {}).get("/Root", {})
    if root:
        for key in ("/AcroForm", "/Names", "/OpenAction", "/AA", "/Outlines"):
            if key in root:
                raise DocumentNormalizationError(
                    "pdf_active_content",
                    "PDF active content is not supported by bounded operations.",
                )
    for page in getattr(reader, "pages", ()):
        annotations = page.get("/Annots")
        if annotations:
            raise DocumentNormalizationError(
                "pdf_active_content",
                "PDF annotations are not supported by bounded operations.",
            )


def _close_writer(writer: Any | None) -> None:
    close = getattr(writer, "close", None)
    if callable(close):
        close()


def _write_output(
    writer: Any,
    provenance: tuple[PdfPageProvenance, ...],
    operation: str,
    source_document_count: int,
    source_page_count: int,
) -> PdfOperationResult:
    output = BytesIO()
    try:
        writer.write(output)
    except Exception as exc:
        raise DocumentNormalizationError(
            "pdf_operation_write", "PDF operation could not be written safely."
        ) from exc
    finally:
        close = getattr(writer, "close", None)
        if callable(close):
            close()
    payload = output.getvalue()
    if len(payload) > MAX_OUTPUT_BYTES:
        raise DocumentNormalizationError(
            "pdf_output_bytes_limit", "PDF output byte count is out of bounds."
        )
    return PdfOperationResult(
        operation=operation,
        payload=payload,
        page_count=len(provenance),
        provenance=provenance,
        source_document_count=source_document_count,
        source_page_count=source_page_count,
    )


def _validate_range(value: object) -> tuple[int, int]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise DocumentNormalizationError(
            "pdf_split_range_shape", "PDF split range must contain two page numbers."
        )
    start, end = value
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 1
        or end < start
    ):
        raise DocumentNormalizationError(
            "pdf_split_range_invalid", "PDF split range is invalid."
        )
    return start, end


def merge_pdfs(payloads: Sequence[bytes]) -> PdfOperationResult:
    """Merge admitted PDF bytes in caller order and return bounded provenance."""
    if not isinstance(payloads, (tuple, list)) or not payloads:
        raise DocumentNormalizationError(
            "pdf_merge_inputs_empty", "PDF merge requires at least one input."
        )
    if len(payloads) > MAX_MERGE_INPUT_FILES:
        raise DocumentNormalizationError(
            "pdf_merge_input_limit", "PDF merge input count is out of bounds."
        )
    binaries = tuple(_payload_bytes(payload) for payload in payloads)
    if sum(len(payload) for payload in binaries) > MAX_AGGREGATE_INPUT_BYTES:
        raise DocumentNormalizationError(
            "pdf_merge_aggregate_bytes",
            "PDF merge aggregate input bytes are out of bounds.",
        )
    readers: list[Any] = []
    writer = _writer()
    provenance: list[PdfPageProvenance] = []
    source_page_count = 0
    try:
        for document_index, binary in enumerate(binaries):
            reader = _open_pdf_reader(binary)
            readers.append(reader)
            _reject_active_content(reader)
            pages = list(reader.pages)
            source_page_count += len(pages)
            if source_page_count > MAX_OUTPUT_PAGES:
                raise DocumentNormalizationError(
                    "pdf_output_page_limit",
                    "PDF merge output page count is out of bounds.",
                )
            for page_index, page in enumerate(pages):
                writer.add_page(page)
                provenance.append(
                    PdfPageProvenance(
                        len(provenance) + 1, document_index, page_index + 1
                    )
                )
        return _write_output(
            writer, tuple(provenance), "merge", len(binaries), source_page_count
        )
    except DocumentNormalizationError:
        raise
    except Exception as exc:
        raise DocumentNormalizationError(
            "pdf_merge_failed", "PDF merge failed safely."
        ) from exc
    finally:
        for reader in readers:
            _close_reader(reader)
        _close_writer(writer)


def split_pdf(payload: bytes, ranges: Sequence[tuple[int, int]]) -> PdfOperationResult:
    """Split one admitted PDF into explicitly selected one-based page ranges."""
    binary = _payload_bytes(payload)
    if not isinstance(ranges, (tuple, list)) or not ranges:
        raise DocumentNormalizationError(
            "pdf_split_ranges_empty", "PDF split requires at least one range."
        )
    if len(ranges) > MAX_SPLIT_RANGES:
        raise DocumentNormalizationError(
            "pdf_split_range_limit", "PDF split range count is out of bounds."
        )
    normalized = tuple(_validate_range(value) for value in ranges)
    reader = _open_pdf_reader(binary)
    writer: Any | None = None
    provenance: list[PdfPageProvenance] = []
    seen: set[int] = set()
    try:
        _reject_active_content(reader)
        writer = _writer()
        source_pages = list(reader.pages)
        for start, end in normalized:
            width = end - start + 1
            if width > MAX_RANGE_WIDTH:
                raise DocumentNormalizationError(
                    "pdf_split_range_width", "PDF split range is too wide."
                )
            if end > len(source_pages):
                raise DocumentNormalizationError(
                    "pdf_split_range_page", "PDF split range exceeds source pages."
                )
            for page_number in range(start, end + 1):
                if page_number in seen:
                    raise DocumentNormalizationError(
                        "pdf_split_range_overlap",
                        "PDF split ranges overlap or duplicate pages.",
                    )
                seen.add(page_number)
                writer.add_page(source_pages[page_number - 1])
                provenance.append(
                    PdfPageProvenance(len(provenance) + 1, 0, page_number)
                )
        if len(provenance) > MAX_TOTAL_SELECTED_PAGES:
            raise DocumentNormalizationError(
                "pdf_split_selected_limit",
                "PDF split selected page count is out of bounds.",
            )
        if len(provenance) > MAX_OUTPUT_PAGES:
            raise DocumentNormalizationError(
                "pdf_output_page_limit", "PDF split output page count is out of bounds."
            )
        if writer is None:
            raise DocumentNormalizationError(
                "pdf_operation_write", "PDF operation writer is unavailable."
            )
        return _write_output(writer, tuple(provenance), "split", 1, len(source_pages))
    except DocumentNormalizationError:
        raise
    except Exception as exc:
        raise DocumentNormalizationError(
            "pdf_split_failed", "PDF split failed safely."
        ) from exc
    finally:
        _close_reader(reader)
        _close_writer(writer)


__all__ = [
    "ACTIVE_CONTENT_POLICY",
    "BYTE_IDENTICAL_DETERMINISM",
    "EMBEDDED_SCRIPT_EXECUTION",
    "EXTERNAL_URI_FETCH",
    "MAX_AGGREGATE_INPUT_BYTES",
    "MAX_INPUT_BYTES_PER_FILE",
    "MAX_MERGE_INPUT_FILES",
    "MAX_OUTPUT_BYTES",
    "MAX_OUTPUT_PAGES",
    "MAX_PDF_PAGES_PER_INPUT",
    "MAX_RANGE_WIDTH",
    "MAX_SPLIT_RANGES",
    "MAX_TOTAL_SELECTED_PAGES",
    "SEMANTIC_DETERMINISM",
    "USER_PAGE_NUMBERING",
    "PdfOperationResult",
    "PdfPageProvenance",
    "merge_pdfs",
    "split_pdf",
]
