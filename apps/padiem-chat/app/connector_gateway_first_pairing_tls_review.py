"""#4139 CENTRAL: source-only first-pairing Cloudflare TLS transport admission.

A Windows PC cannot present a *previously installed* per-device client
certificate before its first enrollment. This adapter is a narrowly scoped
alternative to the reviewed mTLS *returning-device* adapter. It recognizes
Cloudflare's incoming TLS transport metadata for ONE canonical WSS bootstrap
path; it deliberately DOES NOT authenticate or authorize a PC.

The existing canonical Broker's owner-bound one-time pairing proof, signed
counter frames, current Identity consent, post-redeem revalidation, and the
single-socket protected-install ACK are mandatory after this transport gate.
A valid HTTPS connection alone may NEVER redeem a challenge or grant any
READ/WRITE/dispatch rights. This verifier is not trusted device identity.

This module is not imported by the deployed Worker or product app. The source
flag is only a test-harness constructor guard, never a production activation.
Cloudflare request.cf is runtime-injected in a real Worker; a local synthetic
test double does not establish Cloudflare provenance.
"""
from __future__ import annotations

from typing import Any

from .canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from .connector_gateway_tls_ingress_source_review import _property

# Cloudflare may add CF-Visitor and X-Forwarded-Proto to incoming requests.
# Neither header supplies trusted TLS evidence and neither is consulted.
# Do not reject legitimate edge traffic solely because they are present.
# Refuse credential-bearing/browser-asserted metadata instead.
_FORBIDDEN_FIRST_PAIR_HEADERS = (
    "origin", "cookie", "authorization", "sec-websocket-protocol",
    "client-cert", "client-cert-chain", "cf-client-cert-sha256",
    "cf-tls-client-auth",
)


def _first_pair_headers_clean(headers: Any) -> bool:
    if not callable(getattr(headers, "get", None)):
        return False
    try:
        return all(headers.get(name) is None for name in _FORBIDDEN_FIRST_PAIR_HEADERS)
    except Exception:
        return False


FIRST_PAIRING_TLS_ONLY_PRODUCTION_WIRED = False
FIRST_PAIRING_WSS_PUBLIC_MOUNTED = False
_ALLOWED_TLS = frozenset({"TLSv1.2", "TLSv1.3"})
_CANONICAL_URL = "https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH
_CANONICAL_PATH = CONNECTOR_GATEWAY_WSS_PATH.encode("ascii")


class CloudflareFirstPairingTlsTransportReview:
    """Verify an exact Cloudflare TLS *transport*, not a client certificate.

    An unknown Worker request, a forged HTTP header, a plaintext edge
    connection, or a noncanonical WS upgrade is refused *before* the Broker
    receives a frame. Server-owned Identity and Broker proofs remain separate.
    """

    def __init__(
        self, *, incoming_worker_request: Any = None,
        source_review_authorized: bool = False,
    ) -> None:
        if source_review_authorized is not True:
            raise RuntimeError("Connector first-pairing TLS review not activated")
        self._request = incoming_worker_request

    def permits_worker_upgrade(self) -> bool:
        """Preflight before Cloudflare creates or returns a WebSocketPair.

        This proves only eligible incoming edge *transport* metadata, not a
        physical device. All existing Broker/Identity/ACK checks are required
        after WebSocket acceptance. Never authorize a pairing from TLS alone.
        """
        try:
            request = self._request
            if (
                type(getattr(request, "url", None)) is not str
                or request.url != _CANONICAL_URL
                or not _first_pair_headers_clean(request.headers)
            ):
                return False
            cf = _property(request, "cf")
            # Cloudflare runtime metadata, NOT a caller-provided header.
            return type(_property(cf, "tlsVersion")) is str and (
                _property(cf, "tlsVersion") in _ALLOWED_TLS
            )
        except Exception:
            return False

    async def verify(self, websocket: Any) -> bool:
        if not self.permits_worker_upgrade():
            return False
        try:
            scope = websocket.scope
            if (
                type(scope) is not dict
                or scope.get("type") != "websocket"
                or scope.get("scheme") != "wss"
                or scope.get("path") != CONNECTOR_GATEWAY_WSS_PATH
                or scope.get("raw_path") != _CANONICAL_PATH
                or scope.get("query_string") != b""
                or not _first_pair_headers_clean(websocket.headers)
            ):
                return False
            return True
        except (AttributeError, TypeError, ValueError):
            return False
        except Exception:
            return False


__all__ = (
    "FIRST_PAIRING_TLS_ONLY_PRODUCTION_WIRED",
    "FIRST_PAIRING_WSS_PUBLIC_MOUNTED",
    "CloudflareFirstPairingTlsTransportReview",
)
