"""#3977 exact-model native parameter transport contracts (no live credentials)."""
import json
from pathlib import Path

import httpx
import pytest

from app.pilot.gateway import _validate_body, _InvalidBody
from app.pilot.model_native_parameters import (
    UnsupportedModelParameter,
    validate_native_parameters,
)
from app.pilot.platform import call_platform_chat_completions, stream_platform_chat_completions
from app.pilot.schemas import PilotChatRequest
from app.pilot.provider import _build_upstream_request


def request(model, **params):
    return _validate_body({
        "model": model,
        "messages": [{"role": "user", "content": "hello"}],
        **params,
    })


@pytest.mark.parametrize("model", [
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.5-flash-lite",
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-31b-it",
    "sensenova/sensenova-6.8-flash-lite",
    "poolside/laguna-s-2.1",
    "inception/mercury-2.5",
    "atria/Atria-Dawn-Preview",
    "agnes-ai/agnes-3.0-flash",
    "experiential/qwen3.8-flash-next-uncensored",
    "kira/qwen3.8-flash-free",
])
def test_all_eleven_registered_models_omit_hidden_defaults(model):
    b = request(model)
    assert b["temperature"] is None
    assert b["max_tokens"] is None
    assert b["model_parameters"] == {}


def test_model_native_google_reasoning_only_when_explicit():
    assert request("google/gemini-3.1-flash-lite", reasoning_effort="low")["model_parameters"] == {"reasoning_effort": "low"}
    assert request("google/gemini-3.5-flash-lite", reasoning_effort="minimal")["model_parameters"] == {"reasoning_effort": "minimal"}
    with pytest.raises(_InvalidBody, match="reasoning_effort"):
        request("google/gemini-3.1-flash-lite", reasoning_effort="none")


def test_unknown_native_field_is_not_silently_discarded():
    with pytest.raises(UnsupportedModelParameter, match="unsupported model-native fields"):
        validate_native_parameters("google/gemini-3.1-flash-lite", {"thinking": {"type": "enabled"}})


def test_native_sensenova_exact_documented_sampling():
    native = request(
        "sensenova/sensenova-6.8-flash-lite",
        top_p=0.95, top_k=20, min_p=0.0,
        presence_penalty=1.5, repetition_penalty=1.0,
    )["model_parameters"]
    assert native == {
        "top_p": 0.95, "top_k": 20, "min_p": 0.0,
        "presence_penalty": 1.5, "repetition_penalty": 1.0,
    }


@pytest.mark.parametrize("model", [
    "google/gemma-4-26b-a4b-it",
    "poolside/laguna-s-2.1",
    "experiential/qwen3.8-flash-next-uncensored",
    "kira/qwen3.8-flash-free",
    "inception/mercury-2.5",
    "unknown/vendor-model",
])
def test_unverified_reasoning_field_is_rejected_before_egress(model):
    with pytest.raises(_InvalidBody, match="not documented"):
        request(model, reasoning_effort="high")


@pytest.mark.parametrize("params", [
    {"top_p": 1.5}, {"top_k": 0}, {"min_p": -0.1},
    {"presence_penalty": 9}, {"repetition_penalty": 0},
    {"top_p": True}, {"top_p": float("nan")},
])
def test_invalid_native_values_are_rejected(params):
    with pytest.raises(_InvalidBody):
        request("sensenova/sensenova-6.8-flash-lite", **params)


def test_no_global_4096_model_ceiling_and_explicit_values_unchanged():
    assert request("google/gemini-3.1-flash-lite", max_tokens=65536)["max_tokens"] == 65536
    assert request("google/gemini-3.1-flash-lite", temperature=1.0)["temperature"] == 1.0
    with pytest.raises(_InvalidBody):
        request("google/gemini-3.1-flash-lite", max_tokens=2147483648)
    assert PilotChatRequest(model="x", messages=[{"role": "user", "content": "hi"}]).temperature is None
    assert _build_upstream_request("k", [{"role": "user", "content": "hi"}], None, None, "exact") == {
        "model": "exact", "messages": [{"role": "user", "content": "hi"}],
    }


@pytest.fixture
def google_native_transport(monkeypatch):
    from app.pilot import platform_secrets as ps
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    # Only mock transport, no real Provider or credentials.
    monkeypatch.setattr(ps, "resolve_secret", lambda spec: "synthetic-placeholder-for-mock-123456")
    # Routing tests use a test-only provider rather than altering live registry.
    return ps


@pytest.mark.asyncio
async def test_platform_completed_exact_native_parameters(google_native_transport, monkeypatch):
    seen = {}
    from app.pilot import platform as plt
    monkeypatch.setattr(plt, "_request_headers", lambda spec, model_id=None: {"Content-Type": "application/json"})
    async def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "id": "synthetic", "model": "gemini-3.1-flash-lite",
            "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })
    await call_platform_chat_completions(
        model_id="google/gemini-3.1-flash-lite",
        upstream_model="gemini-3.1-flash-lite",
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        model_parameters={"reasoning_effort": "low"},
        max_tokens=65536,
        transport=httpx.MockTransport(handler),
    )
    assert seen["body"]["model"] == "gemini-3.1-flash-lite"
    assert seen["body"]["reasoning_effort"] == "low"
    assert seen["body"]["max_tokens"] == 65536
    assert "temperature" not in seen["body"]


@pytest.mark.asyncio
async def test_platform_rejects_unsupported_before_upstream(monkeypatch):
    from app.pilot import platform as plt
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plt, "_request_headers", lambda spec, model_id=None: {"Content-Type": "application/json"})
    async def handler(req):
        raise AssertionError("should not call unsupported upstream")
    with pytest.raises(Exception, match="not documented"):
        await call_platform_chat_completions(
            model_id="experiential/qwen3.8-flash-next-uncensored",
            upstream_model="qwen3.8-flash-next-uncensored",
            provider="ExLab",
            platform_provider_id="experiential",
            messages=[{"role": "user", "content": "hi"}],
            model_parameters={"reasoning_effort": "xhigh"},
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_platform_stream_exact_native_parameter_parity(monkeypatch):
    from app.pilot import platform as plt
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plt, "_request_headers", lambda spec, model_id=None: {"Content-Type": "application/json"})
    seen = {}
    async def handler(req):
        seen["body"] = json.loads(req.content)
        sse = (
            'data: {"id":"synthetic","model":"gemini-3.1-flash-lite","choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"), headers={"content-type": "text/event-stream"})

    events = []
    async for event in stream_platform_chat_completions(
        model_id="google/gemini-3.1-flash-lite",
        upstream_model="gemini-3.1-flash-lite",
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        model_parameters={"reasoning_effort": "high"},
        transport=httpx.MockTransport(handler),
    ):
        events.append(event)
    assert seen["body"]["model"] == "gemini-3.1-flash-lite"
    assert seen["body"]["reasoning_effort"] == "high"
    assert seen["body"]["stream"] is True
    assert "temperature" not in seen["body"]
    assert "max_tokens" not in seen["body"]
    assert any(getattr(e, "delta_content", None) == "ok" for e in events)


def test_user_surfaces_do_not_synthesize_02_or_fixed_budget():
    base = Path(__file__).resolve().parents[1]
    start = (base / "static/start.js").read_text(encoding="utf8")
    workspace = (base / "static/workspace.js").read_text(encoding="utf8")
    pilot = (base / "templates/pilot.html").read_text(encoding="utf8")
    assert "temperature: atriaPreview" not in start
    assert "max_tokens: atriaPreview" not in start
    assert "temperature: 0.2" not in workspace
    assert "maxTokens: 512" not in workspace
    assert 'name="temperature" min="0" max="2" step="0.1" value=""' in pilot
