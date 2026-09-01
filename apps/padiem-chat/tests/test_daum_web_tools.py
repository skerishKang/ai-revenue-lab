from __future__ import annotations

import json

import httpx
import pytest

from app.config import ConfigError, Settings
from app.web_tools import DAUM_SEARCH_ORIGIN, DaumWebProvider, WebToolError, create_web_provider


def test_daum_settings_require_server_side_key_and_redact_it() -> None:
    with pytest.raises(ConfigError, match="PADIEM_CHAT_DAUM_REST_API_KEY"):
        Settings.from_values(web_provider="daum")

    settings = Settings.from_values(
        web_provider="daum",
        daum_rest_api_key="kakao-rest-server-only",
        web_timeout_seconds="9",
    )
    assert settings.web_provider == "daum"
    assert settings.daum_rest_api_key == "kakao-rest-server-only"
    assert settings.web_timeout_seconds == 9.0
    assert "kakao-rest-server-only" not in repr(settings)


@pytest.mark.asyncio
async def test_daum_search_uses_kakao_api_and_returns_safe_evidence() -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "documents": [
                    {
                        "title": "<b>공식</b> 문서",
                        "contents": "현재 정보 &amp; 설명",
                        "url": "https://example.com/source#part",
                        "datetime": "2026-09-01T12:00:00.000+09:00",
                    }
                ]
            },
        )

    settings = Settings.from_values(
        web_provider="daum",
        daum_rest_api_key="kakao-rest-server-only",
    )
    provider = create_web_provider(settings, transport=httpx.MockTransport(handler))
    assert isinstance(provider, DaumWebProvider)

    results = await provider.search("현재 Node.js LTS", 2)
    assert seen["method"] == "GET"
    assert seen["url"].startswith(DAUM_SEARCH_ORIGIN + "/v2/search/web?")
    assert seen["auth"] == "KakaoAK kakao-rest-server-only"
    assert len(results) == 1
    assert results[0].title == "공식 문서"
    assert results[0].url == "https://example.com/source"
    assert results[0].provider == "daum"
    assert results[0].source_type == "search"
    assert "kakao-rest-server-only" not in json.dumps(results[0].public_dict())


@pytest.mark.asyncio
async def test_daum_search_does_not_require_firecrawl() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "dapi.kakao.com"
        return httpx.Response(200, json={"documents": []})

    provider = DaumWebProvider(
        Settings.from_values(
            web_provider="daum",
            daum_rest_api_key="kakao-rest-server-only",
            firecrawl_api_key=None,
        ),
        httpx.MockTransport(handler),
    )
    assert await provider.search("검색") == []


@pytest.mark.asyncio
async def test_daum_fetch_without_optional_extractor_is_truthful_failure() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("no page fetch network should occur")

    provider = DaumWebProvider(
        Settings.from_values(
            web_provider="daum",
            daum_rest_api_key="kakao-rest-server-only",
        ),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebToolError) as info:
        await provider.fetch("https://example.com/page")
    assert info.value.code == "web_fetch_unavailable"
    assert "설정" in info.value.user_message
    assert calls == 0


@pytest.mark.asyncio
async def test_daum_live_runtime_enables_automatic_search_flag() -> None:
    settings = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.example",
        live_enabled=True,
        web_provider="daum",
        daum_rest_api_key="kakao-rest-server-only",
    )
    provider = create_web_provider(settings, transport=httpx.MockTransport(lambda request: None))
    assert getattr(provider, "_automatic_search_enabled") is True
