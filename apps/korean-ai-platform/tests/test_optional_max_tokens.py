"""Shared B14 optional max_tokens contract (#3551).

Omitted generation limits must stay omitted end-to-end. Product-specific callers
may still provide an explicit bounded value; the existing explicit 1..4096
validation is intentionally unchanged in this PR.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.pilot.gateway import _validate_body
from app.pilot.kilo_provider import (
    KILO_NEMOTRON_MODEL_ID,
    KILO_NEMOTRON_UPSTREAM_MODEL,
    KILO_PROVIDER_ID,
)
from app.pilot.platform import call_platform_chat_completions
from app.pilot.provider import call_chat_completions
from app.pilot.schemas import PilotChatRequest


def _raw_request(**overrides):
    body = {
        "model": KILO_NEMOTRON_MODEL_ID,
        "messages": [{"role": "user", "content": "hello"}],
    }
    body.update(overrides)
    return body


def test_gateway_preserves_omitted_max_tokens_as_none() -> None:
    validated = _validate_body(_raw_request())
    assert validated["max_tokens"] is None

    explicit = _validate_body(_raw_request(max_tokens=2048))
    assert explicit["max_tokens"] == 2048


def test_schema_default_is_unspecified_not_300() -> None:
    request = PilotChatRequest(
        model=KILO_NEMOTRON_MODEL_ID,
        messages=[{"role": "user", "content": "hello"}],
    )
    assert request.max_tokens is None


@pytest.mark.asyncio
async def test_platform_adapter_omits_unspecified_max_tokens(monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "model": KILO_NEMOTRON_UPSTREAM_MODEL,
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            },
        )

    await call_platform_chat_completions(
        model_id=KILO_NEMOTRON_MODEL_ID,
        upstream_model=KILO_NEMOTRON_UPSTREAM_MODEL,
        provider="Kilo Gateway / NVIDIA",
        platform_provider_id=KILO_PROVIDER_ID,
        messages=[{"role": "user", "content": "hello"}],
        transport=httpx.MockTransport(handler),
    )

    assert "max_tokens" not in seen["body"]


@pytest.mark.asyncio
async def test_platform_adapter_preserves_explicit_max_tokens(monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "model": KILO_NEMOTRON_UPSTREAM_MODEL,
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            },
        )

    await call_platform_chat_completions(
        model_id=KILO_NEMOTRON_MODEL_ID,
        upstream_model=KILO_NEMOTRON_UPSTREAM_MODEL,
        provider="Kilo Gateway / NVIDIA",
        platform_provider_id=KILO_PROVIDER_ID,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=2048,
        transport=httpx.MockTransport(handler),
    )

    assert seen["body"]["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_legacy_byok_adapter_also_omits_unspecified_max_tokens() -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "model": "synthetic-model",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            },
        )

    await call_chat_completions(
        api_key="test-key-not-secret",
        messages=[{"role": "user", "content": "hello"}],
        transport=httpx.MockTransport(handler),
        base_url="https://provider.example",
        upstream_model="synthetic-model",
        timeout_seconds=10,
        response_model="synthetic-model",
    )

    assert "max_tokens" not in seen["body"]
