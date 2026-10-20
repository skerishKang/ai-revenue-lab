"""Platform-credential dispatch authorization for the public B14 Worker (#5224).

The B14 Worker is published on the account's public ``workers.dev`` subdomain,
so every mounted route is anonymously reachable. The platform-owned provider
credential is the Owner's cost, so an anonymous public request must never be
able to spend it.

The trusted caller is the existing Cloudflare Service Binding path. The B62
Chat and B54 Engine products reach B14 through the ``B14_SERVICE`` binding.
Two independent, owner-controlled signals identify that path:

1. The request carries the canonical internal Service Binding origin
   ``https://b14.internal``. A public request can never present it, because
   Cloudflare derives the request URL from the hostname that actually routed
   to the Worker and no public route resolves ``b14.internal``.
2. The request carries no Cloudflare edge client headers. The edge always
   adds ``cf-connecting-ip`` and ``cf-ray`` to a public client request, while a
   Worker-to-Worker subrequest carries only the headers the calling Worker
   explicitly set.

Either signal is sufficient. A request that carries an edge client header is
a public request and is denied before any provider dispatch.

The BYOK branch is deliberately outside this boundary: it spends the caller's
own key, not the platform-owned credential, and it keeps the existing public
customer API and the existing Cloudflare deployment configuration unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

# Canonical internal Service Binding origin. The same value is already used by
# the B54 Engine B14 transport and by the B62 Chat B14 model-authority
# transport, so this boundary reuses the existing deployment convention
# instead of introducing a second one.
INTERNAL_ORIGIN_HOST = "b14.internal"

# Cloudflare edge client headers. The public edge always adds them to a client
# request; a Worker-to-Worker subrequest never carries them.
_EDGE_CLIENT_HEADERS = ("cf-connecting-ip", "cf-ray")

_AUTHORIZED_ORIGIN_REASON = "service_binding_internal_origin"
_AUTHORIZED_SUBREQUEST_REASON = "service_binding_worker_subrequest"
_DENIED_REASON = "unauthorized_public_ingress"


@dataclass(frozen=True)
class DispatchAuthorization:
    """One immutable platform-dispatch authorization decision."""

    allowed: bool
    reason: str
    status_code: int


def _request_host(request: object) -> str:
    """Return the lowercase host of the request URL, or an empty string."""
    url = getattr(request, "url", None)
    if not isinstance(url, str):
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _has_edge_client_headers(request: object) -> bool:
    """Return True when the request carries Cloudflare edge client headers.

    An unreadable header mapping is treated as an edge request, so an
    unexpected request shape fails closed instead of being trusted.
    """
    headers = getattr(request, "headers", None)
    if headers is None:
        return True
    try:
        return any(headers.get(name) for name in _EDGE_CLIENT_HEADERS)
    except Exception:
        return True


def authorize_platform_dispatch(request: object) -> DispatchAuthorization:
    """Decide whether one request may spend the platform-owned credential.

    The decision is taken from the request origin only. A public edge request
    is denied before any provider dispatch, so an anonymous external caller
    can never spend the platform-owned credential.
    """
    if _request_host(request) == INTERNAL_ORIGIN_HOST:
        return DispatchAuthorization(
            allowed=True,
            reason=_AUTHORIZED_ORIGIN_REASON,
            status_code=200,
        )
    if not _has_edge_client_headers(request):
        return DispatchAuthorization(
            allowed=True,
            reason=_AUTHORIZED_SUBREQUEST_REASON,
            status_code=200,
        )
    return DispatchAuthorization(
        allowed=False,
        reason=_DENIED_REASON,
        status_code=401,
    )
