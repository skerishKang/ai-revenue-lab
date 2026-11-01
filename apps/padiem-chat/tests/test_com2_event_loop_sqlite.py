import asyncio
import sqlite3
import threading
import time

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.d1_sqlite import SqliteD1
from app import file_lane

def test_twenty_light_http_requests_during_slow_sqlite(monkeypatch):
    async def run():
        conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set()
            if not release.wait(3):
                raise RuntimeError("timeout")
            return 1
        conn.create_function("slow", 0, slow)
        db = SqliteD1(conn, threaded=True)
        async def slow_route(request):
            return JSONResponse(await db.prepare("SELECT slow() AS value").first())
        async def authenticated_owner(request):
            return "test-owner"
        monkeypatch.setattr(file_lane, "owner", authenticated_owner)
        app = Starlette(routes=[Route("/slow", slow_route), Route("/api/files/capabilities", file_lane.file_capabilities)])
        app.state.file_lane_client = type("Lane", (), {"ready": True})()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                slow_task = asyncio.create_task(client.get("/slow"))
                assert await asyncio.to_thread(entered.wait, 2)
                started = time.monotonic()
                try:
                    results = await asyncio.wait_for(asyncio.gather(*[client.get("/api/files/capabilities") for _ in range(20)]), timeout=0.8)
                    assert all(r.status_code == 200 for r in results)
                    assert time.monotonic() - started < 0.8
                finally:
                    release.set()
                assert (await slow_task).json() == {"value": 1}
        finally:
            release.set()
            conn.close()
    asyncio.run(run())

def test_threaded_sqlite_batch_atomic_and_changes_are_isolated():
    async def run():
        conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY)")
        db = SqliteD1(conn, threaded=True)
        try:
            results = await asyncio.gather(*[db.prepare("INSERT OR IGNORE INTO t VALUES (?)").bind(1).run() for _ in range(20)])
            assert sorted(r["meta"]["changes"] for r in results) == [0]*19 + [1]
            try:
                await db.batch([db.prepare("INSERT INTO t VALUES (2)"), db.prepare("INSERT INTO t VALUES (1)")])
                assert False, "batch must fail"
            except sqlite3.IntegrityError:
                pass
            assert await db.prepare("SELECT id FROM t WHERE id=2").first() is None
        finally:
            conn.close()
    asyncio.run(run())
