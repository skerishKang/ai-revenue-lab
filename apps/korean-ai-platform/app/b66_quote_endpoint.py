"""B66 quotation-extraction endpoints hosted inside the existing B14 Worker.

The browser never chooses a provider/model.  These routes accept one bounded
quotation source, delegate document admission/request construction/model-output
validation to the canonical B66 authorities staged by deploy.sh, and execute
through the already-installed B14 gateway.

Native binary documents additionally pass through Core's single parser-authority
boundary.  On a Production Worker with no reviewed isolated parser composition,
that boundary fails closed before any model call; the browser may then continue
with the existing manual-review registration path.
"""

from __future__ import annotations

import base64
import binascii
import importlib
import json
import uuid
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Router

from app.pilot import gateway as pilot_gateway

router = Router()

EXTRACT_IMAGE_PATH = "/v1/quote/extract-image"
EXTRACT_DOCUMENT_PATH = "/v1/quote/extract-document"
EXTRACT_LOCAL_TEXT_PATH = "/v1/quote/extract-local-text"
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_LOCAL_TEXT_CHARS = 32000
MAX_REQUEST_BYTES = 6 * 1024 * 1024
_REQUIRED_FIELDS = frozenset({"name", "media_type", "base64"})
_LOCAL_TEXT_FIELDS = frozenset({"name", "media_type", "byte_size", "local_text"})
_IMAGE_MEDIA = frozenset({"image/jpeg", "image/png", "image/webp"})


def _authority():
    """Load the staged canonical #3212 extraction authority."""

    return importlib.import_module("app.b66_extraction_routing")


def _intake_authority():
    """Load the staged canonical B66 file-intake authority."""

    return importlib.import_module("app.b66_file_intake")


def _document_identity_authority():
    """Load Core's canonical document identity authority without parsing bytes."""

    return importlib.import_module("padiem_ai_core.document_normalization")


def _error(code: str, *, status: int = 422) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


async def _bounded_json(request: Request) -> dict[str, Any] | None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None
    raw_length = request.headers.get("content-length")
    if raw_length:
        try:
            if int(raw_length) > MAX_REQUEST_BYTES:
                raise ValueError
        except ValueError:
            return None
    body = await request.body()
    if not body or len(body) > MAX_REQUEST_BYTES:
        return None
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _decode_image(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_base64")
    max_encoded = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 4
    if len(value) > max_encoded:
        raise ValueError("image_too_large")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid_base64") from exc
    if not raw:
        raise ValueError("empty_file")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image_too_large")
    return raw


def _response_payload(response: JSONResponse) -> dict[str, Any] | None:
    try:
        payload = json.loads(bytes(response.body))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_error_code(exc: Exception, fallback: str = "invalid_request") -> str:
    code = getattr(exc, "code", None) or (str(exc) if str(exc) else fallback)
    return code if isinstance(code, str) and len(code) <= 80 else fallback


async def _execute_extraction(
    *,
    authority: Any,
    chat_body: dict[str, Any],
    source_kind: str,
    filename: str,
    media_type: str,
    byte_size: int,
) -> JSONResponse:
    """Execute one canonical B66 extraction request and validate its response."""

    try:
        validated_body = pilot_gateway._validate_body(chat_body)
    except ValueError as exc:
        return _error(_safe_error_code(exc))
    except Exception:
        return _error("extraction_authority_unavailable", status=503)

    request_id = "b66_" + uuid.uuid4().hex[:16]
    try:
        upstream = await pilot_gateway._handle_alpha_chat(request_id, validated_body)
    except Exception:
        return _error("b14_execution_failed", status=502)

    upstream_payload = _response_payload(upstream)
    if upstream.status_code != 200 or upstream_payload is None:
        # Do not project provider messages/codes into the product surface.
        return _error("b14_upstream_unavailable", status=502)

    choices = upstream_payload.get("choices")
    if (
        not isinstance(choices, list)
        or not choices
        or not isinstance(choices[0], dict)
        or not isinstance(choices[0].get("message"), dict)
        or not isinstance(choices[0]["message"].get("content"), str)
    ):
        return _error("invalid_model_response", status=502)

    try:
        raw_model = json.loads(choices[0]["message"]["content"])
    except json.JSONDecodeError:
        return _error("invalid_model_json", status=502)

    try:
        normalized = authority.normalize_model_output(
            raw_model,
            source_kind=source_kind,
            filename=filename,
        )
    except Exception:
        return _error("model_output_validation_failed", status=502)

    if not isinstance(normalized, dict) or normalized.get("ok") is not True:
        code = normalized.get("code") if isinstance(normalized, dict) else None
        safe_code = (
            "model_output_" + code
            if isinstance(code, str) and code and len(code) <= 64
            else "model_output_validation_failed"
        )
        return _error(safe_code, status=502)

    extraction = normalized.get("extraction")
    unknowns = normalized.get("unknowns")
    if not isinstance(extraction, dict) or not isinstance(unknowns, list):
        return _error("model_output_validation_failed", status=502)

    return JSONResponse(
        {
            "ok": True,
            "result": {
                "extraction": extraction,
                "unknowns": unknowns,
                "quotecore_authority": normalized.get("quotecore_authority") is True,
                "source": {
                    "kind": source_kind,
                    "filename": filename,
                    "media_type": media_type,
                    "byte_size": byte_size,
                },
            },
        },
        headers={"Cache-Control": "no-store"},
    )


@router.route(EXTRACT_IMAGE_PATH, methods=["POST"])
async def extract_image(request: Request) -> JSONResponse:
    payload = await _bounded_json(request)
    if payload is None:
        return _error("invalid_request")
    if set(payload) != _REQUIRED_FIELDS:
        return _error("unsupported_fields")

    name = payload.get("name")
    media_type = payload.get("media_type")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
        return _error("invalid_file_name")
    if not isinstance(media_type, str) or media_type not in _IMAGE_MEDIA:
        return _error("image_only_mvp")

    try:
        image_bytes = _decode_image(payload.get("base64"))
        authority = _authority()
        chat_body = authority.build_image_extraction_request(
            image_bytes,
            media_type=media_type,
            filename=name.strip(),
            source_kind="image",
        )
    except ValueError as exc:
        return _error(_safe_error_code(exc))
    except Exception:
        return _error("extraction_authority_unavailable", status=503)

    return await _execute_extraction(
        authority=authority,
        chat_body=chat_body,
        source_kind="image",
        filename=name.strip(),
        media_type=media_type,
        byte_size=len(image_bytes),
    )


@router.route(EXTRACT_LOCAL_TEXT_PATH, methods=["POST"])
async def extract_local_text(request: Request) -> JSONResponse:
    """Extract quotation facts from browser-local document text.

    The browser owns only bounded binary-to-text extraction. The text remains
    untrusted and is revalidated here before entering the existing governed
    B66 text extraction/model-output validation path.
    """

    payload = await _bounded_json(request)
    if payload is None:
        return _error("invalid_request")
    if set(payload) != _LOCAL_TEXT_FIELDS:
        return _error("unsupported_fields")

    name = payload.get("name")
    media_type = payload.get("media_type")
    byte_size = payload.get("byte_size")
    local_text = payload.get("local_text")

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
        return _error("invalid_file_name")
    if (
        isinstance(byte_size, bool)
        or not isinstance(byte_size, int)
        or byte_size <= 0
        or byte_size > MAX_DOCUMENT_BYTES
    ):
        return _error("invalid_file_size")
    if not isinstance(local_text, str) or not local_text.strip():
        return _error("empty_text")
    text = local_text.strip()
    if len(text) > MAX_LOCAL_TEXT_CHARS:
        return _error("text_too_large")

    try:
        identity = _document_identity_authority()
        identity.validate_document_identity(
            name=name.strip(),
            media_type=media_type,
            source_kind="binary",
        )
    except Exception as exc:
        return _error(_safe_error_code(exc, "unsupported_file_type"))

    try:
        authority = _authority()
        chat_body = authority.build_text_extraction_request(
            text,
            filename=name.strip(),
            source_kind="native_document",
        )
    except ValueError as exc:
        return _error(_safe_error_code(exc))
    except Exception:
        return _error("extraction_authority_unavailable", status=503)

    return await _execute_extraction(
        authority=authority,
        chat_body=chat_body,
        source_kind="native_document",
        filename=name.strip(),
        media_type=str(media_type),
        byte_size=byte_size,
    )


@router.route(EXTRACT_DOCUMENT_PATH, methods=["POST"])
async def extract_document(request: Request) -> JSONResponse:
    payload = await _bounded_json(request)
    if payload is None:
        return _error("invalid_request")
    if set(payload) != _REQUIRED_FIELDS:
        return _error("unsupported_fields")

    try:
        intake = _intake_authority()
        admitted = intake.handle_intake_payload(payload)
    except Exception:
        return _error("file_intake_authority_unavailable", status=503)

    if not isinstance(admitted, dict) or admitted.get("ok") is not True:
        error = admitted.get("error") if isinstance(admitted, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        safe_code = code if isinstance(code, str) and 0 < len(code) <= 80 else "document_intake_failed"
        status = 503 if safe_code == "parser_authority_unavailable" else 422
        return _error(safe_code, status=status)

    result = admitted.get("result")
    if not isinstance(result, dict):
        return _error("document_intake_failed", status=503)

    kind = result.get("kind")
    if kind == "scanned_pdf_candidate":
        return _error("scanned_pdf_manual_review_required")
    if kind != "native_document":
        return _error("native_document_only")

    name = result.get("name")
    media_type = result.get("media_type")
    text = result.get("text")
    byte_size = result.get("byte_size")
    if (
        not isinstance(name, str)
        or not isinstance(media_type, str)
        or not isinstance(text, str)
        or not text.strip()
        or isinstance(byte_size, bool)
        or not isinstance(byte_size, int)
        or byte_size <= 0
    ):
        return _error("document_intake_failed", status=503)

    try:
        authority = _authority()
        chat_body = authority.build_text_extraction_request(
            text,
            filename=name,
            source_kind="native_document",
        )
    except ValueError as exc:
        return _error(_safe_error_code(exc))
    except Exception:
        return _error("extraction_authority_unavailable", status=503)

    return await _execute_extraction(
        authority=authority,
        chat_body=chat_body,
        source_kind="native_document",
        filename=name,
        media_type=media_type,
        byte_size=byte_size,
    )
