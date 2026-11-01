"""#6604 — the replay store's durability mode, end to end through the middleware.

The store-level scenes live with the verifier
(`packages/padiem-control-plane/tests/test_edge_replay_sync_mode_261102.py`).
This one proves the change reaches the request path: a COM2 host serving with
`PADIEM_EDGE_REPLAY_SYNC_MODE=normal` still answers a fresh signed request 200,
still answers the same id 403, and still verifies one request at a time.
"""
import asyncio
import hashlib
import hmac
import sys
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane"))
from com2_edge_proof import EdgeProofVerifier
from app.com2_edge_middleware import EdgeProofMiddleware

SECRET = "synthetic-only-secret-0123456789"


def signed(method, path, request_id, at="1700000000"):
    signed_text = "\n".join(("v1", method, path, at, request_id, "TLSv1.3"))
    signature = hmac.new(SECRET.encode(), signed_text.encode(), hashlib.sha256).hexdigest()
    return {"x-padiem-edge-at": at, "x-padiem-edge-id": request_id,
            "x-padiem-edge-tls": "TLSv1.3", "x-padiem-edge-proof": "v1=" + signature}


def test_normal_mode_serves_a_signed_request_and_still_refuses_its_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_EDGE_REPLAY_SYNC_MODE", "normal")
    monkeypatch.setattr("com2_edge_proof.time.time", lambda: 1700000000)

    async def ok(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/api/test", ok, methods=["GET"])])
    verifier = EdgeProofVerifier(SECRET, str(tmp_path / "replay.sqlite"), all_requests=True)
    assert verifier.sync_mode == "normal"
    app = EdgeProofMiddleware(inner, verifier=verifier)

    async def twice():
        from test_com2_edge_middleware import _call
        return [await _call(app, "/api/test", "7" * 32), await _call(app, "/api/test", "7" * 32)]

    assert asyncio.run(twice()) == [200, 403]
    with TestClient(inner) as client:
        assert client.get("/api/test", headers=signed("GET", "/api/test", "8" * 32)).status_code == 200


def test_normal_mode_keeps_one_verify_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_EDGE_REPLAY_SYNC_MODE", "normal")
    monkeypatch.setattr("com2_edge_proof.time.time", lambda: 1700000000)

    class CountingVerifier:
        def __init__(self):
            self.live = 0
            self.peak = 0
            self.ok = 0

        def verify(self, *, method, path, headers):
            self.live += 1
            self.peak = max(self.peak, self.live)
            time.sleep(0.05)
            self.live -= 1
            self.ok += 1
            return True

    async def echo_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})

    from test_com2_edge_middleware import _call
    verifier = CountingVerifier()
    app = EdgeProofMiddleware(echo_app, verifier=verifier)

    async def all_at_once():
        return await asyncio.gather(*[
            _call(app, f"/api/item-{index}", f"{index:032x}") for index in range(8)])

    results = asyncio.run(all_at_once())
    assert set(results) == {200}, results
    assert verifier.peak == 1, verifier.peak
    assert verifier.ok == 8
