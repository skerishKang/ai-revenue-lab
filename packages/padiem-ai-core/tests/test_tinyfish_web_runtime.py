from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core.web_runtime import (
    MAX_PROVIDER_RESPONSE_BYTES,
    TINYFISH_FETCH_ORIGIN,
    TINYFISH_SEARCH_ORIGIN,
    TinyFishWebProvider,
    WebRuntimeConfig,
    WebRuntimeError,
    create_web_provider,
)


def run(coro):
    return asyncio.run(coro)


def test_tinyfish_config_requires_server_key_and_redacts_it() -> None:
    with pytest.raises(ValueError, match="server-side API key"):
        WebRuntimeConfig(provider="tinyfish")

    config = WebRuntimeConfig(
        provider="TINYFISH",
        tinyfish_api_key=" tf-secret-server-only ",
        web_timeout_seconds=7,
    )
    assert config.provider == "tinyfish"
    assert config.tinyfish_api_key == "tf-secret-server-only"
    assert "tf-secret-server-only" not in repr(config)
    public = config.to_public_dict()
    assert public["tinyfish_configured"] is True
    assert "tf-secret-server-only" not in json.dumps(public)


def test_factory_returns_tinyfish_provider() -> None:
    provider = create_web_provider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret")
    )
    assert isinstance(provider, TinyFishWebProvider)


def test_tinyfish_search_uses_fixed_origin_key_header_and_safe_evidence() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "query": "latest Padiem",
                "results": [
                    {
                        "position": 1,
                        "site_name": "Example",
                        "title": "Useful result",
                        "snippet": "Useful current snippet",
                        "url": "https://example.com/a#section",
                    },
                    {
                        "position": 2,
                        "title": "Unsafe result",
                        "snippet": "private",
                        "url": "http://127.0.0.1/private",
                    },
                ],
                "total_results": 2,
            },
        )

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(handler),
    )
    results = run(provider.search("latest Padiem", 5))

    assert seen["method"] == "GET"
    assert str(seen["url"]).startswith(TINYFISH_SEARCH_ORIGIN)
    assert seen["headers"]["x-api-key"] == "tf-secret"  # type: ignore[index]
    assert seen["params"] == {"query": "latest Padiem"}
    assert len(results) == 1
    assert results[0].provider == "tinyfish"
    assert results[0].source_type == "search"
    assert results[0].url == "https://example.com/a"
    assert results[0].title == "Useful result"
    assert results[0].snippet == "Useful current snippet"


def test_tinyfish_search_honors_core_result_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": "q",
                "results": [
                    {"title": f"r{i}", "snippet": "s", "url": f"https://example.com/{i}"}
                    for i in range(10)
                ],
                "total_results": 10,
            },
        )

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(handler),
    )
    assert len(run(provider.search("q", 3))) == 3


def test_tinyfish_fetch_uses_fixed_origin_markdown_and_revalidates_final_url() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/start",
                        "final_url": "https://example.com/final#ignored",
                        "title": "Fetched title",
                        "description": "desc",
                        "language": "en",
                        "text": "# Clean body\n\nFetched content",
                        "latency_ms": 12,
                    }
                ],
                "errors": [],
            },
        )

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(handler),
    )
    evidence = run(provider.fetch("https://example.com/start#source"))

    assert seen["method"] == "POST"
    assert seen["url"] == TINYFISH_FETCH_ORIGIN
    assert seen["headers"]["x-api-key"] == "tf-secret"  # type: ignore[index]
    assert seen["body"] == {
        "urls": ["https://example.com/start"],
        "format": "markdown",
    }
    assert evidence.provider == "tinyfish"
    assert evidence.source_type == "fetch"
    assert evidence.url == "https://example.com/final"
    assert evidence.title == "Fetched title"
    assert "Clean body" in evidence.snippet


def test_tinyfish_fetch_rejects_unsafe_returned_final_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/start",
                        "final_url": "http://127.0.0.1/private",
                        "title": "unsafe",
                        "text": "private",
                    }
                ],
                "errors": [],
            },
        )

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.fetch("https://example.com/start"))
    assert info.value.code == "unsafe_web_result"


def test_tinyfish_fetch_per_url_error_fails_closed_without_detail_leak() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [],
                "errors": [{"url": "https://example.com", "error": "PRIVATE DETAIL"}],
            },
        )

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.fetch("https://example.com"))
    assert info.value.code == "web_request_failed"
    assert "PRIVATE" not in info.value.message
    assert "tf-secret" not in info.value.message


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "web_auth"),
        (403, "web_auth"),
        (429, "web_busy"),
        (500, "web_unavailable"),
        (503, "web_unavailable"),
        (404, "web_request_failed"),
    ],
)
def test_tinyfish_errors_are_normalized_without_secret_or_body_leak(status: int, code: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "PRIVATE-UPSTREAM-DETAIL"})

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.search("test"))
    assert info.value.code == code
    assert "PRIVATE-UPSTREAM-DETAIL" not in info.value.message
    assert "tf-secret" not in info.value.message


def test_tinyfish_response_byte_cap_and_redirect_policy_are_fail_closed() -> None:
    async def huge_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1))

    huge = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(huge_handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(huge.search("test"))
    assert info.value.code == "web_response_too_large"

    calls = 0

    async def redirect_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    redirect = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(redirect_handler),
    )
    with pytest.raises(WebRuntimeError) as redirect_info:
        run(redirect.search("test"))
    assert redirect_info.value.code == "web_request_failed"
    assert calls == 1


def test_tinyfish_timeout_transport_and_malformed_shape_are_normalized() -> None:
    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("PRIVATE timeout detail", request=request)

    timeout_provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(WebRuntimeError) as timeout_info:
        run(timeout_provider.search("test"))
    assert timeout_info.value.code == "web_timeout"
    assert "PRIVATE" not in timeout_info.value.message

    async def transport_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("PRIVATE transport detail", request=request)

    transport_provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(transport_handler),
    )
    with pytest.raises(WebRuntimeError) as transport_info:
        run(transport_provider.search("test"))
    assert transport_info.value.code == "web_unavailable"
    assert "PRIVATE" not in transport_info.value.message

    async def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": {"not": "a list"}})

    malformed_provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(malformed_handler),
    )
    with pytest.raises(WebRuntimeError) as malformed_info:
        run(malformed_provider.search("test"))
    assert malformed_info.value.code == "web_malformed"


def test_tinyfish_internal_request_surface_accepts_only_fixed_origins_and_methods() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="tf-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="origin"):
        run(provider._request("GET", "https://evil.example"))  # noqa: SLF001
    with pytest.raises(RuntimeError, match="method"):
        run(provider._request("DELETE", TINYFISH_SEARCH_ORIGIN))  # noqa: SLF001
    assert calls == 0
