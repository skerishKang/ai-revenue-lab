"""KAgent facade for bounded embedded-image PDF page previews."""

from __future__ import annotations

from dataclasses import dataclass, field

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_preview import PdfPreviewResult as CorePdfPreviewResult
from padiem_ai_core.pdf_preview import (
    render_pdf_embedded_image_previews as _render_core,
)

from .claw_skill_registry import CAPABILITY_PDF_TRANSFORM
from .file_intake_safety import (
    DetectedFormat,
    FileIntakeResult,
    FileIntakeSafetyError,
    inspect_file,
)

PDF_MEDIA_TYPE = "application/pdf"
PDF_PREVIEW_SOURCE_KIND = "embedded_image_xobjects"
PDF_PREVIEW_ERROR_CODES = frozenset(
    {"pdf_preview_input_gate_rejected", "pdf_preview_render_failed"}
)


class PdfPreviewError(ValueError):
    """Fail-closed PDF preview error carrying one stable reason code."""

    def __init__(self, code: str) -> None:
        if code not in PDF_PREVIEW_ERROR_CODES:
            raise ValueError(f"unknown PDF preview error code: {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PdfPreviewResult:
    """Verified embedded-image previews plus the admission receipt."""

    capability_id: str
    source_kind: str
    gate: FileIntakeResult
    artifact: CorePdfPreviewResult = field(repr=False)

    def __post_init__(self) -> None:
        if self.capability_id != CAPABILITY_PDF_TRANSFORM:
            raise ValueError("PDF preview result has an invalid capability ID.")
        if self.source_kind != PDF_PREVIEW_SOURCE_KIND:
            raise ValueError("PDF preview result has an invalid source kind.")
        if (
            not self.gate.safe_to_parse
            or self.gate.detected_format is not DetectedFormat.PDF
            or self.artifact.page_count < 1
        ):
            raise ValueError("PDF preview result has invalid admission metadata.")

    def to_public_dict(self) -> dict[str, object]:
        public = self.artifact.safe_dict()
        return {
            "capability_id": self.capability_id,
            "source_kind": self.source_kind,
            "input_gate": self.gate.safe_dict(),
            **public,
        }


def preview_pdf_pages(name: str, payload: bytes) -> PdfPreviewResult:
    """Preview embedded images from an admitted PDF without full-page rendering."""

    try:
        gate = inspect_file(name, payload)
    except (FileIntakeSafetyError, TypeError) as error:
        raise PdfPreviewError("pdf_preview_input_gate_rejected") from error
    if not gate.safe_to_parse or gate.detected_format is not DetectedFormat.PDF:
        raise PdfPreviewError("pdf_preview_input_gate_rejected")
    try:
        artifact = _render_core(
            name=name,
            media_type=PDF_MEDIA_TYPE,
            payload=payload,
        )
    except DocumentNormalizationError as error:
        raise PdfPreviewError("pdf_preview_render_failed") from error
    return PdfPreviewResult(
        capability_id=CAPABILITY_PDF_TRANSFORM,
        source_kind=PDF_PREVIEW_SOURCE_KIND,
        gate=gate,
        artifact=artifact,
    )


__all__ = [
    "PDF_MEDIA_TYPE",
    "PDF_PREVIEW_ERROR_CODES",
    "PDF_PREVIEW_SOURCE_KIND",
    "PdfPreviewError",
    "PdfPreviewResult",
    "preview_pdf_pages",
]
