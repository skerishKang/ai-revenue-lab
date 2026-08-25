from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from typing import Any, Callable

from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import NoSafeRoute

MAX_IMAGE_BYTES = 4 * 1024 * 1024
_ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_DATA_PREFIXES = {media: f"data:{media};base64," for media in _ALLOWED_MEDIA_TYPES}


class MultimodalContractError(ValueError):
    pass


def _matches_magic(media_type: str, data: bytes) -> bool:
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def validate_image_data_url(value: Any) -> str:
    if not isinstance(value, str):
        raise MultimodalContractError("image_url.url must be a data URL string")

    media_type = None
    payload = None
    for candidate, prefix in _DATA_PREFIXES.items():
        if value.startswith(prefix):
            media_type = candidate
            payload = value[len(prefix):]
            break
    if media_type is None or payload is None:
        raise MultimodalContractError(
            "image_url.url must be a base64 data URL for JPEG, PNG, or WebP"
        )
    if not payload:
        raise MultimodalContractError("image data must not be empty")
    if len(payload) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise MultimodalContractError("decoded image must not exceed 4 MiB")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MultimodalContractError("image data must be valid base64") from exc
    if not decoded:
        raise MultimodalContractError("image data must not be empty")
    if len(decoded) > MAX_IMAGE_BYTES:
        raise MultimodalContractError("decoded image must not exceed 4 MiB")
    if not _matches_magic(media_type, decoded):
        raise MultimodalContractError("image media type does not match image bytes")
    return f"data:{media_type};base64,{payload}"


def validate_user_multimodal_content(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list) or not 2 <= len(content) <= 4:
        raise MultimodalContractError("multimodal user content must have 2–4 parts")

    normalized: list[dict[str, Any]] = []
    text_count = 0
    image_count = 0
    total_text_chars = 0

    for index, part in enumerate(content):
        if not isinstance(part, dict):
            raise MultimodalContractError(f"multimodal part {index} must be an object")
        part_type = part.get("type")
        if part_type == "text":
            if set(part) != {"type", "text"}:
                raise MultimodalContractError("text part has unsupported fields")
            text = part.get("text")
            if not isinstance(text, str) or not text.strip():
                raise MultimodalContractError("text part must contain non-empty text")
            text = text.strip()
            total_text_chars += len(text)
            if total_text_chars > 32000:
                raise MultimodalContractError("multimodal text must not exceed 32000 characters")
            text_count += 1
            normalized.append({"type": "text", "text": text})
            continue

        if part_type == "image_url":
            if set(part) != {"type", "image_url"}:
                raise MultimodalContractError("image_url part has unsupported fields")
            image_url = part.get("image_url")
            if not isinstance(image_url, dict) or set(image_url) != {"url"}:
                raise MultimodalContractError("image_url must contain only url")
            safe_url = validate_image_data_url(image_url.get("url"))
            image_count += 1
            if image_count > 1:
                raise MultimodalContractError("only one image is supported per request")
            normalized.append({"type": "image_url", "image_url": {"url": safe_url}})
            continue

        raise MultimodalContractError("unsupported multimodal content part type")

    if text_count < 1:
        raise MultimodalContractError("multimodal user content requires a text part")
    if image_count != 1:
        raise MultimodalContractError("multimodal user content requires exactly one image")
    return normalized


def _prepare_multimodal_raw(raw: Any) -> tuple[Any, dict[int, list[dict[str, Any]]], bool]:
    if not isinstance(raw, dict):
        return raw, {}, False
    messages = raw.get("messages")
    if not isinstance(messages, list):
        return raw, {}, False

    normalized_by_index: dict[int, list[dict[str, Any]]] = {}
    surrogate = deepcopy(raw)
    has_image = False

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        role = message.get("role")
        if role != "user":
            raise MultimodalContractError("only user messages may contain multimodal content")
        normalized = validate_user_multimodal_content(content)
        normalized_by_index[index] = normalized
        has_image = True
        text = "\n".join(
            part["text"] for part in normalized if part.get("type") == "text"
        )
        surrogate["messages"][index] = {"role": "user", "content": text}

    return surrogate, normalized_by_index, has_image


def install_gateway_multimodal_contract(gateway_module: Any) -> None:
    """Wrap the existing gateway validator once, preserving text behavior exactly."""
    if getattr(gateway_module, "_multimodal_contract_installed", False):
        return

    base_validate: Callable[[Any], dict] = gateway_module._validate_body
    invalid_body_cls = gateway_module._InvalidBody

    def _validate_body_with_multimodal(raw: Any) -> dict:
        try:
            surrogate, normalized_by_index, has_image = _prepare_multimodal_raw(raw)
        except MultimodalContractError as exc:
            raise invalid_body_cls(str(exc)) from exc

        body = base_validate(surrogate)
        if not has_image:
            return body

        for index, normalized in normalized_by_index.items():
            body["messages"][index] = {
                "role": "user",
                "content": normalized,
            }

        opts = dict(body.get("business14") or {})
        required = list(opts.get("required_capabilities") or [])
        if "image" not in required:
            required.append("image")
        opts["required_capabilities"] = required
        body["business14"] = opts

        model_id = body["model"]
        if model_id != "b14/auto":
            catalog_model = get_catalog_by_id(model_id)
            if catalog_model is None:
                raise invalid_body_cls(
                    "multimodal image input is supported only by Business 14 catalog routing"
                )
            if "image" not in catalog_model.capabilities:
                raise NoSafeRoute(
                    reason_code="manual_model_capability_mismatch",
                    message="선택한 모델은 이미지 입력을 지원하지 않습니다.",
                    upstream_called=False,
                )
            # Manual fallback candidates are not capability-filtered in the legacy
            # manual router. Disable fallback rather than risk an image request
            # reaching a text-only model.
            opts["allow_external_fallback"] = False

        return body

    gateway_module._validate_body = _validate_body_with_multimodal
    gateway_module._multimodal_contract_installed = True
