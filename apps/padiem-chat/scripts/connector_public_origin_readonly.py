"""#4139 exact-host, read-only endpoint diagnostic for existing Connector ingress.

This deliberately cannot deploy, publish DNS/routes, call a model, authenticate
an owner, register a PC, or read/use cookies, credentials or private services.
An HTTP response never proves authenticated owner consent, WSS pairing or DPAPI.
"""
from __future__ import annotations

from http.client import HTTPSConnection, HTTPException
import socket
import ssl
from typing import Any

# Product-owned, EXACT host/path; no user-configurable URL or arbitrary fetch.
_ISOLATED_HOST = "connector-acceptance.padiem.net"
_OWNER_SETUP_PATH = "/api/claw/connector/enrollments/setup"


def probe_isolated_owner_setup(
    *, resolver: Any = socket.getaddrinfo,
    connection_factory: Any = HTTPSConnection,
    tls_context_factory: Any = ssl.create_default_context,
) -> dict[str, Any]:
    """Bounded metadata only, no redirects, auth, response body or URL echo."""
    result: dict[str, Any] = {
        "dns_resolves": False,
        "https_responds": False,
        "owner_setup_http_status": None,
        "owner_authenticated": False,
        "wss_pairing_proven": False,
        "changed_cloudflare_or_pc": False,
    }
    try:
        addresses = resolver(_ISOLATED_HOST, 443, type=socket.SOCK_STREAM)
        result["dns_resolves"] = bool(addresses)
    except (OSError, ValueError, TypeError):
        return result
    if not result["dns_resolves"]:
        return result

    connection = None
    try:
        # System trust store & hostname verification. No requests.Session,
        # system proxy, redirects, bearer, cookie, body or user-controlled URL.
        connection = connection_factory(
            _ISOLATED_HOST, port=443, timeout=3.0,
            context=tls_context_factory(),
        )
        connection.request(
            "GET", _OWNER_SETUP_PATH,
            headers={"Accept": "text/html", "Cache-Control": "no-store"},
        )
        response = connection.getresponse()
        status = getattr(response, "status", None)
        if type(status) is int and 100 <= status <= 599:
            result["https_responds"] = True
            result["owner_setup_http_status"] = status
    except (OSError, ValueError, TypeError, TimeoutError, HTTPException):
        pass
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
    return result


def blockers_for_probe(facts: dict[str, Any]) -> tuple[str, ...]:
    """Route existence is not identity, enrollment or WebSocket evidence."""
    if facts.get("dns_resolves") is not True:
        return ("acceptance_public_dns_unavailable",)
    if facts.get("https_responds") is not True:
        return ("acceptance_public_https_unavailable",)
    if facts.get("owner_setup_http_status") == 404:
        return ("acceptance_owner_setup_http_404",)
    # Even HTTPS 200/401/403 only establishes an HTTP response.
    return ()
