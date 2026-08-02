"""OpenRouter provider adapter for Business 14 Alpha.

Security requirements:
- API key read from server env var only (OPENROUTER_API_KEY)
- Never sent to browser, never logged, never in response
- HTTP-Referer and X-OpenRouter-Title use non-secret values only
- Exact host allow-list (openrouter.ai)
- Redirects disabled
- Connect/read/total timeout bounds
- Response body size limit
- Upstream error body length limit
- Authorization via Bearer header

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

from app.pilot.openrouter_config import openrouter_config
from app.pilot.redaction import redact_sensitive
from app.pilot.errors import (
    MalformedUpstreamResponse,
    PilotNotConfigured,
    UpstreamAuthFailed,
    UpstreamRateLimited,
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
        upstream_model: OpenRouter upstream model ID
        provider: Provider name for metadata
        transport: Optional MockTransport for testing (forces mock behavior)

    Returns:
        OpenAI-compatible response dict with business14 metadata
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


async def _live_call(
    messages: list[dict[str, str]],
    temperature: float | None,
    max_tokens: int | None,
    upstream_model: str,
    model_id: str,
    provider: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Make a real HTTP call to OpenRouter (live mode only)."""
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

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(openrouter_config.total_timeout_seconds),
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
            "openrouter_request_error error=%s",
            redact_sensitive(str(e)),
        )
        raise UpstreamServerError()

    latency_ms = int((time.monotonic() - start) * 1000)

    if response.status_code < 200 or response.status_code >= 300:
        await _handle_upstream_error(response)

    raw_text = response.text
    if len(raw_text) > MAX_RESPONSE_BYTES:
        raise MalformedUpstreamResponse()

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

    return {
        "id": response_data.get("id", f"b14live_{uuid.uuid4().hex[:12]}"),
        "object": "chat.completion",
        "model": upstream_model,
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
    }


async def _handle_upstream_error(response: httpx.Response) -> None:
    """Map OpenRouter error responses to PilotError subclasses."""
    status = response.status_code

    body_text = ""
    try:
        body_text = response.text or ""
    except Exception:
        body_text = ""

    body_text = _truncate_error_body(body_text)
    logger.warning(
        "openrouter_upstream_error status=%d body=%s",
        status,
        redact_sensitive(body_text),
    )

    if status in (401, 403):
        raise UpstreamAuthFailed()
    if status == 429:
        raise UpstreamRateLimited()
    if status == 400:
        raise MalformedUpstreamResponse()
    if 500 <= status < 600:
        raise UpstreamServerError()
    if 300 <= status < 400:
        raise MalformedUpstreamResponse()
    raise UpstreamServerError()


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
        "latency_ms": 0,
        "request_id": request_id,
        "estimated_usd": None,
        "estimated_krw": None,
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
) -> dict[str, Any]:
    """Build Business 14 metadata for a live response."""
    from app.pilot.catalog import get_catalog_by_id

    cm = get_catalog_by_id(model_id)
    estimated_usd = None
    estimated_krw = None
    if cm and prompt_tokens is not None and completion_tokens is not None:
        estimated_usd = cm.estimate_cost_usd(prompt_tokens, completion_tokens)
        estimated_krw = cm.estimate_cost_krw(prompt_tokens, completion_tokens)

    return {
        "provider_mode": "live",
        "mode": "live",
        "provider": provider,
        "model_route": model_id,
        "upstream_model": upstream_model,
        "latency_ms": latency_ms,
        "request_id": request_id,
        "estimated_usd": estimated_usd,
        "estimated_krw": estimated_krw,
        "route_mode": "auto" if model_id == "b14/auto" else "manual",
        "attempt_count": attempt_count,
        "fallback_used": fallback_used,
        "evidence_status": "live_verified",
    }
