"""#4139 source-only Cloudflare Worker ASGI WebSocket upgrade bridge.

The actual Worker entrypoint DOES NOT import, call or mount this module.
Neither request.cf, request headers nor URL scheme attest a physical PC or
trusted Cloudflare ingress. Binding authority is exclusively server-owned.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from .connector_gateway_worker_binding_composition import build_review_only_gateway_from_worker_env

REVIEW_WORKER_WSS_URL = "https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH
WORKER_GATEWAY_ASGI_FETCH_PRODUCTION_WIRED = False


def _untrusted_headers(request: Any) -> bool:
    headers = getattr(request, "headers", None)
    if not callable(getattr(headers, "get", None)):
        return True
    try:
        return (
            headers.get("upgrade") != "websocket"
            or headers.get("origin") is not None
            or headers.get("cookie") is not None
            or headers.get("authorization") is not None
            or headers.get("sec-websocket-protocol") is not None
        )
    except Exception:
        return True



def strict_source_only_websocket_scope(app: Any) -> Any:
    """Translate Cloudflare ASGI HTTPS transport scheme to ASGI WebSocket WSS.

    Cloudflare's request_to_scope(ws=True) preserves request.url.protocol
    ("https"), whereas Starlette WebSocket.url.scheme is expected to be "wss"
    by the canonical #4139 host. This is ONLY protocol representation, not a
    TLS or client certificate attestation: trusted_tls_ingress.verify() still
    owns that proof and may not accept untrusted request headers.
    """
    async def guarded(scope: Any, receive: Any, send: Any) -> None:
        valid = (
            type(scope) is dict
            and scope.get("type") == "websocket"
            and scope.get("scheme") == "https"
            and scope.get("path") == CONNECTOR_GATEWAY_WSS_PATH
            and scope.get("raw_path") == CONNECTOR_GATEWAY_WSS_PATH.encode("ascii")
            and scope.get("query_string") == b""
        )
        if not valid:
            await send({"type": "websocket.close", "code": 1008})
            return
        corrected = dict(scope)
        corrected["scheme"] = "wss"
        await app(corrected, receive, send)

    return guarded


async def dispatch_review_only_worker_wss_upgrade(
    *, request: Any = None, worker_env: Any = None,
    trusted_tls_ingress: Any = None, source_test_authorized: bool = False,
) -> Any:
    """Review only: byte-exact origin and Upgrade before any private RPC.

    Source-test authorization never grants production entitlement. Future
    deployment MUST prove real Cloudflare Python ASGI WebSocket upgrade and
    independently attested TLS ingress, not synthetic header values.
    """
    if source_test_authorized is not True:
        raise RuntimeError("PADIEM Connector public Worker WSS is not activated")
    if type(getattr(request, "url", None)) is not str:
        raise ValueError("Worker request URL unavailable")
    if request.url != REVIEW_WORKER_WSS_URL or _untrusted_headers(request):
        raise ValueError("Unreviewed WebSocket upgrade request")
    parsed = urlsplit(request.url)
    if (parsed.scheme != "https" or parsed.netloc != "chat.padiem.net"
        or parsed.path != CONNECTOR_GATEWAY_WSS_PATH
        or parsed.query or parsed.fragment):
        raise ValueError("Unreviewed WebSocket request origin")
    app = build_review_only_gateway_from_worker_env(
        worker_env=worker_env, trusted_tls_ingress=trusted_tls_ingress,
        source_test_authorized=True,
    )
    # Lazy official Cloudflare Workers Python ASGI adapter, NEVER loaded from
    # user CLI or a deployed Worker entrypoint by this PR.
    from workers import asgi
    # The SDK's asgi.fetch() is HTTP-only. A WS upgrade must invoke
    # asgi.websocket() to construct a real WebSocketPair and status 101.
    # Never route the pairing channel through HTTP request processing.
    return await asgi.websocket(strict_source_only_websocket_scope(app), request, worker_env)
