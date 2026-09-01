from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import ipaddress
import json
import re
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit
import uuid

import httpx

from .contracts import Evidence

FIRECRAWL_ORIGIN = "https://api.firecrawl.dev"
DAUM_SEARCH_ORIGIN = "https://dapi.kakao.com"
DAUM_WEB_SEARCH_PATH = "/v2/search/web"
MAX_PROVIDER_RESPONSE_BYTES = 1_048_576
MAX_QUERY_CHARS = 2_000
MAX_RESULTS = 5
MAX_TITLE_CHARS = 300
MAX_SNIPPET_CHARS = 2_000
MAX_URL_CHARS = 2_048
MAX_TIMEOUT_SECONDS = 30.0
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home")
_ALLOWED_PROVIDERS = frozenset({"off", "mock", "firecrawl", "daum"})
_ALLOWED_FIRECRAWL_PATHS = frozenset({"/v2/search", "/v2/scrape"})
_ALLOWED_DAUM_SORTS = frozenset({"accuracy", "recency"})


class WebRuntimeError(RuntimeError):
    """Safe, normalized failure exposed by the shared read-only web runtime."""

    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class WebRuntimeConfig:
    provider: str = "off"
    firecrawl_api_key: str | None = field(default=None, repr=False)
    daum_rest_api_key: str | None = field(default=None, repr=False)
    daum_search_sort: str = "accuracy"
    web_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower() if isinstance(self.provider, str) else ""
        if provider not in _ALLOWED_PROVIDERS:
            raise ValueError("provider must be one of: off, mock, firecrawl, daum")
        object.__setattr__(self, "provider", provider)

        timeout = self.web_timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < float(timeout) <= MAX_TIMEOUT_SECONDS
        ):
            raise ValueError(f"web_timeout_seconds must be > 0 and <= {MAX_TIMEOUT_SECONDS:g}")
        object.__setattr__(self, "web_timeout_seconds", float(timeout))

        firecrawl_key = self.firecrawl_api_key
        if firecrawl_key is not None:
            if not isinstance(firecrawl_key, str) or not firecrawl_key.strip():
                raise ValueError("firecrawl_api_key must be a non-empty string or None")
            object.__setattr__(self, "firecrawl_api_key", firecrawl_key.strip())
        if provider == "firecrawl" and self.firecrawl_api_key is None:
            raise ValueError("firecrawl provider requires a server-side API key")

        daum_key = self.daum_rest_api_key
        if daum_key is not None:
            if not isinstance(daum_key, str) or not daum_key.strip():
                raise ValueError("daum_rest_api_key must be a non-empty string or None")
            object.__setattr__(self, "daum_rest_api_key", daum_key.strip())
        if provider == "daum" and self.daum_rest_api_key is None:
            raise ValueError("daum provider requires a server-side REST API key")

        daum_sort = self.daum_search_sort.strip().lower() if isinstance(self.daum_search_sort, str) else ""
        if daum_sort not in _ALLOWED_DAUM_SORTS:
            raise ValueError("daum_search_sort must be accuracy or recency")
        object.__setattr__(self, "daum_search_sort", daum_sort)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "web_timeout_seconds": self.web_timeout_seconds,
            "firecrawl_configured": self.firecrawl_api_key is not None,
            "daum_configured": self.daum_rest_api_key is not None,
            "daum_search_sort": self.daum_search_sort,
        }


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


def _daum_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    without_tags = re.sub(r"<[^>]*>", " ", value)
    return _bounded_text(html.unescape(without_tags), limit)


def normalize_public_url(value: str) -> str:
    """Normalize a literal public URL and reject obvious local/private targets.

    This is a literal-host policy. It does not perform DNS resolution and therefore
    does not claim DNS-rebinding protection. Network providers in this module call
    fixed provider origins; target URLs are sent as data only when an approved
    extractor provider is explicitly configured.
    """

    if not isinstance(value, str):
        raise ValueError("URL must be a string")
    raw = value.strip()
    if not raw or len(raw) > MAX_URL_CHARS or any(ord(ch) < 32 for ch in raw):
        raise ValueError("URL is empty, too long, or contains control characters")

    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL is malformed") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("only public http/https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL host is required")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL userinfo is not allowed")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("URL port is invalid")

    host = parsed.hostname.rstrip(".").lower()
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("URL host is invalid") from exc

    if (
        ascii_host == "localhost"
        or ascii_host == "localhost.localdomain"
        or ascii_host == "metadata.google.internal"
        or any(ascii_host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES)
    ):
        raise ValueError("internal network hosts are not allowed")

    try:
        address = ipaddress.ip_address(ascii_host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", ascii_host):
            raise ValueError("ambiguous numeric host notation is not allowed")
    else:
        mapped = getattr(address, "ipv4_mapped", None)
        candidate = mapped or address
        if not candidate.is_global:
            raise ValueError("non-global IP addresses are not allowed")

    netloc = ascii_host
    if ":" in ascii_host:
        netloc = f"[{ascii_host}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def _query(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("query must be a string")
    query = value.strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must contain 1 to {MAX_QUERY_CHARS} characters")
    return query


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RESULTS:
        raise ValueError(f"limit must be between 1 and {MAX_RESULTS}")
    return value


def _evidence(*, title: Any, url: Any, snippet: Any, provider: str, source_type: str) -> Evidence | None:
    if not isinstance(url, str):
        return None
    try:
        safe_url = normalize_public_url(url)
    except ValueError:
        return None
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
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
        raise WebRuntimeError("web_tools_off", "web runtime is disabled", 503)

    async def fetch(self, url: str) -> Evidence:
        normalize_public_url(url)
        raise WebRuntimeError("web_tools_off", "web runtime is disabled", 503)


class MockWebProvider:
    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        safe_query = _query(query)
        count = _limit(limit)
        return [
            Evidence(
                id=f"mock-search-{index}",
                title=f"Mock search result {index}",
                url=f"https://example.com/search/{index}",
                snippet=f"Mock result for {safe_query[:120]}",
                retrieved_at="2000-01-01T00:00:00Z",
                provider="mock",
                source_type="search",
            )
            for index in range(1, count + 1)
        ]

    async def fetch(self, url: str) -> Evidence:
        safe_url = normalize_public_url(url)
        return Evidence(
            id="mock-fetch-1",
            title="Mock web page",
            url=safe_url,
            snippet="Mock page content; no network request was made.",
            retrieved_at="2000-01-01T00:00:00Z",
            provider="mock",
            source_type="fetch",
        )


class FirecrawlWebProvider:
    def __init__(self, config: WebRuntimeConfig, transport: httpx.AsyncBaseTransport | None = None):
        if config.provider != "firecrawl" or not config.firecrawl_api_key:
            raise ValueError("Firecrawl provider requires firecrawl configuration")
        self._api_key = config.firecrawl_api_key
        self._timeout_seconds = config.web_timeout_seconds
        self._transport = transport

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if path not in _ALLOWED_FIRECRAWL_PATHS:
            raise RuntimeError("unapproved Firecrawl path")
        timeout = httpx.Timeout(
            connect=min(self._timeout_seconds, 8.0),
            read=self._timeout_seconds,
            write=min(self._timeout_seconds, 8.0),
            pool=min(self._timeout_seconds, 8.0),
        )
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout, follow_redirects=False) as client:
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
                            raise WebRuntimeError(
                                "web_response_too_large",
                                "web provider response exceeded the safe size limit",
                                502,
                            )
                        raw.extend(chunk)
        except WebRuntimeError:
            raise
        except httpx.TimeoutException as exc:
            raise WebRuntimeError("web_timeout", "web provider timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise WebRuntimeError("web_unavailable", "web provider transport failed", 502) from exc

        if status in {401, 403}:
            raise WebRuntimeError("web_auth", "web provider authentication failed", 503)
        if status == 429:
            raise WebRuntimeError("web_busy", "web provider is rate limited", 503)
        if status >= 500:
            raise WebRuntimeError("web_unavailable", "web provider is unavailable", 502)
        if status < 200 or status >= 300:
            raise WebRuntimeError("web_request_failed", "web provider rejected the request", 502)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebRuntimeError("web_malformed", "web provider returned malformed data", 502) from exc
        if not isinstance(data, dict) or data.get("success") is False:
            raise WebRuntimeError("web_malformed", "web provider returned malformed data", 502)
        return data

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        safe_query = _query(query)
        safe_limit = _limit(limit)
        data = await self._post("/v2/search", {"query": safe_query, "limit": safe_limit, "sources": ["web"]})
        payload = data.get("data")
        if isinstance(payload, dict):
            items = payload.get("web", [])
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        if not isinstance(items, list):
            raise WebRuntimeError("web_malformed", "web search result shape is invalid", 502)
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
            raise WebRuntimeError("web_malformed", "web page result shape is invalid", 502)
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
            raise WebRuntimeError("unsafe_web_result", "web provider returned an unsafe source URL", 502)
        return evidence


class DaumWebProvider:
    """Daum Search for search grounding, with optional Firecrawl page extraction.

    Search traffic always goes to Kakao's fixed Daum Search origin. Firecrawl is
    never used for search in this provider; when a Firecrawl key is also configured,
    it is only an optional extractor for explicit page-fetch features.
    """

    def __init__(self, config: WebRuntimeConfig, transport: httpx.AsyncBaseTransport | None = None):
        if config.provider != "daum" or not config.daum_rest_api_key:
            raise ValueError("Daum provider requires daum configuration")
        self._api_key = config.daum_rest_api_key
        self._search_sort = config.daum_search_sort
        self._timeout_seconds = config.web_timeout_seconds
        self._transport = transport
        self._firecrawl_api_key = config.firecrawl_api_key

    async def _search_request(self, query: str, limit: int, sort: str) -> dict[str, Any]:
        timeout = httpx.Timeout(
            connect=min(self._timeout_seconds, 8.0),
            read=self._timeout_seconds,
            write=min(self._timeout_seconds, 8.0),
            pool=min(self._timeout_seconds, 8.0),
        )
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout, follow_redirects=False) as client:
                async with client.stream(
                    "GET",
                    DAUM_SEARCH_ORIGIN + DAUM_WEB_SEARCH_PATH,
                    headers={
                        "Authorization": f"KakaoAK {self._api_key}",
                        "Accept": "application/json",
                    },
                    params={
                        "query": query,
                        "sort": sort,
                        "page": 1,
                        "size": limit,
                    },
                ) as response:
                    status = response.status_code
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                            raise WebRuntimeError(
                                "web_response_too_large",
                                "web provider response exceeded the safe size limit",
                                502,
                            )
                        raw.extend(chunk)
        except WebRuntimeError:
            raise
        except httpx.TimeoutException as exc:
            raise WebRuntimeError("web_timeout", "web provider timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise WebRuntimeError("web_unavailable", "web provider transport failed", 502) from exc

        if status in {401, 403}:
            raise WebRuntimeError("web_auth", "web provider authentication failed", 503)
        if status == 429:
            raise WebRuntimeError("web_busy", "web provider is rate limited", 503)
        if status >= 500:
            raise WebRuntimeError("web_unavailable", "web provider is unavailable", 502)
        if status < 200 or status >= 300:
            raise WebRuntimeError("web_request_failed", "web provider rejected the request", 502)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebRuntimeError("web_malformed", "web provider returned malformed data", 502) from exc
        if not isinstance(data, dict) or not isinstance(data.get("documents", []), list):
            raise WebRuntimeError("web_malformed", "web search result shape is invalid", 502)
        return data

    async def search_with_sort(self, query: str, limit: int = 5, *, sort: str = "accuracy") -> list[Evidence]:
        safe_query = _query(query)
        safe_limit = _limit(limit)
        safe_sort = sort.strip().lower() if isinstance(sort, str) else ""
        if safe_sort not in _ALLOWED_DAUM_SORTS:
            raise ValueError("sort must be accuracy or recency")
        data = await self._search_request(safe_query, safe_limit, safe_sort)
        items = data.get("documents", [])
        result: list[Evidence] = []
        for item in items[:safe_limit]:
            if not isinstance(item, dict):
                continue
            if not isinstance(item.get("url"), str):
                continue
            try:
                safe_url = normalize_public_url(item["url"])
            except ValueError:
                continue
            result.append(
                Evidence(
                    id=f"ev-{uuid.uuid4().hex[:12]}",
                    title=_daum_text(item.get("title"), MAX_TITLE_CHARS) or safe_url,
                    url=safe_url,
                    snippet=_daum_text(item.get("contents"), MAX_SNIPPET_CHARS),
                    retrieved_at=_now(),
                    provider="daum",
                    source_type="search",
                )
            )
        return result

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        return await self.search_with_sort(query, limit, sort=self._search_sort)

    async def fetch(self, url: str) -> Evidence:
        safe_url = normalize_public_url(url)
        if not self._firecrawl_api_key:
            raise WebRuntimeError(
                "web_fetch_unavailable",
                "page fetch is not configured for the search provider",
                503,
            )
        extractor_config = WebRuntimeConfig(
            provider="firecrawl",
            firecrawl_api_key=self._firecrawl_api_key,
            web_timeout_seconds=self._timeout_seconds,
        )
        extractor = FirecrawlWebProvider(extractor_config, transport=self._transport)
        return await extractor.fetch(safe_url)


def create_web_provider(
    config: WebRuntimeConfig | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> WebProvider:
    resolved = config or WebRuntimeConfig()
    if resolved.provider == "off":
        return OffWebProvider()
    if resolved.provider == "mock":
        return MockWebProvider()
    if resolved.provider == "firecrawl":
        return FirecrawlWebProvider(resolved, transport=transport)
    if resolved.provider == "daum":
        return DaumWebProvider(resolved, transport=transport)
    raise RuntimeError("unreachable web provider configuration")
