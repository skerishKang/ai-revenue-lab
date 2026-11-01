"""Real BookAI JS proxy/signature/sync loop -> COM2 ASGI -> SQLite migration 082."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.applications import Starlette

from app.bookai_records import install_bookai_records_routes
from app.d1_sqlite import SqliteD1, connect

NOW = 1793534400
TEST_SECRET = "synthetic-bookai-records-integration-credential"
USER_A = "sub_integration_alpha"
USER_B = "sub_integration_beta"
PATH = "/api/bookai/records"
ROOT = Path(__file__).resolve().parents[3]
BRIDGE = Path(__file__).with_name("bookai_records_app_bridge.mjs")


@pytest.fixture
def database(tmp_path):
    connection = connect(str(tmp_path / "bookai-records.sqlite3"))
    migrations = list((ROOT / "apps/padiem-chat/migrations").glob("082_*bookai*.sql"))
    assert len(migrations) == 1, "the actual BookAI migration 082 is required"
    connection.executescript(migrations[0].read_text(encoding="utf-8"))
    try:
        yield SqliteD1(connection)
    finally:
        connection.close()


class AppBridge:
    """JSON lines carry test-only HTTP requests; JWT/private keys stay inside Node."""
    def __init__(self, client):
        self.client = client
        self.requests = []

    async def __aenter__(self):
        node = shutil.which("node")
        assert node, "Node is required to execute the actual BookAI app integration"
        self.process = await asyncio.create_subprocess_exec(
            node, str(BRIDGE), cwd=ROOT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024,
        )
        return self

    async def __aexit__(self, *_):
        self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), 10)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()

    async def _send(self, message):
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.process.stdin.drain()

    async def call(self, *, subject=USER_A, mutate=None, **command):
        await self._send({"subject": subject, "secret": TEST_SECRET, "now": NOW, **command})
        while True:
            line = await asyncio.wait_for(self.process.stdout.readline(), 20)
            if not line:
                raise AssertionError("Node app bridge stopped before returning a result")
            message = json.loads(line)
            if message["type"] == "result":
                assert "error" not in message, message.get("error")
                return message["result"]
            assert message["type"] == "fetch"
            assert message["url"].startswith("https://chat.padiem.net/api/bookai/records")
            assert "cookie" not in message["headers"], "browser session must stay in the app proxy"
            assert message["headers"]["x-bookai-subject"] == subject
            self.requests.append((message["method"], message["url"]))
            if mutate:
                mutate(message)
            response = await self.client.request(
                message["method"], message["url"],
                headers=message["headers"], content=message["body"].encode("utf-8"),
            )
            await self._send({"type": "upstream_result", "id": message["id"],
                             "status": response.status_code,
                             "headers": dict(response.headers), "body": response.text})

    async def request(self, method="GET", path=PATH, *, data=None, **options):
        return await self.call(operation="request", method=method, path=path, data=data, **options)


def application(database):
    app = Starlette()
    install_bookai_records_routes(
        app, env={"BOOKAI_COM2_SYNC_SECRET": TEST_SECRET}, db_binding=database, clock=lambda: NOW
    )
    return app


def record(record_id, *, updated_at=100, body="saved note", deleted=False, kind="note"):
    return {"record_id": record_id, "book_id": "bible-web", "locator": "bible:web:ACT:9:3",
            "kind": kind, "payload": {"body": body}, "updated_at": updated_at, "deleted": deleted}


@pytest.mark.asyncio
async def test_real_app_proxy_roundtrip_isolation_latest_edit_and_delete(database):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application(database)),
                                base_url="https://chat.padiem.net") as client:
        async with AppBridge(client) as app:
            first = record("same-record-id", body="사울을 읽으며 남긴 메모")
            response = await app.request("POST", data={"records": [first]})
            assert response["status"] == 200
            assert response["body"] == {"accepted": 1, "kept_newer": []}
            own = await app.request(path=PATH + "?since=0&limit=500")
            assert own["body"]["records"] == [first]
            assert "no-store" in own["headers"]["cache-control"]

            empty = await app.request(subject=USER_B)
            assert empty["body"]["records"] == []
            second = record("same-record-id", body="다른 계정의 기록", updated_at=500)
            assert (await app.request("POST", subject=USER_B, data={"records": [second]}))["status"] == 200
            newer = record("same-record-id", updated_at=300, body="edited")
            assert (await app.request("POST", data={"records": [newer]}))["body"]["accepted"] == 1
            stale = await app.request("POST", data={"records": [first]})
            assert stale["body"] == {"accepted": 0, "kept_newer": ["same-record-id"]}
            deleted = record("same-record-id", updated_at=400, body="edited", deleted=True)
            assert (await app.request("POST", data={"records": [deleted]}))["body"]["accepted"] == 1
            assert (await app.request(path=PATH + "?since=300"))["body"]["records"] == [deleted]
            assert (await app.request(subject=USER_B))["body"]["records"] == [second]

            # New route composition reads the same persisted SQLite records.
            restarted = application(database)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(restarted),
                                        base_url="https://chat.padiem.net") as restart_client:
                async with AppBridge(restart_client) as restart_app:
                    assert (await restart_app.request())["body"]["records"] == [deleted]


@pytest.mark.asyncio
async def test_actual_app_signature_rejects_body_subject_query_tampering_and_expiry(database):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application(database)),
                                base_url="https://chat.padiem.net") as client:
        async with AppBridge(client) as app:
            for mutate in [
                lambda wire: wire.update(body=wire["body"] + " "),
                lambda wire: wire["headers"].update({"x-bookai-subject": USER_B}),
                lambda wire: wire["headers"].update({"x-bookai-signature": "0" * 64}),
            ]:
                result = await app.request("POST", data={"records": [record("blocked")]}, mutate=mutate)
                assert result["status"] == 401
            result = await app.request(path=PATH + "?since=0&limit=500",
                                      mutate=lambda wire: wire.update(url=wire["url"].replace("since=0", "since=1")))
            assert result["status"] == 401
            for offset in [-301, 301]:
                expired = await app.request("POST", data={"records": [record("expired")]}, clockOffset=offset)
                assert expired["status"] == 401
            assert (await app.request())["body"]["records"] == []
            assert (await app.request(subject=USER_B))["body"]["records"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("updated_at,positive_count", [(1000, 0), (0, 0), (0, 700)])
async def test_actual_app_sync_recovers_620_equal_timestamp_records_and_tombstones(
    database, updated_at, positive_count
):
    rows = [record("equal-%04d" % i, updated_at=updated_at, body="same millisecond " + str(i),
                   deleted=i == 0, kind=["note", "progress", "highlight", "ai_chat"][i % 4])
            for i in range(620)]
    rows += [record("later-%04d" % i, updated_at=1000, body="after the zero bucket " + str(i))
             for i in range(positive_count)]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application(database)),
                                base_url="https://chat.padiem.net") as client:
        async with AppBridge(client) as app:
            posted = await app.request("POST", data={"records": rows})
            assert posted["body"] == {"accepted": len(rows), "kept_newer": []}
            page = await app.request()
            assert len(page["body"]["records"]) == 500
            assert page["body"]["next_since"] == updated_at
            assert page["body"]["more"] is True
            # Execute the shipped client loop, not a Python copy of its paging algorithm.
            result = await app.call(operation="sync")
            assert result["status"]["state"] == "synced", result["status"]
            assert sorted(result["records"], key=lambda item: item["record_id"]) == rows
            assert result["records"][0]["deleted"] is True
            assert any(int(parse_qs(urlsplit(url).query).get("limit", ["500"])[0]) > 500
                       for method, url in app.requests if method == "GET")
            if positive_count:
                assert any(int(parse_qs(urlsplit(url).query).get("since", ["0"])[0]) > 0
                           for method, url in app.requests if method == "GET")
            isolated = await app.call(operation="sync", subject=USER_B)
            assert isolated["records"] == []
