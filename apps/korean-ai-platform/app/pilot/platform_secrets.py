"""Generic platform-owned multi-provider credential plane for Business 14.

This module defines the credential-source contract shared by every
platform-owned upstream Provider. The first concrete registration is Agnes AI
(see ``app/pilot/platform.py``), but this module is intentionally Provider-agnostic:
any Provider is onboarded one at a time through :func:`register_platform_provider`
with its own credential binding and a fixed upstream origin.

Credential sources
-------------------
- ``platform_secret`` — B14 server owns the Provider account/key; the secret is
  read from a server-side environment variable (the *binding name*), never from
  the request. The secret value is never logged, returned, stored, or reused.
- ``request_byok`` — the caller supplies a per-request key (handled by the
  separate BYOK gateway path; this plane only records the source).
- ``none`` — no credential required (e.g. a public endpoint).

Security invariants enforced here:
- fixed/server-configured upstream origin only (no caller-supplied URL);
- host allow-list per Provider (defense in depth on top of SSRF validation);
- cross-Provider key isolation (each Provider reads only its own binding);
- missing required secret fails closed (``resolve_secret`` returns ``""``).
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from app.pilot.errors import PilotNotConfigured


class CredentialSource(str, Enum):
    """Minimum supported credential-source contract for platform Providers."""

    PLATFORM_SECRET = "platform_secret"
    REQUEST_BYOK = "request_byok"
    NONE = "none"


@dataclass(frozen=True)
class PlatformProviderSpec:
    """A registered platform-owned upstream Provider (non-secret metadata only)."""

    provider_id: str
    credential_source: CredentialSource
    credential_binding_name: str
    base_origin: str
    allowed_hosts: tuple[str, ...] = ()
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id is required")
        if not isinstance(self.credential_source, CredentialSource):
            raise ValueError("credential_source must be a CredentialSource")
        if not self.credential_binding_name:
            raise ValueError("credential_binding_name is required")
        _validate_origin(self.base_origin, self.allowed_hosts)
        if self.credential_source == CredentialSource.PLATFORM_SECRET and not self.allowed_hosts:
            raise ValueError(
                "platform_secret providers must declare allowed_hosts"
            )


_PLATFORM_PROVIDERS: dict[str, PlatformProviderSpec] = {}


def register_platform_provider(spec: PlatformProviderSpec) -> None:
    """Register (or replace) a platform-owned Provider.

    Generic by design: onboarding Agnes AI or any later Provider is a single
    ``register_platform_provider(...)`` call with that Provider's own binding
    name and fixed origin. No Provider-specific code path is added here.
    """
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
    """Return the platform secret for ``spec``, or ``""`` if absent/placeholder.

    The secret value is NEVER logged, stored in metadata, or returned outside
    the single outbound Authorization header of the Provider ``spec`` describes.
    Cross-Provider reuse is structurally impossible: this function reads only
    ``spec.credential_binding_name``.
    """
    if spec.credential_source != CredentialSource.PLATFORM_SECRET:
        return ""
    raw = os.environ.get(spec.credential_binding_name, "")
    if not raw:
        return ""
    if _looks_like_placeholder(raw):
        return ""
    return raw


def is_secret_present(spec: PlatformProviderSpec) -> bool:
    """Eligibility check: a platform_secret Provider is eligible iff its secret exists."""
    return bool(resolve_secret(spec))


def _validate_origin(origin: str, allowed_hosts: tuple[str, ...]) -> None:
    """Validate a fixed Provider origin (SSRF + host allow-list)."""
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
