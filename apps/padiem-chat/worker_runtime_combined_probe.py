"""Real Workerd/Pyodide multiplex for the four original runtime probes.

Each case delegates the original WorkerEntrypoint.fetch() with the *real*
incoming Workers Request. Only the /probe?case=... routing is new. Keep P01
last in the single-process runner: its existing synthetic route test patches
module globals and must not influence the HTTP/R2 contract probes.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from workers import Response, WorkerEntrypoint
from worker_runtime_timeout_probe import Default as TimeoutProbe
from worker_runtime_web_transport_probe import Default as WebTransportProbe
from worker_runtime_r2_read_probe import Default as R2ReadProbe
from worker_runtime_p01_binding_probe import Default as P01BindingProbe


PROBES = {
    "timeout": TimeoutProbe.fetch,
    "web_transport": WebTransportProbe.fetch,
    "r2_read": R2ReadProbe.fetch,
    "p01_binding": P01BindingProbe.fetch,
}


# #4139: temporary Workerd ONLY; never import this synthetic gateway from the
# production padiem-chat/worker.py. A 101 here proves the real Cloudflare
# Python ASGI/WS upgrade transport, NOT canonical Identity/Broker or TLS.
RUNTIME_WSS_PROBE_PATH = "/api/claw/connector/gateway/session"
_RUNTIME_CLIENT_PROOF = "synthetic-frame-no-credential"
_RUNTIME_SERVER_OPEN = "PADIEM_CONNECTOR_ASGI_WS_OPEN"
_RUNTIME_SERVER_ACK = "PADIEM_CONNECTOR_ASGI_WS_REPLY"


async def connector_asgi_websocket_runtime_probe(scope, receive, send):
    """Pure ASGI fixture: no session, no credential, no Broker or privileged IO."""
    if scope.get("type") != "websocket" or scope.get("path") != RUNTIME_WSS_PROBE_PATH:
        await send({"type": "websocket.close", "code": 1008})
        return
    opened = await receive()
    if opened.get("type") != "websocket.connect":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.send", "text": _RUNTIME_SERVER_OPEN})
    incoming = await receive()
    if (incoming.get("type") == "websocket.receive"
            and incoming.get("text") == _RUNTIME_CLIENT_PROOF):
        await send({"type": "websocket.send", "text": _RUNTIME_SERVER_ACK})
    # No credential or ACK data is ever sent. The test client closes.




class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(str(request.url))
        if url.path == RUNTIME_WSS_PROBE_PATH and not url.query:
            if request.headers.get("upgrade") != "websocket":
                return Response("Upgrade Required", status=426)
            from workers import asgi
            # Worker Python SDK: asgi.websocket(app, request) accepts two args.
            # The synthetic transport probe must exercise the same signature
            # as CENTRAL's review-only production candidate.
            return await asgi.websocket(connector_asgi_websocket_runtime_probe, request)
        if url.path == "/ready" and not url.query:
            return Response("ok", status=200)
        if url.path != "/probe":
            return Response("not found", status=404)
        try:
            params = parse_qs(url.query, strict_parsing=True)
        except ValueError:
            return Response("invalid probe case", status=400)
        if set(params) != {"case"} or len(params["case"]) != 1:
            return Response("invalid probe case", status=400)
        handler = PROBES.get(params["case"][0])
        if handler is None:
            return Response("invalid probe case", status=400)
        # The old handlers inspect only request.url (the path remains /probe).
        # Passing the original real Workerd Request preserves the exact
        # JS-object/Request transport assertions in each legacy probe.
        return await handler(None, request)
