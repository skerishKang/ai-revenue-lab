"""KAgent composition facade for bounded native PDF merge and split."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_operations import (
    MAX_MERGE_INPUT_FILES,
    PdfPageProvenance,
    merge_pdfs,
    split_pdf,
)
from padiem_ai_core.pdf_operations import (
    PdfOperationResult as CorePdfOperationResult,
)

from .claw_skill_registry import CAPABILITY_PDF_CREATE, CAPABILITY_PDF_TRANSFORM
from .document_parser_contract import is_bounded_reason_code
from .file_intake_safety import DetectedFormat, FileIntakeSafetyError, inspect_file
from .pdf_inspection import inspect_pdf_document

PDF_MEDIA_TYPE = "application/pdf"
STATUS_OK = "ok"
STATUS_REFUSED = "refused"
VALIDATION_NOT_RUN = "not_run"
VALIDATION_OUTPUT_PASS = "output_gate_and_readback_pass"
REASON_REQUEST_INVALID = "pdf_operation_request_invalid"
REASON_INPUT_GATE = "pdf_input_gate_rejected"
REASON_OUTPUT_GATE = "pdf_output_gate_rejected"
REASON_OUTPUT_READBACK = "pdf_output_readback_rejected"
REASON_OPERATION = "pdf_operation_refused"


@dataclass(frozen=True, slots=True)
class PdfOperationReceipt:
    status: str
    capability_id: str
    reason_code: str
    media_type: str | None
    input_count: int | None
    output_page_count: int | None
    output_byte_size: int | None
    page_provenance: tuple[PdfPageProvenance, ...]
    validation_status: str

    def __post_init__(self) -> None:
        if self.status not in {STATUS_OK, STATUS_REFUSED}:
            raise ValueError("PDF operation receipt status is invalid.")
        if not is_bounded_reason_code(self.reason_code):
            raise ValueError("PDF operation receipt reason is not bounded.")
        if self.validation_status not in {VALIDATION_NOT_RUN, VALIDATION_OUTPUT_PASS}:
            raise ValueError("PDF operation validation status is invalid.")
        if self.status == STATUS_OK:
            if (
                self.reason_code != "ok"
                or self.validation_status != VALIDATION_OUTPUT_PASS
            ):
                raise ValueError(
                    "Successful PDF operation receipt has invalid verification fields."
                )
            if self.media_type != PDF_MEDIA_TYPE:
                raise ValueError(
                    "Successful PDF operation receipt has an invalid media type."
                )
            if (
                not isinstance(self.input_count, int)
                or self.input_count < 1
                or not isinstance(self.output_page_count, int)
                or self.output_page_count < 1
                or not isinstance(self.output_byte_size, int)
                or self.output_byte_size < 1
                or len(self.page_provenance) != self.output_page_count
            ):
                raise ValueError(
                    "Successful PDF operation receipt has invalid bounded metadata."
                )
        else:
            if self.reason_code == "ok" or self.validation_status != VALIDATION_NOT_RUN:
                raise ValueError("Refused PDF operation receipt cannot claim success.")
            if (
                any(
                    value is not None
                    for value in (
                        self.media_type,
                        self.input_count,
                        self.output_page_count,
                        self.output_byte_size,
                    )
                )
                or self.page_provenance
            ):
                raise ValueError(
                    "Refused PDF operation receipt carries output metadata."
                )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "media_type": self.media_type,
            "input_count": self.input_count,
            "output_page_count": self.output_page_count,
            "output_byte_size": self.output_byte_size,
            "page_provenance": [item.safe_dict() for item in self.page_provenance],
            "validation_status": self.validation_status,
        }


@dataclass(frozen=True, slots=True)
class PdfOperationArtifact:
    payload: bytes = field(repr=False)
    media_type: str
    byte_size: int
    page_count: int
    page_provenance: tuple[PdfPageProvenance, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes) or not self.payload:
            raise ValueError("PDF operation artifact requires bytes.")
        if self.media_type != PDF_MEDIA_TYPE or self.byte_size != len(self.payload):
            raise ValueError("PDF operation artifact has invalid media metadata.")
        if self.page_count < 1 or len(self.page_provenance) != self.page_count:
            raise ValueError("PDF operation artifact has invalid page metadata.")


@dataclass(frozen=True, slots=True)
class PdfOperationResult:
    receipt: PdfOperationReceipt
    artifact: PdfOperationArtifact | None = None

    def __post_init__(self) -> None:
        if self.receipt.status == STATUS_OK and self.artifact is None:
            raise ValueError("Successful PDF operation requires an artifact.")
        if self.receipt.status != STATUS_OK and self.artifact is not None:
            raise ValueError("Refused PDF operation cannot carry an artifact.")

    def to_public_dict(self) -> dict[str, object]:
        return self.receipt.to_public_dict()


def _refusal(
    capability_id: str,
    reason_code: str,
    *,
    input_count: int | None = None,
) -> PdfOperationResult:
    if not is_bounded_reason_code(reason_code):
        reason_code = REASON_OPERATION
    return PdfOperationResult(
        receipt=PdfOperationReceipt(
            status=STATUS_REFUSED,
            capability_id=capability_id,
            reason_code=reason_code,
            media_type=None,
            input_count=None,
            output_page_count=None,
            output_byte_size=None,
            page_provenance=(),
            validation_status=VALIDATION_NOT_RUN,
        )
    )


def _core_refusal(
    capability_id: str, error: DocumentNormalizationError
) -> PdfOperationResult:
    reason = getattr(error, "code", None)
    return _refusal(
        capability_id, reason if is_bounded_reason_code(reason) else REASON_OPERATION
    )


def _admit_documents(
    documents: object,
) -> tuple[tuple[bytes, ...], PdfOperationResult | None]:
    if not isinstance(documents, (tuple, list)) or not documents:
        return (), _refusal(CAPABILITY_PDF_CREATE, REASON_REQUEST_INVALID)
    if len(documents) > MAX_MERGE_INPUT_FILES:
        return (), _refusal(CAPABILITY_PDF_CREATE, "pdf_merge_input_limit")
    admitted: list[bytes] = []
    for document in documents:
        if not isinstance(document, (tuple, list)) or len(document) != 2:
            return (), _refusal(CAPABILITY_PDF_CREATE, REASON_REQUEST_INVALID)
        name, payload = document
        try:
            gate = inspect_file(name, payload)
        except (FileIntakeSafetyError, TypeError):
            return (), _refusal(CAPABILITY_PDF_CREATE, REASON_INPUT_GATE)
        if not gate.safe_to_parse or gate.detected_format is not DetectedFormat.PDF:
            return (), _refusal(CAPABILITY_PDF_CREATE, REASON_INPUT_GATE)
        admitted.append(bytes(payload))
    return tuple(admitted), None


def _finish(
    capability_id: str,
    operation: str,
    input_count: int,
    result: CorePdfOperationResult,
) -> PdfOperationResult:
    output_name = f"{operation}.pdf"
    try:
        gate = inspect_file(output_name, result.payload)
        if not gate.safe_to_parse or gate.detected_format is not DetectedFormat.PDF:
            return _refusal(capability_id, REASON_OUTPUT_GATE, input_count=input_count)
        readback = inspect_pdf_document(output_name, result.payload)
        if not readback.safe_to_read or readback.inspection is None:
            return _refusal(
                capability_id, REASON_OUTPUT_READBACK, input_count=input_count
            )
        if readback.inspection.page_count != result.page_count:
            return _refusal(
                capability_id, REASON_OUTPUT_READBACK, input_count=input_count
            )
    except (DocumentNormalizationError, FileIntakeSafetyError, TypeError):
        return _refusal(capability_id, REASON_OUTPUT_READBACK, input_count=input_count)
    receipt = PdfOperationReceipt(
        status=STATUS_OK,
        capability_id=capability_id,
        reason_code="ok",
        media_type=PDF_MEDIA_TYPE,
        input_count=input_count,
        output_page_count=result.page_count,
        output_byte_size=len(result.payload),
        page_provenance=result.provenance,
        validation_status=VALIDATION_OUTPUT_PASS,
    )
    artifact = PdfOperationArtifact(
        payload=result.payload,
        media_type=PDF_MEDIA_TYPE,
        byte_size=len(result.payload),
        page_count=result.page_count,
        page_provenance=result.provenance,
    )
    return PdfOperationResult(receipt=receipt, artifact=artifact)


def merge_pdf_documents(
    documents: Sequence[tuple[str, bytes]],
) -> PdfOperationResult:
    """Run the common gate for each input, then canonical Core PDF merge."""
    admitted, refusal = _admit_documents(documents)
    if refusal is not None:
        return refusal
    try:
        result = merge_pdfs(admitted)
    except DocumentNormalizationError as error:
        return _core_refusal(CAPABILITY_PDF_CREATE, error)
    return _finish(CAPABILITY_PDF_CREATE, "merged", len(admitted), result)


def split_pdf_document(
    filename: str,
    payload: bytes,
    ranges: Sequence[tuple[int, int]],
) -> PdfOperationResult:
    """Run the common gate, then split by explicit one-based page ranges."""
    try:
        gate = inspect_file(filename, payload)
    except (FileIntakeSafetyError, TypeError):
        return _refusal(CAPABILITY_PDF_TRANSFORM, REASON_INPUT_GATE)
    if not gate.safe_to_parse or gate.detected_format is not DetectedFormat.PDF:
        return _refusal(CAPABILITY_PDF_TRANSFORM, REASON_INPUT_GATE)
    try:
        result = split_pdf(payload, ranges)
    except DocumentNormalizationError as error:
        return _core_refusal(CAPABILITY_PDF_TRANSFORM, error)
    return _finish(CAPABILITY_PDF_TRANSFORM, "split", 1, result)


__all__ = [
    "PDF_MEDIA_TYPE",
    "PdfOperationArtifact",
    "PdfOperationReceipt",
    "PdfOperationResult",
    "merge_pdf_documents",
    "split_pdf_document",
]
