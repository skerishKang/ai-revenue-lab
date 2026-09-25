"""Bounded deterministic table extraction for machine-generated PDF pages."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from .document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    DocumentNormalizationError,
    validate_document_identity,
)

MAX_PDF_TABLE_PAGES = 32
MAX_PDF_TABLE_TABLES = 64
MAX_PDF_TABLE_SOURCE_BYTES = MAX_BINARY_DOCUMENT_BYTES
MAX_PDF_TABLE_ROWS = 512
MAX_PDF_TABLE_CELLS = 4096
MAX_PDF_TABLE_CELL_CHARS = 4096
MAX_PDF_TABLE_TEXT_CHARS = 65536
PDF_TABLE_SOURCE_KIND = "ruled_machine_generated"
PDF_TABLE_SCOPE = "bounded_ruled_tables"
PDF_TABLE_STATUS_FOUND = "tables_found"
PDF_TABLE_STATUS_PARTIAL = "partial_supported"
PDF_TABLE_STATUS_UNSUPPORTED = "unsupported_layout"
PDF_TABLE_SETTINGS = {
    "vertical_strategy": "lines_strict",
    "horizontal_strategy": "lines_strict",
}


@dataclass(frozen=True, slots=True)
class PdfTable:
    """One bounded table with page, geometry, row, and cell provenance."""

    page_number: int
    table_index: int
    bbox: tuple[float, float, float, float]
    rows: tuple[tuple[str, ...], ...] = field(repr=False)
    source_kind: str = PDF_TABLE_SOURCE_KIND

    def __post_init__(self) -> None:
        if self.page_number < 1 or self.table_index < 1:
            raise ValueError("PDF table provenance is invalid.")
        if len(self.bbox) != 4 or not all(math.isfinite(value) for value in self.bbox):
            raise ValueError("PDF table bounding box is invalid.")
        if not self.rows or any(not row for row in self.rows):
            raise ValueError("PDF table rows are empty.")
        column_count = len(self.rows[0])
        if any(len(row) != column_count for row in self.rows):
            raise ValueError("PDF table rows are not rectangular.")
        if sum(len(row) for row in self.rows) > MAX_PDF_TABLE_CELLS:
            raise ValueError("PDF table cell count exceeds the limit.")
        if (
            sum(len(cell) for row in self.rows for cell in row)
            > MAX_PDF_TABLE_TEXT_CHARS
        ):
            raise ValueError("PDF table text count exceeds the limit.")
        if self.source_kind != PDF_TABLE_SOURCE_KIND:
            raise ValueError("PDF table source kind is invalid.")

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def cell_count(self) -> int:
        return sum(len(row) for row in self.rows)

    def safe_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "table_index": self.table_index,
            "bbox": list(self.bbox),
            "row_count": self.row_count,
            "cell_count": self.cell_count,
            "rows": [list(row) for row in self.rows],
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True, slots=True)
class PdfTableResult:
    """Bounded table extraction result and explicit unsupported pages."""

    page_count: int
    tables: tuple[PdfTable, ...] = field(repr=False)
    unsupported_page_numbers: tuple[int, ...] = ()
    scope: str = PDF_TABLE_SCOPE

    def __post_init__(self) -> None:
        if self.page_count < 1 or self.page_count > MAX_PDF_TABLE_PAGES:
            raise ValueError("PDF table page count is invalid.")
        if len(self.tables) > MAX_PDF_TABLE_TABLES:
            raise ValueError("PDF table count exceeds the limit.")
        if sum(table.row_count for table in self.tables) > MAX_PDF_TABLE_ROWS:
            raise ValueError("PDF table row count exceeds the limit.")
        if sum(table.cell_count for table in self.tables) > MAX_PDF_TABLE_CELLS:
            raise ValueError("PDF table cell count exceeds the limit.")
        if (
            sum(
                len(cell) for table in self.tables for row in table.rows for cell in row
            )
            > MAX_PDF_TABLE_TEXT_CHARS
        ):
            raise ValueError("PDF table text count exceeds the limit.")
        if any(table.page_number > self.page_count for table in self.tables):
            raise ValueError("PDF table page provenance exceeds the document.")
        if any(
            page < 1 or page > self.page_count for page in self.unsupported_page_numbers
        ):
            raise ValueError("PDF unsupported page provenance is invalid.")
        if len(set(self.unsupported_page_numbers)) != len(
            self.unsupported_page_numbers
        ):
            raise ValueError("PDF unsupported page provenance is not unique.")
        if self.scope != PDF_TABLE_SCOPE:
            raise ValueError("PDF table scope is invalid.")

    @property
    def status(self) -> str:
        if not self.tables:
            return PDF_TABLE_STATUS_UNSUPPORTED
        if self.unsupported_page_numbers:
            return PDF_TABLE_STATUS_PARTIAL
        return PDF_TABLE_STATUS_FOUND

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def row_count(self) -> int:
        return sum(table.row_count for table in self.tables)

    @property
    def cell_count(self) -> int:
        return sum(table.cell_count for table in self.tables)

    def safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "scope": self.scope,
            "page_count": self.page_count,
            "table_count": self.table_count,
            "row_count": self.row_count,
            "cell_count": self.cell_count,
            "unsupported_page_numbers": list(self.unsupported_page_numbers),
            "tables": [table.safe_dict() for table in self.tables],
        }


def _table_error(code: str, message: str) -> DocumentNormalizationError:
    return DocumentNormalizationError(code, message)


def _normalize_cell(value: Any) -> str:
    if value is None:
        raise _table_error(
            "pdf_table_cell_ambiguous", "PDF table contains an ambiguous empty cell."
        )
    if not isinstance(value, str):
        raise _table_error(
            "pdf_table_cell_invalid", "PDF table contains an invalid cell value."
        )
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > MAX_PDF_TABLE_CELL_CHARS:
        raise _table_error(
            "pdf_table_cell_limit", "PDF table cell text exceeds the limit."
        )
    return normalized


def _normalize_bbox(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise _table_error(
            "pdf_table_bbox_invalid", "PDF table bounding box is invalid."
        )
    try:
        bbox = tuple(round(float(item), 3) for item in value)
    except (TypeError, ValueError) as error:
        raise _table_error(
            "pdf_table_bbox_invalid", "PDF table bounding box is invalid."
        ) from error
    if not all(math.isfinite(item) for item in bbox):
        raise _table_error(
            "pdf_table_bbox_invalid", "PDF table bounding box is invalid."
        )
    return bbox


def _extract_page_tables(
    page: Any,
    page_number: int,
    *,
    table_count: int,
    parse_errors: tuple[type[BaseException], ...],
) -> tuple[tuple[PdfTable, ...], int]:
    try:
        found = page.find_tables(table_settings=PDF_TABLE_SETTINGS)
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError) as error:
        raise _table_error(
            "pdf_table_detection_failed", "PDF table detection failed."
        ) from error
    if not found:
        return (), table_count
    tables: list[PdfTable] = []
    for table_index, raw_table in enumerate(found, start=1):
        if table_count + len(tables) >= MAX_PDF_TABLE_TABLES:
            raise _table_error(
                "pdf_table_count_limit", "PDF table count exceeds the limit."
            )
        try:
            raw_rows = raw_table.extract()
            bbox = _normalize_bbox(raw_table.bbox)
        except parse_errors as error:
            if isinstance(error, DocumentNormalizationError):
                raise
            raise _table_error(
                "pdf_table_extraction_failed", "PDF table extraction failed."
            ) from error
        if not raw_rows:
            raise _table_error(
                "pdf_table_ambiguous", "PDF table has ambiguous or empty rows."
            )
        rows: list[tuple[str, ...]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, (tuple, list)) or not raw_row:
                raise _table_error("pdf_table_ambiguous", "PDF table row is ambiguous.")
            rows.append(tuple(_normalize_cell(cell) for cell in raw_row))
        if len(rows) > MAX_PDF_TABLE_ROWS:
            raise _table_error(
                "pdf_table_row_limit", "PDF table row count exceeds the limit."
            )
        if any(len(row) != len(rows[0]) for row in rows):
            raise _table_error(
                "pdf_table_ambiguous", "PDF table rows are not rectangular."
            )
        tables.append(
            PdfTable(
                page_number=page_number,
                table_index=table_index,
                bbox=bbox,
                rows=tuple(rows),
            )
        )
    return tuple(tables), table_count + len(tables)


def _load_pdfplumber() -> tuple[Any, type[BaseException], type[BaseException]]:
    try:
        import pdfplumber
        from pdfminer.pdfdocument import PDFException
        from pdfplumber.utils.exceptions import PdfminerException
    except ModuleNotFoundError as error:
        raise _table_error(
            "pdf_table_dependency_unavailable", "PDF table dependency is unavailable."
        ) from error
    return pdfplumber, PDFException, PdfminerException


def extract_pdf_tables(
    *,
    name: Any,
    media_type: Any = "application/pdf",
    payload: Any,
) -> PdfTableResult:
    """Extract bounded ruled tables without OCR or layout fabrication."""

    _, safe_media = validate_document_identity(
        name=name, media_type=media_type, source_kind="binary"
    )
    if safe_media != "application/pdf":
        raise _table_error(
            "pdf_table_media_type_invalid", "PDF table extraction requires a PDF."
        )
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise _table_error("pdf_table_payload_invalid", "PDF table payload is invalid.")
    binary = bytes(payload)
    if len(binary) > MAX_BINARY_DOCUMENT_BYTES:
        raise _table_error(
            "pdf_table_payload_limit", "PDF table payload exceeds the byte limit."
        )
    pdfplumber, pdf_exception, pdfminer_exception = _load_pdfplumber()
    parse_errors = (
        pdf_exception,
        pdfminer_exception,
        KeyError,
        IndexError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        RecursionError,
    )
    tables: list[PdfTable] = []
    unsupported_pages: list[int] = []
    try:
        with pdfplumber.open(BytesIO(binary), strict_metadata=True) as document:
            page_count = len(document.pages)
            if page_count < 1:
                raise _table_error(
                    "pdf_table_no_pages", "PDF table extraction requires a page."
                )
            if page_count > MAX_PDF_TABLE_PAGES:
                raise _table_error(
                    "pdf_table_page_limit", "PDF table page count exceeds the limit."
                )
            for page_index, page in enumerate(document.pages, start=1):
                page_tables, _ = _extract_page_tables(
                    page,
                    page_index,
                    table_count=len(tables),
                    parse_errors=parse_errors,
                )
                if not page_tables:
                    unsupported_pages.append(page_index)
                tables.extend(page_tables)
    except DocumentNormalizationError:
        raise
    except parse_errors as error:
        raise _table_error(
            "pdf_table_reader_failed", "PDF table reader failed."
        ) from error
    return PdfTableResult(
        page_count=page_count,
        tables=tuple(tables),
        unsupported_page_numbers=tuple(unsupported_pages),
    )


__all__ = [
    "MAX_PDF_TABLE_CELLS",
    "MAX_PDF_TABLE_CELL_CHARS",
    "MAX_PDF_TABLE_PAGES",
    "MAX_PDF_TABLE_ROWS",
    "MAX_PDF_TABLE_SOURCE_BYTES",
    "MAX_PDF_TABLE_TABLES",
    "MAX_PDF_TABLE_TEXT_CHARS",
    "PDF_TABLE_SCOPE",
    "PDF_TABLE_SETTINGS",
    "PDF_TABLE_SOURCE_KIND",
    "PDF_TABLE_STATUS_FOUND",
    "PDF_TABLE_STATUS_PARTIAL",
    "PDF_TABLE_STATUS_UNSUPPORTED",
    "PdfTable",
    "PdfTableResult",
    "extract_pdf_tables",
]
