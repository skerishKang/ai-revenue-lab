"""#4139 CI-ONLY Python Workerd WebSocket transport fixture.

Never deploy, expose publicly, or use for any device/owner authorization.
The real edge admission verifier in worker.py MUST continue checking
request.cf.tlsVersion. This fixture deliberately bypasses TLS metadata ONLY
because local Workerd has no Cloudflare edge TLS connection. It tests the
official workers.asgi.websocket(app, request) framing implementation.
"""
from urllib.parse import urlsplit

from workers import Response, WorkerEntrypoint

from worker import _WSS, _socket_app

_FORBIDDEN = ("origin", "cookie", "authorization", "sec-websocket-protocol")


async def _observed_scope_app(scope, receive, send):
    """Emit the SDK-generated ASGI scheme as a bounded nonsecret test marker.

    This is fixture-only: production source never logs or exports scope.
    """
    scheme = scope.get("scheme")
    if scheme not in ("https", "wss", "http", "ws"):
        scheme = "UNKNOWN"
    # Classification ONLY: no path, hostname, query, headers, secrets or
    # client-controlled strings are echoed. Probe exact SDK scope shape.
    raw = scope.get("raw_path")
    raw_status = (
        "EXACT" if type(raw) is bytes and raw == _WSS.encode("ascii")
        else "ABSENT" if raw is None else "OTHER"
    )
    query = scope.get("query_string")
    query_status = (
        "EMPTY_BYTES" if type(query) is bytes and query == b""
        else "ABSENT" if query is None else "OTHER"
    )

    async def audited_send(message):
        await send(message)
        if message.get("type") == "websocket.accept":
            for value in (
                "PADIEM_CANARY_SCHEME_" + scheme,
                "PADIEM_CANARY_RAW_" + raw_status,
                "PADIEM_CANARY_QUERY_" + query_status,
            ):
                await send({"type": "websocket.send", "text": value})

    await _socket_app(scope, receive, audited_send)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # Canonical #4139 Worker guards require native Python string URL.
        # Fail this source contract under real Workers SDK type drift.
        if type(getattr(request, "url", None)) is not str:
            return Response("URL_TYPE_UNSUPPORTED", status=503)
        target = urlsplit(request.url)
        if (request.method != "GET" or target.path != _WSS
                or target.query or target.fragment):
            return Response("NOT_FOUND", status=404)
        if request.headers.get("upgrade") != "websocket":
            return Response("UPGRADE_REQUIRED", status=426)
        if any(request.headers.get(h) is not None for h in _FORBIDDEN):
            return Response("UNTRUSTED_REQUEST", status=403)
        from workers import asgi
        return await asgi.websocket(_observed_scope_app, request)
