from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.b14_client import B14Client, ChatRuntimeError
from app.config import ConfigError, Settings
from app.main import create_app

USER_MESSAGES = [{"role": "user", "content": "안녕하세요"}]


def success_payload():
    return {
        "choices": [{"message": {"role": "assistant", "content": "안녕하세요. 무엇을 도와드릴까요?"}}],
        "business14": {"request_id": "b14req_test123", "route_mode": "auto", "selected_model": "openrouter/free", "selected_provider": "OpenRouter"},
    }


def test_settings_require_b14_url_in_b14_mode(monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.delenv("PADIEM_CHAT_B14_BASE_URL", raising=False)
    with pytest.raises(ConfigError): Settings.from_env()


def test_settings_reject_url_credentials_query_fragment(monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    for bad in ["ftp://example.com", "https://user:pw@example.com", "https://example.com?target=evil", "https://example.com#frag"]:
        monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", bad)
        with pytest.raises(ConfigError): Settings.from_env()


@pytest.mark.asyncio
async def test_mock_mode_makes_zero_network_calls():
    calls = 0
    async def handler(request):
        nonlocal calls; calls += 1; return httpx.Response(500)
    result = await B14Client(Settings(runtime_mode="mock"), transport=httpx.MockTransport(handler)).complete(USER_MESSAGES)
    assert calls == 0
    assert result["runtime"] == "mock"
    assert "실제 모델을 호출하지 않았습니다" in result["answer"]


@pytest.mark.asyncio
async def test_b14_request_is_fixed_auto_route_and_has_no_provider_key():
    seen = {}
    async def handler(request):
        seen["url"] = str(request.url); seen["headers"] = dict(request.headers); seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=success_payload())
    result = await B14Client(Settings(runtime_mode="b14", b14_base_url="https://b14.example"), httpx.MockTransport(handler)).complete(USER_MESSAGES)
    assert seen["url"] == "https://b14.example/api/pilot/v1/chat/completions"
    assert seen["body"]["model"] == "b14/auto"
    assert seen["body"]["business14"] == {"task_type": "general", "optimize_for": "korean", "allow_external_fallback": True, "max_attempts": 3}
    assert "x-business14-provider-key" not in seen["headers"]
    assert "authorization" not in seen["headers"]
    assert result == {"answer": "안녕하세요. 무엇을 도와드릴까요?", "request_id": "b14req_test123", "runtime": "b14", "route": {"mode": "auto", "model": "openrouter/free", "provider": "OpenRouter"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "code", "client_status"), [(429, "upstream_busy", 503), (500, "upstream_error", 502)])
async def test_b14_http_errors_are_friendly(status, code, client_status):
    async def handler(request): return httpx.Response(status, json={"private_upstream_detail": "must not leak"})
    client = B14Client(Settings(runtime_mode="b14", b14_base_url="https://b14.example"), httpx.MockTransport(handler))
    with pytest.raises(ChatRuntimeError) as info: await client.complete(USER_MESSAGES)
    assert info.value.code == code and info.value.status_code == client_status
    assert "private_upstream_detail" not in info.value.user_message


@pytest.mark.asyncio
async def test_malformed_b14_success_fails_closed():
    async def handler(request): return httpx.Response(200, json={"choices": []})
    client = B14Client(Settings(runtime_mode="b14", b14_base_url="https://b14.example"), httpx.MockTransport(handler))
    with pytest.raises(ChatRuntimeError) as info: await client.complete(USER_MESSAGES)
    assert info.value.code == "malformed_upstream"


@pytest.mark.asyncio
async def test_timeout_is_normalized():
    async def handler(request): raise httpx.ReadTimeout("timeout", request=request)
    client = B14Client(Settings(runtime_mode="b14", b14_base_url="https://b14.example"), httpx.MockTransport(handler))
    with pytest.raises(ChatRuntimeError) as info: await client.complete(USER_MESSAGES)
    assert info.value.status_code == 504 and info.value.code == "upstream_timeout"


@pytest.mark.asyncio
async def test_api_chat_mock_round_trip_and_validation():
    app = create_app(Settings(runtime_mode="mock"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.post("/api/chat", json={"messages": USER_MESSAGES, "mode": "auto"})
        assert ok.status_code == 200 and ok.json()["runtime"] == "mock"
        assert (await client.post("/api/chat", json={"messages": USER_MESSAGES, "mode": "provider-x"})).status_code == 422
        assert (await client.post("/api/chat", json={"messages": USER_MESSAGES, "mode": "auto", "b14_base_url": "https://evil.example"})).status_code == 422
        assert (await client.post("/api/chat", json={"messages": [{"role": "assistant", "content": "hello"}], "mode": "auto"})).status_code == 422


@pytest.mark.asyncio
async def test_api_chat_b14_adapter_with_mocked_transport():
    async def handler(request): return httpx.Response(200, json=success_payload())
    app = create_app(Settings(runtime_mode="b14", b14_base_url="https://b14.example"), transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat", json={"messages": USER_MESSAGES, "mode": "auto"})
    assert response.status_code == 200 and response.json()["route"]["model"] == "openrouter/free"


def test_runtime_frontend_keeps_simple_anchor_and_truth_labels():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")
    js = (root / "static/app.js").read_text(encoding="utf-8")
    assert "무엇을 도와드릴까요" in html and "무엇이든 물어보세요" in html and "자동 추천" in html
    assert "파일 기능 · 준비 중" in html and "웹 검색 · 준비 중" in html
    assert "모의 응답 · 실제 모델 호출 없음" in js and 'fetch("/api/chat"' in js
    assert "OPENROUTER" not in html.upper() and "API_KEY" not in html and "API_KEY" not in js


def test_runtime_reuses_accepted_phase1_css_exactly():
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    accepted = repo / "reference/business-62-padiem-chat-v1/styles.css"
    assert accepted.is_file()
    assert (root / "static/styles.css").read_bytes() == accepted.read_bytes()
