from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core.web_runtime import (
    DAUM_SEARCH_ORIGIN,
    DAUM_WEB_SEARCH_PATH,
    FIRECRAWL_ORIGIN,
    DaumWebProvider,
    WebRuntimeConfig,
    WebRuntimeError,
    create_web_provider,
)


def run(coro):
    return asyncio.run(coro)


def test_daum_config_requires_server_key_and_redacts_it() -> None:
    with pytest.raises(ValueError, match="REST API key"):
        WebRuntimeConfig(provider="daum")

    config = WebRuntimeConfig(
        provider="DAUM",
        daum_rest_api_key=" kakao-rest-secret ",
        daum_search_sort="RECENCY",
        web_timeout_seconds=8,
    )
    assert config.provider == "daum"
    assert config.daum_rest_api_key == "kakao-rest-secret"
    assert config.daum_search_sort == "recency"
    assert "kakao-rest-secret" not in repr(config)
    assert "kakao-rest-secret" not in json.dumps(config.to_public_dict())
    assert config.to_public_dict()["daum_configured"] is True

    with pytest.raises(ValueError, match="daum_search_sort"):
        WebRuntimeConfig(provider="off", daum_search_sort="newest")


def test_factory_returns_daum_provider() -> None:
    provider = create_web_provider(
        WebRuntimeConfig(provider="daum", daum_rest_api_key="kakao-rest-secret")
    )
    assert isinstance(provider, DaumWebProvider)


def test_daum_search_uses_fixed_api_and_normalizes_evidence() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "meta": {"total_count": 2, "pageable_count": 2, "is_end": True},
                "documents": [
                    {
                        "title": "<b>Node.js</b> LTS &amp; release",
                        "contents": "현재 <b>LTS</b> 릴리스 설명 &amp; 정보",
                        "url": "https://example.com/node#section",
                        "datetime": "2026-08-20T09:00:00.000+09:00",
                    },
                    {
                        "title": "unsafe",
                        "contents": "private",
                        "url": "http://127.0.0.1/private",
                        "datetime": "2026-08-20T09:00:00.000+09:00",
                    },
                ],
            },
        )

    provider = DaumWebProvider(
        WebRuntimeConfig(
            provider="daum",
            daum_rest_api_key="kakao-rest-secret",
            daum_search_sort="recency",
        ),
        httpx.MockTransport(handler),
    )
    results = run(provider.search("현재 Node.js LTS", 3))

    assert seen["path"] == DAUM_WEB_SEARCH_PATH
    assert str(seen["url"]).startswith(DAUM_SEARCH_ORIGIN + DAUM_WEB_SEARCH_PATH)
    assert seen["headers"]["authorization"] == "KakaoAK kakao-rest-secret"  # type: ignore[index]
    assert seen["params"] == {
        "query": "현재 Node.js LTS",
        "sort": "recency",
        "page": "1",
        "size": "3",
    }
    assert len(results) == 1
    assert results[0].provider == "daum"
    assert results[0].source_type == "search"
    assert results[0].url == "https://example.com/node"
    assert results[0].title == "Node.js LTS & release"
    assert results[0].snippet == "현재 LTS 릴리스 설명 & 정보"
    assert "kakao-rest-secret" not in json.dumps(results[0].to_public_dict())


def test_daum_search_with_sort_supports_accuracy_and_recency() -> None:
    observed_sorts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed_sorts.append(request.url.params["sort"])
        return httpx.Response(200, json={"documents": []})

    provider = DaumWebProvider(
        WebRuntimeConfig(provider="daum", daum_rest_api_key="kakao-rest-secret"),
        httpx.MockTransport(handler),
    )
    run(provider.search_with_sort("one", sort="accuracy"))
    run(provider.search_with_sort("two", sort="recency"))
    with pytest.raises(ValueError, match="sort"):
        run(provider.search_with_sort("three", sort="newest"))
    assert observed_sorts == ["accuracy", "recency"]


def test_daum_fetch_without_optional_extractor_fails_closed_without_network() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("fetch must not invent a direct crawler")

    provider = DaumWebProvider(
        WebRuntimeConfig(provider="daum", daum_rest_api_key="kakao-rest-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.fetch("https://example.com/page"))
    assert info.value.code == "web_fetch_unavailable"
    assert calls == 0


def test_daum_fetch_uses_firecrawl_only_as_optional_extractor() -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        assert str(request.url) == FIRECRAWL_ORIGIN + "/v2/scrape"
        assert request.headers["authorization"] == "Bearer fc-extractor-only"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "markdown": "Fetched body",
                    "metadata": {
                        "title": "Fetched",
                        "sourceURL": "https://example.com/page",
                    },
                },
            },
        )

    provider = DaumWebProvider(
        WebRuntimeConfig(
            provider="daum",
            daum_rest_api_key="kakao-rest-secret",
            firecrawl_api_key="fc-extractor-only",
        ),
        httpx.MockTransport(handler),
    )
    evidence = run(provider.fetch("https://example.com/page"))
    assert seen == [("POST", FIRECRAWL_ORIGIN + "/v2/scrape")]
    assert evidence.provider == "firecrawl"
    assert evidence.source_type == "fetch"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "web_auth"),
        (403, "web_auth"),
        (429, "web_busy"),
        (500, "web_unavailable"),
        (404, "web_request_failed"),
    ],
)
def test_daum_errors_are_normalized_without_secret_or_body_leak(status: int, code: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "PRIVATE-UPSTREAM-DETAIL"})

    provider = DaumWebProvider(
        WebRuntimeConfig(provider="daum", daum_rest_api_key="kakao-rest-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.search("test"))
    assert info.value.code == code
    assert "PRIVATE-UPSTREAM-DETAIL" not in info.value.message
    assert "kakao-rest-secret" not in info.value.message


def test_daum_malformed_payload_is_normalized() -> None:
    responses = [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=["bad"]),
        httpx.Response(200, json={"documents": {"bad": "shape"}}),
    ]
    for response in responses:
        async def handler(request: httpx.Request, response=response) -> httpx.Response:
            return response

        provider = DaumWebProvider(
            WebRuntimeConfig(provider="daum", daum_rest_api_key="kakao-rest-secret"),
            httpx.MockTransport(handler),
        )
        with pytest.raises(WebRuntimeError) as info:
            run(provider.search("test"))
        assert info.value.code == "web_malformed"
