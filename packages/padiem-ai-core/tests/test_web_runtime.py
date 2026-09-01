from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core import Evidence
from padiem_ai_core.web_runtime import (
    FIRECRAWL_ORIGIN,
    MAX_PROVIDER_RESPONSE_BYTES,
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    FirecrawlWebProvider,
    MockWebProvider,
    OffWebProvider,
    WebRuntimeConfig,
    WebRuntimeError,
    create_web_provider,
    normalize_public_url,
)


def run(coro):
    return asyncio.run(coro)


def test_web_config_defaults_off_and_redacts_server_key() -> None:
    default = WebRuntimeConfig()
    assert default.provider == "off"
    assert default.firecrawl_api_key is None
    assert default.daum_rest_api_key is None
    assert default.web_timeout_seconds == 15.0

    with pytest.raises(ValueError, match="server-side API key"):
        WebRuntimeConfig(provider="firecrawl")

    configured = WebRuntimeConfig(
        provider="FIRECRAWL",
        firecrawl_api_key=" fc-secret-server-only ",
        web_timeout_seconds=9,
    )
    assert configured.provider == "firecrawl"
    assert configured.firecrawl_api_key == "fc-secret-server-only"
    assert "fc-secret-server-only" not in repr(configured)
    assert "fc-secret-server-only" not in json.dumps(configured.to_public_dict())
    assert configured.to_public_dict() == {
        "provider": "firecrawl",
        "web_timeout_seconds": 9.0,
        "firecrawl_configured": True,
        "daum_configured": False,
        "daum_search_sort": "accuracy",
    }


@pytest.mark.parametrize("bad", [0, -1, 30.1, True, "15"])
def test_web_config_rejects_invalid_timeout(bad) -> None:
    with pytest.raises(ValueError, match="web_timeout_seconds"):
        WebRuntimeConfig(web_timeout_seconds=bad)  # type: ignore[arg-type]


def test_web_config_rejects_unknown_provider_and_blank_key() -> None:
    with pytest.raises(ValueError, match="provider"):
        WebRuntimeConfig(provider="browser")
    with pytest.raises(ValueError, match="non-empty"):
        WebRuntimeConfig(provider="off", firecrawl_api_key="   ")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/",
        "https://sub.localhost/path",
        "http://localhost.localdomain/",
        "http://metadata.google.internal/latest/meta-data/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "https://user:pass@example.com/",
        "http://2130706433/",
        "http://127.1/",
        "https://foo.internal/path",
        "https://foo.lan/path",
        "https://foo.home/path",
    ],
)
def test_public_url_policy_rejects_local_private_userinfo_and_odd_numeric_hosts(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_public_url(url)


def test_public_url_policy_normalizes_idna_and_strips_fragment() -> None:
    normalized = normalize_public_url("https://광주.kr/path?q=1#frag")
    assert normalized.startswith("https://xn--")
    assert normalized.endswith("/path?q=1")
    assert "#" not in normalized


def test_public_url_policy_preserves_valid_port_and_adds_root_path() -> None:
    assert normalize_public_url("HTTPS://example.com:8443#x") == "https://example.com:8443/"


def test_public_url_policy_rejects_control_char_and_overlong_value() -> None:
    with pytest.raises(ValueError):
        normalize_public_url("https://example.com/\x01x")
    with pytest.raises(ValueError):
        normalize_public_url("https://example.com/" + "x" * 2050)


def test_query_and_limit_bounds_are_fail_closed() -> None:
    mock = MockWebProvider()
    with pytest.raises(ValueError, match="query"):
        run(mock.search(""))
    with pytest.raises(ValueError, match="query"):
        run(mock.search("x" * (MAX_QUERY_CHARS + 1)))
    with pytest.raises(ValueError, match="limit"):
        run(mock.search("ok", 0))
    with pytest.raises(ValueError, match="limit"):
        run(mock.search("ok", MAX_RESULTS + 1))
    with pytest.raises(ValueError, match="limit"):
        run(mock.search("ok", True))  # type: ignore[arg-type]


def test_off_and_mock_providers_make_zero_network_calls() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be called")

    transport = httpx.MockTransport(handler)
    off = create_web_provider(WebRuntimeConfig(provider="off"), transport=transport)
    assert isinstance(off, OffWebProvider)
    with pytest.raises(WebRuntimeError) as info:
        run(off.search("test"))
    assert info.value.code == "web_tools_off"

    mock = create_web_provider(WebRuntimeConfig(provider="mock"), transport=transport)
    assert isinstance(mock, MockWebProvider)
    results = run(mock.search("free AI API", 2))
    page = run(mock.fetch("https://example.com/page#section"))
    assert len(results) == 2
    assert all(isinstance(item, Evidence) for item in results)
    assert results[0].provider == "mock"
    assert page.url == "https://example.com/page"
    assert page.source_type == "fetch"
    assert calls == 0


def test_default_factory_is_off_and_zero_network() -> None:
    provider = create_web_provider()
    assert isinstance(provider, OffWebProvider)


def test_firecrawl_search_uses_fixed_v2_endpoint_and_drops_unsafe_result() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "Example result",
                            "url": "https://example.com/a#section",
                            "description": "A useful result",
                        },
                        {
                            "title": "Unsafe result",
                            "url": "http://127.0.0.1/private",
                            "description": "must be dropped",
                        },
                    ]
                },
            },
        )

    config = WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-test-secret")
    provider = FirecrawlWebProvider(config, httpx.MockTransport(handler))
    results = run(provider.search("current AI news", 3))

    assert seen["url"] == FIRECRAWL_ORIGIN + "/v2/search"
    assert seen["body"] == {"query": "current AI news", "limit": 3, "sources": ["web"]}
    assert seen["headers"]["authorization"] == "Bearer fc-test-secret"  # type: ignore[index]
    assert len(results) == 1
    assert results[0].url == "https://example.com/a"
    assert results[0].provider == "firecrawl"
    assert results[0].source_type == "search"
    assert "fc-test-secret" not in json.dumps(results[0].to_public_dict())


def test_firecrawl_scrape_uses_fixed_v2_endpoint_and_bounded_evidence() -> None:
    seen: dict[str, object] = {}
    long_markdown = "x" * 5000

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "markdown": long_markdown,
                    "metadata": {
                        "title": "T" * 600,
                        "sourceURL": "https://example.com/final#ignored",
                    },
                },
            },
        )

    provider = FirecrawlWebProvider(
        WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-test"),
        httpx.MockTransport(handler),
    )
    evidence = run(provider.fetch("https://example.com/start"))

    assert seen["url"] == FIRECRAWL_ORIGIN + "/v2/scrape"
    assert seen["body"] == {
        "url": "https://example.com/start",
        "formats": ["markdown"],
        "onlyMainContent": True,
    }
    assert evidence.url == "https://example.com/final"
    assert len(evidence.title) <= 301
    assert len(evidence.snippet) <= 2001
    assert evidence.source_type == "fetch"


def test_firecrawl_revalidates_returned_fetch_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "markdown": "private",
                    "metadata": {"sourceURL": "http://127.0.0.1/private"},
                },
            },
        )

    provider = FirecrawlWebProvider(
        WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-test"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.fetch("https://example.com/start"))
    assert info.value.code == "unsafe_web_result"


def test_firecrawl_does_not_follow_provider_redirect() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    provider = FirecrawlWebProvider(
        WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.search("test"))
    assert info.value.code == "web_request_failed"
    assert calls == 1


def test_firecrawl_response_byte_cap_is_enforced() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1))

    provider = FirecrawlWebProvider(
        WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.search("test"))
    assert info.value.code == "web_response_too_large"


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
def test_firecrawl_errors_are_normalized_without_body_or_key_leak(status: int, code: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "PRIVATE-UPSTREAM-DETAIL"})

    provider = FirecrawlWebProvider(
        WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebRuntimeError) as info:
        run(provider.search("test"))
    assert info.value.code == code
    assert "PRIVATE-UPSTREAM-DETAIL" not in info.value.message
    assert "fc-secret" not in info.value.message
    assert "PRIVATE-UPSTREAM-DETAIL" not in str(info.value)
    assert "fc-secret" not in str(info.value)


def test_firecrawl_timeout_and_transport_errors_are_normalized() -> None:
    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("PRIVATE timeout detail", request=request)

    timeout_provider = FirecrawlWebProvider(
        WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(WebRuntimeError) as timeout_info:
        run(timeout_provider.search("test"))
    assert timeout_info.value.code == "web_timeout"
    assert "PRIVATE" not in timeout_info.value.message

    async def transport_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("PRIVATE transport detail", request=request)

    transport_provider = FirecrawlWebProvider(
        WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(transport_handler),
    )
    with pytest.raises(WebRuntimeError) as transport_info:
        run(transport_provider.search("test"))
    assert transport_info.value.code == "web_unavailable"
    assert "PRIVATE" not in transport_info.value.message


def test_firecrawl_malformed_utf8_json_and_shape_are_normalized() -> None:
    responses = [
        httpx.Response(200, content=b"\xff\xfe"),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"success": False, "error": "PRIVATE"}),
        httpx.Response(200, json={"success": True, "data": {"web": {"bad": "shape"}}}),
    ]

    for response in responses:
        async def handler(request: httpx.Request, response=response) -> httpx.Response:
            return response

        provider = FirecrawlWebProvider(
            WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-secret"),
            httpx.MockTransport(handler),
        )
        with pytest.raises(WebRuntimeError) as info:
            run(provider.search("test"))
        assert info.value.code == "web_malformed"
        assert "PRIVATE" not in info.value.message
        assert "fc-secret" not in info.value.message


def test_firecrawl_rejects_unapproved_internal_path_before_network() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"success": True, "data": {}})

    provider = FirecrawlWebProvider(
        WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="unapproved Firecrawl path"):
        run(provider._post("/v2/anything", {}))  # noqa: SLF001 - invariant test
    assert calls == 0


def test_public_serialization_contains_no_secret_fields() -> None:
    config = WebRuntimeConfig(provider="firecrawl", firecrawl_api_key="fc-secret")
    public = config.to_public_dict()
    assert not ({"api_key", "firecrawl_api_key", "daum_rest_api_key", "secret", "credential", "token"} & set(public))
    assert "fc-secret" not in json.dumps(public)
