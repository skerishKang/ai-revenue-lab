"""KAgent facade for bounded ruled PDF table extraction."""

from __future__ import annotations

from dataclasses import dataclass, field

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_table import PdfTableResult as CorePdfTableResult
from padiem_ai_core.pdf_table import extract_pdf_tables as _extract_core

from .claw_skill_registry import CAPABILITY_PDF_READ
from .file_intake_safety import FileIntakeSafetyError
from .pdf_inspection import PdfInspectionResult, inspect_pdf_document

PDF_TABLE_SOURCE_KIND = "ruled_machine_generated"
PDF_TABLE_ERROR_CODES = frozenset(
    {
        "pdf_table_input_rejected",
        "pdf_table_output_mismatch",
        "pdf_table_extraction_failed",
    }
)


class PdfTableError(ValueError):
    """Fail-closed PDF table error carrying one stable reason code."""

    def __init__(self, code: str) -> None:
        if code not in PDF_TABLE_ERROR_CODES:
            raise ValueError(f"unknown PDF table error code: {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PdfTableExtractionResult:
    """Verified table extraction plus canonical PDF inspection receipt."""

    capability_id: str
    source_kind: str
    inspection: PdfInspectionResult
    artifact: CorePdfTableResult = field(repr=False)

    def __post_init__(self) -> None:
        if self.capability_id != CAPABILITY_PDF_READ:
            raise ValueError("PDF table result has an invalid capability ID.")
        if self.source_kind != PDF_TABLE_SOURCE_KIND:
            raise ValueError("PDF table result has an invalid source kind.")
        if (
            not self.inspection.safe_to_read
            or self.inspection.inspection is None
            or self.artifact.page_count != self.inspection.inspection.page_count
        ):
            raise ValueError("PDF table result has invalid inspection metadata.")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "source_kind": self.source_kind,
            "input_gate": self.inspection.gate.safe_dict(),
            **self.artifact.safe_dict(),
        }


def extract_pdf_tables_from_document(
    filename: str, payload: bytes
) -> PdfTableExtractionResult:
    """Extract bounded ruled tables after canonical PDF admission."""

    try:
        inspection = inspect_pdf_document(filename, payload)
    except (
        FileIntakeSafetyError,
        TypeError,
        ValueError,
        RuntimeError,
        OSError,
    ) as error:
        raise PdfTableError("pdf_table_input_rejected") from error
    if not inspection.safe_to_read or inspection.inspection is None:
        raise PdfTableError("pdf_table_input_rejected")
    try:
        artifact = _extract_core(
            name=filename,
            media_type="application/pdf",
            payload=payload,
        )
    except (
        DocumentNormalizationError,
        TypeError,
        ValueError,
        RuntimeError,
        OSError,
    ) as error:
        raise PdfTableError("pdf_table_extraction_failed") from error
    if artifact.page_count != inspection.inspection.page_count:
        raise PdfTableError("pdf_table_output_mismatch")
    try:
        return PdfTableExtractionResult(
            capability_id=CAPABILITY_PDF_READ,
            source_kind=PDF_TABLE_SOURCE_KIND,
            inspection=inspection,
            artifact=artifact,
        )
    except (TypeError, ValueError) as error:
        raise PdfTableError("pdf_table_output_mismatch") from error


__all__ = [
    "PDF_TABLE_ERROR_CODES",
    "PDF_TABLE_SOURCE_KIND",
    "PdfTableError",
    "PdfTableExtractionResult",
    "extract_pdf_tables_from_document",
]
