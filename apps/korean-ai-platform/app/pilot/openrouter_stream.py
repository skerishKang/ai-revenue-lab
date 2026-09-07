"""Internal OpenRouter SSE streaming primitive for Business 14.

This module does not expose streaming through the public Pilot gateway. The
existing gateway continues to reject ``stream=true`` until Router Core,
gateway, Core transport, and client semantics are separately reviewed.

The primitive owns only one upstream attempt. It never performs fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.pilot.errors import (
    MalformedUpstreamResponse,
    UpstreamAuthFailed,
    UpstreamClientError,
    UpstreamRateLimited,
    UpstreamServerError,
)


@dataclass(frozen=True, slots=True)
class OpenRouterStreamUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")


@dataclass(frozen=True, slots=True)
class OpenRouterStreamEvent:
    response_id: str | None = None
    model: str | None = None
    delta_content: str | None = None
    finish_reason: str | None = None
    usage: OpenRouterStreamUsage | None = None
    done: bool = False

    def __post_init__(self) -> None:
        for name in ("response_id", "model", "delta_content", "finish_reason"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string or None")
        if self.usage is not None and not isinstance(self.usage, OpenRouterStreamUsage):
            raise ValueError("usage must be OpenRouterStreamUsage or None")
        if not isinstance(self.done, bool):
            raise ValueError("done must be a boolean")
        if self.done and (
            self.delta_content is not None
            or self.finish_reason is not None
            or self.usage is not None
        ):
            raise ValueError("done event must not contain delta, finish reason, or usage")


def _raise_upstream_error(status: int) -> None:
    """Mirror the existing non-streaming OpenRouter adapter error contract."""
    if status in (401, 403):
        raise UpstreamAuthFailed()
    if status == 429:
        raise UpstreamRateLimited()
    if status == 400:
        raise MalformedUpstreamResponse()
    if 500 <= status < 600:
        raise UpstreamServerError()
    if 300 <= status < 500:
        raise UpstreamClientError(status)
    raise MalformedUpstreamResponse()


def _pop_sse_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Extract complete SSE frames while preserving a fragmented remainder."""
    frames: list[bytes] = []
    rest = buffer
    while True:
        candidates: list[tuple[int, bytes]] = []
        for separator in (b"\r\n\r\n", b"\n\n"):
            index = rest.find(separator)
            if index >= 0:
                candidates.append((index, separator))
        if not candidates:
            return frames, rest
        index, separator = min(candidates, key=lambda item: item[0])
        frames.append(rest[:index])
        rest = rest[index + len(separator) :]


def _usage_from_payload(raw: Any) -> OpenRouterStreamUsage | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise MalformedUpstreamResponse()
    values: dict[str, int | None] = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = raw.get(name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise MalformedUpstreamResponse()
        values[name] = value
    return OpenRouterStreamUsage(**values)


def _parse_sse_frame(frame: bytes) -> OpenRouterStreamEvent | None:
    try:
        text = frame.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedUpstreamResponse() from exc

    data_lines: list[str] = []
    for line in text.splitlines():
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)
            continue
        # Standard SSE metadata fields and unknown extension fields are not
        # part of the model payload and are deliberately ignored.

    if not data_lines:
        return None

    data = "\n".join(data_lines).strip()
    if data == "[DONE]":
        return OpenRouterStreamEvent(done=True)
    if not data:
        raise MalformedUpstreamResponse()

    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise MalformedUpstreamResponse() from exc
    if not isinstance(payload, dict):
        raise MalformedUpstreamResponse()

    response_id = payload.get("id")
    model = payload.get("model")
    if response_id is not None and not isinstance(response_id, str):
        raise MalformedUpstreamResponse()
    if model is not None and not isinstance(model, str):
        raise MalformedUpstreamResponse()

    usage = _usage_from_payload(payload.get("usage"))
    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise MalformedUpstreamResponse()

    delta_content: str | None = None
    finish_reason: str | None = None
    if choices:
        choice = choices[0]
        if not isinstance(choice, dict):
            raise MalformedUpstreamResponse()
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            raise MalformedUpstreamResponse()
        content = delta.get("content")
        if content is not None and not isinstance(content, str):
            raise MalformedUpstreamResponse()
        delta_content = content
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise MalformedUpstreamResponse()
    elif usage is None:
        raise MalformedUpstreamResponse()

    return OpenRouterStreamEvent(
        response_id=response_id,
        model=model,
        delta_content=delta_content,
        finish_reason=finish_reason,
        usage=usage,
    )


def _mock_events(upstream_model: str) -> tuple[OpenRouterStreamEvent, ...]:
    response_id = "b14mock_stream"
    return (
        OpenRouterStreamEvent(
            response_id=response_id,
            model=upstream_model,
            delta_content="이것은 Mock 스트리밍 응답입니다. 실제 Provider 호출 없음.",
        ),
        OpenRouterStreamEvent(
            response_id=response_id,
            model=upstream_model,
            finish_reason="stop",
            usage=OpenRouterStreamUsage(0, 0, 0),
        ),
        OpenRouterStreamEvent(done=True),
    )
