"""Generic platform-owned multi-provider credential plane for Business 14.

Provider metadata contains no secret values. Each platform-owned Provider has a
fixed HTTPS origin, its own credential binding, an allow-list, and an API style
used only by the bounded transport dispatcher.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


class CredentialSource(str, Enum):
    PLATFORM_SECRET = "platform_secret"
    REQUEST_BYOK = "request_byok"
    NONE = "none"


_ALLOWED_API_STYLES = frozenset({"chat_completions", "responses"})


@dataclass(frozen=True)
class PlatformProviderSpec:
    """A registered platform-owned upstream Provider (non-secret metadata only)."""

    provider_id: str
    credential_source: CredentialSource
    credential_binding_name: str
    base_origin: str
    allowed_hosts: tuple[str, ...] = ()
    enabled: bool = True
    api_style: str = "chat_completions"

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id is required")
        if not isinstance(self.credential_source, CredentialSource):
            raise ValueError("credential_source must be a CredentialSource")
        if not self.credential_binding_name:
            raise ValueError("credential_binding_name is required")
        if self.api_style not in _ALLOWED_API_STYLES:
            raise ValueError(f"unsupported platform provider api_style: {self.api_style}")
        _validate_origin(self.base_origin, self.allowed_hosts)
        if self.credential_source == CredentialSource.PLATFORM_SECRET and not self.allowed_hosts:
            raise ValueError("platform_secret providers must declare allowed_hosts")


_PLATFORM_PROVIDERS: dict[str, PlatformProviderSpec] = {}


def register_platform_provider(spec: PlatformProviderSpec) -> None:
    global _PLATFORM_PROVIDERS
    _PLATFORM_PROVIDERS[spec.provider_id] = spec


def get_platform_provider(provider_id: str) -> PlatformProviderSpec | None:
    return _PLATFORM_PROVIDERS.get(provider_id)


def list_platform_providers() -> list[PlatformProviderSpec]:
    return list(_PLATFORM_PROVIDERS.values())


def reset_platform_providers() -> None:
    """Clear the registry (used by tests to isolate registrations)."""
    _PLATFORM_PROVIDERS.clear()


_PLACEHOLDER_SUBSTRINGS = (
    "your-",
    "sk-your",
    "test-key",
    "demo-key",
    "placeholder",
    "example",
    "$agnes",
    "$openrouter",
    "$opencode",
    "change-me",
    "xxxx",
)


def _looks_like_placeholder(value: str) -> bool:
    low = value.strip().lower()
    if len(low) < 8:
        return True
    for token in _PLACEHOLDER_SUBSTRINGS:
        if token in low:
            return True
    return False


def resolve_secret(spec: PlatformProviderSpec) -> str:
    """Return only this Provider's platform secret, or ``""`` when unavailable."""
    if spec.credential_source != CredentialSource.PLATFORM_SECRET:
        return ""
    raw = os.environ.get(spec.credential_binding_name, "")
    if not raw or _looks_like_placeholder(raw):
        return ""
    return raw


def is_secret_present(spec: PlatformProviderSpec) -> bool:
    return bool(resolve_secret(spec))


def _validate_origin(origin: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlparse(origin)
    if parsed.scheme != "https":
        raise ValueError("platform provider base origin must use https://")
    if parsed.username or parsed.password:
        raise ValueError("platform provider base origin must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("platform provider base origin must not contain query/fragment")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("platform provider base origin must have a hostname")
    if host in ("localhost", "localhost.localdomain", "local", "broadcasthost"):
        raise ValueError("platform provider base origin must not point to localhost")
    if allowed_hosts and host not in allowed_hosts:
        raise ValueError(f"platform provider host {host} not in allow-list")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return
    if (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_multicast
        or addr.is_reserved
    ):
        raise ValueError("platform provider base origin must not point to a non-routable address")
