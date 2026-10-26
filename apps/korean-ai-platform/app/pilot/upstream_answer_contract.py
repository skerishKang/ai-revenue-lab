"""Fail-closed text-answer contract for completed and streamed B14 chat (#3554).

HTTP success or an SSE terminal marker never proves that an assistant answer
exists. No provider body, text, prompt or raw finish reason is logged here.
"""
from __future__ import annotations

from typing import Any

from app.pilot.errors import MalformedUpstreamResponse, PilotError
from .malformed_diagnostics import text_content

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


def _has_tool_calls(message: dict[str, Any]) -> bool:
    """Whether an assistant turn carries at least one tool call."""

    tool_calls = message.get("tool_calls")
    return isinstance(tool_calls, list) and bool(tool_calls)


def require_completed_text_answer(
    data: dict[str, Any], *, allow_tool_calls: bool = False
) -> None:
    """Validate provider-first-choice text without inspecting or returning its text.

    #5536: when the request declared a tool, a tool call is a complete answer
    of its own. The assistant content may then be absent or empty, because the
    model's product is the call rather than prose. A request that declared no
    tool keeps the strict text-answer contract unchanged.
    """
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise MalformedUpstreamResponse("choices_empty_or_invalid")
    first = choices[0]
    if not isinstance(first, dict):
        raise MalformedUpstreamResponse("choice_not_object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise MalformedUpstreamResponse("message_not_object")
    content = text_content(message.get("content"))
    if message.get("content") is not None:
        message["content"] = content
    if content is None or (isinstance(content, str) and not content.strip()):
        if allow_tool_calls and _has_tool_calls(message):
            return
        raise UpstreamEmptyAnswer(first.get("finish_reason"))
    if not isinstance(content, str):
        raise MalformedUpstreamResponse("content_not_str")
