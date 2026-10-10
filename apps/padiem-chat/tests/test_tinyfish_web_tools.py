from __future__ import annotations

import json

import httpx
import pytest

from app.config import ConfigError, Settings
from app.web_tools import (
    TINYFISH_FETCH_ORIGIN,
    TINYFISH_SEARCH_ORIGIN,
    TinyFishWebProvider,
    WebToolError,
    create_web_provider,
)


def test_tinyfish_settings_require_server_side_key_and_redact_it() -> None:
    with pytest.raises(ConfigError, match="TINYFISH_API_KEY"):
        Settings.from_values(web_provider="tinyfish")

    settings = Settings.from_values(
        web_provider="tinyfish",
        tinyfish_api_key="tf-server-only",
        web_timeout_seconds="9",
    )
    assert settings.web_provider == "tinyfish"
    assert settings.tinyfish_api_key == "tf-server-only"
    assert settings.web_timeout_seconds == 9.0
    assert "tf-server-only" not in repr(settings)


@pytest.mark.asyncio
async def test_tinyfish_search_uses_fixed_origin_and_returns_safe_evidence() -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers["x-api-key"]
        seen["query"] = dict(request.url.params).get("query")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Current AI news",
                        "url": "https://example.com/source#part",
                        "description": "현재 정보 &amp; 설명",
                    },
                    {
                        "title": "Unsafe result",
                        "url": "http://127.0.0.1/private",
                        "snippet": "must be dropped",
                    },
                ]
            },
        )

    settings = Settings.from_values(
        web_provider="tinyfish",
        tinyfish_api_key="tf-server-only",
    )
    provider = create_web_provider(settings, transport=httpx.MockTransport(handler))
    assert isinstance(provider, TinyFishWebProvider)

    results = await provider.search("현재 AI 뉴스", 2)
    assert seen["method"] == "GET"
    assert seen["url"].startswith(TINYFISH_SEARCH_ORIGIN)
    assert seen["api_key"] == "tf-server-only"
    assert seen["query"] == "현재 AI 뉴스"
    assert len(results) == 1
    assert results[0].title == "Current AI news"
    assert results[0].url == "https://example.com/source"
    assert results[0].provider == "tinyfish"
    assert results[0].source_type == "search"
    assert "tf-server-only" not in json.dumps(results[0].public_dict())


@pytest.mark.asyncio
async def test_tinyfish_fetch_posts_url_and_unwraps_envelope() -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers["x-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/",
                        "final_url": "https://example.com/final#ignored",
                        "title": "Fetched page",
                        "format": "markdown",
                        "text": "page body content",
                    }
                ],
                "errors": [],
            },
        )

    provider = TinyFishWebProvider(
        Settings.from_values(web_provider="tinyfish", tinyfish_api_key="tf-server-only"),
        httpx.MockTransport(handler),
    )

    evidence = await provider.fetch("https://example.com/start#strip")
    assert seen["method"] == "POST"
    assert seen["url"] == TINYFISH_FETCH_ORIGIN
    assert seen["api_key"] == "tf-server-only"
    assert seen["body"] == {"urls": ["https://example.com/start"]}
    assert evidence.url == "https://example.com/final"
    assert evidence.snippet == "page body content"
    assert evidence.provider == "tinyfish"
    assert evidence.source_type == "fetch"


@pytest.mark.asyncio
async def test_tinyfish_fetch_private_input_url_fails_before_network() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("no network should occur for a private URL")

    provider = TinyFishWebProvider(
        Settings.from_values(web_provider="tinyfish", tinyfish_api_key="tf-server-only"),
        httpx.MockTransport(handler),
    )
    with pytest.raises((ValueError, Exception)):
        await provider.fetch("http://127.0.0.1/private")
    assert calls == 0


@pytest.mark.asyncio
async def test_tinyfish_live_runtime_enables_automatic_search_flag() -> None:
    settings = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.example",
        live_enabled=True,
        web_provider="tinyfish",
        tinyfish_api_key="tf-server-only",
    )
    provider = create_web_provider(settings, transport=httpx.MockTransport(lambda request: None))
    assert isinstance(provider, TinyFishWebProvider)
    assert getattr(provider, "_automatic_search_enabled") is True


@pytest.mark.asyncio
async def test_tinyfish_quota_exhausted_is_distinct_from_a_generic_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "INSUFFICIENT_CREDITS"})

    provider = TinyFishWebProvider(
        Settings.from_values(web_provider="tinyfish", tinyfish_api_key="tf-server-only"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebToolError) as info:
        await provider.search("test")
    assert info.value.code == "web_quota_exhausted"
    assert info.value.code != "web_request_failed"
    assert "소진" in info.value.user_message
    assert "INSUFFICIENT_CREDITS" not in info.value.user_message
    assert "tf-server-only" not in info.value.user_message
