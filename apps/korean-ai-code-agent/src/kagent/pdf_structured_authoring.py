"""KAgent facade for bounded structured PDF authoring."""

from __future__ import annotations

from dataclasses import dataclass, field

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_authoring import (
    PdfAuthoringArtifact,
    PdfAuthoringDocument,
    PdfHeadingBlock,
    PdfImageBlock,
    PdfTableBlock,
    PdfTextBlock,
)
from padiem_ai_core.pdf_authoring import (
    author_structured_pdf as _author_core,
)

from . import image_skill
from .claw_skill_registry import CAPABILITY_PDF_CREATE, RESERVED_CAPABILITY_IDS
from .file_intake_safety import FileIntakeSafetyError
from .image_skill import ImageSkillError
from .pdf_inspection import PdfInspectionResult, inspect_pdf_document

PDF_STRUCTURED_AUTHORING_SOURCE_KIND = "bounded_structured_document"
PDF_STRUCTURED_AUTHORING_VALIDATION_PASS = "pdf_intake_and_readback_pass"
PDF_STRUCTURED_AUTHORING_REASON_CAPABILITY_UNAVAILABLE = (
    "pdf_structured_authoring_capability_unavailable"
)
PDF_STRUCTURED_AUTHORING_REASON_REQUEST_INVALID = (
    "pdf_structured_authoring_request_invalid"
)
PDF_STRUCTURED_AUTHORING_REASON_IMAGE_REJECTED = (
    "pdf_structured_authoring_image_rejected"
)
PDF_STRUCTURED_AUTHORING_REASON_IMAGE_UNSUPPORTED = (
    "pdf_structured_authoring_image_unsupported"
)
PDF_STRUCTURED_AUTHORING_REASON_AUTHORING_FAILED = "pdf_structured_authoring_failed"
PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED = (
    "pdf_structured_authoring_output_rejected"
)
PDF_STRUCTURED_AUTHORING_ERROR_CODES = frozenset(
    {
        PDF_STRUCTURED_AUTHORING_REASON_CAPABILITY_UNAVAILABLE,
        PDF_STRUCTURED_AUTHORING_REASON_REQUEST_INVALID,
        PDF_STRUCTURED_AUTHORING_REASON_IMAGE_REJECTED,
        PDF_STRUCTURED_AUTHORING_REASON_IMAGE_UNSUPPORTED,
        PDF_STRUCTURED_AUTHORING_REASON_AUTHORING_FAILED,
        PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED,
    }
)


class PdfStructuredAuthoringError(ValueError):
    """Fail-closed structured PDF authoring error."""

    def __init__(self, code: str) -> None:
        if code not in PDF_STRUCTURED_AUTHORING_ERROR_CODES:
            raise ValueError(f"unknown PDF structured authoring error code: {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PdfStructuredAuthoringResult:
    capability_id: str
    source_kind: str
    artifact: PdfAuthoringArtifact = field(repr=False)
    inspection: PdfInspectionResult
    validation_status: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, PdfAuthoringArtifact):
            raise TypeError("PDF structured authoring result has an invalid artifact.")
        if not isinstance(self.inspection, PdfInspectionResult):
            raise TypeError("PDF structured authoring result has invalid inspection.")
        if self.capability_id != CAPABILITY_PDF_CREATE:
            raise ValueError(
                "PDF structured authoring result has an invalid capability ID."
            )
        if self.source_kind != PDF_STRUCTURED_AUTHORING_SOURCE_KIND:
            raise ValueError(
                "PDF structured authoring result has an invalid source kind."
            )
        if (
            not self.inspection.safe_to_read
            or self.inspection.inspection is None
            or self.inspection.inspection.page_count != self.artifact.page_count
        ):
            raise ValueError("PDF structured authoring result failed inspection.")
        if self.validation_status != PDF_STRUCTURED_AUTHORING_VALIDATION_PASS:
            raise ValueError(
                "PDF structured authoring result has invalid validation status."
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "source_kind": self.source_kind,
            "artifact": self.artifact.safe_dict(),
            "output_gate": self.inspection.gate.safe_dict(),
            "validation_status": self.validation_status,
            "native_text_available": self.inspection.native_text_available,
            "native_text_state": self.inspection.native_text_state,
        }


def _admit_images(document: PdfAuthoringDocument) -> None:
    for block in document.blocks:
        if not isinstance(block, PdfImageBlock):
            continue
        try:
            admitted = image_skill.image_inspect(
                block.data,
                filename=block.filename,
            )
        except ImageSkillError as error:
            raise PdfStructuredAuthoringError(
                PDF_STRUCTURED_AUTHORING_REASON_IMAGE_REJECTED
            ) from error
        image = admitted.inspection
        if image.format not in {"PNG", "JPEG"} or image.multi_frame:
            raise PdfStructuredAuthoringError(
                PDF_STRUCTURED_AUTHORING_REASON_IMAGE_UNSUPPORTED
            )


def _expects_native_text(document: PdfAuthoringDocument) -> bool:
    return any(
        isinstance(block, (PdfHeadingBlock, PdfTextBlock, PdfTableBlock))
        for block in document.blocks
    )


def create_structured_pdf(document: object) -> PdfStructuredAuthoringResult:
    """Author, admit, and canonically inspect one bounded structured PDF."""

    if CAPABILITY_PDF_CREATE not in RESERVED_CAPABILITY_IDS:
        raise PdfStructuredAuthoringError(
            PDF_STRUCTURED_AUTHORING_REASON_CAPABILITY_UNAVAILABLE
        )
    if not isinstance(document, PdfAuthoringDocument):
        raise PdfStructuredAuthoringError(
            PDF_STRUCTURED_AUTHORING_REASON_REQUEST_INVALID
        )
    _admit_images(document)
    try:
        artifact = _author_core(document)
    except (
        DocumentNormalizationError,
        TypeError,
        ValueError,
        RuntimeError,
        OSError,
    ) as error:
        raise PdfStructuredAuthoringError(
            PDF_STRUCTURED_AUTHORING_REASON_AUTHORING_FAILED
        ) from error
    try:
        inspection = inspect_pdf_document("authored.pdf", artifact.data)
    except (
        DocumentNormalizationError,
        FileIntakeSafetyError,
        TypeError,
        ValueError,
        RuntimeError,
        OSError,
    ) as error:
        raise PdfStructuredAuthoringError(
            PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED
        ) from error
    if (
        not inspection.safe_to_read
        or inspection.inspection is None
        or inspection.inspection.page_count != artifact.page_count
        or (
            _expects_native_text(document)
            and inspection.inspection.native_text_available is not True
        )
    ):
        raise PdfStructuredAuthoringError(
            PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED
        )
    try:
        return PdfStructuredAuthoringResult(
            capability_id=CAPABILITY_PDF_CREATE,
            source_kind=PDF_STRUCTURED_AUTHORING_SOURCE_KIND,
            artifact=artifact,
            inspection=inspection,
            validation_status=PDF_STRUCTURED_AUTHORING_VALIDATION_PASS,
        )
    except (TypeError, ValueError) as error:
        raise PdfStructuredAuthoringError(
            PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED
        ) from error


__all__ = [
    "PDF_STRUCTURED_AUTHORING_ERROR_CODES",
    "PDF_STRUCTURED_AUTHORING_REASON_AUTHORING_FAILED",
    "PDF_STRUCTURED_AUTHORING_REASON_CAPABILITY_UNAVAILABLE",
    "PDF_STRUCTURED_AUTHORING_REASON_IMAGE_REJECTED",
    "PDF_STRUCTURED_AUTHORING_REASON_IMAGE_UNSUPPORTED",
    "PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED",
    "PDF_STRUCTURED_AUTHORING_REASON_REQUEST_INVALID",
    "PDF_STRUCTURED_AUTHORING_SOURCE_KIND",
    "PDF_STRUCTURED_AUTHORING_VALIDATION_PASS",
    "PdfStructuredAuthoringError",
    "PdfStructuredAuthoringResult",
    "create_structured_pdf",
]
