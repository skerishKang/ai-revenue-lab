"""B66 live image-extraction endpoint hosted inside the existing B14 Worker.

The browser never chooses a provider/model.  This route accepts one bounded
quotation image, delegates request construction + model-output validation to
the canonical #3212 B66 extraction authority staged by deploy.sh, and executes
through the already-installed B14 gateway.
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
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 6 * 1024 * 1024
_REQUIRED_FIELDS = frozenset({"name", "media_type", "base64"})
_IMAGE_MEDIA = frozenset({"image/jpeg", "image/png", "image/webp"})


def _authority():
    """Load the staged canonical #3212 authority.

    deploy.sh copies the reviewed source file into the Worker app package as
    app/b66_extraction_routing.py before pywrangler bundles the Worker. Keeping
    the import lazy makes ordinary source/unit tests able to inject the same
    authority without creating a second committed implementation.
    """

    return importlib.import_module("app.b66_extraction_routing")


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
        # Reuse the installed canonical gateway validator, including the
        # multimodal wrapper.  No second request schema lives here.
        validated_body = pilot_gateway._validate_body(chat_body)
    except ValueError as exc:
        code = getattr(exc, "code", None) or (str(exc) if str(exc) else "invalid_request")
        safe_code = code if isinstance(code, str) and len(code) <= 80 else "invalid_request"
        return _error(safe_code)
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

    content = choices[0]["message"]["content"]
    try:
        raw_model = json.loads(content)
    except json.JSONDecodeError:
        return _error("invalid_model_json", status=502)

    try:
        normalized = authority.normalize_model_output(
            raw_model,
            source_kind="image",
            filename=name.strip(),
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
                    "kind": "image",
                    "filename": name.strip(),
                    "media_type": media_type,
                    "byte_size": len(image_bytes),
                },
            },
        },
        headers={"Cache-Control": "no-store"},
    )
