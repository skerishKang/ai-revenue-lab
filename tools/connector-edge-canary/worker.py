"""#4139 isolated Cloudflare Python SDK edge probe.

This intentionally has no Identity, Broker, credentials, customer or device
bindings. Running locally or via an isolated temporary Worker cannot register
a device or grant filesystem access. Never import this entrypoint in B62.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from workers import Response, WorkerEntrypoint

_TLS = frozenset(("TLSv1.2", "TLSv1.3"))
_HEALTH = "/__padiem_canary/tls"
_WSS = "/__padiem_canary/wss"
_DENIED = ("origin", "cookie", "authorization", "sec-websocket-protocol")


def _tls_classification(request: object) -> str:
    """Only fixed markers; never serialize request.cf or certificate details."""
    try:
        cf = getattr(request, "cf", None)
        if cf is None:
            return "CF_UNAVAILABLE"
        value = getattr(cf, "tlsVersion", None)
        if value is None:
            return "TLS_VERSION_UNAVAILABLE"
        return "TLS_OK" if value in _TLS else "TLS_UNACCEPTED"
    except Exception:
        return "TLS_METADATA_ERROR"


async def _socket_app(scope, receive, send):
    if scope.get("type") != "websocket" or scope.get("path") != _WSS:
        await send({"type": "websocket.close", "code": 1008})
        return
    if (await receive()).get("type") != "websocket.connect":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.send", "text": "PADIEM_CANARY_OPEN"})
    received = await receive()
    if (received.get("type") == "websocket.receive"
            and received.get("text") == "PADIEM_CANARY_NO_SECRET_PING"):
        await send({"type": "websocket.send", "text": "PADIEM_CANARY_PONG"})
    await send({"type": "websocket.close", "code": 1000})


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlsplit(str(request.url))
        if request.method != "GET" or url.query or url.fragment:
            return Response("NOT_FOUND", status=404)
        classification = _tls_classification(request)
        if url.path == _HEALTH:
            return Response(
                classification,
                status=200 if classification == "TLS_OK" else 503,
                headers={"cache-control": "no-store"},
            )
        if url.path != _WSS:
            return Response("NOT_FOUND", status=404)
        if classification != "TLS_OK":
            return Response("TLS_REQUIRED", status=403)
        if request.headers.get("upgrade") != "websocket":
            return Response("UPGRADE_REQUIRED", status=426)
        if any(request.headers.get(h) is not None for h in _DENIED):
            return Response("UNTRUSTED_REQUEST", status=403)
        from workers import asgi
        return await asgi.websocket(_socket_app, request)
