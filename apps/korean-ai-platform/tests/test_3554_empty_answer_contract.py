"""#3554: HTTP 200 / SSE done without assistant text must not count as success."""
from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform as plat
from app.pilot.errors import MalformedUpstreamResponse
from app.pilot.sensenova_provider import (
    SENSENOVA_CREDENTIAL_BINDING,
    SENSENOVA_MODEL_ID,
    SENSENOVA_PROVIDER_ID,
    SENSENOVA_UPSTREAM_MODEL,
)
from app.pilot.upstream_answer_contract import UpstreamEmptyAnswer, require_completed_text_answer


def _payload(content, *, finish="stop"):
    return {"model": SENSENOVA_UPSTREAM_MODEL, "choices": [
        {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
    ], "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}}


def _client_args(transport):
    return dict(
        model_id=SENSENOVA_MODEL_ID,
        upstream_model=SENSENOVA_UPSTREAM_MODEL,
        provider="SenseNova",
        platform_provider_id=SENSENOVA_PROVIDER_ID,
        messages=[{"role": "user", "content": "synthetic fixture"}],
        max_tokens=8,
        transport=transport,
    )


@pytest.mark.parametrize("body,reason", [
    (_payload(None, finish="length"), "length"),
    (_payload("", finish="stop"), "stop"),
    (_payload("  \n\t", finish="stop"), "stop"),
    (_payload(None, finish="private raw value"), "other"),
    (_payload(None, finish={"private": "secret"}), "other"),
])
def test_completed_empty_answer_is_nonretryable_failure(body, reason):
    with pytest.raises(UpstreamEmptyAnswer) as raised:
        require_completed_text_answer(body)
    assert raised.value.code == "upstream_empty_answer"
    assert raised.value.status_code == 502
    assert raised.value.finish_category == reason
    assert not getattr(raised.value, "retryable", False)
    assert "private" not in raised.value.message


@pytest.mark.parametrize("content", [False, [], {"text": "hidden"}, 42])
def test_invalid_content_shape_is_malformed(content):
    with pytest.raises(MalformedUpstreamResponse):
        require_completed_text_answer(_payload(content))


def test_valid_text_content_including_korean_passes():
    require_completed_text_answer(_payload("정상 답변입니다."))
    require_completed_text_answer(_payload("  ok  "))


@pytest.mark.asyncio
async def test_direct_live_adapter_200_empty_not_success(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, "fake-test-secret")
    seen = []

    def responder(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_payload(None, finish="length"))

    with pytest.raises(UpstreamEmptyAnswer):
        await plat.call_platform_chat_completions(**_client_args(httpx.MockTransport(responder)))
    assert len(seen) == 1
    assert seen[0]["model"] == SENSENOVA_UPSTREAM_MODEL
    assert seen[0]["max_tokens"] == 8


@pytest.mark.asyncio
async def test_stream_done_without_text_not_success(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, "fake-test-secret")
    events = [
        {"model": SENSENOVA_UPSTREAM_MODEL,
         "choices": [{"delta": {"content": None}, "finish_reason": "length"}]}
    ]
    wire = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=wire))
    seen = []
    with pytest.raises(UpstreamEmptyAnswer) as raised:
        async for event in plat.stream_platform_chat_completions(**_client_args(transport)):
            seen.append(event)
    assert raised.value.finish_category == "length"
    assert not any(event.done for event in seen)


@pytest.mark.asyncio
async def test_stream_with_text_has_terminal(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, "fake-test-secret")
    parts = [
        {"choices": [{"delta": {"content": "정상 응답"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": None}, "finish_reason": "stop"}]},
    ]
    wire = "".join("data: " + json.dumps(item, ensure_ascii=False) + "\n\n" for item in parts) + "data: [DONE]\n\n"
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=wire))
    result = [e async for e in plat.stream_platform_chat_completions(**_client_args(transport))]
    assert any(e.delta_content == "정상 응답" for e in result)
    assert result[-1].done


def test_gateway_502_empty_no_retries_and_no_fallback(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(SENSENOVA_CREDENTIAL_BINDING, "fake-test-secret")
    calls = []

    # Do not patch the same function into recursion: retain the original adapter.
    real_provider_call = plat.call_platform_chat_completions

    async def one_call(**kw):
        calls.append((kw["model_id"], kw["upstream_model"]))
        return await real_provider_call(
            **{**kw, "transport": httpx.MockTransport(
                lambda req: httpx.Response(200, json=_payload(None, finish="length"))
            )}
        )
    monkeypatch.setattr(plat, "call_platform_chat_completions", one_call)
    with TestClient(create_app()) as client:
        response = client.post("/api/pilot/v1/chat/completions", json={
            "model": SENSENOVA_MODEL_ID, "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 8,
            "business14": {"max_retries": 0, "allow_external_fallback": False}
        })
    assert response.status_code == 502
    result = response.json()["error"]
    assert result["code"] == "upstream_empty_answer"
    assert result["attempt_count"] == 1
    assert result["fallback_used"] is False
    assert len(calls) == 1
    assert calls[0] == (SENSENOVA_MODEL_ID, SENSENOVA_UPSTREAM_MODEL)
