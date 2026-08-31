from __future__ import annotations

from typing import Protocol

import httpx

from padiem_ai_core import Evidence as CoreEvidence
from padiem_ai_core.web_runtime import (
    FIRECRAWL_ORIGIN,
    MAX_PROVIDER_RESPONSE_BYTES,
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    MAX_SNIPPET_CHARS,
    MAX_TITLE_CHARS,
    MAX_URL_CHARS,
    FirecrawlWebProvider as CoreFirecrawlWebProvider,
    MockWebProvider as CoreMockWebProvider,
    OffWebProvider as CoreOffWebProvider,
    WebRuntimeConfig,
    WebRuntimeError,
    normalize_public_url as core_normalize_public_url,
)

from .config import Settings
from .evidence import Evidence


class WebToolError(RuntimeError):
    def __init__(self, code: str, user_message: str, status_code: int = 502):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.status_code = status_code


class WebProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> list[CoreEvidence]: ...

    async def fetch(self, url: str) -> CoreEvidence: ...


def _url_error_message(exc: ValueError) -> str:
    message = str(exc)
    if "http/https" in message:
        return "공개 http/https URL만 사용할 수 있습니다."
    if "userinfo" in message:
        return "공개 URL에 사용자 인증정보를 포함할 수 없습니다."
    if "port" in message:
        return "URL 포트가 올바르지 않습니다."
    if "ambiguous numeric" in message:
        return "비표준 IP 주소 형식은 사용할 수 없습니다."
    if "internal network" in message or "non-global" in message:
        return "내부 또는 비공개 IP 주소는 사용할 수 없습니다."
    if "host" in message:
        return "URL 호스트가 올바르지 않습니다."
    return "URL 형식이 올바르지 않습니다."


def normalize_public_url(value: str) -> str:
    """B62 compatibility surface backed by the shared Core URL policy."""

    try:
        return core_normalize_public_url(value)
    except ValueError as exc:
        raise ValueError(_url_error_message(exc)) from exc


def _runtime_error_message(exc: WebRuntimeError) -> str:
    if exc.code == "web_tools_off":
        return "웹 도구가 아직 활성화되지 않았습니다."
    if exc.code == "web_response_too_large":
        return "웹 도구 응답이 너무 커서 안전하게 처리할 수 없습니다."
    if exc.code == "web_timeout":
        return "웹 정보를 가져오는 데 시간이 너무 오래 걸렸습니다."
    if exc.code == "web_unavailable":
        if "transport failed" in exc.message:
            return "웹 도구 연결이 잠시 불안정합니다."
        return "웹 도구가 잠시 응답하지 않습니다."
    if exc.code == "web_auth":
        return "웹 도구 설정을 확인할 수 없습니다."
    if exc.code == "web_busy":
        return "웹 검색 사용량이 많습니다. 잠시 후 다시 시도해 주세요."
    if exc.code == "web_request_failed":
        return "웹 요청을 처리하지 못했습니다."
    if exc.code == "web_malformed":
        if "search result shape" in exc.message:
            return "웹 검색 결과 형식을 확인할 수 없습니다."
        if "page result shape" in exc.message:
            return "웹 페이지 응답 형식을 확인할 수 없습니다."
        return "웹 도구 응답 형식을 확인할 수 없습니다."
    if exc.code == "unsafe_web_result":
        return "웹 페이지의 출처 주소를 안전하게 확인할 수 없습니다."
    return "웹 도구 요청을 처리하지 못했습니다."


def _translate_runtime_error(exc: WebRuntimeError) -> WebToolError:
    return WebToolError(exc.code, _runtime_error_message(exc), exc.status_code)


def _from_core_evidence(item: CoreEvidence) -> Evidence:
    if not isinstance(item.url, str):
        raise WebToolError("web_malformed", "웹 근거의 출처 주소를 확인할 수 없습니다.", 502)
    return Evidence(
        id=item.id.replace("ev-", "ev_", 1),
        title=item.title,
        url=item.url,
        snippet=item.snippet,
        retrieved_at=item.retrieved_at,
        provider=item.provider,
        source_type=item.source_type,
    )


class OffWebProvider:
    def __init__(self):
        self._core = CoreOffWebProvider()

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        try:
            await self._core.search(query, limit=limit)
        except WebRuntimeError as exc:
            raise _translate_runtime_error(exc) from exc
        raise RuntimeError("off provider unexpectedly returned")

    async def fetch(self, url: str) -> Evidence:
        try:
            await self._core.fetch(url)
        except WebRuntimeError as exc:
            raise _translate_runtime_error(exc) from exc
        raise RuntimeError("off provider unexpectedly returned")


class MockWebProvider:
    def __init__(self):
        self._core = CoreMockWebProvider()

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        try:
            core_items = await self._core.search(query, limit=limit)
        except WebRuntimeError as exc:
            raise _translate_runtime_error(exc) from exc
        safe_query = query.strip()
        return [
            Evidence(
                id=f"mock_search_{index}",
                title=f"모의 검색 결과 {index}",
                url=item.url or f"https://example.com/search/{index}",
                snippet=f"‘{safe_query[:120]}’에 대한 모의 결과입니다. 실제 웹 호출은 없습니다.",
                retrieved_at="2000-01-01T00:00:00Z",
                provider="mock",
                source_type="search",
            )
            for index, item in enumerate(core_items, start=1)
        ]

    async def fetch(self, url: str) -> Evidence:
        try:
            item = await self._core.fetch(url)
        except WebRuntimeError as exc:
            raise _translate_runtime_error(exc) from exc
        return Evidence(
            id="mock_fetch_1",
            title="모의 웹 페이지",
            url=item.url or normalize_public_url(url),
            snippet="모의 페이지 내용입니다. 실제 웹 호출은 없습니다.",
            retrieved_at="2000-01-01T00:00:00Z",
            provider="mock",
            source_type="fetch",
        )


class FirecrawlWebProvider:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if settings.web_provider != "firecrawl" or not settings.firecrawl_api_key:
            raise ValueError("Firecrawl provider requires configured server settings")
        config = WebRuntimeConfig(
            provider="firecrawl",
            firecrawl_api_key=settings.firecrawl_api_key,
            web_timeout_seconds=settings.web_timeout_seconds,
        )
        self._core = CoreFirecrawlWebProvider(config, transport=transport)

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        try:
            items = await self._core.search(query, limit=limit)
        except WebRuntimeError as exc:
            raise _translate_runtime_error(exc) from exc
        return [_from_core_evidence(item) for item in items]

    async def fetch(self, url: str) -> Evidence:
        try:
            item = await self._core.fetch(url)
        except WebRuntimeError as exc:
            raise _translate_runtime_error(exc) from exc
        return _from_core_evidence(item)


def create_web_provider(
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> WebProvider:
    if settings.web_provider == "off":
        return OffWebProvider()
    if settings.web_provider == "mock":
        return MockWebProvider()
    if settings.web_provider == "firecrawl":
        return FirecrawlWebProvider(settings, transport=transport)
    raise RuntimeError("unreachable web provider configuration")
