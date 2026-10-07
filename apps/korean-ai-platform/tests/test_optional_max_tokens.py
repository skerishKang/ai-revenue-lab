"""Shared B14 optional max_tokens contract (#3551, ceiling revised #3553).

Omitted generation limits must stay omitted end-to-end. Product-specific callers
may still provide an explicit bounded value. The explicit request ceiling is now
the per-model maximum output budget (``model_output_caps.MAX_REQUEST_TOKENS``)
rather than the old blanket ``4096`` that starved reasoning models.

Owner policy 2026-10-07: the value that reaches upstream is normalized to the
*selected* model's own cap (``effective_max_tokens``). An over-limit request is
clamped, never rejected, so a caller asking for more than a route can produce
still gets a bounded successful call.
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
from app.pilot.model_output_caps import MAX_REQUEST_TOKENS, effective_max_tokens
from app.pilot.platform import call_platform_chat_completions
from app.pilot.provider import call_chat_completions
from app.pilot.schemas import PilotChatRequest

AGNES_MODEL_ID = "agnes-ai/agnes-3.0-flash"
POOLSIDE_MODEL_ID = "poolside/laguna-s-2.1"
POOLSIDE_CAP = 32768


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


# ---------------------------------------------------------------------------
# Per-selected-model normalization (owner policy 2026-10-07)
# ---------------------------------------------------------------------------
def test_effective_max_tokens_preserves_omitted() -> None:
    assert effective_max_tokens(POOLSIDE_MODEL_ID, None) is None
    assert effective_max_tokens(KILO_NEMOTRON_MODEL_ID, None) is None


def test_effective_max_tokens_passes_values_within_the_model_cap() -> None:
    assert effective_max_tokens(POOLSIDE_MODEL_ID, 2048) == 2048
    assert effective_max_tokens(POOLSIDE_MODEL_ID, POOLSIDE_CAP) == POOLSIDE_CAP


def test_effective_max_tokens_clamps_above_the_model_cap() -> None:
    assert effective_max_tokens(POOLSIDE_MODEL_ID, MAX_REQUEST_TOKENS) == POOLSIDE_CAP
    assert effective_max_tokens(KILO_NEMOTRON_MODEL_ID, 999999) == 65536


def test_effective_max_tokens_uses_the_global_bound_when_unadvertised() -> None:
    # agnes advertises no cap, and an unregistered id has no entry either, so the
    # forwarded value is bounded by the largest budget any registered route uses.
    assert effective_max_tokens(AGNES_MODEL_ID, 999999) == MAX_REQUEST_TOKENS
    assert effective_max_tokens("not/registered", 999999) == MAX_REQUEST_TOKENS


def _install_recording_platform(monkeypatch, *, fail_first: bool = False) -> list[dict]:
    """Install live mode + a recording platform dispatch (no network call)."""
    from app.pilot import platform as plat
    from app.pilot.b14_runtime_config import runtime_config as rcfg
    from app.pilot.errors import UpstreamRateLimited

    monkeypatch.setenv("PADIEM_AGNES_API_KEY", "sk-unit-agnes-0123456789")
    monkeypatch.setenv("PADIEM_POOLSIDE_API_KEY", "sk-unit-poolside-0123456789")
    monkeypatch.setattr(rcfg, "provider_mode", "live")

    calls: list[dict] = []

    async def fake(
        *,
        model_id,
        upstream_model,
        provider,
        platform_provider_id,
        messages,
        temperature=0.2,
        max_tokens=300,
        transport=None,
    ):
        calls.append({"model_id": model_id, "max_tokens": max_tokens})
        if fail_first and len(calls) == 1:
            raise UpstreamRateLimited()
        return {
            "id": "cmpl-test",
            "object": "chat.completion",
            "model": upstream_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            "_live": True,
            "_actual_response_model": upstream_model,
        }

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    return calls


def test_gateway_clamps_an_explicit_model_request_at_dispatch(client, monkeypatch) -> None:
    """A caller may still ask for 131072; the route's own cap is what is sent."""
    calls = _install_recording_platform(monkeypatch)

    resp = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": POOLSIDE_MODEL_ID,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": MAX_REQUEST_TOKENS,
        },
    )

    assert resp.status_code == 200
    assert calls == [{"model_id": POOLSIDE_MODEL_ID, "max_tokens": POOLSIDE_CAP}]


def test_gateway_clamps_per_candidate_on_the_auto_chain(client, monkeypatch) -> None:
    """b14/auto is an internal fixed chain (#2677), not a product selector.

    The clamp follows the candidate that actually answers, so the second
    position's smaller cap applies only to that attempt instead of narrowing the
    first attempt's budget.
    """
    calls = _install_recording_platform(monkeypatch, fail_first=True)

    resp = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": "b14/auto",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": MAX_REQUEST_TOKENS,
            "business14": {"max_attempts": 2},
        },
    )

    assert resp.status_code == 200
    assert calls == [
        {"model_id": AGNES_MODEL_ID, "max_tokens": MAX_REQUEST_TOKENS},
        {"model_id": POOLSIDE_MODEL_ID, "max_tokens": POOLSIDE_CAP},
    ]

