"""#6838: B14 decides reasoning effort per model; the public registry names no value."""
from __future__ import annotations

import json

import httpx
import pytest

from app.pilot import platform
from app.pilot import reasoning_policy as policy
from app.pilot.call_ledger import CallLedgerError, LedgerDraft, new_log_id
from app.pilot.model_registry_file import read_registry

from _pilot_lane_paths import chat_surface

# The ledger records the endpoint the gateway mounted, so the suite reads that
# surface from the router instead of writing the path (it is the same kind of
# deployment value as a model id).
ENDPOINT = chat_surface()

_REGISTRY = read_registry()
_CANDIDATES = [
    model for model in _REGISTRY["models"]
    if model["enabled"]
    and _REGISTRY["providers"][model["provider_id"]]["enabled"]
    and model["provider_id"] != "opencode-go"
]


def _ledger() -> LedgerDraft:
    return LedgerDraft(
        log_id=new_log_id(), request_id="b14req_reasoning",
        endpoint=ENDPOINT, protocol="unknown",
        streaming=False, requested_model_id=None,
        started_at="2026-11-05T00:00:00Z",
    )


def _kwargs(model, transport):
    return {
        "model_id": model["id"],
        "upstream_model": model["upstream_model"],
        "provider": model["provider_name"],
        "platform_provider_id": model["provider_id"],
        "messages": [{"role": "user", "content": "fixture question"}],
        "transport": transport,
    }


def _live(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(
        platform, "_request_headers",
        lambda spec, model_id=None: {"Content-Type": "application/json"},
    )


def _ok(upstream):
    def handler(request):
        return httpx.Response(200, json={
            "id": "synthetic", "model": upstream,
            "choices": [{
                "message": {"role": "assistant", "content": "fixture answer"},
                "finish_reason": "stop",
            }],
        })
    return handler


def test_supported_default_is_the_deepest_accepted_level():
    assert policy.normalize_policy({"supported": True, "values": ["low", "high"]}) == (
        True, ("low", "high"), "high", False,
    )


def test_an_explicit_default_is_honoured():
    assert policy.normalize_policy(
        {"supported": True, "values": ["low", "high"], "default": "low"}
    ) == (True, ("low", "high"), "low", False)


def test_a_model_without_the_block_is_unsupported():
    assert policy.normalize_policy({}) == (False, (), None, False)


def test_an_unsupported_model_may_not_declare_values():
    with pytest.raises(policy.ReasoningPolicyError):
        policy.normalize_policy({"supported": False, "values": ["high"]})


def test_an_unknown_level_is_refused():
    with pytest.raises(policy.ReasoningPolicyError):
        policy.normalize_policy({"supported": True, "values": ["deepest"]})


def test_an_unknown_key_is_refused():
    with pytest.raises(policy.ReasoningPolicyError):
        policy.normalize_policy({"supported": True, "values": ["high"], "mode": "x"})


def test_a_caller_reasoning_value_is_stripped_before_validation():
    assert policy.strip_reasoning(
        {"reasoning_effort": "minimal", "top_p": 0.5}
    ) == {"top_p": 0.5}
    assert policy.strip_reasoning({"reasoning_effort": "minimal"}) is None
    assert policy.strip_reasoning(None) is None


def test_only_a_rejection_naming_the_option_is_detected():
    assert policy.rejects_reasoning_effort(
        b'{"error":{"message":"Unsupported parameter: reasoning_effort"}}'
    )
    assert policy.rejects_reasoning_effort(b'{"error":"reasoning effort is invalid"}')
    assert not policy.rejects_reasoning_effort(b'{"error":"rate limited"}')


def test_ledger_records_the_level_actually_sent():
    policy.note_sent_reasoning("fixture-model", "high")
    draft = _ledger()
    attempt = draft.record_attempt(provider="fixture", model_id="fixture-model")
    assert attempt.reasoning_effort == "high"


def test_ledger_records_no_level_when_the_option_was_dropped():
    policy.note_sent_reasoning("fixture-model", None)
    draft = _ledger()
    attempt = draft.record_attempt(provider="fixture", model_id="fixture-model")
    assert attempt.reasoning_effort is None


def test_ledger_refuses_an_unknown_level():
    draft = _ledger()
    with pytest.raises(CallLedgerError):
        draft.record_attempt(
            provider="fixture", model_id="fixture-model", reasoning_effort="deepest",
        )


@pytest.mark.asyncio
async def test_platform_lane_ignores_the_caller_and_uses_the_registry(monkeypatch):
    _live(monkeypatch)
    monkeypatch.setattr(policy, "reasoning_effort_for_model", lambda model_id: "high")
    model = _CANDIDATES[0]
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return _ok(model["upstream_model"])(request)

    await platform.call_platform_chat_completions(
        **_kwargs(model, httpx.MockTransport(handler)),
        model_parameters={"reasoning_effort": "minimal"},
    )
    assert len(seen) == 1
    assert seen[0]["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_platform_lane_sends_nothing_for_an_unsupported_model(monkeypatch):
    _live(monkeypatch)
    monkeypatch.setattr(policy, "reasoning_effort_for_model", lambda model_id: None)
    model = _CANDIDATES[0]
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return _ok(model["upstream_model"])(request)

    await platform.call_platform_chat_completions(
        **_kwargs(model, httpx.MockTransport(handler)),
        model_parameters={"reasoning_effort": "minimal"},
    )
    assert len(seen) == 1
    assert "reasoning_effort" not in seen[0]


@pytest.mark.asyncio
async def test_the_decision_is_made_again_for_the_fallback_model(monkeypatch):
    _live(monkeypatch)
    assert len(_CANDIDATES) >= 2
    first, second = _CANDIDATES[0], _CANDIDATES[1]
    levels = {first["id"]: "high", second["id"]: "low"}
    monkeypatch.setattr(
        policy, "reasoning_effort_for_model", lambda model_id: levels.get(model_id)
    )
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={
            "id": "synthetic", "model": body["model"],
            "choices": [{
                "message": {"role": "assistant", "content": "fixture answer"},
                "finish_reason": "stop",
            }],
        })

    for model in (first, second):
        await platform.call_platform_chat_completions(
            **_kwargs(model, httpx.MockTransport(handler)),
        )
    assert [body["reasoning_effort"] for body in seen] == ["high", "low"]


@pytest.mark.asyncio
async def test_a_rejected_reasoning_option_is_retried_once_without_it(monkeypatch):
    _live(monkeypatch)
    monkeypatch.setattr(policy, "reasoning_effort_for_model", lambda model_id: "high")
    model = _CANDIDATES[0]
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "reasoning_effort" in body:
            return httpx.Response(
                400, json={"error": {"message": "Unsupported parameter: reasoning_effort"}},
            )
        return _ok(model["upstream_model"])(request)

    response = await platform.call_platform_chat_completions(
        **_kwargs(model, httpx.MockTransport(handler)),
    )
    assert response["choices"][0]["message"]["content"] == "fixture answer"
    assert len(seen) == 2
    assert "reasoning_effort" in seen[0]
    assert "reasoning_effort" not in seen[1]
    draft = _ledger()
    attempt = draft.record_attempt(provider="fixture", model_id=model["id"])
    assert attempt.reasoning_effort is None


@pytest.mark.asyncio
async def test_the_stream_lane_retries_the_rejected_option_once(monkeypatch):
    _live(monkeypatch)
    monkeypatch.setattr(policy, "reasoning_effort_for_model", lambda model_id: "high")
    model = _CANDIDATES[0]
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "reasoning_effort" in body:
            return httpx.Response(400, json={"error": "reasoning_effort is not supported"})
        sse = (
            "data: " + json.dumps({
                "id": "synthetic", "model": body["model"],
                "choices": [{"delta": {"content": "fixture answer"},
                             "finish_reason": "stop"}],
            }) + "\n\ndata: [DONE]\n\n"
        )
        return httpx.Response(
            200, content=sse.encode(), headers={"content-type": "text/event-stream"},
        )

    events = [
        event async for event in platform.stream_platform_chat_completions(
            **_kwargs(model, httpx.MockTransport(handler)),
        )
    ]
    assert any(event.delta_content == "fixture answer" for event in events)
    assert len(seen) == 2
    assert "reasoning_effort" in seen[0]
    assert "reasoning_effort" not in seen[1]
