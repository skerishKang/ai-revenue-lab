"""#7543 S07 — one Claw execute per Idempotency-Key across worker processes.

The execute route replays the first reply for a repeated key from a
process-local cache. With two worker processes a duplicate that lands on the
other process missed that cache and executed again. These tests pin the shared
receipt row that closes the gap, and the rule that a host without the receipt
table (or without a database) keeps the process-local behaviour exactly.

"Another process" is reproduced two ways: real subprocesses over one database
file, and — inside this process — a second SQLite connection on the same file
plus an emptied local cache, which is all another process is to this route.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app import claw_execute_receipt_store, claw_routes
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_execute_receipt_store import (
    D1ClawExecuteReceiptStore,
    MAX_RECEIPT_BODY_BYTES,
    RECEIPT_CLAIMED,
    RECEIPT_DONE,
    RECEIPT_PENDING,
)
from app.config import Settings
from app.d1_sqlite import SqliteD1, connect
from app.local_cpython import apply_migrations
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
RECEIPT_MIGRATION = "108_claw_execute_receipts.sql"
FIXTURE = Path(__file__).parent / "fixtures" / "claw_execute_receipt_worker_7543.py"

_spec = importlib.util.spec_from_file_location("claw_execute_receipt_worker_7543", FIXTURE)
worker_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker_fixture)

BASE = worker_fixture.BASE
OWNER = worker_fixture.OWNER
EXECUTE_PATH = worker_fixture.EXECUTE_PATH
PAYLOAD = worker_fixture.PAYLOAD
OTHER_REPLY = b'{"ok":true,"result":{"result_text":"answered by the other worker"}}'
OTHER_HEADERS = (("content-type", "application/json"), ("cache-control", "no-store"))


@pytest.fixture(autouse=True)
def _empty_local_replay_cache():
    """Every test starts as a process that has seen no execute yet."""
    claw_routes.reset_claw_execute_idempotency()
    yield
    claw_routes.reset_claw_execute_idempotency()


def _prepare_database(path: Path, *, with_receipt_table: bool = True) -> None:
    """The host's startup path: every shipped migration, in order."""
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        apply_migrations(connection, MIGRATIONS)
        if not with_receipt_table:
            # A host that has not applied 108 yet.
            connection.execute("DROP TABLE claw_execute_receipts")
    finally:
        connection.close()


def _rows(connection: sqlite3.Connection, sql: str) -> list[tuple]:
    return [tuple(row) for row in connection.execute(sql).fetchall()]


class Host:
    """One Chat app over its own SQLite connection, signed in as OWNER."""

    def __init__(self, database: Path):
        self.connection = connect(str(database))
        self.db = SqliteD1(self.connection, threaded=True)
        self.settings = worker_fixture.build_settings()
        self.adapter = MagicMock()
        self.adapter.execute = AsyncMock(
            side_effect=lambda *a, **k: worker_fixture.make_outcome()
        )
        self.app = create_app(
            self.settings, history_store=worker_fixture.StubHistory(), d1_binding=self.db
        )
        self.app.state.claw_p01_adapter = self.adapter
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url=BASE,
            headers={"Origin": BASE},
        )
        self.client.cookies.set(
            SESSION_COOKIE, create_session_token(self.settings, OWNER),
            domain="chat.example.test", path="/",
        )

    async def execute(self, key: str) -> httpx.Response:
        return await self.client.post(
            EXECUTE_PATH, json=PAYLOAD, headers={"Idempotency-Key": key}
        )

    def receipt_rows(self) -> list[tuple]:
        return _rows(
            self.connection,
            "SELECT user_id, idempotency_key, state FROM claw_execute_receipts",
        )

    async def close(self) -> None:
        await self.client.aclose()
        self.connection.close()


class OtherProcess:
    """The receipt store as a second worker process holds it: own connection."""

    def __init__(self, database: Path):
        self.connection = connect(str(database))
        self.store = D1ClawExecuteReceiptStore(SqliteD1(self.connection, threaded=True))

    def close(self) -> None:
        self.connection.close()


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    # All subprocess traffic is in-process ASGI; never inherit a proxy.
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        environment.pop(name, None)
    # The workers must import exactly the tree under test, whatever else is
    # installed in this interpreter.
    environment["PYTHONPATH"] = os.pathsep.join(item for item in sys.path if item)
    environment["PADIEM_CHAT_SESSION_USER_ROW_CHECK"] = "false"
    return environment


def _wait_until(predicate, seconds: float = 60.0) -> None:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("worker subprocess did not become ready")


# ---------------------------------------------------------------------------
# 1. Two real processes, one key.
# ---------------------------------------------------------------------------


def test_two_processes_with_the_same_key_execute_once_and_answer_identically(tmp_path):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    executions = tmp_path / "executions.log"
    start = tmp_path / "start"
    ready = [tmp_path / f"ready-{index}" for index in range(2)]
    processes = [
        subprocess.Popen(
            [sys.executable, str(FIXTURE), str(database), str(executions), str(marker),
             str(start), "claw-7543-two-process-key", "0.6"],
            env=_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        for marker in ready
    ]
    try:
        _wait_until(lambda: all(marker.exists() for marker in ready)
                    or any(process.poll() is not None for process in processes))
        start.touch()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout.strip().splitlines()[-1]))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)

    executed_by = executions.read_text(encoding="utf-8").split()
    assert len(executed_by) == 1, f"the request executed {len(executed_by)} times"
    assert [item["status"] for item in results] == [200, 200]
    assert results[0]["body"] == results[1]["body"]
    assert json.loads(results[0]["body"])["ok"] is True
    # Both processes answered; only one of them is the one that executed.
    assert {item["pid"] for item in results} > {int(executed_by[0])}


# ---------------------------------------------------------------------------
# 2. The same rule, deterministically, inside one test process.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_stored_by_another_process_is_replayed_without_executing(tmp_path):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    first_host, second_host = Host(database), Host(database)
    try:
        first = await first_host.execute("claw-7543-replay-key")
        assert first.status_code == 200, first.text
        assert first_host.receipt_rows() == [(OWNER, "claw-7543-replay-key", "done")]

        # The duplicate reaches a process whose local cache never saw the key.
        claw_routes.reset_claw_execute_idempotency()
        second = await second_host.execute("claw-7543-replay-key")
        assert second.status_code == 200
        assert second.content == first.content
        assert second.headers["cache-control"] == first.headers["cache-control"]
        assert first_host.adapter.execute.await_count == 1
        assert second_host.adapter.execute.await_count == 0
    finally:
        await first_host.close()
        await second_host.close()


@pytest.mark.asyncio
async def test_duplicate_waits_for_a_claim_held_by_another_process_then_replays(tmp_path):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    host, other = Host(database), OtherProcess(database)
    try:
        held = await other.store.claim(OWNER, "claw-7543-waiting-key")
        assert held.status == RECEIPT_CLAIMED

        pending = asyncio.create_task(host.execute("claw-7543-waiting-key"))
        await asyncio.sleep(0.35)
        assert not pending.done(), "the duplicate must wait for the other process"
        assert await other.store.complete(
            OWNER, "claw-7543-waiting-key", held.claim_id,
            status_code=200, headers=OTHER_HEADERS, body=OTHER_REPLY, ttl_seconds=60.0,
        )
        response = await asyncio.wait_for(pending, timeout=5)
        assert response.status_code == 200
        assert response.content == OTHER_REPLY
        assert host.adapter.execute.await_count == 0

        # The replayed reply is now local too: a third arrival needs no row.
        other.connection.execute("DELETE FROM claw_execute_receipts")
        again = await host.execute("claw-7543-waiting-key")
        assert again.content == OTHER_REPLY
        assert host.adapter.execute.await_count == 0
    finally:
        await host.close()
        other.close()


@pytest.mark.asyncio
async def test_claim_another_process_never_finishes_answers_in_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(claw_routes, "_CLAW_EXECUTE_IDEMPOTENCY_WAIT_SECONDS", 0.4)
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    host, other = Host(database), OtherProcess(database)
    try:
        assert (await other.store.claim(OWNER, "claw-7543-stuck-key")).status == RECEIPT_CLAIMED
        response = await host.execute("claw-7543-stuck-key")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "idempotency_in_progress"
        assert host.adapter.execute.await_count == 0
        # The other process's claim is untouched.
        assert host.receipt_rows() == [(OWNER, "claw-7543-stuck-key", "pending")]
    finally:
        await host.close()
        other.close()


@pytest.mark.asyncio
async def test_claim_released_by_another_process_answers_in_progress_then_a_retry_executes(tmp_path):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    host, other = Host(database), OtherProcess(database)
    try:
        held = await other.store.claim(OWNER, "claw-7543-released-key")
        pending = asyncio.create_task(host.execute("claw-7543-released-key"))
        await asyncio.sleep(0.25)
        # The other process's execute raised: no reply, claim released.
        await other.store.release(OWNER, "claw-7543-released-key", held.claim_id)
        response = await asyncio.wait_for(pending, timeout=5)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "idempotency_in_progress"
        assert host.adapter.execute.await_count == 0

        retry = await host.execute("claw-7543-released-key")
        assert retry.status_code == 200, retry.text
        assert host.adapter.execute.await_count == 1
    finally:
        await host.close()
        other.close()


# ---------------------------------------------------------------------------
# 3. No receipt table, no database, no signed-in owner: local behaviour only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_without_the_receipt_table_the_local_replay_is_unchanged(tmp_path):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database, with_receipt_table=False)
    host = Host(database)
    try:
        first = await host.execute("claw-7543-no-table-key")
        second = await host.execute("claw-7543-no-table-key")
        assert first.status_code == 200, first.text
        assert second.status_code == 200
        assert second.content == first.content
        assert host.adapter.execute.await_count == 1

        # Two arrivals at once still share one execution through the local set.
        release = asyncio.Event()

        async def slow(*_args, **_kwargs):
            await release.wait()
            return worker_fixture.make_outcome()

        host.adapter.execute = AsyncMock(side_effect=slow)
        both = [asyncio.create_task(host.execute("claw-7543-no-table-concurrent"))
                for _ in range(2)]
        await asyncio.sleep(0.2)
        release.set()
        answers = await asyncio.gather(*both)
        assert [answer.status_code for answer in answers] == [200, 200]
        assert answers[0].content == answers[1].content
        assert host.adapter.execute.await_count == 1
        tables = {row[0] for row in host.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "claw_execute_receipts" not in tables
    finally:
        await host.close()


def test_guest_requests_never_write_a_receipt(tmp_path):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    connection = connect(str(database))
    settings = Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off")
    app = create_app(settings=settings, d1_binding=SqliteD1(connection, threaded=True))
    adapter = MagicMock()
    adapter.execute = AsyncMock(side_effect=lambda *a, **k: worker_fixture.make_outcome())
    app.state.claw_p01_adapter = adapter
    try:
        client = TestClient(app)
        headers = {"Idempotency-Key": "claw-7543-guest-key"}
        first = client.post(EXECUTE_PATH, json=PAYLOAD, headers=headers)
        second = client.post(EXECUTE_PATH, json=PAYLOAD, headers=headers)
        assert first.status_code == 200, first.text
        assert second.json() == first.json()
        assert adapter.execute.await_count == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM claw_execute_receipts").fetchone()[0] == 0
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 4. A handler that raises leaves no claim behind.
# ---------------------------------------------------------------------------


def test_handler_failure_releases_the_claim_so_a_retry_executes(tmp_path, monkeypatch):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    connection = connect(str(database))
    monkeypatch.setattr(claw_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(claw_routes, "current_user_id", lambda request: OWNER)
    calls: list[int] = []

    @claw_routes._idempotent_claw_execute
    async def handler(request):
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("the first execute blew up")
        return JSONResponse({"ok": True, "attempt": len(calls)})

    app = Starlette(routes=[Route("/execute", handler, methods=["POST"])])
    app.state.account_data_db = SqliteD1(connection, threaded=True)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        headers = {"Idempotency-Key": "claw-7543-raising-key"}
        assert client.post("/execute", headers=headers).status_code == 500
        assert connection.execute(
            "SELECT COUNT(*) FROM claw_execute_receipts").fetchone()[0] == 0
        retry = client.post("/execute", headers=headers)
        assert retry.status_code == 200
        assert retry.json() == {"ok": True, "attempt": 2}
        assert _rows(connection, "SELECT state FROM claw_execute_receipts") == [("done",)]
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 4b. An execute that produced a reply never runs again for that key, even
#     when the reply cannot be stored; a claim the store cannot take is not
#     executed at all.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_too_large_to_store_still_stops_another_process_from_executing(
    tmp_path, monkeypatch
):
    # Shrink the stored-reply ceiling to just above the fixed fallback reply,
    # and make the real reply far larger: the real one cannot be stored.
    fallback_bytes = len(claw_routes._replay_unavailable_reply()[1])
    monkeypatch.setattr(
        claw_execute_receipt_store, "MAX_RECEIPT_BODY_BYTES", fallback_bytes + 1)
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    first_host, second_host = Host(database), Host(database)
    first_host.adapter.execute = AsyncMock(
        side_effect=lambda *a, **k: worker_fixture.make_outcome(answer="긴 결과 " * 200))
    try:
        first = await first_host.execute("claw-7543-unstorable-key")
        assert first.status_code == 200, first.text
        assert first_host.receipt_rows() == [(OWNER, "claw-7543-unstorable-key", "done")]

        # The retry reaches another process: no local cache, only the row.
        claw_routes.reset_claw_execute_idempotency()
        second = await second_host.execute("claw-7543-unstorable-key")
        assert second_host.adapter.execute.await_count == 0, "the key executed twice"
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "idempotency_replay_unavailable"
        assert first_host.adapter.execute.await_count == 1
    finally:
        await first_host.close()
        await second_host.close()


@pytest.mark.asyncio
async def test_store_error_while_saving_the_reply_keeps_the_key_executed(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(claw_routes, "_CLAW_EXECUTE_IDEMPOTENCY_WAIT_SECONDS", 0.3)
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    first_host, second_host = Host(database), Host(database)

    async def broken_complete(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(D1ClawExecuteReceiptStore, "complete", broken_complete)
            first = await first_host.execute("claw-7543-save-error-key")
        assert first.status_code == 200, first.text
        # Neither the reply nor its fallback could be written: the claim stays.
        assert first_host.receipt_rows() == [(OWNER, "claw-7543-save-error-key", "pending")]

        claw_routes.reset_claw_execute_idempotency()
        second = await second_host.execute("claw-7543-save-error-key")
        assert second_host.adapter.execute.await_count == 0, "the key executed twice"
        assert second.status_code == 503
        assert second.json()["error"]["code"] == "idempotency_in_progress"
    finally:
        await first_host.close()
        await second_host.close()


@pytest.mark.asyncio
async def test_claim_store_error_answers_503_without_executing(tmp_path, monkeypatch):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    host = Host(database)

    async def locked_claim(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(D1ClawExecuteReceiptStore, "claim", locked_claim)
    try:
        response = await host.execute("claw-7543-locked-key")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "idempotency_unavailable"
        assert host.adapter.execute.await_count == 0
        # Nothing is cached for the key: a later retry is a fresh attempt.
        monkeypatch.undo()
        retry = await host.execute("claw-7543-locked-key")
        assert retry.status_code == 200, retry.text
        assert host.adapter.execute.await_count == 1
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_a_running_execute_renews_its_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(claw_routes, "LEASE_RENEW_SECONDS", 0.05)
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    host = Host(database)
    release = asyncio.Event()

    async def slow(*_args, **_kwargs):
        await release.wait()
        return worker_fixture.make_outcome()

    host.adapter.execute = AsyncMock(side_effect=slow)

    def expiry() -> int:
        return host.connection.execute(
            "SELECT expires_at_ms FROM claw_execute_receipts").fetchone()[0]

    try:
        pending = asyncio.create_task(host.execute("claw-7543-renewed-key"))
        await asyncio.sleep(0.1)
        before = expiry()
        await asyncio.sleep(0.2)
        assert expiry() > before, "the claim was not renewed while executing"
        release.set()
        assert (await pending).status_code == 200
    finally:
        await host.close()


# ---------------------------------------------------------------------------
# 5. The store's own rules.
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def stores(tmp_path):
    database = tmp_path / "chat.sqlite3"
    _prepare_database(database)
    clock = _Clock()
    connections = [connect(str(database)), connect(str(database))]
    yield (
        D1ClawExecuteReceiptStore(SqliteD1(connections[0], threaded=True), clock=clock),
        D1ClawExecuteReceiptStore(SqliteD1(connections[1], threaded=True), clock=clock),
        clock,
        connections[0],
    )
    for connection in connections:
        connection.close()


@pytest.mark.asyncio
async def test_only_one_of_many_simultaneous_claims_wins(stores):
    first, second, _clock, connection = stores
    claims = await asyncio.gather(*(
        (first if index % 2 else second).claim(OWNER, "claw-7543-race-key")
        for index in range(12)
    ))
    assert [claim.status for claim in claims].count(RECEIPT_CLAIMED) == 1
    assert all(claim.status in (RECEIPT_CLAIMED, RECEIPT_PENDING) for claim in claims)
    assert connection.execute("SELECT COUNT(*) FROM claw_execute_receipts").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_reply_is_stored_only_by_the_claim_owner_and_read_by_everyone(stores):
    first, second, _clock, _connection = stores
    claim = await first.claim(OWNER, "claw-7543-owner-key")
    assert not await second.complete(
        OWNER, "claw-7543-owner-key", "not-the-claim-id",
        status_code=200, headers=OTHER_HEADERS, body=b"{}", ttl_seconds=60.0,
    )
    assert (await second.read(OWNER, "claw-7543-owner-key")).status == RECEIPT_PENDING
    assert await first.complete(
        OWNER, "claw-7543-owner-key", claim.claim_id,
        status_code=202, headers=OTHER_HEADERS, body=OTHER_REPLY, ttl_seconds=60.0,
    )
    seen = await second.claim(OWNER, "claw-7543-owner-key")
    assert seen.status == RECEIPT_DONE
    assert (seen.reply.status_code, seen.reply.body, seen.reply.headers) == (
        202, OTHER_REPLY, OTHER_HEADERS)
    assert 0 < seen.reply.remaining_seconds <= 60.0
    # A stored reply is not something a release can remove.
    await first.release(OWNER, "claw-7543-owner-key", claim.claim_id)
    assert (await second.read(OWNER, "claw-7543-owner-key")).status == RECEIPT_DONE


@pytest.mark.asyncio
async def test_the_key_is_scoped_to_its_owner(stores):
    first, second, _clock, _connection = stores
    mine = await first.claim(OWNER, "claw-7543-shared-key")
    theirs = await second.claim("usr_" + "8" * 32, "claw-7543-shared-key")
    assert (mine.status, theirs.status) == (RECEIPT_CLAIMED, RECEIPT_CLAIMED)


@pytest.mark.asyncio
async def test_expired_rows_are_removed_by_the_next_claim(stores):
    first, second, clock, connection = stores
    done = await first.claim(OWNER, "claw-7543-old-reply")
    await first.complete(
        OWNER, "claw-7543-old-reply", done.claim_id,
        status_code=200, headers=OTHER_HEADERS, body=OTHER_REPLY, ttl_seconds=60.0,
    )
    await first.claim(OWNER, "claw-7543-abandoned", lease_seconds=600.0)

    clock.now += 61
    # The reply window is over: the key executes again, and its row is new.
    assert await second.read(OWNER, "claw-7543-old-reply") is None
    assert (await second.claim(OWNER, "claw-7543-old-reply")).status == RECEIPT_CLAIMED
    # The abandoned claim is still inside its lease.
    assert (await second.claim(OWNER, "claw-7543-abandoned")).status == RECEIPT_PENDING

    clock.now += 600
    assert (await second.claim(OWNER, "claw-7543-unrelated")).status == RECEIPT_CLAIMED
    assert _rows(connection, "SELECT idempotency_key FROM claw_execute_receipts") == [
        ("claw-7543-unrelated",)]


@pytest.mark.asyncio
async def test_a_reply_that_cannot_be_stored_is_reported_not_truncated(stores):
    first, _second, _clock, _connection = stores
    claim = await first.claim(OWNER, "claw-7543-big-reply")
    for body in (b"x" * (MAX_RECEIPT_BODY_BYTES + 1), b"\xff\xfe not utf-8"):
        assert not await first.complete(
            OWNER, "claw-7543-big-reply", claim.claim_id,
            status_code=200, headers=OTHER_HEADERS, body=body, ttl_seconds=60.0,
        )
    assert (await first.read(OWNER, "claw-7543-big-reply")).status == RECEIPT_PENDING


def test_receipt_migration_applies_twice_and_lands_the_table(tmp_path):
    connection = sqlite3.connect(tmp_path / "twice.sqlite3")
    try:
        script = (MIGRATIONS / RECEIPT_MIGRATION).read_text(encoding="utf-8")
        connection.executescript(script)
        connection.executescript(script)
        columns = [row[1] for row in connection.execute(
            "PRAGMA table_info(claw_execute_receipts)")]
        assert columns == [
            "user_id", "idempotency_key", "claim_id", "state", "status_code",
            "headers_json", "response_body", "created_at_ms", "expires_at_ms",
        ]
    finally:
        connection.close()
