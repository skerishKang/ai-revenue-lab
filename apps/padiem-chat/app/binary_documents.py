from __future__ import annotations

import base64
import binascii
from typing import Any

from padiem_ai_core.document_normalization import (
    BINARY_DOCUMENT_MEDIA,
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_PDF_PAGES,
    MAX_XLSX_COLUMNS,
    MAX_XLSX_NONEMPTY_CELLS,
    MAX_XLSX_ROWS,
    MAX_XLSX_SHEETS,
    DocumentNormalizationError,
    extract_binary_document,
)

from .documents import DocumentAttachment


class BinaryDocumentValidationError(ValueError):
    pass


_BINARY_ERROR_MESSAGES = {
    "invalid_name": "문서 파일 이름 형식이 올바르지 않습니다.",
    "name_required": "문서 파일 이름 형식이 올바르지 않습니다.",
    "unsupported_binary_media_type": "PDF, DOCX, PPTX, XLSX 문서만 이 형식으로 첨부할 수 있습니다.",
    "media_extension_mismatch": "문서 확장자와 파일 형식이 일치하지 않습니다.",
    "invalid_binary_payload": "문서 데이터가 올바르지 않습니다.",
    "empty_document": "빈 문서는 첨부할 수 없습니다.",
    "binary_too_large": "PDF·Office 문서는 2 MiB 이하만 첨부할 수 있습니다.",
    "extracted_text_too_long": "문서에서 추출한 텍스트가 40,000자를 초과합니다.",
    "pdf_magic_mismatch": "PDF 형식과 실제 파일 내용이 일치하지 않습니다.",
    "pdf_encrypted": "암호화된 PDF는 현재 첨부할 수 없습니다.",
    "pdf_no_pages": "PDF에서 읽을 페이지를 찾지 못했습니다.",
    "pdf_page_limit": "PDF는 80페이지 이하만 첨부할 수 있습니다.",
    "pdf_empty_text": "이 PDF에서는 텍스트를 읽지 못했습니다. 스캔 문서 OCR은 아직 지원하지 않습니다.",
    "pdf_invalid": "PDF를 안전하게 읽지 못했습니다.",
    "docx_missing_part": "DOCX 파일을 안전하게 읽지 못했습니다.",
    "docx_empty": "DOCX에서 읽을 텍스트를 찾지 못했습니다.",
    "pptx_missing_slides": "PPTX 파일을 안전하게 읽지 못했습니다.",
    "pptx_empty": "PPTX에서 읽을 텍스트를 찾지 못했습니다.",
    "xlsx_invalid": "XLSX 파일을 안전하게 읽지 못했습니다.",
    "xlsx_no_sheets": "XLSX에서 워크시트를 찾지 못했습니다.",
    "xlsx_sheet_limit": "XLSX는 워크시트 20개 이하만 첨부할 수 있습니다.",
    "xlsx_dimension_limit": "XLSX는 시트당 500행 × 50열 범위까지만 읽을 수 있습니다.",
    "xlsx_cell_limit": "XLSX의 값이 너무 많습니다.",
    "xlsx_empty": "XLSX에서 읽을 값을 찾지 못했습니다.",
    "document_dependency_unavailable": "문서 처리 기능을 사용할 수 없습니다.",
}
_OOXML_CODES = {
    "ooxml_archive_size",
    "ooxml_entry_count",
    "ooxml_unsafe_path",
    "ooxml_encrypted",
    "ooxml_entry_size",
    "ooxml_total_size",
    "ooxml_dtd_rejected",
    "ooxml_malformed",
    "ooxml_invalid_xml",
}


def _decode_payload(payload: Any) -> bytes:
    if not isinstance(payload, str) or not payload:
        raise BinaryDocumentValidationError("문서 데이터가 올바르지 않습니다.")
    if len(payload) > ((MAX_BINARY_DOCUMENT_BYTES + 2) // 3) * 4:
        raise BinaryDocumentValidationError("PDF·Office 문서는 2 MiB 이하만 첨부할 수 있습니다.")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BinaryDocumentValidationError("문서 데이터가 올바르지 않습니다.") from exc
    if not decoded:
        raise BinaryDocumentValidationError("빈 문서는 첨부할 수 없습니다.")
    if len(decoded) > MAX_BINARY_DOCUMENT_BYTES:
        raise BinaryDocumentValidationError("PDF·Office 문서는 2 MiB 이하만 첨부할 수 있습니다.")
    return decoded


def _translate_binary_error(exc: DocumentNormalizationError, media_type: Any) -> BinaryDocumentValidationError:
    if exc.code in _OOXML_CODES:
        if media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            return BinaryDocumentValidationError("XLSX 압축 구조를 안전하게 읽지 못했습니다.")
        if media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return BinaryDocumentValidationError("DOCX 파일을 안전하게 읽지 못했습니다.")
        if media_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            return BinaryDocumentValidationError("PPTX 파일을 안전하게 읽지 못했습니다.")
    message = _BINARY_ERROR_MESSAGES.get(exc.code)
    if message is None and exc.code in {
        "invalid_text",
        "text_too_long",
        "binary_text_rejected",
        "excessive_control_characters",
    }:
        message = "문서에서 추출한 텍스트를 사용할 수 없습니다."
    return BinaryDocumentValidationError(message or "지원하지 않는 문서 형식입니다.")


def parse_binary_document_item(item: Any) -> DocumentAttachment:
    if not isinstance(item, dict) or set(item) != {"type", "name", "media_type", "base64"}:
        raise BinaryDocumentValidationError("지원하지 않는 바이너리 문서 첨부 항목이 있습니다.")
    if item.get("type") != "document":
        raise BinaryDocumentValidationError("문서 첨부 형식이 올바르지 않습니다.")
    payload = _decode_payload(item.get("base64"))
    try:
        document = extract_binary_document(
            name=item.get("name"),
            media_type=item.get("media_type"),
            payload=payload,
        )
    except DocumentNormalizationError as exc:
        raise _translate_binary_error(exc, item.get("media_type")) from exc
    return DocumentAttachment(
        name=document.name,
        media_type=document.media_type,
        text=document.text,
        byte_size=document.byte_size,
    )
