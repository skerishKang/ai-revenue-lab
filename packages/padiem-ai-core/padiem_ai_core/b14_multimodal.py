from __future__ import annotations

import base64
import binascii
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .b14_execution import B14ChatRequest, MAX_B14_MESSAGE_CHARS, MAX_B14_MESSAGES

MAX_B14_IMAGE_BYTES = 4 * 1024 * 1024
MAX_B14_MULTIMODAL_PARTS = 4
_ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_ALLOWED_ROLES = frozenset({"system", "user", "assistant"})


def _image_magic_matches(media_type: str, data: bytes) -> bool:
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def _normalize_image_data_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("image_url.url must be a data URL string")
    media_type = None
    payload = None
    for candidate in _ALLOWED_IMAGE_MEDIA_TYPES:
        prefix = f"data:{candidate};base64,"
        if value.startswith(prefix):
            media_type = candidate
            payload = value[len(prefix):]
            break
    if media_type is None or payload is None:
        raise ValueError("image_url.url must be a JPEG, PNG, or WebP base64 data URL")
    if not payload:
        raise ValueError("image data must not be empty")
    if len(payload) > ((MAX_B14_IMAGE_BYTES + 2) // 3) * 4 + 4:
        raise ValueError("decoded image must not exceed 4 MiB")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image data must be valid base64") from exc
    if not decoded:
        raise ValueError("image data must not be empty")
    if len(decoded) > MAX_B14_IMAGE_BYTES:
        raise ValueError("decoded image must not exceed 4 MiB")
    if not _image_magic_matches(media_type, decoded):
        raise ValueError("image media type does not match image bytes")
    return f"data:{media_type};base64,{payload}"


def _normalize_multimodal_content(role: str, content: Any) -> tuple[Mapping[str, Any], ...]:
    if role != "user":
        raise ValueError("only user messages may contain multimodal content")
    if isinstance(content, (str, bytes)) or not isinstance(content, Sequence):
        raise ValueError("multimodal content must be a sequence of parts")
    parts = tuple(content)
    if not 2 <= len(parts) <= MAX_B14_MULTIMODAL_PARTS:
        raise ValueError("multimodal user content must have 2 to 4 parts")

    normalized: list[Mapping[str, Any]] = []
    text_count = 0
    image_count = 0
    total_text_chars = 0
    for part in parts:
        if not isinstance(part, Mapping):
            raise ValueError("multimodal parts must be objects")
        part_type = part.get("type")
        if part_type == "text":
            if set(part) != {"type", "text"}:
                raise ValueError("text part has unsupported fields")
            text = part.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text part must contain non-empty text")
            text = text.strip()
            total_text_chars += len(text)
            if total_text_chars > MAX_B14_MESSAGE_CHARS:
                raise ValueError(
                    f"multimodal text must not exceed {MAX_B14_MESSAGE_CHARS} characters"
                )
            text_count += 1
            normalized.append(MappingProxyType({"type": "text", "text": text}))
            continue
        if part_type == "image_url":
            if set(part) != {"type", "image_url"}:
                raise ValueError("image_url part has unsupported fields")
            image_url = part.get("image_url")
            if not isinstance(image_url, Mapping) or set(image_url) != {"url"}:
                raise ValueError("image_url must contain only url")
            safe_url = _normalize_image_data_url(image_url.get("url"))
            image_count += 1
            if image_count > 1:
                raise ValueError("only one image is supported per multimodal message")
            normalized.append(
                MappingProxyType(
                    {
                        "type": "image_url",
                        "image_url": MappingProxyType({"url": safe_url}),
                    }
                )
            )
            continue
        raise ValueError("unsupported multimodal content part type")
    if text_count < 1:
        raise ValueError("multimodal user content requires a text part")
    if image_count != 1:
        raise ValueError("multimodal user content requires exactly one image")
    return tuple(normalized)


def _normalize_messages(messages: Sequence[Mapping[str, Any]]) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, str], ...]]:
    if isinstance(messages, (str, bytes)):
        raise ValueError("messages must be a sequence of message objects")
    items = tuple(messages)
    if not 1 <= len(items) <= MAX_B14_MESSAGES:
        raise ValueError(f"messages must contain 1 to {MAX_B14_MESSAGES} items")

    normalized: list[Mapping[str, Any]] = []
    surrogates: list[Mapping[str, str]] = []
    for index, message in enumerate(items):
        if not isinstance(message, Mapping):
            raise ValueError(f"messages[{index}] must be a mapping")
        if set(message) != {"role", "content"}:
            raise ValueError(f"messages[{index}] must contain only role and content")
        role = message.get("role")
        if role not in _ALLOWED_ROLES:
            raise ValueError(f"messages[{index}].role is invalid")
        content = message.get("content")
        if isinstance(content, str):
            if not content.strip():
                raise ValueError(f"messages[{index}].content must be non-empty")
            text = content.strip()
            if len(text) > MAX_B14_MESSAGE_CHARS:
                raise ValueError(
                    f"messages[{index}].content must not exceed {MAX_B14_MESSAGE_CHARS} characters"
                )
            normalized.append(MappingProxyType({"role": role, "content": text}))
            surrogates.append({"role": role, "content": text})
            continue
        parts = _normalize_multimodal_content(role, content)
        normalized.append(MappingProxyType({"role": role, "content": parts}))
        surrogate_text = "\n".join(part["text"] for part in parts if part["type"] == "text")
        surrogates.append({"role": role, "content": surrogate_text})

    return tuple(normalized), tuple(surrogates)


def _thaw_message(message: Mapping[str, Any]) -> dict[str, Any]:
    content = message["content"]
    if isinstance(content, str):
        return {"role": message["role"], "content": content}
    parts: list[dict[str, Any]] = []
    for part in content:
        if part["type"] == "text":
            parts.append({"type": "text", "text": part["text"]})
        else:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": part["image_url"]["url"]},
                }
            )
    return {"role": message["role"], "content": parts}


class B14MultimodalChatRequest(B14ChatRequest):
    """B14ChatRequest-compatible request with the existing B14 image contract."""

    def __post_init__(self) -> None:
        normalized, surrogates = _normalize_messages(self.messages)
        validated = B14ChatRequest(
            messages=surrogates,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            routing=self.routing,
        )
        object.__setattr__(self, "messages", normalized)
        object.__setattr__(self, "model", validated.model)
        object.__setattr__(self, "temperature", validated.temperature)
        object.__setattr__(self, "max_tokens", validated.max_tokens)
        object.__setattr__(self, "routing", validated.routing)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_thaw_message(message) for message in self.messages],
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        routing = self.routing.to_dict()
        if routing:
            payload["business14"] = routing
        return payload
