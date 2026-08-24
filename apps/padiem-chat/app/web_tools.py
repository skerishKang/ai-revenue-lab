from __future__ import annotations

import ipaddress
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import Settings
from .evidence import Evidence

FIRECRAWL_ORIGIN = "https://api.firecrawl.dev"
MAX_PROVIDER_RESPONSE_BYTES = 1_048_576
MAX_QUERY_CHARS = 2_000
MAX_RESULTS = 5
MAX_TITLE_CHARS = 300
MAX_SNIPPET_CHARS = 2_000
MAX_URL_CHARS = 2_048
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home")


class WebToolError(RuntimeError):
    def __init__(self, code: str, user_message: str, status_code: int = 502):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.status_code = status_code


class WebProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> list[Evidence]: ...
    async def fetch(self, url: str) -> Evidence: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def normalize_public_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("URL 형식이 올바르지 않습니다.")
    raw = value.strip()
    if not raw or len(raw) > MAX_URL_CHARS or any(ord(ch) < 32 for ch in raw):
        raise ValueError("URL 형식이 올바르지 않습니다.")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL 형식이 올바르지 않습니다.") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("공개 http/https URL만 사용할 수 있습니다.")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("공개 URL에 사용자 인증정보를 포함할 수 없습니다.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("URL 포트가 올바르지 않습니다.")

    host = parsed.hostname.rstrip(".").lower()
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("URL 호스트가 올바르지 않습니다.") from exc

    if (
        ascii_host == "localhost"
        or ascii_host == "localhost.localdomain"
        or ascii_host == "metadata.google.internal"
        or any(ascii_host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES)
    ):
        raise ValueError("내부 네트워크 주소는 사용할 수 없습니다.")

    try:
        address = ipaddress.ip_address(ascii_host)
    except ValueError:
        # Reject numeric-looking alternative IPv4 notations such as 2130706433
        # or dotted forms that URL stacks may reinterpret as an IP address.
        if re.fullmatch(r"[0-9.]+", ascii_host):
            raise ValueError("비표준 IP 주소 형식은 사용할 수 없습니다.")
    else:
        mapped = getattr(address, "ipv4_mapped", None)
        candidate = mapped or address
        if not candidate.is_global:
            raise ValueError("내부 또는 비공개 IP 주소는 사용할 수 없습니다.")

    netloc = ascii_host
    if ":" in ascii_host:
        netloc = f"[{ascii_host}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _query(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("검색어 형식이 올바르지 않습니다.")
    query = value.strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError("검색어는 1자 이상 2000자 이하로 입력해 주세요.")
    return query


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RESULTS:
        raise ValueError(f"검색 결과 수는 1개 이상 {MAX_RESULTS}개 이하만 지원합니다.")
    return value


def _evidence(*, title: Any, url: Any, snippet: Any, provider: str, source_type: str) -> Evidence | None:
    if not isinstance(url, str):
        return None
    try:
        safe_url = normalize_public_url(url)
    except ValueError:
        return None
    return Evidence(
        id=f"ev_{uuid.uuid4().hex[:12]}",
        title=_bounded_text(title, MAX_TITLE_CHARS) or safe_url,
        url=safe_url,
        snippet=_bounded_text(snippet, MAX_SNIPPET_CHARS),
        retrieved_at=_now(),
        provider=provider,
        source_type=source_type,
    )


class OffWebProvider:
    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        _query(query)
        _limit(limit)
        raise WebToolError("web_tools_off", "웹 도구가 아직 활성화되지 않았습니다.", 503)

    async def fetch(self, url: str) -> Evidence:
        normalize_public_url(url)
        raise WebToolError("web_tools_off", "웹 도구가 아직 활성화되지 않았습니다.", 503)


class MockWebProvider:
    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        safe_query = _query(query)
        count = _limit(limit)
        return [
            Evidence(
                id=f"mock_search_{index}",
                title=f"모의 검색 결과 {index}",
                url=f"https://example.com/search/{index}",
                snippet=f"‘{safe_query[:120]}’에 대한 모의 결과입니다. 실제 웹 호출은 없습니다.",
                retrieved_at="2000-01-01T00:00:00Z",
                provider="mock",
                source_type="search",
            )
            for index in range(1, count + 1)
        ]

    async def fetch(self, url: str) -> Evidence:
        safe_url = normalize_public_url(url)
        return Evidence(
            id="mock_fetch_1",
            title="모의 웹 페이지",
            url=safe_url,
            snippet="모의 페이지 내용입니다. 실제 웹 호출은 없습니다.",
            retrieved_at="2000-01-01T00:00:00Z",
            provider="mock",
            source_type="fetch",
        )


class FirecrawlWebProvider:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if settings.web_provider != "firecrawl" or not settings.firecrawl_api_key:
            raise ValueError("Firecrawl provider requires configured server settings")
        self._api_key = settings.firecrawl_api_key
        self._timeout_seconds = settings.web_timeout_seconds
        self._transport = transport

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if path not in {"/v2/search", "/v2/scrape"}:
            raise RuntimeError("unapproved Firecrawl path")
        timeout = httpx.Timeout(
            connect=min(self._timeout_seconds, 8.0),
            read=self._timeout_seconds,
            write=min(self._timeout_seconds, 8.0),
            pool=min(self._timeout_seconds, 8.0),
        )
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    FIRECRAWL_ORIGIN + path,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                ) as response:
                    status = response.status_code
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                            raise WebToolError(
                                "web_response_too_large",
                                "웹 도구 응답이 너무 커서 안전하게 처리할 수 없습니다.",
                                502,
                            )
                        raw.extend(chunk)
        except WebToolError:
            raise
        except httpx.TimeoutException as exc:
            raise WebToolError("web_timeout", "웹 정보를 가져오는 데 시간이 너무 오래 걸렸습니다.", 504) from exc
        except httpx.HTTPError as exc:
            raise WebToolError("web_unavailable", "웹 도구 연결이 잠시 불안정합니다.", 502) from exc

        if status in {401, 403}:
            raise WebToolError("web_auth", "웹 도구 설정을 확인할 수 없습니다.", 503)
        if status == 429:
            raise WebToolError("web_busy", "웹 검색 사용량이 많습니다. 잠시 후 다시 시도해 주세요.", 503)
        if status >= 500:
            raise WebToolError("web_unavailable", "웹 도구가 잠시 응답하지 않습니다.", 502)
        if status < 200 or status >= 300:
            raise WebToolError("web_request_failed", "웹 요청을 처리하지 못했습니다.", 502)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebToolError("web_malformed", "웹 도구 응답 형식을 확인할 수 없습니다.", 502) from exc
        if not isinstance(data, dict) or data.get("success") is False:
            raise WebToolError("web_malformed", "웹 도구 응답 형식을 확인할 수 없습니다.", 502)
        return data

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        safe_query = _query(query)
        safe_limit = _limit(limit)
        data = await self._post(
            "/v2/search",
            {"query": safe_query, "limit": safe_limit, "sources": ["web"]},
        )
        payload = data.get("data")
        if isinstance(payload, dict):
            items = payload.get("web", [])
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        if not isinstance(items, list):
            raise WebToolError("web_malformed", "웹 검색 결과 형식을 확인할 수 없습니다.", 502)
        result: list[Evidence] = []
        for item in items[:safe_limit]:
            if not isinstance(item, dict):
                continue
            evidence = _evidence(
                title=item.get("title"),
                url=item.get("url"),
                snippet=item.get("description") or item.get("markdown") or item.get("snippet"),
                provider="firecrawl",
                source_type="search",
            )
            if evidence is not None:
                result.append(evidence)
        return result

    async def fetch(self, url: str) -> Evidence:
        safe_url = normalize_public_url(url)
        data = await self._post(
            "/v2/scrape",
            {"url": safe_url, "formats": ["markdown"], "onlyMainContent": True},
        )
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise WebToolError("web_malformed", "웹 페이지 응답 형식을 확인할 수 없습니다.", 502)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        returned_url = metadata.get("sourceURL") or metadata.get("url") or safe_url
        evidence = _evidence(
            title=metadata.get("title"),
            url=returned_url,
            snippet=payload.get("markdown") or payload.get("text") or metadata.get("description"),
            provider="firecrawl",
            source_type="fetch",
        )
        if evidence is None:
            raise WebToolError("unsafe_web_result", "웹 페이지의 출처 주소를 안전하게 확인할 수 없습니다.", 502)
        return evidence


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
