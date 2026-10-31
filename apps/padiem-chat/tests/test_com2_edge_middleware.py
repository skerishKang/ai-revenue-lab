import hashlib
import hmac
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
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


def test_api_proof_rejects_forgery_stale_and_replay(tmp_path, monkeypatch):
    monkeypatch.setattr("com2_edge_proof.time.time", lambda: 1700000000)
    async def ok(request):
        return PlainTextResponse("ok")
    app = Starlette(routes=[Route("/api/test", ok, methods=["GET", "POST"])])
    verifier = EdgeProofVerifier(SECRET, str(tmp_path / "replay.sqlite"), all_requests=True)
    app.add_middleware(EdgeProofMiddleware, verifier=verifier)
    with TestClient(app) as client:
        assert client.get("/api/test").status_code == 403
        proof = signed("POST", "/api/test", "1" * 32)
        assert client.post("/api/test", headers=proof).status_code == 200
        assert client.post("/api/test", headers=proof).status_code == 403
        forged = signed("GET", "/api/test", "2" * 32)
        forged["x-padiem-edge-proof"] = "v1=" + "0" * 64
        assert client.get("/api/test", headers=forged).status_code == 403
        assert client.get("/api/test", headers=signed("GET", "/api/test", "3" * 32, at="1699999699")).status_code == 403
        assert client.get("/api/test", headers=signed("POST", "/api/test", "4" * 32)).status_code == 403


def test_websocket_and_disabled_middleware(tmp_path, monkeypatch):
    monkeypatch.setattr("com2_edge_proof.time.time", lambda: 1700000000)
    async def ws(socket):
        await socket.accept()
        await socket.send_text("ok")
        await socket.close()
    route = WebSocketRoute("/api/socket", ws)
    app = Starlette(routes=[route])
    verifier = EdgeProofVerifier(SECRET, str(tmp_path / "replay.sqlite"), all_requests=True)
    app.add_middleware(EdgeProofMiddleware, verifier=verifier)
    with TestClient(app) as client:
        with client.websocket_connect("/api/socket", headers=signed("GET", "/api/socket", "5" * 32)) as socket:
            assert socket.receive_text() == "ok"
    with TestClient(Starlette(routes=[route])) as client:
        with client.websocket_connect("/api/socket") as socket:
            assert socket.receive_text() == "ok"
