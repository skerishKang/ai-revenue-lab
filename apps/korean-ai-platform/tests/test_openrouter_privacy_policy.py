from __future__ import annotations

import json

import httpx
import pytest

from app.pilot.openrouter_config import openrouter_config
from app.pilot.schemas import ChatMessage, PilotChatRequest


GEMINI = "google/gemini-2.5-flash"
FREE_ROUTE_MODEL = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
MESSAGES = [{"role": "user", "content": "안녕하세요"}]
PRIVACY_POLICY = {"data_collection": "deny", "zdr": True}
FREE_ROUTE_POLICY = {"max_price": {"prompt": 0, "completion": 0}}


@pytest.fixture(autouse=True)
def _gemini_catalog_entry(monkeypatch):
    """Reinstall the deleted Gemini route for this policy contract.

    Decision #1933 removed Gemini from the single-route Kilo Gateway catalog,
    but its P5-approved hard privacy policy stays pinned in production code.
    These tests restore the historical entry so the policy assertions stay
    genuinely validated.
    """
    import app.pilot.catalog as cat
    from app.pilot.catalog import CatalogModel

    original_models = cat.CATALOG_MODELS
    original_by_id = cat.CATALOG_BY_ID
    gemini = CatalogModel(
        model_id=GEMINI,
        upstream_model=GEMINI,
        display_name="Google: Gemini 2.5 Flash",
        provider="Google",
        provider_type="external",
        input_price_usd_per_1m=0.30,
        output_price_usd_per_1m=2.50,
        currency="usd",
        context_window=1048576,
        korean_score=5,
        latency_ms=750,
        capabilities=frozenset({"chat", "image", "long_context", "coding"}),
        region="외부",
        sort_order=10,
        credential_source="openrouter",
        platform_provider_id="",
    )
    cat.CATALOG_MODELS = [*original_models, gemini]
    cat.CATALOG_BY_ID = {m.model_id: m for m in cat.CATALOG_MODELS}
    try:
        yield
    finally:
        cat.CATALOG_MODELS = original_models
        cat.CATALOG_BY_ID = original_by_id


def _enable_fixture_live_mode(monkeypatch) -> None:
    monkeypatch.setattr(openrouter_config, "provider_mode", "live")
    monkeypatch.setattr(openrouter_config, "api_key", "fixture_value_not_a_secret_123456")
    monkeypatch.setattr(openrouter_config, "base_url", "https://openrouter.ai/api/v1")


def _completion_response(model: str) -> dict:
    return {
        "id": "or_fixture_completion",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "안녕하세요."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }


def _stream_bytes(model: str) -> bytes:
    first = {
        "id": "or_fixture_stream",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": "첫 토큰"},
                "finish_reason": None,
            }
        ],
    }
    final = {
        "id": "or_fixture_stream",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }
    return (
        b"data: "
        + json.dumps(first).encode("utf-8")
        + b"\n\n"
        + b"data: "
        + json.dumps(final).encode("utf-8")
        + b"\n\n"
        + b"data: [DONE]\n\n"
    )


def test_provider_policy_is_exact_and_does_not_spread_to_other_paid_models():
    assert build_openrouter_provider_policy(GEMINI) == PRIVACY_POLICY
    assert build_openrouter_provider_policy(FREE_ROUTE_MODEL) == FREE_ROUTE_POLICY
    assert build_openrouter_provider_policy("deepseek/deepseek-chat") is None


def test_caller_schema_cannot_override_openrouter_provider_privacy_policy():
    with pytest.raises(TypeError):
        PilotChatRequest(
            model=GEMINI,
            messages=[ChatMessage(role="user", content="안녕하세요")],
            provider={"data_collection": "allow", "zdr": False},  # type: ignore[call-arg]
        )


@pytest.mark.asyncio
async def test_completed_gemini_request_always_sends_hard_privacy_policy(monkeypatch):
    _enable_fixture_live_mode(monkeypatch)
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_completion_response(GEMINI))

    result = await call_openrouter_chat_completions(
        messages=MESSAGES,
        temperature=0.2,
        max_tokens=256,
        model_id=GEMINI,
        upstream_model=GEMINI,
        provider="Google",
        transport=httpx.MockTransport(handler),
    )

    assert result["model"] == GEMINI
    assert len(seen) == 1
    assert seen[0]["model"] == GEMINI
    assert seen[0]["provider"] == PRIVACY_POLICY


@pytest.mark.asyncio
async def test_streaming_gemini_request_always_sends_same_hard_privacy_policy(monkeypatch):
    _enable_fixture_live_mode(monkeypatch)
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_stream_bytes(GEMINI),
        )

    events = [
        event
        async for event in stream_openrouter_chat_completions(
            messages=MESSAGES,
            temperature=0.2,
            max_tokens=256,
            model_id=GEMINI,
            upstream_model=GEMINI,
            provider="Google",
            transport=httpx.MockTransport(handler),
        )
    ]

    assert len(seen) == 1
    assert seen[0]["model"] == GEMINI
    assert seen[0]["stream"] is True
    assert seen[0]["provider"] == PRIVACY_POLICY
    assert [event.delta_content for event in events if event.delta_content] == ["첫 토큰"]
    assert events[-1].done is True
