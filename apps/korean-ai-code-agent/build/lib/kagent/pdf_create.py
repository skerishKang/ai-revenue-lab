"""KAgent facade for bounded PDF creation from admitted image pages."""

from __future__ import annotations

from dataclasses import dataclass, field

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.image_helpers import ImagePdfOutput

from . import image_skill
from .claw_skill_registry import CAPABILITY_PDF_CREATE, RESERVED_CAPABILITY_IDS
from .file_intake_safety import FileIntakeSafetyError
from .image_skill import FACADE_ERROR_CODES as IMAGE_FACADE_ERROR_CODES
from .image_skill import ImageSkillError
from .pdf_inspection import inspect_pdf_document

PDF_MEDIA_TYPE = "application/pdf"
PDF_CREATE_SOURCE_IMAGE_PAGES = "admitted_image_pages"
PDF_CREATE_STATUS_OK = "ok"
PDF_CREATE_VALIDATION_PASS = "pdf_intake_and_readback_pass"
PDF_CREATE_REASON_CAPABILITY_UNAVAILABLE = "pdf_create_capability_unavailable"
PDF_CREATE_REASON_PAGES_INVALID = "pdf_create_pages_invalid"
PDF_CREATE_REASON_OUTPUT_REJECTED = "pdf_create_output_rejected"
PDF_CREATE_ERROR_CODES = (
    frozenset(
        {
            PDF_CREATE_REASON_CAPABILITY_UNAVAILABLE,
            PDF_CREATE_REASON_PAGES_INVALID,
            PDF_CREATE_REASON_OUTPUT_REJECTED,
        }
    )
    | IMAGE_FACADE_ERROR_CODES
)


class PdfCreateError(ValueError):
    """Fail-closed PDF creation error carrying one stable reason code."""

    def __init__(self, code: str) -> None:
        if code not in PDF_CREATE_ERROR_CODES:
            raise ValueError(f"unknown PDF create error code: {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PdfCreateResult:
    """A verified in-memory PDF artifact with bounded image-page provenance."""

    capability_id: str
    source_kind: str
    artifact: ImagePdfOutput = field(repr=False)
    validation_status: str
    native_text_state: str

    def __post_init__(self) -> None:
        if self.capability_id != CAPABILITY_PDF_CREATE:
            raise ValueError("PDF create result has an invalid capability ID.")
        if self.source_kind != PDF_CREATE_SOURCE_IMAGE_PAGES:
            raise ValueError("PDF create result has an invalid source kind.")
        if (
            not isinstance(self.artifact.data, bytes)
            or not self.artifact.data
            or self.artifact.page_count < 1
            or len(self.artifact.pages) != self.artifact.page_count
        ):
            raise ValueError("PDF create result has invalid artifact metadata.")
        if self.validation_status != PDF_CREATE_VALIDATION_PASS:
            raise ValueError("PDF create result has invalid validation status.")
        if not isinstance(self.native_text_state, str) or not self.native_text_state:
            raise ValueError("PDF create result has invalid native text state.")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": PDF_CREATE_STATUS_OK,
            "capability_id": self.capability_id,
            "source_kind": self.source_kind,
            "media_type": PDF_MEDIA_TYPE,
            "output_page_count": self.artifact.page_count,
            "output_byte_size": self.artifact.size_bytes,
            "page_provenance": [page.safe_dict() for page in self.artifact.pages],
            "validation_status": self.validation_status,
            "native_text_state": self.native_text_state,
        }


def create_pdf_from_image_pages(
    pages: object,
) -> PdfCreateResult:
    """Create and read back one PDF from ordered admitted image pages."""

    if CAPABILITY_PDF_CREATE not in RESERVED_CAPABILITY_IDS:
        raise PdfCreateError(PDF_CREATE_REASON_CAPABILITY_UNAVAILABLE)
    if not isinstance(pages, tuple) or not pages:
        raise PdfCreateError(PDF_CREATE_REASON_PAGES_INVALID)
    try:
        artifact = image_skill.image_to_pdf(pages)
    except ImageSkillError as error:
        raise PdfCreateError(error.code) from error
    try:
        readback = inspect_pdf_document("created.pdf", artifact.data)
    except (DocumentNormalizationError, FileIntakeSafetyError, TypeError) as error:
        raise PdfCreateError(PDF_CREATE_REASON_OUTPUT_REJECTED) from error
    inspection = readback.inspection
    if inspection is None or inspection.page_count != artifact.page_count:
        raise PdfCreateError(PDF_CREATE_REASON_OUTPUT_REJECTED)
    return PdfCreateResult(
        capability_id=CAPABILITY_PDF_CREATE,
        source_kind=PDF_CREATE_SOURCE_IMAGE_PAGES,
        artifact=artifact,
        validation_status=PDF_CREATE_VALIDATION_PASS,
        native_text_state=inspection.native_text_state,
    )


__all__ = [
    "PDF_CREATE_ERROR_CODES",
    "PDF_CREATE_REASON_CAPABILITY_UNAVAILABLE",
    "PDF_CREATE_REASON_OUTPUT_REJECTED",
    "PDF_CREATE_REASON_PAGES_INVALID",
    "PDF_CREATE_SOURCE_IMAGE_PAGES",
    "PDF_CREATE_STATUS_OK",
    "PDF_CREATE_VALIDATION_PASS",
    "PDF_MEDIA_TYPE",
    "PdfCreateError",
    "PdfCreateResult",
    "create_pdf_from_image_pages",
]
