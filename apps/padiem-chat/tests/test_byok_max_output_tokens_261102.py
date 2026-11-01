"""PADIEM Custom BYOK output-token budget and truncation-notice contracts.

The LIMITS_AUDIT_2 finding (docs/research/LIMITS_AUDIT_2_20261102.md, the
``byok_client.py:44`` row) left the Anthropic BYOK output budget pinned at
4,096 with the per-model output ceiling unverified. The budget is now: the
single ``PADIEM_BYOK_MAX_OUTPUT_TOKENS`` operator override when set to a
valid positive integer, otherwise the documented model-family output limit
when known, otherwise the conservative historical default. Every wire also
marks a length-limited answer with a visible truncation notice instead of
ending silently. All wires run over ``httpx.MockTransport``; no live
provider call is made anywhere in this module.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.byok_client import (
    ANTHROPIC_MAX_TOKENS,
    MAX_OUTPUT_TOKENS_ENV,
    TRUNCATION_NOTICE,
    _anthropic_max_tokens,
)
from app.byok_credentials import CUSTOM_PROVIDERS, resolve_custom_selection
from test_5002_byok_product_e2e import DEFAULT_ANSWER, ProviderRecorder
from test_5121_multi_provider_byok import (
    API_KEY,
    client_for,
    data,
    named,
    sse,
)

STREAM_ANSWER = "길게 답변"


# ---------------------------------------------------------------------------
# Wire fixtures (same shapes as test_5121_multi_provider_byok, with the
# provider's own length-limit end reason made explicit)
# ---------------------------------------------------------------------------


def anthropic_json_handler(*, stop_reason=None):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": DEFAULT_ANSWER}],
                "stop_reason": stop_reason,
                "usage": {"input_tokens": 11, "output_tokens": 4},
            },
        )

    return handler


def anthropic_stream_handler(*, stop_reason=None):
    delta = {"stop_reason": stop_reason} if stop_reason else {}

    def handler(_request):
        return sse(
            named(
                "message_start",
                {"type": "message_start", "message": {"usage": {"input_tokens": 11}}},
            ),
            named(
                "content_block_delta",
                {"type": "content_block_delta",
                 "delta": {"type": "text_delta", "text": DEFAULT_ANSWER}},
            ),
            named(
                "message_delta",
                {"type": "message_delta", "delta": delta, "usage": {"output_tokens": 4}},
            ),
            named("message_stop", {"type": "message_stop"}),
        )

    return handler


def openai_json_handler(*, finish_reason=None):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {"message": {"content": DEFAULT_ANSWER},
                     "finish_reason": finish_reason}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )

    return handler


def openai_stream_handler(*, finish_reason="stop"):
    def handler(_request):
        blocks = [
            data({"model": "gpt-4o-mini", "choices": [{"delta": {"content": "길게 "}}]}),
            data({"model": "gpt-4o-mini", "choices": [{"delta": {"content": "답변"}}]}),
            data({
                "model": "gpt-4o-mini",
                "choices": [{"delta": {}, "finish_reason": finish_reason}],
            }),
            "data: [DONE]\n\n",
        ]
        return sse(*blocks)

    return handler


def gemini_json_handler(*, finish_reason="STOP"):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": DEFAULT_ANSWER}]},
                     "finishReason": finish_reason}
                ],
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 5,
                },
            },
        )

    return handler


def gemini_stream_handler(*, finish_reason="STOP"):
    def handler(_request):
        return sse(
            data({"candidates": [{"content": {"parts": [{"text": "길게 "}]}}]}),
            data({
                "candidates": [
                    {"content": {"parts": [{"text": "답변"}]},
                     "finishReason": finish_reason}
                ],
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 5,
                },
            }),
        )

    return handler


async def complete_wire(recorder, provider, model, *, stream=False):
    client = client_for(recorder)
    return await client.complete(
        selection=resolve_custom_selection(provider, model),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS[provider].base_origin,
        messages=[{"role": "user", "content": "안녕하세요"}],
        stream=stream,
    )


# ---------------------------------------------------------------------------
# Output budget: documented model limit > env override ordering
# ---------------------------------------------------------------------------


def test_truncation_notice_names_the_interruption():
    assert TRUNCATION_NOTICE.startswith("\n\n")
    assert "답변이 길어 중간에 끊겼습니다" in TRUNCATION_NOTICE


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-4-5", 64_000),
        ("claude-sonnet-4-5-20250929", 64_000),
        ("claude-haiku-4-5-20251001", 64_000),
        ("claude-opus-4-1-20250805", 32_000),
        ("claude-fable-5", 128_000),
        ("claude-mythos-5", 128_000),
        ("claude-opus-5", 128_000),
        ("claude-sonnet-5", 128_000),
    ],
)
def test_documented_model_families_use_the_official_output_limit(model, expected):
    assert _anthropic_max_tokens(model) == expected


def test_undocumented_models_keep_the_conservative_default():
    # Legacy families the current docs.claude.com tables no longer publish
    # (checked 2026-11-02) stay unverified, so they keep the historical budget.
    assert _anthropic_max_tokens("claude-3-5-sonnet-latest") == ANTHROPIC_MAX_TOKENS
    assert _anthropic_max_tokens("claude-sonnet-4-20250514") == ANTHROPIC_MAX_TOKENS
    assert _anthropic_max_tokens("claude-2.1") == ANTHROPIC_MAX_TOKENS
    assert _anthropic_max_tokens("totally-unknown-model") == ANTHROPIC_MAX_TOKENS
    assert ANTHROPIC_MAX_TOKENS == 4096


def test_env_override_replaces_every_computed_budget(monkeypatch):
    monkeypatch.setenv(MAX_OUTPUT_TOKENS_ENV, "16384")
    assert _anthropic_max_tokens("claude-sonnet-4-5-20250929") == 16384
    assert _anthropic_max_tokens("totally-unknown-model") == 16384


@pytest.mark.parametrize("raw", ["", "   ", "abc", "16.5", "0", "-5", "4096 tokens"])
def test_invalid_env_values_change_nothing(monkeypatch, raw):
    monkeypatch.setenv(MAX_OUTPUT_TOKENS_ENV, raw)
    assert _anthropic_max_tokens("claude-sonnet-4-5") == 64_000
    assert _anthropic_max_tokens("totally-unknown-model") == ANTHROPIC_MAX_TOKENS


@pytest.mark.asyncio
async def test_anthropic_request_carries_the_model_specific_budget():
    recorder = ProviderRecorder(anthropic_json_handler())
    await complete_wire(recorder, "anthropic", "claude-haiku-4-5-20251001")
    assert recorder.sent(0)["max_tokens"] == 64_000


@pytest.mark.asyncio
async def test_undocumented_model_on_the_wire_keeps_the_default():
    recorder = ProviderRecorder(anthropic_json_handler())
    await complete_wire(recorder, "anthropic", "claude-3-5-sonnet-latest")
    assert recorder.sent(0)["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_env_override_reaches_the_wire(monkeypatch):
    monkeypatch.setenv(MAX_OUTPUT_TOKENS_ENV, "16384")
    recorder = ProviderRecorder(anthropic_json_handler())
    await complete_wire(recorder, "anthropic", "claude-haiku-4-5-20251001")
    assert recorder.sent(0)["max_tokens"] == 16384


# ---------------------------------------------------------------------------
# Length-limited answers end with a visible notice, every wire, both modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_length_finish_reason_appends_the_notice():
    recorder = ProviderRecorder(openai_json_handler(finish_reason="length"))
    result = await complete_wire(recorder, "openai", "gpt-4o-mini")
    assert result["answer"] == DEFAULT_ANSWER + TRUNCATION_NOTICE


@pytest.mark.asyncio
async def test_openai_stop_finish_reason_stays_unmarked():
    recorder = ProviderRecorder(openai_json_handler(finish_reason="stop"))
    result = await complete_wire(recorder, "openai", "gpt-4o-mini")
    assert result["answer"] == DEFAULT_ANSWER


@pytest.mark.asyncio
async def test_openai_stream_length_finish_reason_appends_the_notice():
    recorder = ProviderRecorder(openai_stream_handler(finish_reason="length"))
    result = await complete_wire(recorder, "openai", "gpt-4o-mini", stream=True)
    assert result["answer"] == STREAM_ANSWER + TRUNCATION_NOTICE


@pytest.mark.asyncio
async def test_openai_stream_stop_finish_reason_stays_unmarked():
    recorder = ProviderRecorder(openai_stream_handler(finish_reason="stop"))
    result = await complete_wire(recorder, "openai", "gpt-4o-mini", stream=True)
    assert result["answer"] == STREAM_ANSWER


@pytest.mark.asyncio
async def test_anthropic_max_tokens_stop_reason_appends_the_notice():
    recorder = ProviderRecorder(anthropic_json_handler(stop_reason="max_tokens"))
    result = await complete_wire(recorder, "anthropic", "claude-3-5-sonnet-latest")
    assert result["answer"] == DEFAULT_ANSWER + TRUNCATION_NOTICE


@pytest.mark.asyncio
async def test_anthropic_end_turn_stays_unmarked():
    recorder = ProviderRecorder(anthropic_json_handler(stop_reason="end_turn"))
    result = await complete_wire(recorder, "anthropic", "claude-3-5-sonnet-latest")
    assert result["answer"] == DEFAULT_ANSWER


@pytest.mark.asyncio
async def test_anthropic_stream_max_tokens_stop_reason_appends_the_notice():
    recorder = ProviderRecorder(anthropic_stream_handler(stop_reason="max_tokens"))
    result = await complete_wire(recorder, "anthropic", "claude-3-5-sonnet-latest", stream=True)
    assert result["answer"] == DEFAULT_ANSWER + TRUNCATION_NOTICE


@pytest.mark.asyncio
async def test_anthropic_stream_end_turn_stays_unmarked():
    recorder = ProviderRecorder(anthropic_stream_handler(stop_reason="end_turn"))
    result = await complete_wire(recorder, "anthropic", "claude-3-5-sonnet-latest", stream=True)
    assert result["answer"] == DEFAULT_ANSWER


@pytest.mark.asyncio
async def test_gemini_max_tokens_finish_reason_appends_the_notice():
    recorder = ProviderRecorder(gemini_json_handler(finish_reason="MAX_TOKENS"))
    result = await complete_wire(recorder, "gemini", "gemini-2.0-flash")
    assert result["answer"] == DEFAULT_ANSWER + TRUNCATION_NOTICE


@pytest.mark.asyncio
async def test_gemini_stop_finish_reason_stays_unmarked():
    recorder = ProviderRecorder(gemini_json_handler(finish_reason="STOP"))
    result = await complete_wire(recorder, "gemini", "gemini-2.0-flash")
    assert result["answer"] == DEFAULT_ANSWER


@pytest.mark.asyncio
async def test_gemini_stream_max_tokens_finish_reason_appends_the_notice():
    recorder = ProviderRecorder(gemini_stream_handler(finish_reason="MAX_TOKENS"))
    result = await complete_wire(recorder, "gemini", "gemini-2.0-flash", stream=True)
    assert result["answer"] == STREAM_ANSWER + TRUNCATION_NOTICE


@pytest.mark.asyncio
async def test_gemini_stream_stop_finish_reason_stays_unmarked():
    recorder = ProviderRecorder(gemini_stream_handler(finish_reason="STOP"))
    result = await complete_wire(recorder, "gemini", "gemini-2.0-flash", stream=True)
    assert result["answer"] == STREAM_ANSWER
