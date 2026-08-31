from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Any

from .binary_documents import BinaryDocumentValidationError, parse_binary_document_item
from .documents import DocumentAttachment, DocumentValidationError, parse_document_item

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_NAME_CHARS = 120
ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


class AttachmentValidationError(ValueError):
    pass


def _matches_magic(media_type: str, data: bytes) -> bool:
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def _safe_name(value: Any) -> str:
    if not isinstance(value, str):
        raise AttachmentValidationError("사진 파일 이름 형식이 올바르지 않습니다.")
    cleaned = "".join(ch for ch in value.strip() if ch >= " " and ch != "\x7f")
    if not cleaned:
        raise AttachmentValidationError("사진 파일 이름이 필요합니다.")
    if len(cleaned) > MAX_IMAGE_NAME_CHARS:
        cleaned = cleaned[:MAX_IMAGE_NAME_CHARS]
    return cleaned


@dataclass(frozen=True, slots=True)
class ImageAttachment:
    name: str
    media_type: str
    base64_data: str = field(repr=False)
    byte_size: int = 0

    @property
    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.base64_data}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "type": "image",
            "name": self.name,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
        }


def _parse_image(item: dict[str, Any]) -> ImageAttachment:
    if set(item) != {"type", "name", "media_type", "base64"}:
        raise AttachmentValidationError("지원하지 않는 첨부 파일 항목이 있습니다.")
    media_type = item.get("media_type")
    if media_type not in ALLOWED_IMAGE_MEDIA_TYPES:
        raise AttachmentValidationError("JPEG, PNG, WebP 사진만 첨부할 수 있습니다.")
    name = _safe_name(item.get("name"))
    payload = item.get("base64")
    if not isinstance(payload, str) or not payload:
        raise AttachmentValidationError("사진 데이터가 올바르지 않습니다.")
    if len(payload) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise AttachmentValidationError("사진은 4 MiB 이하만 첨부할 수 있습니다.")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentValidationError("사진 데이터가 올바르지 않습니다.") from exc
    if not decoded:
        raise AttachmentValidationError("빈 사진은 첨부할 수 없습니다.")
    if len(decoded) > MAX_IMAGE_BYTES:
        raise AttachmentValidationError("사진은 4 MiB 이하만 첨부할 수 있습니다.")
    if not _matches_magic(media_type, decoded):
        raise AttachmentValidationError("사진 형식과 실제 파일 내용이 일치하지 않습니다.")
    return ImageAttachment(name=name, media_type=media_type, base64_data=payload, byte_size=len(decoded))


def _parse_document(item: dict[str, Any]) -> DocumentAttachment:
    has_text = "text" in item
    has_base64 = "base64" in item
    if has_text == has_base64:
        raise AttachmentValidationError("문서는 텍스트 또는 바이너리 데이터 중 하나만 보낼 수 있습니다.")
    if has_text:
        try:
            return parse_document_item(item)
        except DocumentValidationError as exc:
            raise AttachmentValidationError(str(exc)) from exc
    try:
        return parse_binary_document_item(item)
    except BinaryDocumentValidationError as exc:
        raise AttachmentValidationError(str(exc)) from exc


def parse_attachments(raw: Any) -> tuple[ImageAttachment | DocumentAttachment, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise AttachmentValidationError("첨부 파일 형식이 올바르지 않습니다.")
    if len(raw) == 0:
        return ()
    if len(raw) > 1:
        raise AttachmentValidationError("현재는 파일을 한 번에 하나만 첨부할 수 있습니다.")

    item = raw[0]
    if not isinstance(item, dict):
        raise AttachmentValidationError("첨부 파일 형식이 올바르지 않습니다.")
    item_type = item.get("type")
    if item_type == "image":
        return (_parse_image(item),)
    if item_type == "document":
        return (_parse_document(item),)
    raise AttachmentValidationError("현재는 사진과 TXT, Markdown, CSV, JSON, PDF, DOCX, PPTX, XLSX 문서만 첨부할 수 있습니다.")
