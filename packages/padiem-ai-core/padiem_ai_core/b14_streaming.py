from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import json
from typing import Any, Mapping

import httpx

from .b14_execution import (
    B14ChatRequest,
    B14ExecutionConfig,
    B14ExecutionError,
    B14RouteMetadata,
    _parse_route_metadata,
    _parse_usage,
    _safe_string,
)
from .contracts import UsageMetadata

B14_STREAM_PREVIEW_PATH = "/api/pilot/v1/chat/completions/stream-preview"


@dataclass(frozen=True, slots=True)
class B14StreamEvent:
    response_id: str | None = None
    model: str | None = None
    delta_content: str | None = None
    finish_reason: str | None = None
    usage: UsageMetadata = field(default_factory=UsageMetadata)
    route: B14RouteMetadata = field(default_factory=B14RouteMetadata)
    done: bool = False

    def __post_init__(self) -> None:
        for name in ("response_id", "model", "delta_content", "finish_reason"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string or None")
        if not isinstance(self.usage, UsageMetadata):
            raise ValueError("usage must be UsageMetadata")
        if not isinstance(self.route, B14RouteMetadata):
            raise ValueError("route must be B14RouteMetadata")
        if not isinstance(self.done, bool):
            raise ValueError("done must be a boolean")
        if self.done and (
            self.delta_content is not None
            or self.finish_reason is not None
            or any(
                value is not None
                for value in (
                    self.usage.input_tokens,
                    self.usage.output_tokens,
                    self.usage.total_tokens,
                )
            )
        ):
            raise ValueError("done event must not contain delta, finish reason, or usage")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "response_id": self.response_id,
            "model": self.model,
            "delta_content": self.delta_content,
            "finish_reason": self.finish_reason,
            "usage": self.usage.to_public_dict(),
            "route": self.route.to_public_dict(),
            "done": self.done,
        }


@dataclass(frozen=True, slots=True)
class _SSEFrame:
    event: str
    data: str


def _pop_sse_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
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


def _decode_sse_frame(raw: bytes) -> _SSEFrame | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise B14ExecutionError(
            "malformed_upstream",
            "Business 14 returned malformed streaming data.",
            upstream_status_code=200,
        ) from exc

    event_name = "message"
    data_lines: list[str] = []
    for line in text.splitlines():
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            value = line[6:]
            if value.startswith(" "):
                value = value[1:]
            event_name = value.strip() or "message"
            continue
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)
            continue
        # id/retry and unknown SSE extension fields are deliberately ignored.

    if not data_lines:
        return None
    return _SSEFrame(event=event_name, data="\n".join(data_lines).strip())


def _malformed(message: str = "Business 14 returned malformed streaming data.") -> B14ExecutionError:
    return B14ExecutionError(
        "malformed_upstream",
        message,
        upstream_status_code=200,
    )


def _parse_error_frame(frame: _SSEFrame) -> B14ExecutionError:
    try:
        payload = json.loads(frame.data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _malformed() from exc
    if not isinstance(payload, Mapping):
        raise _malformed()
    raw_error = payload.get("error")
    if not isinstance(raw_error, Mapping):
        raise _malformed()
    code = _safe_string(raw_error.get("code"), limit=120)
    message = _safe_string(raw_error.get("message"), limit=500)
    if code is None or message is None:
        raise _malformed()
    return B14ExecutionError(
        code,
        message,
        upstream_status_code=200,
        retryable=False,
    )


def _parse_data_frame(frame: _SSEFrame) -> B14StreamEvent:
    if frame.event != "message":
        if frame.event == "error":
            raise _parse_error_frame(frame)
        raise _malformed("Business 14 returned an unsupported streaming event.")

    if frame.data == "[DONE]":
        return B14StreamEvent(done=True)
    if not frame.data:
        raise _malformed()

    try:
        payload = json.loads(frame.data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _malformed() from exc
    if not isinstance(payload, Mapping):
        raise _malformed()
    if payload.get("object") != "chat.completion.chunk":
        raise _malformed("Business 14 returned an unexpected streaming response shape.")

    response_id = _safe_string(payload.get("id"), limit=300)
    model = _safe_string(payload.get("model"), limit=300)
    if payload.get("id") is not None and response_id is None:
        raise _malformed()
    if payload.get("model") is not None and model is None:
        raise _malformed()

    raw_route = payload.get("business14")
    if not isinstance(raw_route, Mapping):
        raise _malformed("Business 14 streaming chunk did not contain route metadata.")
    route = _parse_route_metadata(payload)

    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise _malformed()

    usage = _parse_usage(payload)
    delta_content: str | None = None
    finish_reason: str | None = None
    if choices:
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise _malformed()
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            raise _malformed()
        content = delta.get("content")
        if content is not None and not isinstance(content, str):
            raise _malformed()
        delta_content = content
        finish_reason_raw = choice.get("finish_reason")
        if finish_reason_raw is not None and not isinstance(finish_reason_raw, str):
            raise _malformed()
        finish_reason = finish_reason_raw
    elif all(
        value is None
        for value in (
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
        )
    ):
        raise _malformed()

    return B14StreamEvent(
        response_id=response_id,
        model=model,
        delta_content=delta_content,
        finish_reason=finish_reason,
        usage=usage,
        route=route,
    )


def _validate_stream_request(request: B14ChatRequest) -> None:
    if not isinstance(request, B14ChatRequest):
        raise ValueError("request must be B14ChatRequest")
    if request.model == "b14/auto":
        raise B14ExecutionError(
            "streaming_request_unsupported",
            "Business 14 streaming currently requires an explicit model route.",
        )
    if request.routing.allow_external_fallback is True:
        raise B14ExecutionError(
            "streaming_request_unsupported",
            "Business 14 streaming fallback is not enabled in this Core contract.",
        )
    if request.routing.max_attempts not in (None, 1):
        raise B14ExecutionError(
            "streaming_request_unsupported",
            "Business 14 streaming currently allows one route attempt only.",
        )


def _raise_status_error(status_code: int) -> None:
    if status_code in {401, 403}:
        raise B14ExecutionError(
            "upstream_auth_error",
            "Business 14 rejected the service request authorization.",
            upstream_status_code=status_code,
        )
    if status_code == 429:
        raise B14ExecutionError(
            "upstream_rate_limited",
            "Business 14 is rate limiting requests.",
            upstream_status_code=status_code,
            retryable=True,
        )
    if 400 <= status_code < 500:
        raise B14ExecutionError(
            "upstream_request_error",
            "Business 14 rejected the request.",
            upstream_status_code=status_code,
        )
    if status_code >= 500:
        raise B14ExecutionError(
            "upstream_server_error",
            "Business 14 returned a server error.",
            upstream_status_code=status_code,
            retryable=True,
        )
    if status_code < 200 or status_code >= 300:
        raise B14ExecutionError(
            "upstream_request_error",
            "Business 14 returned an unsupported HTTP status.",
            upstream_status_code=status_code,
        )


class B14StreamingClient:
    def __init__(
        self,
        config: B14ExecutionConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(config, B14ExecutionConfig):
            raise ValueError("config must be B14ExecutionConfig")
        self._config = config
        self._transport = transport

    @property
    def config(self) -> B14ExecutionConfig:
        return self._config

    @property
    def stream_preview_url(self) -> str:
        return self._config.base_url + B14_STREAM_PREVIEW_PATH

    async def stream(self, request: B14ChatRequest) -> AsyncIterator[B14StreamEvent]:
        _validate_stream_request(request)

        payload = request.to_payload()
        payload["stream"] = True
        timeout = httpx.Timeout(
            connect=min(self._config.timeout_seconds, 10.0),
            read=self._config.timeout_seconds,
            write=min(self._config.timeout_seconds, 10.0),
            pool=min(self._config.timeout_seconds, 10.0),
        )

        total_bytes = 0
        buffer = b""
        saw_done = False
        last_route = B14RouteMetadata()
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    self.stream_preview_url,
                    json=payload,
                ) as response:
                    status_code = response.status_code
                    _raise_status_error(status_code)
                    content_type = response.headers.get("content-type", "").lower()
                    if not content_type.startswith("text/event-stream"):
                        raise B14ExecutionError(
                            "malformed_upstream",
                            "Business 14 streaming endpoint returned an unexpected content type.",
                            upstream_status_code=status_code,
                        )

                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > self._config.max_response_bytes:
                            raise B14ExecutionError(
                                "upstream_response_too_large",
                                "Business 14 response exceeded the configured safety limit.",
                                upstream_status_code=status_code,
                            )
                        buffer += chunk
                        frames, buffer = _pop_sse_frames(buffer)
                        for raw_frame in frames:
                            decoded = _decode_sse_frame(raw_frame)
                            if decoded is None:
                                continue
                            event = _parse_data_frame(decoded)
                            if event.done:
                                saw_done = True
                                yield B14StreamEvent(route=last_route, done=True)
                                return
                            last_route = event.route
                            yield event

                    if buffer.strip():
                        decoded = _decode_sse_frame(buffer)
                        if decoded is not None:
                            event = _parse_data_frame(decoded)
                            if event.done:
                                saw_done = True
                                yield B14StreamEvent(route=last_route, done=True)
                                return
                            last_route = event.route
                            yield event
        except B14ExecutionError:
            raise
        except httpx.TimeoutException as exc:
            raise B14ExecutionError(
                "upstream_timeout",
                "Business 14 did not respond before the configured timeout.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise B14ExecutionError(
                "upstream_unavailable",
                "Business 14 transport is unavailable.",
                retryable=True,
            ) from exc

        if not saw_done:
            raise B14ExecutionError(
                "malformed_upstream",
                "Business 14 streaming response ended without a completion marker.",
                upstream_status_code=200,
            )
