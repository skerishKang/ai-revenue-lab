"""#3036: PDF native inspection and page-text read foundation.

The #2824 file-intake gate remains the only admission authority. Once a PDF is
admitted, the Core canonical pypdf reader is reused through ``inspect_pdf``;
this module does not import pypdf, perform OCR, extract tables, author PDFs,
merge/split files, or render pages.
"""

from __future__ import annotations

from dataclasses import dataclass

from padiem_ai_core.document_normalization import PdfInspection, inspect_pdf

from .claw_skill_registry import CAPABILITY_PDF_INSPECT, CAPABILITY_PDF_READ
from .file_intake_safety import DetectedFormat, FileIntakeResult, inspect_file

PDF_CAPABILITY_IDS = (CAPABILITY_PDF_INSPECT, CAPABILITY_PDF_READ)


@dataclass(frozen=True, slots=True)
class PdfInspectionResult:
    inspection: PdfInspection | None
    gate: FileIntakeResult

    @property
    def safe_to_read(self) -> bool:
        return self.inspection is not None

    @property
    def native_text_available(self) -> bool | None:
        return (
            None
            if self.inspection is None
            else self.inspection.native_text_available
        )

    @property
    def native_text_state(self) -> str | None:
        return None if self.inspection is None else self.inspection.native_text_state


def inspect_pdf_document(name: str, data: bytes) -> PdfInspectionResult:
    """Run the existing #2824 gate, then native PDF page-text inspection."""
    gate = inspect_file(name, data)
    if not gate.safe_to_parse or gate.detected_format is not DetectedFormat.PDF:
        return PdfInspectionResult(None, gate)
    return PdfInspectionResult(inspect_pdf(name=name, media_type="application/pdf", payload=data), gate)


__all__ = ["PDF_CAPABILITY_IDS", "PdfInspectionResult", "inspect_pdf_document"]
