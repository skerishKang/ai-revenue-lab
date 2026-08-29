"""Protocol extension dispatcher for platform-owned B14 Providers.

The original platform adapter predates OpenAI Responses API providers and is
kept byte-for-byte stable for existing chat-completions providers. This module
adds one reusable protocol boundary and installs an idempotent dispatcher at
package bootstrap:

- ``chat_completions`` -> existing adapter
- ``responses`` -> bounded OpenAI Responses-compatible adapter

The dispatcher is selected only from server-registered Provider metadata. No
caller can choose an upstream URL or protocol.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
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
from app.pilot.platform_secrets import get_platform_provider, resolve_secret
from app.pilot.redaction import redact_sensitive

logger = logging.getLogger("korean-ai-platform.pilot.platform-protocols")

_MAX_RESPONSE_BYTES = 1024 * 1024
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0
_WRITE_TIMEOUT = 10.0
_POOL_TIMEOUT = 10.0


def _provider_mode() -> str:
    value = os.environ.get("B14_PROVIDER_MODE", "mock").strip().lower()
    return value if value in {"mock", "live"} else "mock"


def _require_spec(platform_provider_id: str):
    spec = get_platform_provider(platform_provider_id)
    if spec is None:
        raise PilotNotConfigured(f"platform provider '{platform_provider_id}' is not registered")
    return spec


def _raise_upstream_error(status: int) -> None:
    if status in (401, 403):
        raise UpstreamAuthFailed()
    if status == 429:
        raise UpstreamRateLimited()
    if 300 <= status < 500:
        raise UpstreamClientError(status)
    if 500 <= status < 600:
        raise UpstreamServerError()
    raise MalformedUpstreamResponse()


def _client_kwargs(transport: httpx.AsyncBaseTransport | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "timeout": httpx.Timeout(
            None,
            connect=_CONNECT_TIMEOUT,
            read=_READ_TIMEOUT,
            write=_WRITE_TIMEOUT,
            pool=_POOL_TIMEOUT,
        )
    }
    if transport is not None:
        result["transport"] = transport
    return result


def _responses_input(messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
    instructions: list[str] = []
    items: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str) or not content:
            raise MalformedUpstreamResponse()
        if role == "system":
            instructions.append(content)
        else:
            items.append({"role": role, "content": content})
    if not items:
        raise MalformedUpstreamResponse()
    return ("\n\n".join(instructions) or None, items)


def _responses_body(
    *,
    upstream_model: str,
    messages: list[dict[str, str]],
    max_tokens: int | None,
    stream: bool,
) -> dict[str, Any]:
    instructions, input_items = _responses_input(messages)
    body: dict[str, Any] = {
        "model": upstream_model,
        "input": input_items,
    }
    if instructions:
        body["instructions"] = instructions
    if max_tokens is not None:
        body["max_output_tokens"] = int(max_tokens)
    if stream:
        body["stream"] = True
    # Deliberately omit temperature: Responses-compatible reasoning models may
    # reject it, while B62 does not require temperature control as product API.
    return body


def _extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    pieces: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "output_text":
                    continue
                text = block.get("text")
                if isinstance(text, str) and text:
                    pieces.append(text)
    return "".join(pieces).strip()


def _responses_usage(raw: Any) -> OpenRouterStreamUsage | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise MalformedUpstreamResponse()
    values: dict[str, int | None] = {}
    mapping = {
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
        "total_tokens": "total_tokens",
    }
    for target, source in mapping.items():
        value = raw.get(source)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise MalformedUpstreamResponse()
        values[target] = value
    return OpenRouterStreamUsage(**values)


def _normalized_completed_response(
    payload: dict[str, Any],
    *,
    upstream_model: str,
    latency_ms: int,
    response_bytes: int,
) -> dict[str, Any]:
    text = _extract_output_text(payload)
    if not text:
        raise MalformedUpstreamResponse()
    actual = payload.get("model")
    actual_model = actual if isinstance(actual, str) and actual else upstream_model
    usage_obj = _responses_usage(payload.get("usage"))
    usage = None
    if usage_obj is not None:
        usage = {
            "prompt_tokens": usage_obj.prompt_tokens,
            "completion_tokens": usage_obj.completion_tokens,
            "total_tokens": usage_obj.total_tokens,
        }
    response_id = payload.get("id")
    if response_id is not None and not isinstance(response_id, str):
        raise MalformedUpstreamResponse()
    return {
        "id": response_id or f"b14live_{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": actual_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "_live": True,
        "_upstream_latency_ms": latency_ms,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": actual_model,
        "_response_bytes": response_bytes,
    }


def _mock_response(model_id: str, upstream_model: str) -> dict[str, Any]:
    return {
        "id": f"b14mock_{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "이것은 Mock 응답입니다. 실제 Provider 호출 없음."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "_mock": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


async def call_platform_responses(
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
    """Execute one bounded OpenAI Responses-compatible platform request."""
    spec = _require_spec(platform_provider_id)
    if spec.api_style != "responses":
        raise PilotNotConfigured(f"Provider '{spec.provider_id}' is not a Responses API provider")
    if _provider_mode() == "mock":
        return _mock_response(model_id, upstream_model)

    secret = resolve_secret(spec)
    if not secret:
        raise PilotNotConfigured(
            f"Provider '{spec.provider_id}' secret is not configured (binding {spec.credential_binding_name})."
        )

    url = f"{spec.base_origin.rstrip('/')}/responses"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}
    body = _responses_body(
        upstream_model=upstream_model,
        messages=messages,
        max_tokens=max_tokens,
        stream=False,
    )
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(**_client_kwargs(transport)) as client:
            response = await client.post(url, headers=headers, json=body, follow_redirects=False)
    except httpx.TimeoutException as exc:
        raise UpstreamTimeout() from exc
    except httpx.RequestError as exc:
        logger.error(
            "platform_responses_error provider=%s error=%s",
            redact_sensitive(provider),
            redact_sensitive(str(exc)),
        )
        raise UpstreamServerError() from exc

    if not 200 <= response.status_code < 300:
        _raise_upstream_error(response.status_code)
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise UpstreamResponseTooLarge(_MAX_RESPONSE_BYTES)
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise MalformedUpstreamResponse() from exc
    if not isinstance(payload, dict):
        raise MalformedUpstreamResponse()
    return _normalized_completed_response(
        payload,
        upstream_model=upstream_model,
        latency_ms=int((time.monotonic() - started) * 1000),
        response_bytes=len(response.content),
    )


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


def _sse_json(frame: bytes) -> dict[str, Any] | None:
    try:
        text = frame.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedUpstreamResponse() from exc
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            value = line[5:]
            data_lines.append(value[1:] if value.startswith(" ") else value)
    if not data_lines:
        return None
    data = "\n".join(data_lines).strip()
    if not data or data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise MalformedUpstreamResponse() from exc
    if not isinstance(payload, dict):
        raise MalformedUpstreamResponse()
    return payload


def _response_identity(payload: dict[str, Any], upstream_model: str) -> tuple[str | None, str]:
    response = payload.get("response")
    if not isinstance(response, dict):
        response = payload
    response_id = response.get("id")
    model = response.get("model")
    if response_id is not None and not isinstance(response_id, str):
        raise MalformedUpstreamResponse()
    if model is not None and not isinstance(model, str):
        raise MalformedUpstreamResponse()
    return response_id, model or upstream_model


async def stream_platform_responses(
    *,
    model_id: str,
    upstream_model: str,
    provider: str,
    platform_provider_id: str,
    messages: list[dict[str, str]],
    temperature: float | None = 0.2,
    max_tokens: int | None = 300,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[OpenRouterStreamEvent]:
    """Normalize Responses SSE events into the existing B14 stream contract."""
    spec = _require_spec(platform_provider_id)
    if spec.api_style != "responses":
        raise PilotNotConfigured(f"Provider '{spec.provider_id}' is not a Responses API provider")
    if _provider_mode() == "mock":
        yield OpenRouterStreamEvent(
            response_id="b14mock_stream",
            model=upstream_model,
            delta_content="이것은 Mock 스트리밍 응답입니다. 실제 Provider 호출 없음.",
        )
        yield OpenRouterStreamEvent(
            response_id="b14mock_stream",
            model=upstream_model,
            finish_reason="stop",
            usage=OpenRouterStreamUsage(0, 0, 0),
        )
        yield OpenRouterStreamEvent(done=True)
        return

    secret = resolve_secret(spec)
    if not secret:
        raise PilotNotConfigured(
            f"Provider '{spec.provider_id}' secret is not configured (binding {spec.credential_binding_name})."
        )
    url = f"{spec.base_origin.rstrip('/')}/responses"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}
    body = _responses_body(
        upstream_model=upstream_model,
        messages=messages,
        max_tokens=max_tokens,
        stream=True,
    )

    total_bytes = 0
    buffer = b""
    saw_completed = False
    saw_delta = False
    try:
        async with httpx.AsyncClient(**_client_kwargs(transport)) as client:
            async with client.stream(
                "POST", url, headers=headers, json=body, follow_redirects=False
            ) as response:
                if not 200 <= response.status_code < 300:
                    _raise_upstream_error(response.status_code)
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_RESPONSE_BYTES:
                        raise UpstreamResponseTooLarge(_MAX_RESPONSE_BYTES)
                    buffer += chunk
                    frames, buffer = _pop_sse_frames(buffer)
                    for frame in frames:
                        payload = _sse_json(frame)
                        if payload is None:
                            continue
                        event_type = payload.get("type")
                        if event_type == "response.output_text.delta":
                            delta = payload.get("delta")
                            if not isinstance(delta, str):
                                raise MalformedUpstreamResponse()
                            response_id, model = _response_identity(payload, upstream_model)
                            saw_delta = saw_delta or bool(delta)
                            yield OpenRouterStreamEvent(
                                response_id=response_id,
                                model=model,
                                delta_content=delta,
                            )
                            continue
                        if event_type == "response.completed":
                            response_payload = payload.get("response")
                            if not isinstance(response_payload, dict):
                                raise MalformedUpstreamResponse()
                            response_id, model = _response_identity(payload, upstream_model)
                            if not saw_delta:
                                final_text = _extract_output_text(response_payload)
                                if final_text:
                                    saw_delta = True
                                    yield OpenRouterStreamEvent(
                                        response_id=response_id,
                                        model=model,
                                        delta_content=final_text,
                                    )
                            usage = _responses_usage(response_payload.get("usage"))
                            yield OpenRouterStreamEvent(
                                response_id=response_id,
                                model=model,
                                finish_reason="stop",
                                usage=usage,
                            )
                            yield OpenRouterStreamEvent(done=True)
                            saw_completed = True
                            return
                        if event_type in {"response.failed", "response.incomplete", "error"}:
                            raise UpstreamServerError()
                        # Creation/progress/content metadata events are intentionally
                        # ignored until a visible text delta or terminal event.

                if buffer.strip():
                    payload = _sse_json(buffer)
                    if payload and payload.get("type") == "response.completed":
                        response_payload = payload.get("response")
                        if not isinstance(response_payload, dict):
                            raise MalformedUpstreamResponse()
                        response_id, model = _response_identity(payload, upstream_model)
                        if not saw_delta:
                            final_text = _extract_output_text(response_payload)
                            if final_text:
                                yield OpenRouterStreamEvent(
                                    response_id=response_id,
                                    model=model,
                                    delta_content=final_text,
                                )
                        yield OpenRouterStreamEvent(
                            response_id=response_id,
                            model=model,
                            finish_reason="stop",
                            usage=_responses_usage(response_payload.get("usage")),
                        )
                        yield OpenRouterStreamEvent(done=True)
                        saw_completed = True
    except httpx.TimeoutException as exc:
        raise UpstreamTimeout() from exc
    except httpx.RequestError as exc:
        logger.error(
            "platform_responses_stream_error provider=%s error=%s",
            redact_sensitive(provider),
            redact_sensitive(str(exc)),
        )
        raise UpstreamServerError() from exc

    if not saw_completed:
        raise MalformedUpstreamResponse()


def install_platform_protocol_dispatch() -> None:
    """Install one idempotent API-style dispatcher over the legacy adapter."""
    from app.pilot import platform as platform_module

    if getattr(platform_module, "_padiem_protocol_dispatch_installed", False):
        return

    original_call = platform_module.call_platform_chat_completions
    original_stream = platform_module.stream_platform_chat_completions

    async def dispatch_call(**kwargs):
        spec = _require_spec(kwargs["platform_provider_id"])
        if spec.api_style == "responses":
            return await call_platform_responses(**kwargs)
        return await original_call(**kwargs)

    async def dispatch_stream(**kwargs):
        spec = _require_spec(kwargs["platform_provider_id"])
        if spec.api_style == "responses":
            async for event in stream_platform_responses(**kwargs):
                yield event
            return
        async for event in original_stream(**kwargs):
            yield event

    platform_module.call_platform_chat_completions = dispatch_call
    platform_module.stream_platform_chat_completions = dispatch_stream
    platform_module._padiem_protocol_dispatch_installed = True
