"""Deterministic scanned-vs-native PDF classification over existing inspection."""

from __future__ import annotations

from dataclasses import dataclass

from .claw_skill_registry import CAPABILITY_PDF_INSPECT
from .pdf_inspection import PdfInspectionResult, inspect_pdf_document

PDF_CLASSIFICATION_NATIVE_TEXT = "native_text"
PDF_CLASSIFICATION_NO_NATIVE_TEXT = "no_native_text_ocr_candidate"
PDF_CLASSIFICATION_CAPABILITY_ID = CAPABILITY_PDF_INSPECT


@dataclass(frozen=True, slots=True)
class PdfClassificationResult:
    inspection_result: PdfInspectionResult
    classification: str | None

    @property
    def safe_to_classify(self) -> bool:
        return self.classification is not None

    @property
    def ocr_candidate(self) -> bool | None:
        if self.classification is None:
            return None
        return self.classification == PDF_CLASSIFICATION_NO_NATIVE_TEXT

    def to_public_dict(self) -> dict[str, object]:
        inspection = self.inspection_result.inspection
        return {
            "capability_id": PDF_CLASSIFICATION_CAPABILITY_ID,
            "classification": self.classification,
            "safe_to_classify": self.safe_to_classify,
            "ocr_candidate": self.ocr_candidate,
            "native_text_available": self.inspection_result.native_text_available,
            "native_text_state": self.inspection_result.native_text_state,
            "page_count": None if inspection is None else inspection.page_count,
            "gate": self.inspection_result.gate.safe_dict(),
        }


def classify_pdf_document(name: str, data: bytes) -> PdfClassificationResult:
    """Classify from native text evidence without invoking OCR or another parser."""
    inspection_result = inspect_pdf_document(name, data)
    if inspection_result.inspection is None:
        classification = None
    elif inspection_result.native_text_available:
        classification = PDF_CLASSIFICATION_NATIVE_TEXT
    else:
        classification = PDF_CLASSIFICATION_NO_NATIVE_TEXT
    return PdfClassificationResult(inspection_result, classification)


__all__ = [
    "PDF_CLASSIFICATION_CAPABILITY_ID",
    "PDF_CLASSIFICATION_NATIVE_TEXT",
    "PDF_CLASSIFICATION_NO_NATIVE_TEXT",
    "PdfClassificationResult",
    "classify_pdf_document",
]
