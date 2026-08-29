from __future__ import annotations

import json

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.catalog import CATALOG_BY_ID
from app.pilot.errors import NoSafeRoute, PilotNotConfigured
from app.pilot.opencode_zen_provider import (
    MUSE_SPARK_HIGH_MODEL_ID,
    MUSE_SPARK_UPSTREAM_MODEL,
    OPENCODE_ZEN_BASE_ORIGIN,
    OPENCODE_ZEN_CREDENTIAL_BINDING,
    OPENCODE_ZEN_PROVIDER_ID,
)
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.router_core import resolve_manual_route

_SYNTH_KEY = "oc_live_abcdefghijklmnopqrstuvwxyz123456"


class _Chunk(httpx.AsyncByteStream):
    def __init__(self, data: bytes):
        self.data = data

    async def __aiter__(self):
        for index in range(0, len(self.data), 31):
            yield self.data[index:index + 31]

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(OPENCODE_ZEN_CREDENTIAL_BINDING, raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)


def test_high_model_and_provider_are_registered_with_responses_protocol():
    spec = get_platform_provider(OPENCODE_ZEN_PROVIDER_ID)
    assert spec is not None
    assert spec.base_origin == OPENCODE_ZEN_BASE_ORIGIN == "https://opencode.ai/zen/v1"
    assert spec.allowed_hosts == ("opencode.ai",)
    assert spec.credential_binding_name == "OPENCODE_ZEN_API_KEY"
    assert spec.api_style == "responses"

    model = CATALOG_BY_ID[MUSE_SPARK_HIGH_MODEL_ID]
    assert model.upstream_model == MUSE_SPARK_UPSTREAM_MODEL == "muse-spark-1.2-contributor-free"
    assert model.platform_provider_id == OPENCODE_ZEN_PROVIDER_ID
    assert model.credential_source == "platform_secret"
    assert model.input_price_usd_per_1m == 0.0
    assert model.output_price_usd_per_1m == 0.0
    assert "free" in model.capabilities


def test_high_manual_route_fails_closed_without_opencode_key():
    with pytest.raises(NoSafeRoute) as info:
        resolve_manual_route(MUSE_SPARK_HIGH_MODEL_ID)
    assert info.value.reason_code == "provider_secret_missing"
    assert info.value.upstream_called is False


def test_high_manual_route_uses_exact_model_when_key_present(monkeypatch):
    monkeypatch.setenv(OPENCODE_ZEN_CREDENTIAL_BINDING, _SYNTH_KEY)
    decision = resolve_manual_route(MUSE_SPARK_HIGH_MODEL_ID)
    assert decision.selected_model == MUSE_SPARK_HIGH_MODEL_ID
    assert decision.selected_upstream_model == MUSE_SPARK_UPSTREAM_MODEL
    assert decision.selected_provider == "OpenCode Zen / Meta"
    assert decision.platform_provider_id == OPENCODE_ZEN_PROVIDER_ID
    assert decision.credential_source == "platform_secret"


@pytest.mark.asyncio
async def test_responses_completed_call_uses_fixed_endpoint_and_normalizes(monkeypatch):
    monkeypatch.setenv(OPENCODE_ZEN_CREDENTIAL_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "model": MUSE_SPARK_UPSTREAM_MODEL,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "한국어 응답"}],
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            },
        )

    result = await plat.call_platform_chat_completions(
        model_id=MUSE_SPARK_HIGH_MODEL_ID,
        upstream_model=MUSE_SPARK_UPSTREAM_MODEL,
        provider="OpenCode Zen / Meta",
        platform_provider_id=OPENCODE_ZEN_PROVIDER_ID,
        messages=[
            {"role": "system", "content": "안전하게 답해라"},
            {"role": "user", "content": "질문"},
        ],
        max_tokens=300,
        transport=httpx.MockTransport(handler),
    )
    assert captured["url"] == "https://opencode.ai/zen/v1/responses"
    assert captured["auth"] == f"Bearer {_SYNTH_KEY}"
    assert captured["body"] == {
        "model": MUSE_SPARK_UPSTREAM_MODEL,
        "input": [{"role": "user", "content": "질문"}],
        "instructions": "안전하게 답해라",
        "max_output_tokens": 300,
    }
    assert result["choices"][0]["message"]["content"] == "한국어 응답"
    assert result["usage"] == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    assert result["_actual_response_model"] == MUSE_SPARK_UPSTREAM_MODEL
    assert _SYNTH_KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_responses_missing_key_makes_zero_network_calls(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        raise AssertionError("missing secret must fail before network")

    with pytest.raises(PilotNotConfigured):
        await plat.call_platform_chat_completions(
            model_id=MUSE_SPARK_HIGH_MODEL_ID,
            upstream_model=MUSE_SPARK_UPSTREAM_MODEL,
            provider="OpenCode Zen / Meta",
            platform_provider_id=OPENCODE_ZEN_PROVIDER_ID,
            messages=[{"role": "user", "content": "질문"}],
            transport=httpx.MockTransport(handler),
        )
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_responses_stream_normalizes_delta_usage_and_done(monkeypatch):
    monkeypatch.setenv(OPENCODE_ZEN_CREDENTIAL_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    captured = {}
    frames = (
        'data: {"type":"response.created","response":{"id":"resp_s","model":"muse-spark-1.2-contributor-free"}}\n\n'
        'data: {"type":"response.output_text.delta","response_id":"resp_s","delta":"안녕"}\n\n'
        'data: {"type":"response.output_text.delta","response_id":"resp_s","delta":"하세요"}\n\n'
        'data: {"type":"response.completed","response":{"id":"resp_s","model":"muse-spark-1.2-contributor-free","status":"completed","output":[],"usage":{"input_tokens":5,"output_tokens":2,"total_tokens":7}}}\n\n'
    ).encode()

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, stream=_Chunk(frames))

    events = [
        event
        async for event in plat.stream_platform_chat_completions(
            model_id=MUSE_SPARK_HIGH_MODEL_ID,
            upstream_model=MUSE_SPARK_UPSTREAM_MODEL,
            provider="OpenCode Zen / Meta",
            platform_provider_id=OPENCODE_ZEN_PROVIDER_ID,
            messages=[{"role": "user", "content": "질문"}],
            max_tokens=128,
            transport=httpx.MockTransport(handler),
        )
    ]
    assert captured["url"] == "https://opencode.ai/zen/v1/responses"
    assert captured["body"]["stream"] is True
    assert "temperature" not in captured["body"]
    assert "".join(event.delta_content or "" for event in events) == "안녕하세요"
    assert events[-1].done is True
    terminal = next(event for event in events if event.finish_reason == "stop")
    assert terminal.usage is not None
    assert terminal.usage.total_tokens == 7
    assert all(_SYNTH_KEY not in repr(event) for event in events)


def test_poolside_and_opencode_secret_bindings_are_distinct():
    poolside = get_platform_provider("poolside")
    opencode = get_platform_provider(OPENCODE_ZEN_PROVIDER_ID)
    assert poolside is not None and opencode is not None
    assert poolside.credential_binding_name == "POOLSIDE_API_KEY"
    assert opencode.credential_binding_name == "OPENCODE_ZEN_API_KEY"
    assert poolside.credential_binding_name != opencode.credential_binding_name
    assert poolside.allowed_hosts != opencode.allowed_hosts
