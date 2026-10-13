"""#4139 review-only Cloudflare Worker mTLS client-certificate admission.

Never mounted or used by the production Worker. The *real incoming* Worker
Request.cf.tlsClientAuth is a Cloudflare runtime property, NOT a forwarded
HTTP header. This unit cannot attest that a Python test double came from the
Cloudflare edge, nor provision a client certificate or authorize a PC.
Production admission requires separately approved edge mTLS configuration,
operator-pinned certificate fingerprint/rotation and served-version readback.

There is intentionally no default allowlist, environment secret lookup,
browser/cookie/header fallback, certificate issuance or public route.
"""
from __future__ import annotations

import hmac
import re
from typing import Any

from .canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH

CLOUDFLARE_MTLS_PRODUCTION_ATTESTED = False
CLOUDFLARE_MTLS_WSS_PUBLIC_ENABLED = False
_CERT_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EXPECTED_URL = "https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH
_DENIED_HEADERS = (
    "origin", "cookie", "authorization", "sec-websocket-protocol",
    "client-cert", "client-cert-chain", "cf-client-cert-sha256",
    "cf-tls-client-auth", "cf-visitor", "x-forwarded-proto",
)


def _property(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _headers_clean(headers: Any) -> bool:
    if not callable(getattr(headers, "get", None)):
        return False
    try:
        return all(headers.get(name) is None for name in _DENIED_HEADERS)
    except Exception:
        return False


class CloudflareMtlsIngressSourceReview:
    """Source-only request-bound read of Cloudflare mTLS metadata.

    `verify` requires *both* Cloudflare's explicit, nonrevoked client-cert
    verdict and an independently pre-approved exact SHA256 fingerprint.
    No asserted request headers are accepted as authority. A local fake
    request.cf can test the algorithm but can NEVER certify Cloudflare ingress.
    """

    def __init__(
        self, *, incoming_worker_request: Any = None,
        approved_sha256_fingerprints: frozenset[str] = frozenset(),
        source_review_authorized: bool = False,
    ) -> None:
        if source_review_authorized is not True:
            raise RuntimeError("Connector Cloudflare mTLS review is not activated")
        if (type(approved_sha256_fingerprints) is not frozenset
            or len(approved_sha256_fingerprints) > 32
            or any(type(p) is not str or _CERT_SHA256.fullmatch(p) is None
                   for p in approved_sha256_fingerprints)):
            raise ValueError("Canonical operator-pinned mTLS fingerprint set required")
        self._request = incoming_worker_request
        self._pins = approved_sha256_fingerprints

    async def verify(self, websocket: Any) -> bool:
        """Refuse on missing metadata, route mismatch, invalid or revoked cert."""
        if not self._pins:
            return False
        try:
            if (
                type(self._request.url) is not str
                or self._request.url != _EXPECTED_URL
                or not _headers_clean(self._request.headers)
            ):
                return False
            scope = websocket.scope
            if (
                type(scope) is not dict
                or scope.get("type") != "websocket"
                or scope.get("scheme") != "wss"
                or scope.get("path") != CONNECTOR_GATEWAY_WSS_PATH
                or scope.get("raw_path") != CONNECTOR_GATEWAY_WSS_PATH.encode("ascii")
                or scope.get("query_string") != b""
                or not _headers_clean(websocket.headers)
            ):
                return False
            tls = _property(_property(self._request, "cf"), "tlsClientAuth")
            if (
                _property(tls, "certPresented") != "1"
                or _property(tls, "certVerified") != "SUCCESS"
                or _property(tls, "certRevoked") != "0"
            ):
                return False
            fingerprint = _property(tls, "certFingerprintSHA256")
            if type(fingerprint) is not str or not _CERT_SHA256.fullmatch(fingerprint):
                return False
            return any(hmac.compare_digest(fingerprint, pin) for pin in self._pins)
        except Exception:
            return False


__all__ = (
    "CloudflareMtlsIngressSourceReview",
    "CLOUDFLARE_MTLS_PRODUCTION_ATTESTED",
    "CLOUDFLARE_MTLS_WSS_PUBLIC_ENABLED",
)
