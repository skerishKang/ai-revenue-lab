"""Offline fixtures for structural diagnostics, tolerant text shapes and recovery."""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.pilot import platform as plat, stream_types
from app.pilot.errors import MalformedUpstreamResponse
from app.pilot.google_provider import _GoogleToolStream

MODEL = "google/gemini-3.5-flash-lite"


def frame(payload, separator=b"\n\n"):
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode() + separator


@pytest.mark.parametrize("parser", [plat._parse_sse_frame, stream_types._parse_sse_frame])
def test_empty_choices_without_usage_is_a_keepalive(parser, caplog):
    assert parser(frame({"choices": []}), provider="google", model_id=MODEL) is None
    assert not caplog.records


@pytest.mark.parametrize("content", [
    ["첫", " 답"],
    [{"type": "text", "text": "첫"}, {"text": " 답"}],
    {"parts": [{"text": "첫"}, {"text": " 답"}]},
])
@pytest.mark.parametrize("field", ["delta", "message"])
def test_stream_text_arrays_and_parts_are_joined(content, field):
    event = plat._parse_sse_frame(frame({"choices": [{field: {"content": content}}]}))
    assert event.delta_content == "첫 답"


@pytest.mark.parametrize("separator", [b"\n\n", b"\r\n\r\n"])
@pytest.mark.parametrize("pop", [plat._pop_sse_frames, stream_types._pop_sse_frames])
def test_every_byte_boundary_preserves_incomplete_frame_and_utf8(pop, separator):
    wire = frame({"choices": [{"delta": {"content": "한글🙂"}}]}, separator)
    done = b"data: [DONE]" + separator
    for split in range(len(wire)):
        frames, remainder = pop(wire[:split])
        assert frames == [] and remainder == wire[:split]
        frames, remainder = pop(remainder + wire[split:] + done[:7])
        assert len(frames) == 1 and remainder == done[:7]
        assert plat._parse_sse_frame(frames[0]).delta_content == "한글🙂"
        frames, remainder = pop(remainder + done[7:])
        assert plat._parse_sse_frame(frames[0]).done is True
        assert remainder == b""


@pytest.mark.parametrize("choice", [
    {"delta": {"content": None}, "finish_reason": "stop"},
    {"finish_reason": "stop"},
    {"message": {"content": None}, "finish_reason": "stop"},
])
def test_finish_only_chunk_and_nested_usage_details(choice):
    event = plat._parse_sse_frame(frame({"choices": [choice], "usage": {
        "prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 1},
        "completion_tokens_details": {"reasoning_tokens": 1},
    }}))
    assert event.finish_reason == "stop" and event.delta_content is None
    assert event.usage.total_tokens == 5 and event.usage.reasoning_tokens == 1


@pytest.mark.parametrize("payload,reason", [
    ({"choices": [{"delta": {"content": 3}}]}, "content_not_str"),
    ({"choices": [], "usage": {"total_tokens": -1}}, "usage_value"),
    ({"choices": {}}, "choices_not_list"),
    ([1], "payload_not_object"),
])
def test_structural_warning_contains_reason_but_no_text_or_untrusted_values(payload, reason, caplog):
    sentinel = "private-fixture-never-log"
    if isinstance(payload, dict):
        payload[sentinel] = sentinel
        payload["extra_content"] = {"google": {"thought_signature": sentinel}}
        if isinstance(payload.get("choices"), list) and payload["choices"]:
            payload["choices"][0]["finish_reason"] = sentinel
    with caplog.at_level(logging.WARNING):
        with pytest.raises(MalformedUpstreamResponse) as caught:
            plat._parse_sse_frame(frame(payload), provider="google", model_id=MODEL)
    assert caught.value.reason == reason
    assert caught.value.code == "malformed_upstream_response"
    records = [r.getMessage() for r in caplog.records if "b14_malformed_upstream" in r.getMessage()]
    assert len(records) == 1 and f"reason={reason}" in records[0]
    assert f"provider=google model={MODEL} path=stream" in records[0]
    assert sentinel not in records[0]
    shape = json.loads(records[0].split(" shape=", 1)[1])
    assert {"keys", "choices_length", "delta_keys", "message_keys", "content_type", "content_length", "finish_reason", "usage_keys"} <= shape.keys() or not isinstance(payload, dict)


@pytest.mark.parametrize("wire,reason", [(b"data: {broken\n\n", "json_decode"),
                                           (b"data: \xff\n\n", "utf8_decode")])
def test_decode_errors_are_classified_without_raw_exceptions(wire, reason, caplog):
    with pytest.raises(MalformedUpstreamResponse) as caught:
        plat._parse_sse_frame(wire, provider="google", model_id=MODEL)
    assert caught.value.reason == reason
    assert len(caplog.records) == 1 and caplog.records[0].exc_info is None


@pytest.mark.parametrize("payload,reason", [
    ({"candidates": [{}, {}]}, "candidate_count"),
    ({"candidates": [{"content": {"parts": [{"text": 7}]}}]}, "invalid_text"),
])
def test_native_google_decoder_has_safe_reason_and_shape(payload, reason, caplog):
    with pytest.raises(MalformedUpstreamResponse) as caught:
        _GoogleToolStream(set(), MODEL).decode(frame(payload))
    assert caught.value.reason == reason
    assert len(caplog.records) == 1
    assert f"path=native_stream reason={reason}" in caplog.records[0].getMessage()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [["첫", " 답"], [{"text": "첫"}, {"text": " 답"}],
                                      {"parts": [{"text": "첫 답"}]}, "첫 답"])
async def test_completed_google_text_parts_and_text_only_signature(monkeypatch, content):
    from app.pilot.b14_runtime_config import runtime_config
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "offline-fixture")
    payload = {"choices": [{"message": {"role": "assistant", "content": content,
        "extra_content": {"google": {"thought_signature": "opaque-fixture"}}}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3,
                  "prompt_tokens_details": {"cached_tokens": 1},
                  "completion_tokens_details": {"reasoning_tokens": 0}}}
    result = await plat.call_platform_chat_completions(model_id=MODEL,
        upstream_model="gemini-3.5-flash-lite", provider="Google AI Studio",
        platform_provider_id="google", messages=[{"role":"user", "content":"offline fixture"}],
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    message = result["choices"][0]["message"]
    assert message["content"] == "첫 답"
    assert message["signature"] == "opaque-fixture" and "extra_content" not in message


@pytest.mark.parametrize("status", [200, 400])
def test_malformed_35_falls_back_once_to_31_with_unchanged_attempt_code(client, monkeypatch, status):
    from app.pilot import router_core
    from app.pilot.b14_runtime_config import runtime_config
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "offline-fixture")
    monkeypatch.setattr(router_core, "_credential_status_for", lambda cm: (True, "present", "platform_secret", cm.platform_provider_id))
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)
    # Supply an already-resolved two-model roster to exercise the production
    # walk without changing selection policy or the configured roster.
    from dataclasses import replace
    decision = router_core.resolve_route(MODEL, {"product_tier": "plus"})
    decision = replace(decision, fallback_allowed=True, eligible_fallback=[{
        "model_id": "google/gemini-3.1-flash-lite", "upstream_model": "gemini-3.1-flash-lite",
        "provider": "Google AI Studio", "platform_provider_id": "google",
        "route_id": "platform:google/gemini-3.1-flash-lite"}])
    monkeypatch.setattr(router_core, "resolve_route", lambda *args, **kwargs: decision)
    calls = []
    original = plat.call_platform_chat_completions
    async def call(**kwargs):
        calls.append(kwargs["model_id"])
        def response(request):
            if kwargs["model_id"] == MODEL:
                return httpx.Response(status, json={"choices": [{"message": {"content": 3}}]})
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "recovered"}, "finish_reason": "stop"}]})
        return await original(**kwargs, transport=httpx.MockTransport(response))
    monkeypatch.setattr(plat, "call_platform_chat_completions", call)
    result = client.post("/api/pilot/v1/chat/completions", json={"model": MODEL,
        "messages": [{"role": "user", "content": "offline fixture"}],
        "business14": {"product_tier": "plus"}})
    if status == 400:
        assert result.status_code == 502
        assert result.json()["error"]["code"] == "malformed_upstream_response"
        assert calls == [MODEL]  # HTTP rejection must retain its existing rule.
        return
    assert result.status_code == 200
    assert calls == [MODEL, "google/gemini-3.1-flash-lite"]
    evidence = result.json()["business14"]["attempt_evidence"]
    assert evidence[0]["error_code"] == "malformed_upstream_response"
    assert evidence[1]["outcome"] == "success"
    assert result.json()["business14"]["attempt_count"] == 2


def test_google_compat_text_only_stream_with_thought_signature_is_accepted():
    event = plat._parse_sse_frame(frame({"choices": [{"delta": {"content": "answer",
        "extra_content": {"google": {"thought_signature": "opaque-fixture"}}}}]}))
    assert event.delta_content == "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,reason", [
    ({"choices": [{"message": {"content": "answer"}}], "usage": {"completion_tokens": -1}}, "usage_value"),
    ({"choices": [{"message": {"content": "answer", "extra_content": {"google": {"thought_signature": 7}}}}]}, "invalid_signature"),
    ({"choices": [{"message": {"content": [7]}}]}, "invalid_text"),
])
async def test_completed_rejection_emits_one_safe_structural_warning(monkeypatch, caplog, payload, reason):
    from app.pilot.b14_runtime_config import runtime_config
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "offline-fixture")
    with pytest.raises(MalformedUpstreamResponse) as caught:
        await plat.call_platform_chat_completions(model_id=MODEL, upstream_model="gemini-3.5-flash-lite",
            provider="Google AI Studio", platform_provider_id="google", messages=[{"role":"user", "content":"fixture"}],
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    assert caught.value.reason == reason
    records = [r.getMessage() for r in caplog.records if "b14_malformed_upstream" in r.getMessage()]
    assert len(records) == 1 and f"path=completed reason={reason}" in records[0]
    assert "answer" not in records[0] and "offline-fixture" not in records[0]
