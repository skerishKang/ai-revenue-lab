from __future__ import annotations

import json
from types import MappingProxyType

import httpx
import pytest

from app.config import ConfigError, Settings
from app.tools import TOOL_REGISTRY, get_tool
from app.web_tools import (
    FIRECRAWL_ORIGIN,
    MAX_PROVIDER_RESPONSE_BYTES,
    FirecrawlWebProvider,
    MockWebProvider,
    OffWebProvider,
    WebToolError,
    create_web_provider,
    normalize_public_url,
)


def test_tool_registry_is_small_unique_immutable_and_not_ui_enabled():
    assert isinstance(TOOL_REGISTRY, MappingProxyType)
    assert tuple(TOOL_REGISTRY) == ("web_search", "web_fetch", "deep_research")
    assert len(TOOL_REGISTRY) == 3
    assert all(tool.user_visible is False for tool in TOOL_REGISTRY.values())
    assert get_tool("web_search").title == "웹 검색"
    assert get_tool("deep_research").title == "심층 리서치"
    with pytest.raises(TypeError):
        TOOL_REGISTRY["evil"] = get_tool("web_search")  # type: ignore[index]
    with pytest.raises(ValueError):
        get_tool("evil")


def test_web_config_defaults_off_and_firecrawl_requires_server_key():
    settings = Settings.from_values()
    assert settings.web_provider == "off"
    assert settings.firecrawl_api_key is None
    assert settings.web_timeout_seconds == 15.0

    with pytest.raises(ConfigError):
        Settings.from_values(web_provider="firecrawl")
    configured = Settings.from_values(
        web_provider="firecrawl",
        firecrawl_api_key="fc-secret-server-only",
        web_timeout_seconds="9",
    )
    assert configured.web_provider == "firecrawl"
    assert configured.firecrawl_api_key == "fc-secret-server-only"
    assert "fc-secret-server-only" not in repr(configured)

    for bad in ("31", "0", "not-a-number"):
        with pytest.raises(ConfigError):
            Settings.from_values(web_timeout_seconds=bad)


def test_public_url_policy_rejects_local_private_userinfo_and_odd_numeric_hosts():
    bad = [
        "file:///etc/passwd",
        "http://localhost/",
        "https://sub.localhost/path",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "https://user:pass@example.com/",
        "http://2130706433/",
        "http://127.1/",
    ]
    for url in bad:
        with pytest.raises(ValueError):
            normalize_public_url(url)


def test_public_url_policy_normalizes_idna_and_strips_fragment():
    normalized = normalize_public_url("https://광주.kr/path?q=1#frag")
    assert normalized.startswith("https://xn--")
    assert normalized.endswith("/path?q=1")
    assert "#" not in normalized


@pytest.mark.asyncio
async def test_off_and_mock_providers_make_zero_network_calls():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be called")

    transport = httpx.MockTransport(handler)
    off = create_web_provider(Settings(web_provider="off"), transport=transport)
    assert isinstance(off, OffWebProvider)
    with pytest.raises(WebToolError, match="활성화"):
        await off.search("테스트")

    mock = create_web_provider(Settings(web_provider="mock"), transport=transport)
    assert isinstance(mock, MockWebProvider)
    results = await mock.search("무료 AI API", 2)
    page = await mock.fetch("https://example.com/page")
    assert len(results) == 2
    assert results[0].provider == "mock"
    assert page.source_type == "fetch"
    assert calls == 0


@pytest.mark.asyncio
async def test_firecrawl_search_uses_fixed_v2_endpoint_and_safe_shape():
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "success": True,
            "data": {"web": [
                {"title": "Example result", "url": "https://example.com/a#section", "description": "A useful result"},
                {"title": "Unsafe result", "url": "http://127.0.0.1/private", "description": "must be dropped"},
            ]},
        })

    settings = Settings.from_values(web_provider="firecrawl", firecrawl_api_key="fc-test-secret")
    provider = FirecrawlWebProvider(settings, httpx.MockTransport(handler))
    results = await provider.search("current AI news", 3)

    assert seen["url"] == FIRECRAWL_ORIGIN + "/v2/search"
    assert seen["body"] == {"query": "current AI news", "limit": 3, "sources": ["web"]}
    assert seen["headers"]["authorization"] == "Bearer fc-test-secret"
    assert len(results) == 1
    assert results[0].url == "https://example.com/a"
    assert results[0].provider == "firecrawl"
    assert results[0].source_type == "search"
    assert "fc-test-secret" not in json.dumps(results[0].public_dict())


@pytest.mark.asyncio
async def test_firecrawl_scrape_uses_fixed_v2_endpoint_and_bounded_evidence():
    seen = {}
    long_markdown = "x" * 5000

    async def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "success": True,
            "data": {
                "markdown": long_markdown,
                "metadata": {"title": "T" * 600, "sourceURL": "https://example.com/final#ignored"},
            },
        })

    provider = FirecrawlWebProvider(
        Settings.from_values(web_provider="firecrawl", firecrawl_api_key="fc-test"),
        httpx.MockTransport(handler),
    )
    evidence = await provider.fetch("https://example.com/start")
    assert seen["url"] == FIRECRAWL_ORIGIN + "/v2/scrape"
    assert seen["body"] == {"url": "https://example.com/start", "formats": ["markdown"], "onlyMainContent": True}
    assert evidence.url == "https://example.com/final"
    assert len(evidence.title) <= 301
    assert len(evidence.snippet) <= 2001
    assert evidence.source_type == "fetch"


@pytest.mark.asyncio
async def test_firecrawl_does_not_follow_provider_redirect():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    provider = FirecrawlWebProvider(
        Settings.from_values(web_provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebToolError) as info:
        await provider.search("test")
    assert info.value.code == "web_request_failed"
    assert calls == 1


@pytest.mark.asyncio
async def test_firecrawl_response_byte_cap_is_enforced():
    async def handler(request):
        return httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1))

    provider = FirecrawlWebProvider(
        Settings.from_values(web_provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebToolError) as info:
        await provider.search("test")
    assert info.value.code == "web_response_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "web_auth"), (403, "web_auth"), (429, "web_busy"), (500, "web_unavailable")],
)
async def test_firecrawl_errors_are_normalized_without_body_leak(status, code):
    async def handler(request):
        return httpx.Response(status, json={"error": "PRIVATE-UPSTREAM-DETAIL"})

    provider = FirecrawlWebProvider(
        Settings.from_values(web_provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(WebToolError) as info:
        await provider.search("test")
    assert info.value.code == code
    assert "PRIVATE-UPSTREAM-DETAIL" not in info.value.user_message
    assert "fc-secret" not in info.value.user_message


@pytest.mark.asyncio
async def test_firecrawl_timeout_and_malformed_json_are_normalized():
    async def timeout_handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    provider = FirecrawlWebProvider(
        Settings.from_values(web_provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(WebToolError) as timeout_info:
        await provider.search("test")
    assert timeout_info.value.code == "web_timeout"

    async def malformed_handler(request):
        return httpx.Response(200, content=b"not-json")

    provider2 = FirecrawlWebProvider(
        Settings.from_values(web_provider="firecrawl", firecrawl_api_key="fc-secret"),
        httpx.MockTransport(malformed_handler),
    )
    with pytest.raises(WebToolError) as malformed_info:
        await provider2.search("test")
    assert malformed_info.value.code == "web_malformed"


def test_web_search_ui_remains_disabled_and_css_unchanged():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")
    assert "웹 검색 · 준비 중" in html
    assert "웹 검색" in html
    assert "심층 리서치" in html
    assert 'class="tool-button" disabled' in html
    assert (root / "static/styles.css").read_bytes() == (
        repo / "reference/business-62-padiem-chat-v1/styles.css"
    ).read_bytes()
