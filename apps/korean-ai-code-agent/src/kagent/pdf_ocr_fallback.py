"""Bounded PDF OCR fallback composition over the adopted authorities.

The composition keeps native pypdf text authoritative, renders only through the
existing PDFium facade, and sends only the rendered canonical PNG into the
existing isolated ``image.ocr`` facade. It adds no parser, renderer, OCR child,
file-intake gate, or Skill identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .claw_skill_registry import CAPABILITY_PDF_OCR
from .image_ocr_contract import (
    OCR_RUNTIME_MISSING_REASON_CODE,
    OCR_TIMEOUT_REASON_CODE,
)
from .image_ocr_isolation import OcrOutcome
from .image_skill import ImageOcrResult, ImageSkillError, image_ocr
from .pdf_inspection import PdfInspectionResult, inspect_pdf_document
from .pdf_render import PdfRenderError, PdfRenderResult, render_pdf_page_previews

PDF_OCR_SOURCE_NATIVE = "native"
PDF_OCR_SOURCE_OCR = "ocr"
PDF_OCR_RESULT_NATIVE_ONLY = "native_only"
PDF_OCR_RESULT_OCR_FALLBACK = "ocr_fallback"
PDF_OCR_RESULT_MIXED = "mixed_native_ocr"
PDF_OCR_RESULT_KINDS = frozenset(
    {PDF_OCR_RESULT_NATIVE_ONLY, PDF_OCR_RESULT_OCR_FALLBACK, PDF_OCR_RESULT_MIXED}
)
PDF_OCR_RESULT_NATIVE = "native_pypdf"
PDF_OCR_RESULT_OCR = "paddleocr_isolated"
PDF_OCR_ERROR_CODES = frozenset(
    {
        "pdf_ocr_input_rejected",
        "pdf_ocr_render_failed",
        "pdf_ocr_page_mismatch",
        "pdf_ocr_runtime_missing",
        "pdf_ocr_timeout",
        "pdf_ocr_failed",
    }
)


class PdfOcrError(ValueError):
    """Fail-closed PDF OCR error with a bounded code and optional page."""

    def __init__(self, code: str, *, page_number: int | None = None) -> None:
        if code not in PDF_OCR_ERROR_CODES:
            raise ValueError(f"unknown PDF OCR error code: {code!r}")
        if page_number is not None and (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number < 1
        ):
            raise ValueError("page_number must be a positive integer or None")
        self.code = code
        self.page_number = page_number
        super().__init__(code)

    def safe_dict(self) -> dict[str, object]:
        return {"code": self.code, "page_number": self.page_number}


@dataclass(frozen=True, slots=True)
class PdfOcrPage:
    """One ordered PDF page with explicit native/OCR source provenance."""

    page_number: int
    page_count: int
    text: str
    source_kind: str
    text_source: str
    ocr: ImageOcrResult | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.page_number < 1 or self.page_count < self.page_number:
            raise ValueError("PDF OCR page provenance is invalid.")
        if not isinstance(self.text, str):
            raise TypeError("PDF OCR page text must be a string.")
        expected = {
            PDF_OCR_SOURCE_NATIVE: PDF_OCR_RESULT_NATIVE,
            PDF_OCR_SOURCE_OCR: PDF_OCR_RESULT_OCR,
        }.get(self.source_kind)
        if expected is None or self.text_source != expected:
            raise ValueError("PDF OCR source provenance is invalid.")
        if self.source_kind == PDF_OCR_SOURCE_OCR:
            if self.ocr is None or self.ocr.ocr.outcome is not OcrOutcome.COMPLETED:
                raise ValueError("an OCR-sourced page requires completed OCR evidence.")
        elif self.ocr is not None:
            raise ValueError("a native-sourced page cannot carry OCR evidence.")

    def safe_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "page_count": self.page_count,
            "text": self.text,
            "source_kind": self.source_kind,
            "text_source": self.text_source,
            "ocr": self.ocr.safe_dict() if self.ocr is not None else None,
        }


@dataclass(frozen=True, slots=True)
class PdfOcrFallbackResult:
    """Complete ordered PDF text projection with bounded OCR receipts."""

    capability_id: str
    source_kind: str
    inspection: PdfInspectionResult
    pages: tuple[PdfOcrPage, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if self.capability_id != CAPABILITY_PDF_OCR:
            raise ValueError("PDF OCR result has an invalid capability ID.")
        if not self.inspection.safe_to_read or self.inspection.inspection is None:
            raise ValueError("PDF OCR result has no verified native inspection.")
        inspection = self.inspection.inspection
        page_count = inspection.page_count
        if len(self.pages) != page_count:
            raise ValueError("PDF OCR result page count does not match inspection.")
        if [page.page_number for page in self.pages] != list(range(1, page_count + 1)):
            raise ValueError("PDF OCR result page numbers are not contiguous.")
        if any(page.page_count != page_count for page in self.pages):
            raise ValueError(
                "PDF OCR result page provenance does not match inspection."
            )
        kinds = {page.source_kind for page in self.pages}
        if not kinds or not kinds.issubset({PDF_OCR_SOURCE_NATIVE, PDF_OCR_SOURCE_OCR}):
            raise ValueError("PDF OCR result source kinds are invalid.")
        if self.source_kind not in PDF_OCR_RESULT_KINDS:
            raise ValueError("PDF OCR result source kind is invalid.")
        if self.source_kind == PDF_OCR_RESULT_NATIVE_ONLY:
            if kinds != {PDF_OCR_SOURCE_NATIVE}:
                raise ValueError("native-only PDF OCR result carries OCR pages.")
        elif self.source_kind == PDF_OCR_RESULT_OCR_FALLBACK:
            if kinds != {PDF_OCR_SOURCE_OCR}:
                raise ValueError(
                    "OCR-fallback PDF OCR result must contain only OCR pages."
                )
        elif self.source_kind == PDF_OCR_RESULT_MIXED:
            if kinds != {PDF_OCR_SOURCE_NATIVE, PDF_OCR_SOURCE_OCR}:
                raise ValueError(
                    "mixed PDF OCR result does not contain both source kinds."
                )
        else:
            raise ValueError("PDF OCR result source kind is invalid.")

    @property
    def ocr_page_count(self) -> int:
        return sum(page.source_kind == PDF_OCR_SOURCE_OCR for page in self.pages)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "source_kind": self.source_kind,
            "page_count": len(self.pages),
            "ocr_page_count": self.ocr_page_count,
            "input_gate": self.inspection.gate.safe_dict(),
            "pages": [page.safe_dict() for page in self.pages],
        }


def _render_failure(error: Exception) -> PdfOcrError:
    if isinstance(error, PdfRenderError) and error.code == "pdf_render_output_mismatch":
        return PdfOcrError("pdf_ocr_page_mismatch")
    return PdfOcrError("pdf_ocr_render_failed")


def _ocr_failure(result: ImageOcrResult, page_number: int) -> PdfOcrError:
    reason = result.ocr.reason_code
    if reason == OCR_RUNTIME_MISSING_REASON_CODE:
        return PdfOcrError("pdf_ocr_runtime_missing", page_number=page_number)
    if reason == OCR_TIMEOUT_REASON_CODE:
        return PdfOcrError("pdf_ocr_timeout", page_number=page_number)
    return PdfOcrError("pdf_ocr_failed", page_number=page_number)


def _result_kind(pages: tuple[PdfOcrPage, ...]) -> str:
    kinds = {page.source_kind for page in pages}
    if kinds == {PDF_OCR_SOURCE_NATIVE}:
        return PDF_OCR_RESULT_NATIVE_ONLY
    if kinds == {PDF_OCR_SOURCE_OCR}:
        return PDF_OCR_RESULT_OCR_FALLBACK
    return PDF_OCR_RESULT_MIXED


def _build_result(
    inspection: PdfInspectionResult, pages: tuple[PdfOcrPage, ...]
) -> PdfOcrFallbackResult:
    try:
        return PdfOcrFallbackResult(
            capability_id=CAPABILITY_PDF_OCR,
            source_kind=_result_kind(pages),
            inspection=inspection,
            pages=pages,
        )
    except ValueError as error:
        raise PdfOcrError("pdf_ocr_page_mismatch") from error


def compose_pdf_ocr_fallback(
    filename: str,
    payload: bytes,
    *,
    detector_dir: str,
    recognizer_dir: str,
) -> PdfOcrFallbackResult:
    """Read native PDF text and OCR only pages without sufficient native text."""

    try:
        inspection = inspect_pdf_document(filename, payload)
    except Exception as error:
        raise PdfOcrError("pdf_ocr_input_rejected") from error
    if not inspection.safe_to_read or inspection.inspection is None:
        raise PdfOcrError("pdf_ocr_input_rejected")

    native = inspection.inspection
    if [page.page_number for page in native.pages] != list(
        range(1, native.page_count + 1)
    ):
        raise PdfOcrError("pdf_ocr_page_mismatch")
    fallback_numbers = {page.page_number for page in native.pages if not page.text}
    if not fallback_numbers:
        pages = tuple(
            PdfOcrPage(
                page_number=page.page_number,
                page_count=native.page_count,
                text=page.text,
                source_kind=PDF_OCR_SOURCE_NATIVE,
                text_source=PDF_OCR_RESULT_NATIVE,
            )
            for page in native.pages
        )
        return _build_result(inspection, pages)

    try:
        rendered: PdfRenderResult = render_pdf_page_previews(filename, payload)
    except Exception as error:
        raise _render_failure(error) from error
    if rendered.artifact.page_count != native.page_count:
        raise PdfOcrError("pdf_ocr_page_mismatch")
    rendered_by_number = {page.page_number: page for page in rendered.artifact.pages}
    if set(rendered_by_number) != set(range(1, native.page_count + 1)):
        raise PdfOcrError("pdf_ocr_page_mismatch")

    pages: list[PdfOcrPage] = []
    for native_page in native.pages:
        if native_page.text:
            pages.append(
                PdfOcrPage(
                    page_number=native_page.page_number,
                    page_count=native.page_count,
                    text=native_page.text,
                    source_kind=PDF_OCR_SOURCE_NATIVE,
                    text_source=PDF_OCR_RESULT_NATIVE,
                )
            )
            continue
        rendered_page = rendered_by_number[native_page.page_number]
        ocr_filename = f"pdf-page-{native_page.page_number}.png"
        try:
            ocr_result = image_ocr(
                rendered_page.data,
                filename=ocr_filename,
                detector_dir=detector_dir,
                recognizer_dir=recognizer_dir,
            )
        except ImageSkillError as error:
            raise PdfOcrError(
                "pdf_ocr_input_rejected", page_number=native_page.page_number
            ) from error
        except Exception as error:
            raise PdfOcrError(
                "pdf_ocr_failed", page_number=native_page.page_number
            ) from error
        if ocr_result.ocr.outcome is not OcrOutcome.COMPLETED:
            raise _ocr_failure(ocr_result, native_page.page_number)
        text = "\n".join(result.text for result in ocr_result.ocr.results)
        pages.append(
            PdfOcrPage(
                page_number=native_page.page_number,
                page_count=native.page_count,
                text=text,
                source_kind=PDF_OCR_SOURCE_OCR,
                text_source=PDF_OCR_RESULT_OCR,
                ocr=ocr_result,
            )
        )

    return _build_result(inspection, tuple(pages))


__all__ = [
    "CAPABILITY_PDF_OCR",
    "PDF_OCR_ERROR_CODES",
    "PDF_OCR_RESULT_MIXED",
    "PDF_OCR_RESULT_NATIVE",
    "PDF_OCR_RESULT_NATIVE_ONLY",
    "PDF_OCR_RESULT_OCR",
    "PDF_OCR_RESULT_OCR_FALLBACK",
    "PDF_OCR_SOURCE_NATIVE",
    "PDF_OCR_SOURCE_OCR",
    "PdfOcrError",
    "PdfOcrFallbackResult",
    "PdfOcrPage",
    "compose_pdf_ocr_fallback",
]
