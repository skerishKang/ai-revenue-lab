"""Opt-in COM2 ingress authentication; no client proof header is trusted."""
import asyncio
import time

from starlette.datastructures import Headers
from .request_timing import measure

_PROOF_HEADERS = (
    b"x-padiem-edge-at", b"x-padiem-edge-id",
    b"x-padiem-edge-tls", b"x-padiem-edge-proof",
)


class EdgeProofMiddleware:
    def __init__(self, app, *, verifier):
        self.app = app
        self.verifier = verifier
        # Admission is one SQLite write per request, and the store's busy timeout
        # is five seconds: with the default executor two verifies overlap, the
        # second waits the timeout out, sqlite3.Error is swallowed by the verifier
        # and a legitimately signed request becomes a 403. One at a time, still off
        # the event loop, so a slow disk delays requests without failing them.
        self._verify_slot = asyncio.Semaphore(1)

    async def _verify(self, scope):
        path = scope.get("path", "")
        method = "GET" if scope.get("type") == "websocket" else scope.get("method", "")
        headers = Headers(scope=scope)
        async with self._verify_slot:
            started = time.monotonic()
            valid = await asyncio.to_thread(
                self.verifier.verify, method=method, path=path, headers=headers)
            # Path, verdict and milliseconds, on one line: the headers carry the
            # proof, and a proof is derived from the edge secret.
            print(f"EDGE_VERIFY path={path} result={'ok' if valid else 'reject'} "
                  f"ms={int((time.monotonic() - started) * 1000)}", flush=True)
            return valid

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        if kind == "http" and scope.get("method") == "GET" and scope.get("path") == "/health":
            return await self.app(scope, receive, send)
        names = [name.lower() for name, _ in scope.get("headers", ())]
        valid = all(names.count(name) == 1 for name in _PROOF_HEADERS)
        if valid:
            with measure('edge'):
                valid = await self._verify(scope)
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
