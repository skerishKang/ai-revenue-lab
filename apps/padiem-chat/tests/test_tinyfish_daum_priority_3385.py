"""Offline contract tests for TinyFish-first and Daum quota fallback (#3385)."""
from __future__ import annotations

import httpx
import pytest

from app.config import ConfigError, Settings
from app.web_tools import TinyFishDaumWebProvider, WebToolError, create_web_provider


def config():
    return Settings.from_values(runtime_mode="b14",
        b14_base_url="https://example.com", web_provider="tinyfish_daum",
        tinyfish_api_key="test-only", daum_rest_api_key="test-only")


def test_both_keys_required_and_provider_factory():
    assert isinstance(create_web_provider(config()), TinyFishDaumWebProvider)
    with pytest.raises(ConfigError):
        Settings.from_values(web_provider="tinyfish_daum", tinyfish_api_key="test-only")
    with pytest.raises(ConfigError):
        Settings.from_values(web_provider="tinyfish_daum", daum_rest_api_key="test-only")


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_status", [402, 429])
async def test_tinyfish_quota_then_daum(blocked_status):
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        if "tinyfish" in str(request.url):
            return httpx.Response(blocked_status, json={"error": "quota"})
        return httpx.Response(200, json={"documents": [
            {"title": "source", "url": "https://example.com/article", "contents": "text"}]})
    provider = create_web_provider(config(), transport=httpx.MockTransport(handler))
    results = await provider.search("public question")
    assert len(calls) == 2
    assert results and results[0].provider == "daum"


@pytest.mark.asyncio
async def test_no_fallback_on_500():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(500, json={"error": "unavailable"})
    provider = create_web_provider(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(WebToolError):
        await provider.search("public question")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fetch_has_no_daum_fallback():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(402, json={"error": "quota"})
    provider = create_web_provider(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(WebToolError):
        await provider.fetch("https://example.com/page")
    assert calls == ["https://api.fetch.tinyfish.ai"]


@pytest.mark.asyncio
async def test_primary_success_stays_tinyfish_with_one_call():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"results": [
            {"title": "Original", "url": "https://example.com/original", "snippet": "source"}
        ]})
    p = create_web_provider(config(), transport=httpx.MockTransport(handler))
    items = await p.search("public question")
    assert len(calls) == 1 and "tinyfish" in calls[0]
    assert len(items) == 1 and items[0].provider == "tinyfish"


@pytest.mark.asyncio
async def test_empty_results_are_not_usage_exhaustion():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"results": []})
    p = create_web_provider(config(), transport=httpx.MockTransport(handler))
    assert await p.search("public question") == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_secondary_failure_does_not_make_third_request():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(402, json={"error": "quota"})
        return httpx.Response(500, json={"error": "failed"})
    p = create_web_provider(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(WebToolError) as err:
        await p.search("public question")
    assert err.value.code == "web_unavailable"
    assert len(calls) == 2


def test_live_env_default_and_explicit_off_preserved(monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://example.com")
    monkeypatch.setenv("TINYFISH_API_KEY", "test-only")
    monkeypatch.setenv("PADIEM_CHAT_DAUM_REST_API_KEY", "test-only")
    monkeypatch.delenv("PADIEM_CHAT_WEB_PROVIDER", raising=False)
    assert Settings.from_env().web_provider == "tinyfish_daum"
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    assert Settings.from_env().web_provider == "off"
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.delenv("PADIEM_CHAT_WEB_PROVIDER", raising=False)
    assert Settings.from_env().web_provider == "off"


def test_b14_without_both_keys_fails_closed(monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://example.com")
    monkeypatch.delenv("PADIEM_CHAT_WEB_PROVIDER", raising=False)
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.delenv("PADIEM_CHAT_DAUM_REST_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()
