"""OpenAI-compatible HTTP provider adapter for the BYOK Gateway Pilot.

Uses httpx for non-streaming chat completions.
Supports fake transport (httpx.MockTransport) for network-free testing.
Supports RouteTarget-based multi-provider calling (Phase 2).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from app.pilot.errors import (
    MalformedUpstreamResponse,
    PilotNotConfigured,
    UpstreamAuthFailed,
    UpstreamRateLimited,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.redaction import redact_sensitive
from app.pilot.schemas import ChatMessage, dataclass_to_dict

logger = logging.getLogger("korean-ai-platform.pilot")


import ipaddress


def _serialize_messages(
    messages: list[ChatMessage | dict[str, str]],
) -> list[dict[str, str]]:
    """Normalize messages to plain dicts for JSON serialization."""
    serialized: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, ChatMessage):
                serialized.append(dataclass_to_dict(message))
        else:
            serialized.append(dict(message))
    return serialized


def _validate_base_url(url: str) -> None:
    """Validate that the base URL is safe (no SSRF)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Pilot base URL must use https://")
    if parsed.username or parsed.password:
        raise ValueError("Pilot base URL must not contain credentials")
    if parsed.fragment:
        raise ValueError("Pilot base URL must not contain a fragment")
    host = parsed.hostname
    if not host:
        raise ValueError("Pilot base URL must have a hostname")
    host_lower = host.lower()
    if host_lower in ("localhost", "localhost.localdomain", "local", "broadcasthost"):
        raise ValueError("Pilot base URL must not point to localhost")
    try:
        addr = ipaddress.ip_address(host_lower)
    except ValueError:
        return
    if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_unspecified or addr.is_multicast or addr.is_reserved:
        raise ValueError("Pilot base URL must not point to a non-routable address")


def _build_upstream_request(
    api_key: str,
    messages: list[dict[str, str]],
    temperature: float | None,
    max_tokens: int | None,
    upstream_model: str,
) -> dict[str, Any]:
    """Build the OpenAI-compatible request body."""
    body: dict[str, Any] = {
        "model": upstream_model,
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
    """Parse an OpenAI-compatible upstream response."""
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
    *,
    # Phase 2 multi-provider: RouteTarget override
    base_url: str | None = None,
    upstream_model: str | None = None,
    timeout_seconds: int | None = None,
    response_model: str | None = None,
) -> dict[str, Any]:
    """Call the upstream OpenAI-compatible chat completions endpoint.

    Phase 2 accepts explicit base_url/upstream_model/timeout_seconds for
    multi-provider routing. Falls back to legacy pilot_settings when
    these are not provided.

    Args:
        api_key: Provider API key
        messages: List of message dicts
        temperature: Sampling temperature
        max_tokens: Maximum tokens
        transport: Optional MockTransport for testing
        base_url: Explicit base URL (Phase 2)
        upstream_model: Explicit upstream model name (Phase 2)
        timeout_seconds: Explicit timeout (Phase 2)
        response_model: Model ID to return in response top-level (Phase 2)

    Returns:
        Parsed response dict with business14 metadata
    """
    from app.pilot.config import pilot_settings

    # Determine configuration source
    resolved_url = base_url or pilot_settings.pilot_base_url
    resolved_upstream = upstream_model or pilot_settings.pilot_upstream_model or pilot_settings.pilot_model_id
    resolved_timeout = timeout_seconds or pilot_settings.pilot_timeout_seconds
    resolved_model_id = response_model or pilot_settings.pilot_model_id

    if not resolved_url:
        raise PilotNotConfigured()

    if base_url:
        # Explicit base URL (Phase 2 multi-provider) - already validated by registry
        pass
    else:
        # Legacy mode - validate
        _validate_base_url(resolved_url)

    serialized_messages = _serialize_messages(messages)
    request_body = _build_upstream_request(api_key, serialized_messages, temperature, max_tokens, resolved_upstream)
    chat_url = f"{resolved_url.rstrip('/')}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(resolved_timeout),
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

    if response.status_code < 200 or response.status_code >= 300:
        if response.status_code in (401, 403):
            raise UpstreamAuthFailed()
        if response.status_code == 429:
            raise UpstreamRateLimited()
        if 300 <= response.status_code < 400:
            raise MalformedUpstreamResponse()
        raise UpstreamServerError()

    try:
        response_data = response.json()
    except (json.JSONDecodeError, ValueError):
        raise MalformedUpstreamResponse()

    if not isinstance(response_data, dict):
        raise MalformedUpstreamResponse()

    resp_id, choices, usage = _parse_upstream_response(response_data)

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
        "model": resolved_model_id,
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
            "provider": "",
            "latency_ms": 0,
            "estimated_krw": None,
            "request_id": f"b14req_{uuid.uuid4().hex[:12]}",
        },
    }
