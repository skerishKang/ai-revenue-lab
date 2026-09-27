"""B66 file-intake product adapter.

Source-ready only. This module owns B66-specific request classification and
projection. It reuses IP-CORE for binary document identity/parsing and does not
select or call a model/provider.

No HTTP route is installed by this slice.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import PurePath
from typing import Any, Callable

from padiem_ai_core.b14_multimodal import MAX_B14_IMAGE_BYTES
from padiem_ai_core.document_normalization import (
    BINARY_DOCUMENT_MEDIA,
    MAX_BINARY_DOCUMENT_BYTES,
    NormalizedDocument,
    validate_document_identity,
)
from padiem_ai_core.document_parser_boundary import (
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
    parse_binary_document_via_authority,
)
from padiem_ai_core.document_semantics import DocumentNormalizationError

FILE_INTAKE_PATH = "/api/v1/quote/intake"
SERVER_ROUTE_DEPLOYED = False
MODEL_DEPENDENCY = False
PROVIDER_IDS_IN_ADAPTER = 0

_REQUIRED_FIELDS = frozenset({"name", "media_type", "base64"})
_IMAGE_MEDIA: dict[str, frozenset[str]] = {
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/png": frozenset({".png"}),
    "image/webp": frozenset({".webp"}),
}

_SAFE_ERRORS = {
    "invalid_request": "파일 요청 형식이 올바르지 않습니다.",
    "unsupported_fields": "지원하지 않는 파일 요청 필드가 있습니다.",
    "invalid_file_name": "파일 이름을 확인해 주세요.",
    "legacy_hwp_unsupported": "기존 HWP 파일은 아직 지원하지 않습니다.",
    "unsupported_file_type": "지원하지 않는 파일 형식입니다.",
    "invalid_base64": "파일 데이터 형식이 올바르지 않습니다.",
    "empty_file": "빈 파일은 사용할 수 없습니다.",
    "document_too_large": "문서는 2 MiB 이하만 처리할 수 있습니다.",
    "image_too_large": "이미지는 4 MiB 이하만 처리할 수 있습니다.",
    "image_magic_mismatch": "이미지 확장자와 실제 파일 형식이 일치하지 않습니다.",
    "parser_authority_unavailable": "현재 실행 환경에서는 문서를 안전하게 읽을 수 없습니다.",
    "document_parse_failed": "문서를 안전하게 읽지 못했습니다.",
}


class B66FileIntakeError(ValueError):
    """Bounded safe product-adapter failure."""

    def __init__(self, code: str, safe_message: str | None = None) -> None:
        self.code = code
        self.safe_message = safe_message or _SAFE_ERRORS.get(
            code, "파일을 안전하게 처리하지 못했습니다."
        )
        super().__init__(self.safe_message)


def _error(code: str, message: str | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message or _SAFE_ERRORS.get(
                code, "파일을 안전하게 처리하지 못했습니다."
            ),
        },
    }


def _safe_name(value: Any) -> str:
    if not isinstance(value, str):
        raise B66FileIntakeError("invalid_file_name")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 255:
        raise B66FileIntakeError("invalid_file_name")
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise B66FileIntakeError("invalid_file_name")
    return cleaned


def _decode_payload(
    value: Any,
    *,
    max_bytes: int,
    too_large_code: str,
) -> bytes:
    if not isinstance(value, str) or not value:
        raise B66FileIntakeError("invalid_base64")
    max_encoded = ((max_bytes + 2) // 3) * 4 + 4
    if len(value) > max_encoded:
        raise B66FileIntakeError(too_large_code)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise B66FileIntakeError("invalid_base64") from exc
    if not decoded:
        raise B66FileIntakeError("empty_file")
    if len(decoded) > max_bytes:
        raise B66FileIntakeError(too_large_code)
    return decoded


def _image_magic_matches(media_type: str, payload: bytes) -> bool:
    if media_type == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return (
            len(payload) >= 12
            and payload.startswith(b"RIFF")
            and payload[8:12] == b"WEBP"
        )
    return False


def _image_identity(name: str, media_type: Any) -> tuple[str, str]:
    if not isinstance(media_type, str) or media_type not in _IMAGE_MEDIA:
        raise B66FileIntakeError("unsupported_file_type")
    suffix = PurePath(name.lower()).suffix
    if suffix not in _IMAGE_MEDIA[media_type]:
        raise B66FileIntakeError(
            "media_extension_mismatch",
            "파일 확장자와 파일 형식이 일치하지 않습니다.",
        )
    return name, media_type


def _category(name: str, media_type: Any) -> str:
    suffix = PurePath(name.lower()).suffix
    if suffix == ".hwp":
        raise B66FileIntakeError("legacy_hwp_unsupported")
    if isinstance(media_type, str) and media_type in _IMAGE_MEDIA:
        _image_identity(name, media_type)
        return "image"
    try:
        validate_document_identity(
            name=name,
            media_type=media_type,
            source_kind="binary",
        )
    except DocumentNormalizationError as exc:
        if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            raise B66FileIntakeError(
                "media_extension_mismatch",
                "파일 확장자와 파일 형식이 일치하지 않습니다.",
            ) from exc
        raise B66FileIntakeError(exc.code, exc.safe_message) from exc
    return "native_document"


def _native_parser(
    *,
    parser: Callable[..., NormalizedDocument] | None,
) -> Callable[..., NormalizedDocument]:
    return parser or parse_binary_document_via_authority


def handle_intake_payload(
    payload: Any,
    *,
    parser: Callable[..., NormalizedDocument] | None = None,
) -> dict[str, Any]:
    """Validate one future same-origin B66 file-intake request.

    The request cannot choose a model, provider, URL, parser or route. A trusted
    server composition supplies the parser authority; the default is IP-CORE's
    single reviewed authority.
    """

    if not isinstance(payload, dict):
        return _error("invalid_request")
    if set(payload) != _REQUIRED_FIELDS:
        return _error("unsupported_fields")

    try:
        name = _safe_name(payload.get("name"))
        media_type = payload.get("media_type")
        category = _category(name, media_type)
        raw = _decode_payload(
            payload.get("base64"),
            max_bytes=(
                MAX_B14_IMAGE_BYTES
                if category == "image"
                else MAX_BINARY_DOCUMENT_BYTES
            ),
            too_large_code=(
                "image_too_large"
                if category == "image"
                else "document_too_large"
            ),
        )

        if category == "image":
            if not _image_magic_matches(str(media_type), raw):
                raise B66FileIntakeError("image_magic_mismatch")
            return {
                "ok": True,
                "result": {
                    "kind": "image_candidate",
                    "name": name,
                    "media_type": media_type,
                    "byte_size": len(raw),
                    "next": "vision_model_pending",
                    "model_called": False,
                },
            }

        try:
            document = _native_parser(parser=parser)(
                name=name,
                media_type=media_type,
                payload=raw,
            )
        except DocumentNormalizationError as exc:
            if exc.code == "pdf_empty_text" and str(media_type) == "application/pdf":
                return {
                    "ok": True,
                    "result": {
                        "kind": "scanned_pdf_candidate",
                        "name": name,
                        "media_type": media_type,
                        "byte_size": len(raw),
                        "next": "scanned_pdf_vision_pending",
                        "model_called": False,
                    },
                }
            if exc.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE:
                return _error("parser_authority_unavailable")
            return _error(exc.code, exc.safe_message)
        except Exception:
            return _error("document_parse_failed")

        if not isinstance(document, NormalizedDocument):
            return _error("document_parse_failed")

        return {
            "ok": True,
            "result": {
                "kind": "native_document",
                "name": document.name,
                "media_type": document.media_type,
                "byte_size": document.byte_size,
                "text": document.text,
                "text_chars": document.text_chars,
                "source_kind": document.source_kind,
                "next": "text_extraction_model_pending",
                "model_called": False,
            },
        }
    except B66FileIntakeError as exc:
        return _error(exc.code, exc.safe_message)


__all__ = [
    "B66FileIntakeError",
    "FILE_INTAKE_PATH",
    "MODEL_DEPENDENCY",
    "PROVIDER_IDS_IN_ADAPTER",
    "SERVER_ROUTE_DEPLOYED",
    "handle_intake_payload",
]
