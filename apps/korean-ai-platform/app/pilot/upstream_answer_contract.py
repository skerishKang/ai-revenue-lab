"""Fail-closed text-answer contract for completed and streamed B14 chat (#3554).

HTTP success or an SSE terminal marker never proves that an assistant answer
exists. No provider body, text, prompt or raw finish reason is logged here.
"""
from __future__ import annotations

from typing import Any

from app.pilot.errors import MalformedUpstreamResponse, PilotError

_KNOWN_FINISH = frozenset({"stop", "length", "content_filter", "tool_calls", "function_call"})


def safe_finish_category(value: Any) -> str:
    return value if isinstance(value, str) and value in _KNOWN_FINISH else "other"


class UpstreamEmptyAnswer(PilotError):
    """Provider completed without a non-whitespace text answer; never retryable."""

    def __init__(self, finish_reason: Any = None, *, streamed: bool = False) -> None:
        self.finish_category = safe_finish_category(finish_reason)
        super().__init__(
            # Keep the established auto-stream API error taxonomy stable.
            code="empty_stream_answer" if streamed else "upstream_empty_answer",
            message="Provider가 텍스트 답변을 생성하지 않았습니다.",
            status_code=502,
        )


def require_completed_text_answer(data: dict[str, Any]) -> None:
    """Validate provider-first-choice text without inspecting or returning its text."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise MalformedUpstreamResponse()
    first = choices[0]
    if not isinstance(first, dict):
        raise MalformedUpstreamResponse()
    message = first.get("message")
    if not isinstance(message, dict):
        raise MalformedUpstreamResponse()
    content = message.get("content")
    if content is None or (isinstance(content, str) and not content.strip()):
        raise UpstreamEmptyAnswer(first.get("finish_reason"))
    if not isinstance(content, str):
        raise MalformedUpstreamResponse()
