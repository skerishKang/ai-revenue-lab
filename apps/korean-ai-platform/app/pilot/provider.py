"""OpenAI-compatible HTTP provider adapter for the BYOK Gateway Pilot.

Uses httpx for non-streaming chat completions.
Supports fake transport (httpx.MockTransport) for network-free testing.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from app.pilot.config import pilot_settings
from app.pilot.errors import (
    MalformedUpstreamResponse,
    PilotNotConfigured,
    UpstreamAuthFailed,
    UpstreamRateLimited,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.redaction import redact_headers, redact_sensitive

logger = logging.getLogger("korean-ai-platform.pilot")


def _validate_base_url(url: str) -> None:
    """Validate that the base URL is safe (no SSRF)."""
    if not url.startswith("https://"):
        raise ValueError("Pilot base URL must use https://")

    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Block localhost / loopback
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise ValueError("Pilot base URL must not point to localhost")

    # Block private IP ranges
    if host.startswith("10.") or host.startswith("192.168."):
        raise ValueError("Pilot base URL must not point to a private IP")

    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) == 4 and 16 <= int(parts[1]) <= 31:
            raise ValueError("Pilot base URL must not point to a private IP")

    # Block link-local
    if host.startswith("169.254."):
        raise ValueError("Pilot base URL must not point to a link-local address")


def _build_upstream_request(
    api_key: str,
    messages: list[dict[str, str]],
    temperature: float | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    """Build the OpenAI-compatible request body."""
    body: dict[str, Any] = {
        "model": pilot_settings.pilot_upstream_model or pilot_settings.pilot_model_id,
        "messages": messages,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return body


def _parse_upstream_response(
    response_data: dict[str, Any],
) -> tuple[str, list[dict], dict | None]:
    """Parse an OpenAI-compatible upstream response.

    Returns:
        Tuple of (response_id, choices list, usage dict or None)
    """
    if "choices" not in response_data:
        raise MalformedUpstreamResponse()

    resp_id = response_data.get("id", f"upstream_{uuid.uuid4().hex[:12]}")
    choices = response_data["choices"]
    usage = response_data.get("usage")

    if not isinstance(choices, list) or len(choices) == 0:
        raise MalformedUpstreamResponse()

    return resp_id, choices, usage


async def call_chat_completions(
    api_key: str,
    messages: list[dict[str, str]],
    temperature: float | None = 0.2,
    max_tokens: int | None = 300,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Call the upstream OpenAI-compatible chat completions endpoint.

    Args:
        api_key: Provider API key
        messages: List of message dicts with role and content
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        transport: Optional httpx transport (for fake transport testing)

    Returns:
        Parsed response dict

    Raises:
        Various PilotError subclasses on failure
    """
    if not pilot_settings.configured:
        raise PilotNotConfigured()

    base_url = pilot_settings.pilot_base_url
    _validate_base_url(base_url)

    request_body = _build_upstream_request(api_key, messages, temperature, max_tokens)
    chat_url = f"{base_url.rstrip('/')}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(pilot_settings.pilot_timeout_seconds),
    }
    if transport:
        client_kwargs["transport"] = transport

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            response = await client.post(
                chat_url,
                headers=headers,
                json=request_body,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise UpstreamTimeout()
        except httpx.RequestError as e:
            logger.error(
                "upstream_request_error request_id=%s error=%s",
                uuid.uuid4().hex[:12],
                redact_sensitive(str(e)),
            )
            raise UpstreamServerError()

    if response.status_code == 401:
        raise UpstreamAuthFailed()
    if response.status_code == 429:
        raise UpstreamRateLimited()
    if response.status_code >= 500:
        raise UpstreamServerError()

    try:
        response_data = response.json()
    except (json.JSONDecodeError, ValueError):
        raise MalformedUpstreamResponse()

    if not isinstance(response_data, dict):
        raise MalformedUpstreamResponse()

    resp_id, choices, usage = _parse_upstream_response(response_data)

    # Extract token counts (handle missing usage)
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None
    if usage:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

    return {
        "id": resp_id,
        "object": "chat.completion",
        "model": pilot_settings.pilot_model_id,
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
        "business14": {
            "mode": "byok-pilot",
            "provider": pilot_settings.pilot_provider_id,
            "latency_ms": 0,
            "estimated_krw": 0.0,
            "request_id": f"b14req_{uuid.uuid4().hex[:12]}",
        },
    }
