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


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        target = urlsplit(str(request.url))
        if (request.method != "GET" or target.path != _WSS
                or target.query or target.fragment):
            return Response("NOT_FOUND", status=404)
        if request.headers.get("upgrade") != "websocket":
            return Response("UPGRADE_REQUIRED", status=426)
        if any(request.headers.get(h) is not None for h in _FORBIDDEN):
            return Response("UNTRUSTED_REQUEST", status=403)
        from workers import asgi
        return await asgi.websocket(_socket_app, request)
