from __future__ import annotations

import json

import httpx
import pytest

from app.config import ConfigError, Settings
from app.web_tools import (
    TINYFISH_FETCH_ORIGIN,
    TINYFISH_SEARCH_ORIGIN,
    TinyFishWebProvider,
    create_web_provider,
)


def test_chat_tinyfish_settings_require_server_key_and_redact_it() -> None:
    with pytest.raises(ConfigError, match="TINYFISH_API_KEY"):
        Settings.from_values(web_provider="tinyfish")

    settings = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://engine.example",
        web_provider="tinyfish",
        tinyfish_api_key="tf-chat-secret",
    )
    assert settings.web_provider == "tinyfish"
    assert settings.tinyfish_api_key == "tf-chat-secret"
    assert "tf-chat-secret" not in repr(settings)


def test_chat_factory_returns_tinyfish_and_enables_auto_search_only_in_b14() -> None:
    live = create_web_provider(
        Settings.from_values(
            runtime_mode="b14",
            b14_base_url="https://engine.example",
            web_provider="tinyfish",
            tinyfish_api_key="tf-chat-secret",
        )
    )
    assert isinstance(live, TinyFishWebProvider)
    assert getattr(live, "_automatic_search_enabled") is True


@pytest.mark.asyncio
async def test_chat_tinyfish_search_and_fetch_translate_core_evidence() -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        assert request.headers["x-api-key"] == "tf-chat-secret"
        if request.method == "GET":
            assert request.url.params["query"] == "광주 AI 최신"
            return httpx.Response(
                200,
                json={
                    "query": "광주 AI 최신",
                    "results": [
                        {
                            "position": 1,
                            "site_name": "Example",
                            "title": "검색 결과",
                            "snippet": "최신 검색 스니펫",
                            "url": "https://example.com/search#frag",
                        }
                    ],
                    "total_results": 1,
                },
            )

        assert json.loads(request.content) == {
            "urls": ["https://example.com/page"],
            "format": "markdown",
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/page",
                        "final_url": "https://example.com/page#final",
                        "title": "페이지",
                        "text": "정리된 본문",
                    }
                ],
                "errors": [],
            },
        )

    settings = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://engine.example",
        web_provider="tinyfish",
        tinyfish_api_key="tf-chat-secret",
    )
    provider = TinyFishWebProvider(settings, httpx.MockTransport(handler))

    results = await provider.search("광주 AI 최신", 1)
    page = await provider.fetch("https://example.com/page#source")

    assert seen[0][0] == "GET"
    assert seen[0][1].startswith(TINYFISH_SEARCH_ORIGIN)
    assert seen[1] == ("POST", TINYFISH_FETCH_ORIGIN)
    assert results[0].provider == "tinyfish"
    assert results[0].source_type == "search"
    assert results[0].url == "https://example.com/search"
    assert page.provider == "tinyfish"
    assert page.source_type == "fetch"
    assert page.url == "https://example.com/page"


def test_chat_from_env_reads_tinyfish_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://engine.example")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "tinyfish")
    monkeypatch.setenv("TINYFISH_API_KEY", "tf-env-secret")
    settings = Settings.from_env()
    assert settings.web_provider == "tinyfish"
    assert settings.tinyfish_api_key == "tf-env-secret"
    assert "tf-env-secret" not in repr(settings)
