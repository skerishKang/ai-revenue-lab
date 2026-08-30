"""Generic platform-owned Provider call adapter for Business 14.

OpenAI-compatible chat completions for any registered ``platform_secret``
Provider. The Agnes AI integration is the first concrete registration, but this
module contains no Agnes-specific code: it reads the Provider spec passed to it
and uses only that Provider's own credential binding and fixed origin.

Security boundary
------------------
- secret read from the Provider spec's own binding only (never a caller key);
- fixed upstream origin from the spec (no arbitrary caller URL);
- redirects disabled; bounded per-phase timeouts; bounded response bytes;
- missing secret fails closed with zero upstream calls;
- the secret value is never logged, returned, or stored.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx

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
from app.pilot.openrouter_stream import OpenRouterStreamEvent, OpenRouterStreamUsage
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    is_secret_present,
    register_platform_provider,
    resolve_secret,
)
from app.pilot.redaction import redact_headers, redact_sensitive

logger = logging.getLogger("korean-ai-platform.pilot.platform")

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ERROR_BODY_CHARS = 500

_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0
_WRITE_TIMEOUT = 10.0
_POOL_TIMEOUT = 10.0


def _mock_response(model_id: str, upstream_model: str, provider: str) -> dict[str, Any]:
    """Clearly-labeled mock response (no upstream call)."""
    return {
        "id": f"b14mock_{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "이것은 Mock 응답입니다. 실제 Provider 호출 없음. "
                        f"요청하신 모델: {model_id} (upstream: {upstream_model})"
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "_mock": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


def _require_spec(platform_provider_id: str) -> PlatformProviderSpec:
    spec = get_platform_provider(platform_provider_id)
    if spec is None:
        raise PilotNotConfigured(
            f"platform provider '{platform_provider_id}' is not registered"
        )
    return spec


def _raise_upstream_error(status: int) -> None:
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


async def call_platform_chat_completions(
    *,
    model_id: str,
    upstream_model: str,
    provider: str,
    platform_provider_id: str,
    messages: list[dict[str, str]],
    temperature: float | None = 0.2,
    max_tokens: int | None = 300,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Completed-JSON call to a platform-owned Provider (generic, non-streaming).

    Mock mode (``B14_PROVIDER_MODE=mock``) returns a canned response with zero
    upstream calls. Live mode resolves the Provider's own secret and fails closed
    if the secret is missing.
    """
    import os

    spec = _require_spec(platform_provider_id)

    provider_mode = os.environ.get("B14_PROVIDER_MODE", "mock").strip().lower()
    if provider_mode not in ("mock", "live"):
        provider_mode = "mock"

    if provider_mode == "mock":
        logger.info(
            "platform_mock_call provider=%s model=%s (no real API call)",
            redact_sensitive(provider),
            redact_sensitive(model_id),
        )
        return _mock_response(model_id, upstream_model, provider)

    secret = resolve_secret(spec)
    if not secret:
        # Fail closed, zero upstream calls.
        raise PilotNotConfigured(
            f"Provider '{spec.provider_id}' secret is not configured "
            f"(binding {spec.credential_binding_name})."
        )

    chat_url = f"{spec.base_origin.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {secret}",
    }
    body: dict[str, Any] = {
        "model": upstream_model,
        "messages": messages,
    }
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(
            None,
            connect=_CONNECT_TIMEOUT,
            read=_READ_TIMEOUT,
            write=_WRITE_TIMEOUT,
            pool=_POOL_TIMEOUT,
        ),
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.post(
                chat_url,
                headers=headers,
                json=body,
                follow_redirects=False,
            )
    except httpx.TimeoutException:
        raise UpstreamTimeout()
    except httpx.RequestError as e:
        logger.error(
            "platform_request_error provider=%s error=%s",
            redact_sensitive(provider),
            redact_sensitive(str(e)),
        )
        raise UpstreamServerError()

    if response.status_code < 200 or response.status_code >= 300:
        if response.status_code in (401, 403):
            raise UpstreamAuthFailed()
        if response.status_code == 429:
            raise UpstreamRateLimited()
        if 300 <= response.status_code < 400:
            raise UpstreamClientError(response.status_code)
        raise UpstreamServerError()

    try:
        response_data = response.json()
    except (json.JSONDecodeError, ValueError):
        raise MalformedUpstreamResponse()

    if not isinstance(response_data, dict):
        raise MalformedUpstreamResponse()
    if "choices" not in response_data:
        raise MalformedUpstreamResponse()

    choices = response_data["choices"]
    if not isinstance(choices, list) or len(choices) == 0:
        raise MalformedUpstreamResponse()

    usage = response_data.get("usage")
    prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None

    actual = response_data.get("model")
    actual_response_model = actual if isinstance(actual, str) and actual else None
    latency_ms = int((time.monotonic() - start) * 1000)

    return {
        "id": response_data.get("id", f"b14live_{uuid.uuid4().hex[:12]}"),
        "object": "chat.completion",
        "model": actual_response_model or upstream_model,
        "choices": choices,
        "usage": (
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
            if usage
            else None
        ),
        "_live": True,
        "_upstream_latency_ms": latency_ms,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": actual_response_model,
        "_response_bytes": len(response.content),
    }


async def stream_platform_chat_completions(
    *,
    model_id: str,
    upstream_model: str,
    provider: str,
    platform_provider_id: str,
    messages: list[dict[str, str]],
    temperature: float | None = 0.2,
    max_tokens: int | None = 300,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Any:
    """Streaming call to a platform-owned Provider (OpenAI-compatible SSE).

    Yields :class:`OpenRouterStreamEvent` for compatibility with the Router
    streaming executor. Same security boundary as the completed-JSON path.
    """
    import os

    spec = _require_spec(platform_provider_id)

    provider_mode = os.environ.get("B14_PROVIDER_MODE", "mock").strip().lower()
    if provider_mode not in ("mock", "live"):
        provider_mode = "mock"

    if provider_mode == "mock":
        for event in (
            OpenRouterStreamEvent(
                response_id="b14mock_stream",
                model=upstream_model,
                delta_content="이것은 Mock 스트리밍 응답입니다. 실제 Provider 호출 없음.",
            ),
            OpenRouterStreamEvent(
                response_id="b14mock_stream",
                model=upstream_model,
                finish_reason="stop",
                usage=OpenRouterStreamUsage(0, 0, 0),
            ),
            OpenRouterStreamEvent(done=True),
        ):
            yield event
        return

    secret = resolve_secret(spec)
    if not secret:
        raise PilotNotConfigured(
            f"Provider '{spec.provider_id}' secret is not configured "
            f"(binding {spec.credential_binding_name})."
        )

    chat_url = f"{spec.base_origin.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {secret}",
    }
    body: dict[str, Any] = {
        "model": upstream_model,
        "messages": messages,
        "stream": True,
    }
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(
            None,
            connect=_CONNECT_TIMEOUT,
            read=_READ_TIMEOUT,
            write=_WRITE_TIMEOUT,
            pool=_POOL_TIMEOUT,
        ),
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    saw_done = False
    buffer = b""
    total_bytes = 0
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            async with client.stream(
                "POST",
                chat_url,
                headers=headers,
                json=body,
                follow_redirects=False,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    _raise_upstream_error(response.status_code)

                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > MAX_RESPONSE_BYTES:
                        raise UpstreamResponseTooLarge(MAX_RESPONSE_BYTES)
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
        logger.error(
            "platform_stream_error provider=%s error=%s",
            redact_sensitive(provider),
            redact_sensitive(str(exc)),
        )
        raise UpstreamServerError() from exc

    if not saw_done:
        raise MalformedUpstreamResponse()


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
        rest = rest[index + len(separator):]


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


# ---------------------------------------------------------------------------
# Provider onboarding — generic, one registration per Provider.
# Agnes AI is the first platform-owned Provider. Each later Provider is added
# the same way with its own credential binding and fixed origin; no Agnes-
# specific code path exists anywhere in this module.
# ---------------------------------------------------------------------------
register_platform_provider(
    PlatformProviderSpec(
        provider_id="agnes-ai",
        credential_source=CredentialSource.PLATFORM_SECRET,
        credential_binding_name="AGNES_API_KEY",
        base_origin="https://apihub.agnes-ai.com/v1",
        allowed_hosts=("apihub.agnes-ai.com",),
        enabled=True,
    )
)

# Poolside is registered through the same generic platform-owned Provider
# plane. The module contains only non-secret route metadata; the existing
# Secrets Store resource is bound by wrangler.toml below.
from app.pilot.poolside_provider import register_poolside_provider

register_poolside_provider()
