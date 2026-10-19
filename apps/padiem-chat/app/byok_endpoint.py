"""PADIEM Custom endpoint safety.

Customer-selected provider base URLs are customer data, not trusted routing
configuration. Only HTTPS origins with a public DNS footprint are accepted.
Redirects are never followed by the provider client, so an allowlisted endpoint
cannot bounce the owner's API key to a different host.
"""
from __future__ import annotations

import ipaddress
import json
import re
import time
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

MAX_ENDPOINT_CHARS = 2048
MAX_DNS_RESPONSE_BYTES = 64_000
DNS_CACHE_SECONDS = 60.0

_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NUMERIC_HOST = re.compile(r"^(?:0x[0-9a-f]+|[0-9]+)$", re.IGNORECASE)
_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".home.arpa",
    ".lan",
    ".corp",
    ".intranet",
)
_BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata",
}


class CustomEndpointError(ValueError):
    """The endpoint is not an acceptable HTTPS provider base URL."""

    code = "custom_endpoint_invalid"
    user_message = "API 엔드포인트는 공개 HTTPS 주소여야 합니다."


class CustomEndpointVerificationError(CustomEndpointError):
    """DNS or IP evidence shows the endpoint is not safe to call."""

    code = "custom_endpoint_unsafe"
    user_message = "안전하지 않은 API 엔드포인트라서 호출하지 않았습니다."


class CustomEndpointUnverifiedError(CustomEndpointError):
    """DNS evidence could not be obtained, so the request fails closed."""

    code = "custom_endpoint_unverified"
    user_message = "API 엔드포인트의 DNS 주소를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요."


class DnsResolver(Protocol):
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        """Return every A/AAAA address currently published for the host."""


def _normalize_host(host: str) -> str:
    lowered = host.strip().lower().rstrip(".")
    if not lowered or len(lowered) > 253:
        raise CustomEndpointError("API 엔드포인트 호스트가 올바르지 않습니다.")
    try:
        lowered = lowered.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise CustomEndpointError("API 엔드포인트 호스트가 올바르지 않습니다.") from exc
    labels = lowered.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.match(label) for label in labels):
        raise CustomEndpointError("API 엔드포인트 호스트가 올바르지 않습니다.")
    if any(label.isdigit() for label in labels) or _NUMERIC_HOST.match(lowered):
        # Decimal/octal/hex IPv4 spellings are never provider hostnames.
        raise CustomEndpointError("IP 주소 형식의 API 엔드포인트는 허용하지 않습니다.")
    if lowered in _BLOCKED_HOSTS or any(
        lowered.endswith(suffix) for suffix in _BLOCKED_SUFFIXES
    ):
        raise CustomEndpointError("내부 주소로 향하는 API 엔드포인트는 허용하지 않습니다.")
    try:
        ipaddress.ip_address(lowered)
    except ValueError:
        pass
    else:
        raise CustomEndpointError("IP 주소 형식의 API 엔드포인트는 허용하지 않습니다.")
    return lowered


def normalize_custom_endpoint(value: Any, *, default_endpoint: str) -> str:
    """Return one canonical HTTPS base URL or raise ``CustomEndpointError``.

    A missing/blank value selects the provider's built-in endpoint. User values
    may carry only an origin plus a path that is appended with the provider's
    official wire path; query strings, fragments, userinfo, non-443 ports and
    IP-literal hosts are refused before any key is stored.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return default_endpoint
    if not isinstance(value, str):
        raise CustomEndpointError("API 엔드포인트 형식이 올바르지 않습니다.")
    raw = value.strip()
    if len(raw) > MAX_ENDPOINT_CHARS:
        raise CustomEndpointError("API 엔드포인트가 너무 깁니다.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise CustomEndpointError("API 엔드포인트에 허용되지 않는 문자가 있습니다.")
    if "\\" in raw:
        raise CustomEndpointError("API 엔드포인트 형식이 올바르지 않습니다.")
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https":
        raise CustomEndpointError("API 엔드포인트는 HTTPS만 지원합니다.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise CustomEndpointError("API 엔드포인트에 사용자 정보를 넣을 수 없습니다.")
    if parts.query or parts.fragment:
        raise CustomEndpointError("API 엔드포인트에는 쿼리나 조각을 넣을 수 없습니다.")
    try:
        port = parts.port
    except ValueError as exc:
        raise CustomEndpointError("API 엔드포인트 포트가 올바르지 않습니다.") from exc
    if port not in (None, 443):
        raise CustomEndpointError("API 엔드포인트는 443 포트만 지원합니다.")
    if not parts.hostname:
        raise CustomEndpointError("API 엔드포인트 호스트가 필요합니다.")
    host = _normalize_host(parts.hostname)
    path = parts.path or ""
    if path.endswith("/"):
        path = path[:-1]
    if path and not path.startswith("/"):
        raise CustomEndpointError("API 엔드포인트 경로가 올바르지 않습니다.")
    return urlunsplit(("https", host, path, "", ""))


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


class HttpsDnsResolver:
    """Resolve A/AAAA records over DNS-over-HTTPS.

    The Workers Python runtime has no socket-backed resolver, so the same
    HTTPS path used by the provider client is used for DNS evidence. Every
    answer must be a public unicast address; a private/loopback answer blocks
    the request even when the hostname looks public.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        transport: Any | None = None,
        cache_seconds: float = DNS_CACHE_SECONDS,
    ):
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport
        self._cache_seconds = float(cache_seconds)
        self._cache: dict[str, tuple[float, tuple[str, ...]]] = {}

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        cached = self._cache.get(hostname)
        now = time.time()
        if cached is not None and cached[0] > now:
            return cached[1]
        addresses: list[str] = []
        from . import httpx_compat as httpx

        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
        ) as client:
            for record_type in ("A", "AAAA"):
                url = (
                    "https://cloudflare-dns.com/dns-query?name="
                    + hostname
                    + "&type="
                    + record_type
                )
                async with client.stream(
                    "GET",
                    url,
                    headers={"Accept": "application/dns-json"},
                ) as response:
                    if int(response.status_code) != 200:
                        raise CustomEndpointUnverifiedError(
                            "DNS 확인 서버가 응답하지 않았습니다."
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(bytes(chunk))
                        if len(raw) > MAX_DNS_RESPONSE_BYTES:
                            raise CustomEndpointUnverifiedError(
                                "DNS 응답이 허용 크기를 초과했습니다."
                            )
                try:
                    payload = json.loads(bytes(raw))
                except (ValueError, UnicodeError) as exc:
                    raise CustomEndpointUnverifiedError(
                        "DNS 응답 형식을 확인할 수 없습니다."
                    ) from exc
                if not isinstance(payload, dict):
                    raise CustomEndpointUnverifiedError(
                        "DNS 응답 형식을 확인할 수 없습니다."
                    )
                status_code = payload.get("Status", 0)
                if status_code not in (0, 3):
                    raise CustomEndpointUnverifiedError(
                        "DNS 조회가 실패했습니다."
                    )
                for answer in payload.get("Answer") or []:
                    if not isinstance(answer, dict):
                        continue
                    if answer.get("type") not in (1, 28):
                        continue
                    data = answer.get("data")
                    if isinstance(data, str):
                        addresses.append(data)
        unique = tuple(dict.fromkeys(addresses))
        self._cache[hostname] = (now + self._cache_seconds, unique)
        return unique


async def verify_public_endpoint(
    endpoint: str,
    *,
    default_endpoint: str,
    resolver: DnsResolver,
) -> str:
    """Re-validate a stored endpoint and prove every DNS answer is public."""
    normalized = normalize_custom_endpoint(endpoint, default_endpoint=default_endpoint)
    if normalized == default_endpoint:
        # Built-in provider origins are code-controlled and already shipped.
        return normalized
    host = urlsplit(normalized).hostname or ""
    try:
        addresses = await resolver.resolve(host)
    except CustomEndpointError:
        raise
    except Exception as exc:
        raise CustomEndpointUnverifiedError(
            "API 엔드포인트의 DNS 주소를 확인하지 못했습니다."
        ) from exc
    if not addresses:
        raise CustomEndpointVerificationError(
            "API 엔드포인트의 DNS 주소가 없습니다."
        )
    if any(not _is_public_address(value) for value in addresses):
        raise CustomEndpointVerificationError(
            "사설/루프백 주소로 해석되는 API 엔드포인트는 허용하지 않습니다."
        )
    return normalized
