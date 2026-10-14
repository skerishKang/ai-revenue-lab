"""#4139 isolated-acceptance ONLY: PC-origin WSS -> SAME Broker DO ingress.

The Windows connector dials the existing pinned external endpoint:
wss://connector-acceptance.padiem.net/api/claw/connector/gateway/session.
The original canonical Broker DO owns the native PC socket at the *private*
path /internal/connector/pc-offer-4139. This review-only bridge connects
those two paths through the PREEXISTING canonical Broker Service Binding.

This module is never enabled by the public endpoint or by a browser header.
The product/production origin cannot opt in. The separate acceptance Worker,
the separately scoped release flags and trusted Cloudflare edge TLS are all
necessary. The Broker repeats independent server-side gates and Ed25519 proof.

No new credential authority, user login, public RPC, DO ID, URL secret or
deployment is created. A 101 Service Binding response alone is NOT evidence
of live Windows DPAPI enrollment.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlsplit

from .canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from .connector_gateway_first_pairing_tls_review import (
    CloudflareFirstPairingTlsTransportReview,
)
from .worker_config import binding_value, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME

ACCEPTANCE_NATIVE_WSS_BRIDGE_PRODUCTION_ENABLED = False
_BRIDGE_FLAG = "PADIEM_CONNECTOR_ACCEPTANCE_BROKER_NATIVE_WSS_ENABLED"
_GATEWAY_FLAG = "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED"
_SCOPE_FLAG = "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE"
_SCOPE = "isolated-operator-acceptance-4139"
_STAGE_ORIGIN = "https://connector-acceptance.padiem.net"
_STAGE_URL = _STAGE_ORIGIN + CONNECTOR_GATEWAY_WSS_PATH
_PRIVATE_ORIGIN = "https://canonical-broker-connector.internal"
_PRIVATE_PATH = "/internal/connector/pc-offer-4139"
_PRIVATE_URL = _PRIVATE_ORIGIN + _PRIVATE_PATH
# Do NOT forward any browser/cookie/Origin/token/subprotocol or arbitrary
# request headers to the canonical Broker's accepting WebSocket.
_PRIVATE_UPGRADE_HEADERS = {"upgrade": "websocket"}


def is_review_native_wss_bridge_armed(worker_env: Any) -> bool:
    return (
        binding_value(worker_env, _BRIDGE_FLAG) == "enabled"
        and binding_value(worker_env, _GATEWAY_FLAG) == "enabled"
        and binding_value(worker_env, _SCOPE_FLAG) == _SCOPE
        and binding_value(worker_env, "PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN")
        == _STAGE_ORIGIN
        and binding_value(worker_env, "PADIEM_CHAT_PUBLIC_BASE_URL")
        == _STAGE_ORIGIN
        and binding_value(worker_env, "PADIEM_CHAT_RUNTIME_MODE") == "mock"
    )


def is_native_wss_review_target(request: Any) -> bool:
    try:
        url = getattr(request, "url", None)
        headers = getattr(request, "headers", None)
        return (
            type(url) is str and url == _STAGE_URL
            and getattr(request, "method", None) == "GET"
            and callable(getattr(headers, "get", None))
            and headers.get("upgrade") == "websocket"
            and all(headers.get(name) is None for name in (
                "origin", "cookie", "authorization",
                "sec-websocket-protocol", "cf-tls-client-auth",
                "client-cert", "client-cert-chain",
                "cf-client-cert-sha256",
            ))
            and urlsplit(url).netloc == "connector-acceptance.padiem.net"
        )
    except Exception:
        return False


async def dispatch_isolated_native_pc_wss(
    *, request: Any, worker_env: Any, request_factory: Callable[..., Any],
    response_factory: Callable[..., Any],
) -> Any:
    """Return a bounded refusal unless all acceptance and TLS checks passed.

    Call only from the existing product Worker gateway guard, NEVER from a
    public HTTP bridge that takes a URL/DO name from the user.
    """
    def unavailable():
        return response_factory(
            "Connector acceptance unavailable.", status=503,
            headers={"cache-control": "no-store"},
        )

    if not is_review_native_wss_bridge_armed(worker_env):
        return unavailable()
    if not is_native_wss_review_target(request):
        return unavailable()
    # Cloudflare's Worker-injected request.cf metadata is independent of
    # untrusted X-Forwarded/CF-* HTTP headers. TLS alone is NOT device identity.
    tls = CloudflareFirstPairingTlsTransportReview(
        incoming_worker_request=request, source_review_authorized=True,
        expected_url=_STAGE_URL,
    )
    if not tls.permits_worker_upgrade():
        return unavailable()
    broker = binding_value(worker_env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if not callable(getattr(broker, "fetch", None)):
        return unavailable()
    try:
        # Server-created same-account private Service Binding Request.
        # No public HTTP bearer, Owner session or credential is forwarded.
        internal_request = request_factory(
            _PRIVATE_URL, method="GET", headers=dict(_PRIVATE_UPGRADE_HEADERS),
        )
        result = await broker.fetch(internal_request)
        if getattr(result, "status", None) != 101:
            return unavailable()
        return result
    except Exception:
        # Safe even on unknown Worker/Pyodide/service-binding incompatibility:
        # do not fallback to a second ASGI gateway or unsigned PC authority.
        return unavailable()

# Direct product ingress uses the SAME canonical Broker DO and one-shot
# per-account device proof. No second hostname, Worker, ledger or credential
# store is introduced. These gates are ALL server-owned and default OFF.
_PRODUCT_ORIGIN = "https://chat.padiem.net"
_PRODUCT_URL = _PRODUCT_ORIGIN + CONNECTOR_GATEWAY_WSS_PATH
_PRODUCT_SCOPE = "owner-controlled-production-4139"
_PRODUCT_ENABLED = "PADIEM_CONNECTOR_PRODUCTION_ENABLED"


def is_product_native_wss_bridge_armed(worker_env: Any) -> bool:
    return (
        binding_value(worker_env, _GATEWAY_FLAG) == "enabled"
        and binding_value(worker_env, _PRODUCT_ENABLED) == "enabled"
        and binding_value(worker_env, _SCOPE_FLAG) == _PRODUCT_SCOPE
        and binding_value(worker_env, "PADIEM_CHAT_PUBLIC_BASE_URL") == _PRODUCT_ORIGIN
        and callable(getattr(
            binding_value(worker_env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME),
            "fetch", None,
        ))
    )


async def dispatch_product_native_pc_wss(
    *, request: Any, worker_env: Any, request_factory: Callable[..., Any],
    response_factory: Callable[..., Any],
) -> Any:
    """Bridge ONLY the existing product WSS into the same canonical Broker DO.

    All registered accounts use their own authenticated Identity consent and
    the canonical Broker's signed, one-time device authorization. This ingress
    neither receives a login cookie nor selects or grants a user account.
    """
    def unavailable():
        return response_factory(
            "Connector gateway unavailable.", status=503,
            headers={"cache-control": "no-store"},
        )

    if not is_product_native_wss_bridge_armed(worker_env):
        return unavailable()
    try:
        headers = request.headers
        if not (
            type(request.url) is str
            and request.url == _PRODUCT_URL
            and request.method == "GET"
            and callable(getattr(headers, "get", None))
            and headers.get("upgrade") == "websocket"
        ):
            return unavailable()
        tls = CloudflareFirstPairingTlsTransportReview(
            incoming_worker_request=request, source_review_authorized=True,
            expected_url=_PRODUCT_URL,
        )
        if not tls.permits_worker_upgrade():
            return unavailable()
        broker = binding_value(
            worker_env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
        )
        # The URL and headers are server constants, never browser supplied.
        internal = request_factory(
            _PRIVATE_URL, method="GET", headers=dict(_PRIVATE_UPGRADE_HEADERS),
        )
        response = await broker.fetch(internal)
        if getattr(response, "status", None) == 101:
            return response
    except Exception:
        # No credentials, login identity, challenge or network traceback in
        # an unauthenticated public WSS response. No alternate gateway.
        pass
    return unavailable()
