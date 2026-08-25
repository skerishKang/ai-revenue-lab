"""OpenRouter provider adapter for Business 14 Alpha.

Security requirements:
- API key read from server env var only (OPENROUTER_API_KEY)
- Never sent to browser, never logged, never in response
- HTTP-Referer and X-OpenRouter-Title use non-secret values only
- Exact host allow-list (openrouter.ai)
- Redirects disabled
- Explicit connect/read/write/pool timeout bounds (no implicit total)
- Streamed response body with an enforced 1 MB byte cap (the body is
  never fully buffered: reading aborts as soon as the cap is exceeded)
- Upstream error body length limit (bounded stream read)
- Authorization via Bearer header

Error classification (drives the Router Core fallback contract):
- timeout            -> UpstreamTimeout          (fallback allowed)
- transport failure  -> UpstreamServerError      (fallback allowed)
- HTTP 429           -> UpstreamRateLimited      (fallback allowed)
- HTTP 5xx           -> UpstreamServerError      (fallback allowed)
- HTTP 400 / 3xx     -> MalformedUpstreamResponse (NO fallback)
- HTTP 401 / 403     -> UpstreamAuthFailed        (NO fallback)
- other HTTP 4xx     -> UpstreamClientError       (NO fallback)
- oversize response  -> UpstreamResponseTooLarge  (NO fallback)
- malformed body     -> MalformedUpstreamResponse (NO fallback)

Mock mode returns a canned response with zero upstream calls.
Live mode makes a real HTTP call to OpenRouter.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx

from app.pilot.catalog import get_catalog_by_id
from app.pilot.openrouter_config import openrouter_config
from app.pilot.redaction import redact_sensitive
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

logger = logging.getLogger("korean-ai-platform.pilot")

MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MB
MAX_ERROR_BODY_CHARS = 500


def _truncate_error_body(text: str) -> str:
    if len(text) > MAX_ERROR_BODY_CHARS:
        return text[:MAX_ERROR_BODY_CHARS] + "...[truncated]"
    return text


def _mock_response(model_id: str, upstream_model: str, provider: str) -> dict[str, Any]:
    """Return a clearly-labeled mock response (no upstream call)."""
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
                        "B14_PROVIDER_MODE=mock 상태에서는 OpenRouter에 요청을 보내지 않습니다.\n\n"
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


async def call_openrouter_chat_completions(
    messages: list[dict[str, str]],
    temperature: float | None,
    max_tokens: int | None,
    model_id: str,
    upstream_model: str,
    provider: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Call OpenRouter chat completions (mock or live based on config).

    Args:
        messages: Normalized message dicts
        temperature: Sampling temperature
        max_tokens: Max output tokens
        model_id: Business 14 catalog model ID
        upstream_model: OpenRouter upstream model ID sent in the request body
        provider: Provider name for metadata
        transport: Optional MockTransport for testing

    Returns:
        OpenAI-compatible response dict. The ``model`` field echoes the
        requested upstream model; ``_actual_response_model`` preserves the
        ``model`` field OpenRouter actually returned (for ``openrouter/free``
        this is the concrete free model the router selected).
    """
    if openrouter_config.is_mock:
        logger.info(
            "openrouter_mock_call model=%s upstream=%s (no real API call)",
            redact_sensitive(model_id),
            redact_sensitive(upstream_model),
        )
        return _mock_response(model_id, upstream_model, provider)

    return await _live_call(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        upstream_model=upstream_model,
        model_id=model_id,
        provider=provider,
        transport=transport,
    )


async def _read_error_body_bounded(response: httpx.Response) -> str:
    """Read an upstream error body with a hard byte bound (never full-body)."""
    byte_cap = MAX_ERROR_BODY_CHARS * 4
    parts: list[bytes] = []
    total = 0
    try:
        async for chunk in response.aiter_bytes():
            parts.append(chunk)
            total += len(chunk)
            if total >= byte_cap:
                break
    except httpx.HTTPError:
        pass
    text = b"".join(parts).decode("utf-8", "replace")
    return _truncate_error_body(text)


async def _live_call(
    messages: list[dict[str, str]],
    temperature: float | None,
    max_tokens: int | None,
    upstream_model: str,
    model_id: str,
    provider: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Make a real HTTP call to OpenRouter (live mode only).

    Uses the httpx streaming API: status and headers are inspected before
    any body bytes are consumed, and the success body is read incrementally
    with an enforced byte cap — the full body is never held in memory and
    reading aborts immediately once the cap is exceeded.
    """
    if not openrouter_config.has_key:
        raise PilotNotConfigured(
            "OPENROUTER_API_KEY is not set. "
            "Set B14_PROVIDER_MODE=mock for mock mode, or provide a real key for live mode."
        )

    try:
        openrouter_config.validate_base_url()
    except ValueError as e:
        raise PilotNotConfigured(f"OpenRouter base URL validation failed: {e}")

    base_url = openrouter_config.base_url.rstrip("/")
    chat_url = f"{base_url}/chat/completions"

    headers = openrouter_config.safe_headers()

    body: dict[str, Any] = {
        "model": upstream_model,
        "messages": messages,
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

    start = time.monotonic()
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
                    body_text = await _read_error_body_bounded(response)
                    logger.warning(
                        "openrouter_upstream_error status=%d body=%s",
                        response.status_code,
                        redact_sensitive(body_text),
                    )
                    _raise_upstream_error(response.status_code)

                chunks: list[bytes] = []
                total_bytes = 0
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > MAX_RESPONSE_BYTES:
                        raise UpstreamResponseTooLarge(MAX_RESPONSE_BYTES)
                    chunks.append(chunk)
                raw = b"".join(chunks)
    except httpx.TimeoutException:
        raise UpstreamTimeout()
    except httpx.RequestError as e:
        logger.error(
            "openrouter_request_error error=%s",
            redact_sensitive(str(e)),
        )
        raise UpstreamServerError()

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        response_data = json.loads(raw)
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

    raw_model = response_data.get("model")
    actual_response_model = raw_model if isinstance(raw_model, str) and raw_model else None

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
        "_response_bytes": total_bytes,
    }


def _raise_upstream_error(status: int) -> None:
    """Map an upstream HTTP status to a normalized PilotError.

    Fallback-allowed: 429, 5xx. Everything else fails closed (no fallback).
    """
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


def build_mock_metadata(
    request_id: str,
    model_id: str,
    upstream_model: str,
    provider: str,
) -> dict[str, Any]:
    """Build Business 14 metadata for a mock response."""
    return {
        "provider_mode": "mock",
        "mode": "mock",
        "provider": provider,
        "model_route": model_id,
        "upstream_model": upstream_model,
        "actual_response_model": upstream_model,
        "latency_ms": 0,
        "request_id": request_id,
        "estimated_usd": None,
        "estimated_krw": None,
        "cost_basis": "unknown",
        "route_mode": "manual",
        "attempt_count": 1,
        "fallback_used": False,
        "evidence_status": "mock_no_upstream_call",
    }


def build_live_metadata(
    request_id: str,
    model_id: str,
    upstream_model: str,
    provider: str,
    latency_ms: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    attempt_count: int = 1,
    fallback_used: bool = False,
    mode: str = "live",
    actual_response_model: str | None = None,
) -> dict[str, Any]:
    """Build Business 14 metadata for a live response.

    All arguments must describe the candidate that ACTUALLY answered
    (after any fallback), never the primary candidate.
    """
    cm = get_catalog_by_id(model_id)
    estimated_usd = None
    estimated_krw = None
    cost_basis = "unknown"
    if cm and prompt_tokens is not None and completion_tokens is not None:
        estimated_usd = cm.estimate_cost_usd(prompt_tokens, completion_tokens)
        estimated_krw = cm.estimate_cost_krw(prompt_tokens, completion_tokens)
        if cm.price_is_known:
            cost_basis = "known_free" if estimated_usd == 0.0 else "configured_snapshot"

    return {
        "provider_mode": "live",
        "mode": "live",
        "provider": provider,
        "model_route": model_id,
        "upstream_model": upstream_model,
        "actual_response_model": actual_response_model,
        "latency_ms": latency_ms,
        "request_id": request_id,
        "estimated_usd": estimated_usd,
        "estimated_krw": estimated_krw,
        "cost_basis": cost_basis,
        "route_mode": "auto" if model_id == "b14/auto" else "manual",
        "attempt_count": attempt_count,
        "fallback_used": fallback_used,
        "evidence_status": "live_verified",
    }