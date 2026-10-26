"""Bounded structural diagnostics: no response text, headers or opaque tokens."""
from __future__ import annotations

import json
import logging
from typing import Any

from .errors import MalformedUpstreamResponse

logger = logging.getLogger("korean-ai-platform.pilot.platform")
_KEYS = frozenset({
    "id", "object", "model", "choices", "usage", "error", "delta", "message",
    "index", "role", "content", "parts", "text", "type", "finish_reason",
    "tool_calls", "function_call", "refusal", "extra_content", "signature",
    "prompt_tokens", "completion_tokens", "total_tokens", "prompt_tokens_details",
    "completion_tokens_details", "reasoning_tokens", "cached_tokens",
    "candidates", "content", "parts", "finishReason", "usageMetadata",
    "responseId", "modelVersion", "promptTokenCount", "candidatesTokenCount",
    "totalTokenCount", "thoughtsTokenCount", "thought", "thoughtSignature",
    "functionCall", "safetyRatings", "promptFeedback", "google", "thought_signature",
})
_FINISH = frozenset({"stop", "length", "content_filter", "tool_calls", "function_call",
                     "STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER"})


def _keys(value: Any) -> list[str]:
    # Unknown key names can themselves contain text/secrets; never echo them.
    return sorted({key if key in _KEYS else "<other>" for key in value}) if isinstance(value, dict) else []


def response_shape(payload: Any) -> dict[str, Any]:
    shape: dict[str, Any] = {"type": type(payload).__name__, "keys": _keys(payload)}
    if not isinstance(payload, dict):
        return shape
    choices = payload.get("choices", payload.get("candidates"))
    shape["choices_length"] = len(choices) if isinstance(choices, list) else None
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    shape["delta_keys"] = _keys(first.get("delta"))
    shape["message_keys"] = _keys(first.get("message"))
    message = first.get("delta", first.get("message", first))
    content = message.get("content") if isinstance(message, dict) else None
    shape["content_type"] = type(content).__name__
    shape["content_length"] = len(content) if isinstance(content, (str, list, dict)) else None
    finish = first.get("finish_reason", first.get("finishReason"))
    shape["finish_reason"] = finish if isinstance(finish, str) and finish in _FINISH else (None if finish is None else "<other>")
    shape["usage_keys"] = _keys(payload.get("usage", payload.get("usageMetadata")))
    return shape


def malformed(reason: str, payload: Any = None, *, provider: str = "unknown",
              model: str = "unknown", path: str = "stream") -> MalformedUpstreamResponse:
    logger.warning("b14_malformed_upstream provider=%s model=%s path=%s reason=%s shape=%s",
                   provider, model, path, reason, json.dumps(response_shape(payload), sort_keys=True))
    return MalformedUpstreamResponse(reason)


def text_content(value: Any) -> str | None:
    """Accept text strings, string lists and text parts; reject non-text shapes."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, dict) and set(value) == {"parts"}:
        value = value["parts"]
    if not isinstance(value, list):
        raise MalformedUpstreamResponse("content_not_str")
    pieces = []
    for part in value:
        if isinstance(part, str):
            pieces.append(part)
        elif isinstance(part, dict) and isinstance(part.get("text"), str) and part.get("type", "text") in ("text", "output_text"):
            pieces.append(part["text"])
        else:
            raise MalformedUpstreamResponse("invalid_text")
    return "".join(pieces)
