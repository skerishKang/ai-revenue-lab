"""Internal OpenRouter SSE streaming primitive for Business 14.

This module does not expose streaming through the public Pilot gateway. The
existing gateway continues to reject ``stream=true`` until Router Core,
gateway, Core transport, and client semantics are separately reviewed.

The primitive owns only one upstream attempt. It never performs fallback.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
from typing import Any

import httpx

from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import (
    MalformedUpstreamResponse,
    PilotNotConfigured,
    UpstreamAuthFailed,
    UpstreamClientError,
    UpstreamRateLimited,
    UpstreamResponseTooLarge,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.openrouter import MAX_RESPONSE_BYTES
from app.pilot.openrouter_config import openrouter_config


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


async def stream_openrouter_chat_completions(
    messages: list[dict[str, str]],
    temperature: float | None,
    max_tokens: int | None,
    model_id: str,
    upstream_model: str,
    provider: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[OpenRouterStreamEvent]:
    """Yield normalized events for one OpenRouter streaming attempt.

    The function never performs route selection or fallback. All normal tests
    use MockTransport; live network access remains opt-in and outside CI.
    """
    del provider  # Provider identity belongs to the later Router/Gateway layer.

    if openrouter_config.is_mock:
        for event in _mock_events(upstream_model):
            yield event
        return

    if not openrouter_config.has_key:
        raise PilotNotConfigured(
            "OPENROUTER_API_KEY is not set. Set B14_PROVIDER_MODE=mock for mock mode, "
            "or provide a real key for live mode."
        )

    try:
        openrouter_config.validate_base_url()
    except ValueError as exc:
        raise PilotNotConfigured(f"OpenRouter base URL validation failed: {exc}") from exc

    chat_url = f"{openrouter_config.base_url.rstrip('/')}/chat/completions"
    body: dict[str, Any] = {
        "model": upstream_model,
        "messages": messages,
        "stream": True,
    }
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)

    catalog_model = get_catalog_by_id(model_id)
    if catalog_model is not None and "free" in catalog_model.capabilities:
        body["provider"] = {
            "max_price": {
                "prompt": 0,
                "completion": 0,
            }
        }

    client_kwargs: dict[str, Any] = {
        "timeout": openrouter_config.build_http_timeout(),
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    configured_cap = openrouter_config.max_response_bytes
    if isinstance(configured_cap, bool) or not isinstance(configured_cap, int) or configured_cap <= 0:
        raise PilotNotConfigured("OpenRouter response byte limit must be a positive integer.")
    max_response_bytes = min(MAX_RESPONSE_BYTES, configured_cap)

    saw_done = False
    buffer = b""
    total_bytes = 0
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            async with client.stream(
                "POST",
                chat_url,
                headers=openrouter_config.safe_headers(),
                json=body,
                follow_redirects=False,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    _raise_upstream_error(response.status_code)

                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > max_response_bytes:
                        raise UpstreamResponseTooLarge(max_response_bytes)
                    buffer += chunk
                    frames, buffer = _pop_sse_frames(buffer)
                    for frame in frames:
                        event = _parse_sse_frame(frame)
                        if event is None:
                            continue
                        yield event
                        if event.done:
                            saw_done = True
                            return

                if buffer.strip():
                    event = _parse_sse_frame(buffer)
                    if event is not None:
                        yield event
                        if event.done:
                            saw_done = True
    except httpx.TimeoutException as exc:
        raise UpstreamTimeout() from exc
    except httpx.RequestError as exc:
        raise UpstreamServerError() from exc

    if not saw_done:
        raise MalformedUpstreamResponse()
