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
