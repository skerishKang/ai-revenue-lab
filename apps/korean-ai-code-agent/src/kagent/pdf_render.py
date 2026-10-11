"""KAgent facade for bounded full-page PDF rendering."""

from __future__ import annotations

from dataclasses import dataclass, field

from padiem_ai_core.pdf_render import PdfRenderResult as CorePdfRenderResult
from padiem_ai_core.pdf_render import render_pdf_pages as _render_core

from .claw_skill_registry import CAPABILITY_PDF_INSPECT
from .pdf_inspection import PdfInspectionResult, inspect_pdf_document

PDF_MEDIA_TYPE = "application/pdf"
PDF_RENDER_SOURCE_KIND = "full_page_raster_preview"
PDF_RENDER_ERROR_CODES = frozenset(
    {
        "pdf_render_input_rejected",
        "pdf_render_output_mismatch",
        "pdf_render_failed",
    }
)


class PdfRenderError(ValueError):
    """Fail-closed PDF render error carrying one stable reason code."""

    def __init__(self, code: str) -> None:
        if code not in PDF_RENDER_ERROR_CODES:
            raise ValueError(f"unknown PDF render error code: {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PdfRenderResult:
    """Verified rendered pages plus the canonical intake/readback receipt."""

    capability_id: str
    source_kind: str
    inspection: PdfInspectionResult
    artifact: CorePdfRenderResult = field(repr=False)

    def __post_init__(self) -> None:
        if self.capability_id != CAPABILITY_PDF_INSPECT:
            raise ValueError("PDF render result has an invalid capability ID.")
        if self.source_kind != PDF_RENDER_SOURCE_KIND:
            raise ValueError("PDF render result has an invalid source kind.")
        if (
            not self.inspection.safe_to_read
            or self.inspection.inspection is None
            or self.artifact.page_count != self.inspection.inspection.page_count
        ):
            raise ValueError("PDF render result has invalid readback metadata.")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "source_kind": self.source_kind,
            "input_gate": self.inspection.gate.safe_dict(),
            **self.artifact.safe_dict(),
        }


def render_pdf_page_previews(filename: str, payload: bytes) -> PdfRenderResult:
    """Render an admitted PDF with the adopted PDFium adapter."""

    try:
        inspection = inspect_pdf_document(filename, payload)
    except Exception as error:
        raise PdfRenderError("pdf_render_input_rejected") from error
    if not inspection.safe_to_read or inspection.inspection is None:
        raise PdfRenderError("pdf_render_input_rejected")
    try:
        artifact = _render_core(
            name=filename,
            media_type=PDF_MEDIA_TYPE,
            payload=payload,
        )
    except Exception as error:
        raise PdfRenderError("pdf_render_failed") from error
    if artifact.page_count != inspection.inspection.page_count:
        raise PdfRenderError("pdf_render_output_mismatch")
    return PdfRenderResult(
        capability_id=CAPABILITY_PDF_INSPECT,
        source_kind=PDF_RENDER_SOURCE_KIND,
        inspection=inspection,
        artifact=artifact,
    )


__all__ = [
    "PDF_MEDIA_TYPE",
    "PDF_RENDER_ERROR_CODES",
    "PDF_RENDER_SOURCE_KIND",
    "PdfRenderError",
    "PdfRenderResult",
    "render_pdf_page_previews",
]
