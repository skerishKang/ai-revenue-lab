"""Internal SSE streaming primitive for Business 14.

This module does not expose streaming through the public Pilot gateway. The
existing gateway continues to reject ``stream=true`` until Router Core,
gateway, Core transport, and client semantics are separately reviewed.

The primitive owns only one upstream attempt. It never performs fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.pilot.errors import MalformedUpstreamResponse
from .malformed_diagnostics import malformed, text_content


@dataclass(frozen=True, slots=True)
class StreamUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    # A provider that bills reasoning separately reports it beside the answer.
    # It is stored as the provider reported it, never folded into completion by
    # arithmetic, so a later reader can tell a measured value from a derived one.
    reasoning_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")


@dataclass(frozen=True, slots=True)
class StreamToolCall:
    """One complete function call, never an executable partial argument chunk.

    ``signature`` is the provider's opaque continuation token for this call
    (a Gemini thought signature today). It is relayed verbatim and must be
    returned on a native follow-up; nothing here interprets it.
    """

    id: str
    name: str
    arguments: str
    index: int
    signature: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError("tool call index must be a non-negative integer")
        if not all(isinstance(value, str) and value for value in (self.id, self.name, self.arguments)):
            raise ValueError("tool call fields must be non-empty strings")
        if not isinstance(json.loads(self.arguments), dict):
            raise ValueError("tool call arguments must encode an object")
        if self.signature is not None:
            from app.pilot.tool_channel import MAX_TOOL_SIGNATURE_CHARS

            if (
                not isinstance(self.signature, str)
                or not self.signature.strip()
                or len(self.signature) > MAX_TOOL_SIGNATURE_CHARS
            ):
                raise ValueError("tool call signature must be a bounded string")


@dataclass(frozen=True, slots=True)
class StreamEvent:
    response_id: str | None = None
    model: str | None = None
    delta_content: str | None = None
    finish_reason: str | None = None
    usage: StreamUsage | None = None
    done: bool = False
    tool_call: StreamToolCall | None = None
    # The provider's opaque continuation token for THIS event's own text part.
    # A call carries its token on the call itself; a signed answer text carries
    # it here, so a native follow-up can return each token with the part it
    # belonged to. Nothing in B14 interprets it.
    signature: str | None = None

    def __post_init__(self) -> None:
        for name in ("response_id", "model", "delta_content", "finish_reason"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string or None")
        if self.signature is not None:
            from app.pilot.tool_channel import MAX_TOOL_SIGNATURE_CHARS

            if (
                not isinstance(self.signature, str)
                or not self.signature.strip()
                or len(self.signature) > MAX_TOOL_SIGNATURE_CHARS
            ):
                raise ValueError("event signature must be a bounded string")
        if self.usage is not None and not isinstance(self.usage, StreamUsage):
            raise ValueError("usage must be StreamUsage or None")
        if not isinstance(self.done, bool):
            raise ValueError("done must be a boolean")
        if self.tool_call is not None and not isinstance(self.tool_call, StreamToolCall):
            raise ValueError("tool_call must be StreamToolCall or None")
        if self.done and (
            self.delta_content is not None
            or self.usage is not None
            or self.tool_call is not None
            or self.signature is not None
        ):
            raise ValueError("done event must not contain delta, tool call, or usage")


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


def _usage_from_payload(raw: Any, *, provider="unknown", model="unknown", path="usage", payload=None) -> StreamUsage | None:
    def fail(reason):
        return malformed(reason, payload if payload is not None else {"usage": raw}, provider=provider, model=model, path=path)

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise fail("usage_not_object")
    values: dict[str, int | None] = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = raw.get(name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise fail("usage_value")
        values[name] = value
    details = raw.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    if reasoning is not None and (
        isinstance(reasoning, bool) or not isinstance(reasoning, int) or reasoning < 0
    ):
        raise fail("usage_value")
    return StreamUsage(**values, reasoning_tokens=reasoning)


def _parse_sse_frame(frame: bytes, *, provider="unknown", model_id="unknown") -> StreamEvent | None:
    payload = None
    def fail(reason):
        return malformed(reason, payload, provider=provider, model=model_id, path="stream")

    try:
        text = frame.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise fail("utf8_decode") from None

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
        return StreamEvent(done=True)
    if not data:
        raise fail("empty_data")

    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise fail("json_decode") from None
    if not isinstance(payload, dict):
        raise fail("payload_not_object")

    response_id = payload.get("id")
    model = payload.get("model")
    if response_id is not None and not isinstance(response_id, str):
        raise fail("response_id_not_str")
    if model is not None and not isinstance(model, str):
        raise fail("model_not_str")

    usage = _usage_from_payload(payload.get("usage"), provider=provider, model=model_id, path="stream", payload=payload)
    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise fail("choices_not_list")

    delta_content: str | None = None
    finish_reason: str | None = None
    if choices:
        choice = choices[0]
        if not isinstance(choice, dict):
            raise fail("choice_not_object")
        delta = choice.get("delta", choice.get("message"))
        if delta is None and choice.get("finish_reason") is not None:
            delta = {}
        if not isinstance(delta, dict):
            raise fail("delta_not_object")
        content = delta.get("content")
        try:
            delta_content = text_content(content)
        except MalformedUpstreamResponse as exc:
            raise fail(exc.reason) from None
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise fail("finish_reason_not_str")
    elif usage is None:
        return None  # Empty no-usage chunks are keepalives, not failed answers.

    return StreamEvent(
        response_id=response_id,
        model=model,
        delta_content=delta_content,
        finish_reason=finish_reason,
        usage=usage,
    )


def _mock_events(upstream_model: str) -> tuple[StreamEvent, ...]:
    response_id = "b14mock_stream"
    return (
        StreamEvent(
            response_id=response_id,
            model=upstream_model,
            delta_content="이것은 Mock 스트리밍 응답입니다. 실제 Provider 호출 없음.",
        ),
        StreamEvent(
            response_id=response_id,
            model=upstream_model,
            finish_reason="stop",
            usage=StreamUsage(0, 0, 0),
        ),
        StreamEvent(done=True),
    )
