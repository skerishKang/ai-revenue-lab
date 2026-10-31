"""Opt-in COM2 ingress authentication; no client proof header is trusted."""
from starlette.datastructures import Headers

_PROOF_HEADERS = (
    b"x-padiem-edge-at", b"x-padiem-edge-id",
    b"x-padiem-edge-tls", b"x-padiem-edge-proof",
)


class EdgeProofMiddleware:
    def __init__(self, app, *, verifier):
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        names = [name.lower() for name, _ in scope.get("headers", ())]
        valid = all(names.count(name) == 1 for name in _PROOF_HEADERS)
        if valid:
            valid = self.verifier.verify(
                method="GET" if kind == "websocket" else scope.get("method", ""),
                path=scope.get("path", ""), headers=Headers(scope=scope),
            )
        if not valid:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Forbidden"})
            return
        scope["com2_edge_verified_verifier"] = self.verifier
        await self.app(scope, receive, send)
