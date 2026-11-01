from __future__ import annotations

import base64
import binascii
from typing import Any

from padiem_ai_core.document_normalization import (
    BINARY_DOCUMENT_MEDIA,
    DocumentNormalizationError,
    validate_document_identity,
)
from padiem_ai_core.document_parser_boundary import (
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
    parse_binary_document_via_authority,
    parse_binary_document_via_authority_async,
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
    "pdf_magic_mismatch": "PDF 형식과 실제 파일 내용이 일치하지 않습니다.",
    "pdf_encrypted": "암호화된 문서라 열 수 없습니다. 암호를 풀고 다시 올려 주세요.",
    "ooxml_link_entry": "문서 압축 안에 안전하지 않은 경로 항목이 있어 열지 않았습니다.",
    "pdf_no_pages": "PDF에서 읽을 페이지를 찾지 못했습니다.",
    "pdf_empty_text": "이 PDF에서는 텍스트를 읽지 못했습니다. 스캔 문서 OCR은 아직 지원하지 않습니다.",
    "pdf_invalid": "PDF를 안전하게 읽지 못했습니다.",
    "docx_missing_part": "DOCX 파일을 안전하게 읽지 못했습니다.",
    "docx_empty": "DOCX에서 읽을 텍스트를 찾지 못했습니다.",
    "pptx_missing_slides": "PPTX 파일을 안전하게 읽지 못했습니다.",
    "pptx_empty": "PPTX에서 읽을 텍스트를 찾지 못했습니다.",
    "hwpx_missing_part": "HWPX 파일에서 읽을 내용을 찾지 못했습니다.",
    "hwpx_empty": "HWPX 파일에서 읽을 글자를 찾지 못했습니다. 이미지나 표는 일부 읽지 못할 수 있습니다.",
    "hwpx_mimetype_mismatch": "HWPX 파일 형식을 확인해 주세요.",
    "xlsx_invalid": "XLSX 파일을 안전하게 읽지 못했습니다.",
    "xlsx_no_sheets": "XLSX에서 워크시트를 찾지 못했습니다.",
    "xlsx_empty": "XLSX에서 읽을 값을 찾지 못했습니다.",
    "document_dependency_unavailable": "문서 처리 기능을 사용할 수 없습니다.",
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE: "현재 실행 환경에서는 격리된 문서 파서를 사용할 수 없어 문서를 처리할 수 없습니다.",
    "isolated_parser_transport_failed": "문서 파서 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "isolated_parser_request_unbounded": "문서 파서 요청이 허용 크기를 초과했습니다.",
    "isolated_parser_response_invalid": "문서 파서 응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "isolated_parser_response_unbounded": "문서 파서 응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "isolated_parser_internal_error": "문서 파서가 문서를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
}

# #6126 — a .hwp document is judged by its own first bytes, not its name. The
# OLE2 compound signature is the older binary Hangul format (never converted;
# one stable refusal code), and the ZIP local-header signatures mean a
# mislabeled file that really is an HWPX package and keeps working as HWPX.
# The Core document_normalization module is frozen, so this byte judge lives
# here at the app's single binary-document parse authority instead.
_HWPX_MEDIA_TYPE = "application/hwp+zip"
_HWP_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_HWP_ZIP_LOCAL_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_LEGACY_HWP_GUIDANCE = "한글에서 ‘다른 이름으로 저장 → HWPX’로 저장한 뒤 다시 올려 주세요."
_OOXML_CODES = {
    "ooxml_archive_size",
    "ooxml_unsafe_path",
    "ooxml_entry_size",
    "ooxml_dtd_rejected",
    "ooxml_malformed",
    "ooxml_invalid_xml",
}
# An encrypted document is not a damaged one. "안전하게 읽지 못했습니다" sends the
# owner to look for a corrupt file when the real answer is a password they set.
_OOXML_ENCRYPTED_MESSAGES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "암호화된 문서라 열 수 없습니다. 암호를 풀고 다시 올려 주세요."
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "암호화된 문서라 열 수 없습니다. 암호를 풀고 다시 올려 주세요."
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "암호화된 문서라 열 수 없습니다. 암호를 풀고 다시 올려 주세요."
    ),
}


def _decode_payload(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        if not payload:
            raise BinaryDocumentValidationError("Empty document")
        return payload
    if not isinstance(payload, str) or not payload:
        raise BinaryDocumentValidationError("문서 데이터가 올바르지 않습니다.")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BinaryDocumentValidationError("문서 데이터가 올바르지 않습니다.") from exc
    if not decoded:
        raise BinaryDocumentValidationError("빈 문서는 첨부할 수 없습니다.")
    return decoded


def guidance_for_reason_code(code: str, media_type: Any) -> str | None:
    """The per-code user guidance for one Core reason code, or None.

    The single wording authority for document refusals: the direct parse path
    (``_translate_binary_error``) and the file-lane resolve path both pick
    their answer here, so one code can never grow two different wordings.
    """

    if code == "legacy_hwp_unsupported":
        # #6126: the older binary Hangul format is not converted. This is an
        # ordinary save-as instruction, never an error badge on the screen.
        return _LEGACY_HWP_GUIDANCE
    if code == "ooxml_encrypted":
        return (
            _OOXML_ENCRYPTED_MESSAGES.get(media_type)
            or "암호화된 문서라 열 수 없습니다. 암호를 풀고 다시 올려 주세요."
        )
    if code in _OOXML_CODES:
        if media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            return "XLSX 압축 구조를 안전하게 읽지 못했습니다."
        if media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return "DOCX 파일을 안전하게 읽지 못했습니다."
        if media_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            return "PPTX 파일을 안전하게 읽지 못했습니다."
    message = _BINARY_ERROR_MESSAGES.get(code)
    if message is None and code in {
        "invalid_text",
        "binary_text_rejected",
        "excessive_control_characters",
    }:
        message = "문서에서 추출한 텍스트를 사용할 수 없습니다."
    return message


def _translate_binary_error(exc: DocumentNormalizationError, media_type: Any) -> BinaryDocumentValidationError:
    return BinaryDocumentValidationError(
        guidance_for_reason_code(exc.code, media_type) or "지원하지 않는 문서 형식입니다."
    )


def _validated_item_payload(item: Any) -> tuple[Any, Any, bytes]:
    if not isinstance(item, dict) or set(item) not in ({"type", "name", "media_type", "base64"}, {"type", "name", "media_type", "raw_bytes"}):
        raise BinaryDocumentValidationError("지원하지 않는 바이너리 문서 첨부 항목이 있습니다.")
    if item.get("type") != "document":
        raise BinaryDocumentValidationError("문서 첨부 형식이 올바르지 않습니다.")
    try:
        validate_document_identity(
            name=item.get("name"),
            media_type=item.get("media_type"),
            source_kind="binary",
        )
    except DocumentNormalizationError as exc:
        raise _translate_binary_error(exc, item.get("media_type")) from exc
    payload = _decode_payload(item.get("raw_bytes") if "raw_bytes" in item else item.get("base64"))
    return item.get("name"), item.get("media_type"), payload


def _hwp_head_family(payload: Any) -> str | None:
    """'ole' / 'zip' / None from the document's own first bytes (#6126)."""

    head = bytes(payload[:8]) if isinstance(payload, (bytes, bytearray)) else b""
    if head == _HWP_OLE_MAGIC:
        return "ole"
    if head[:4] in _HWP_ZIP_LOCAL_MAGICS:
        return "zip"
    return None


def _hwp_item_view(item: Any) -> Any:
    """The #6126 byte judge for a .hwp-named document item.

    The OLE2 compound signature is refused with the one legacy guidance code
    before any parse; a ZIP local header marks a mislabeled real HWPX package,
    presented to the frozen Core identity rules under its real HWPX
    extension. Any other item passes through untouched.
    """

    if not isinstance(item, dict) or item.get("type") != "document":
        return item
    name = item.get("name")
    if (item.get("media_type") != _HWPX_MEDIA_TYPE
            or not isinstance(name, str) or not name.lower().endswith(".hwp")):
        return item
    raw = item.get("raw_bytes")
    if not isinstance(raw, (bytes, bytearray)):
        encoded = item.get("base64")
        if not isinstance(encoded, str) or len(encoded) < 16:
            return item
        try:
            raw = base64.b64decode(encoded[:16])
        except (binascii.Error, ValueError):
            return item
    family = _hwp_head_family(raw)
    if family == "ole":
        raise BinaryDocumentValidationError(
            guidance_for_reason_code("legacy_hwp_unsupported", _HWPX_MEDIA_TYPE)
            or _LEGACY_HWP_GUIDANCE
        )
    if family == "zip":
        return {**item, "name": name[:-4] + ".hwpx"}
    return item


def legacy_hwp_parse_name(name: Any, media_type: Any, payload: Any) -> Any:
    """The #6126 parse identity for a .hwp-named binary document.

    The OLE2 compound signature raises the one legacy refusal code before any
    parse (the routes map it through ``guidance_for_reason_code``); a ZIP
    local header returns the name re-suffixed to its real HWPX identity. Any
    other name or media type — and any other head — comes back unchanged for
    the usual checks.
    """

    if (media_type != _HWPX_MEDIA_TYPE or not isinstance(name, str)
            or not name.lower().endswith(".hwp")):
        return name
    family = _hwp_head_family(payload)
    if family == "ole":
        raise DocumentNormalizationError(
            "legacy_hwp_unsupported",
            "Legacy binary HWP is not converted; save the document as HWPX.",
        )
    if family == "zip":
        return name[:-4] + ".hwpx"
    return name


def _attachment_from_document(document: Any) -> DocumentAttachment:
    return DocumentAttachment(
        name=document.name,
        media_type=document.media_type,
        text=document.text,
        byte_size=document.byte_size,
        segments=tuple(document.segments),
    )


def parse_binary_document_item(item: Any) -> DocumentAttachment:
    view = _hwp_item_view(item)
    name, media_type, payload = _validated_item_payload(view)
    try:
        document = parse_binary_document_via_authority(
            name=name,
            media_type=media_type,
            payload=payload,
        )
    except DocumentNormalizationError as exc:
        raise _translate_binary_error(exc, media_type) from exc
    attachment = _attachment_from_document(document)
    if view is not item:
        # #6126: the mislabeled .hwp parsed under its real HWPX identity; the
        # owner's original file name rides on the answer unchanged.
        attachment.name = str(item.get("name"))
    return attachment


async def parse_binary_document_item_async(item: Any) -> DocumentAttachment:
    """Worker request path: parse through the async isolated authority."""

    view = _hwp_item_view(item)
    name, media_type, payload = _validated_item_payload(view)
    try:
        document = await parse_binary_document_via_authority_async(
            name=name,
            media_type=media_type,
            payload=payload,
        )
    except DocumentNormalizationError as exc:
        raise _translate_binary_error(exc, media_type) from exc
    attachment = _attachment_from_document(document)
    if view is not item:
        # #6126: the mislabeled .hwp parsed under its real HWPX identity; the
        # owner's original file name rides on the answer unchanged.
        attachment.name = str(item.get("name"))
    return attachment
