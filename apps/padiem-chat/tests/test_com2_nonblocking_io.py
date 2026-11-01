import asyncio
import threading
from types import SimpleNamespace

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app import claw_local_connect_routes as connect_routes
from app.claw_local_connect_composition import NonprodBrokerPairingConnectPort
from app.local_r2 import LocalDiskR2, ThreadedLocalDiskR2

def test_slow_local_read_does_not_block_twenty_http_requests(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    bucket = ThreadedLocalDiskR2(tmp_path)
    # Fixture setup is synchronous; the host write port itself is awaitable.
    LocalDiskR2.put(bucket, "file.txt", b"payload")
    real_get = LocalDiskR2.get
    def slow_get(self, key):
        entered.set()
        if not release.wait(3):
            raise RuntimeError("test timed out")
        return real_get(self, key)
    monkeypatch.setattr(LocalDiskR2, "get", slow_get)
    async def read(request):
        obj = await bucket.get("file.txt")
        return JSONResponse({"body": obj.body.decode()})
    async def light(request):
        return JSONResponse({"ok": True})
    app = Starlette(routes=[Route("/read", read), Route("/light", light)])
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            task = asyncio.create_task(client.get("/read"))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                replies = await asyncio.wait_for(asyncio.gather(*[client.get("/light") for _ in range(20)]), 0.8)
                assert all(reply.status_code == 200 for reply in replies)
            finally:
                release.set()
            assert (await task).json() == {"body":"payload"}
            assert await bucket.get("missing") is None
    asyncio.run(run())

def test_slow_connect_post_does_not_block_twenty_http_requests(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    port=NonprodBrokerPairingConnectPort(broker_base_url="http://127.0.0.1:8400",
        account_ref="account", workspace_ref="workspace", allowed_owner_ids=("user",))
    def slow_mint(**kwargs):
        entered.set()
        if not release.wait(3):
            raise RuntimeError("test timed out")
        return {"ok":False}
    monkeypatch.setattr(port,"issue_pairing_challenge",slow_mint)
    monkeypatch.setattr(connect_routes,"auth_ready",lambda request: True)
    monkeypatch.setattr(connect_routes,"current_user_id",lambda request: "user")
    async def light(request):
        return JSONResponse({"ok":True})
    app=Starlette(routes=[Route("/api/claw/local-access/connect",connect_routes.claw_local_connect,methods=["POST"]),Route("/light",light)])
    app.state.claw_local_connect=port
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            task=asyncio.create_task(client.post("/api/claw/local-access/connect",json={}))
            try:
                assert await asyncio.to_thread(entered.wait,2)
                replies=await asyncio.wait_for(asyncio.gather(*[client.get("/light") for _ in range(20)]),0.8)
                assert all(reply.status_code==200 for reply in replies)
            finally:
                release.set()
            response=await task
            assert response.status_code==502
    asyncio.run(run())
