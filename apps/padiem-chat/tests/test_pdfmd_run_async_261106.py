"""#5568 follow-on — the run route starts the work instead of waiting for it.

The front edge closes a long request with 504 while the origin is still
converting, so ``convert_item_run`` hands the conversion to a background task
and answers 202 with the working item. These tests pin the behaviour the
screen and the owner now rely on: the quick 202, the single-conversion guard,
the failure record, and the stale-working restart a host restart depends on.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import document_convert_routes
from app.d1_sqlite import SqliteD1, connect
from app.document_convert_store import D1DocumentConvertStore
from app.local_cpython import apply_migrations
from app.local_r2 import LocalDiskR2
from app.usage_gate import CONVERSION_BUCKET_TYPE, UsageDecision
from test_5568_document_convert_routes import (
    MIGRATION,
    OWNER,
    FakeD1,
    build_client,
    open_job,
    pdf_bytes,
    run_item,
    upload,
    wait_item_terminal,
)

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
RUN_CLAIM_WORKER = Path(__file__).parent / "fixtures" / "pdfmd_run_claim_worker_7543.py"


@pytest.fixture(autouse=True)
def _legacy_conversion_contract(monkeypatch):
    """The run route is exercised behind the #5710 gate, like the route tests."""
    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)


def _conversion_stand_in(delay: float, calls: list, failure: Exception | None = None):
    """The real engine behind a wall-clock delay, so the answer can beat the work."""
    real = document_convert_routes.convert_pdf_to_markdown

    def convert(*args, **kwargs):
        calls.append(time.monotonic())
        time.sleep(delay)
        if failure is not None:
            raise failure
        return real(*args, **kwargs)

    return convert


@pytest.mark.asyncio
async def test_run_answers_202_before_the_conversion_finishes(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes, "convert_pdf_to_markdown", _conversion_stand_in(0.4, calls)
    )
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Async 1 page 1"]), name="async.pdf")
        item_id = created.json()["items"][0]["id"]

        started = time.monotonic()
        run = await run_item(client, item_id)
        answered_in = time.monotonic() - started
        assert run.status_code == 202, run.text
        assert run.json()["item"]["status"] == "working"
        # The whole point: the answer must not wait for the conversion.
        assert answered_in < 0.9, f"run answered in {answered_in:.2f}s"

        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "reviewed"
        assert ran["page_count"] == 1
        assert ran["has_markdown"] is True
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_second_run_while_working_does_not_start_a_second_conversion(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes, "convert_pdf_to_markdown", _conversion_stand_in(0.3, calls)
    )
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Async 2 page 1"]), name="once.pdf")
        item_id = created.json()["items"][0]["id"]

        first = await run_item(client, item_id)
        assert first.status_code == 202, first.text
        second = await run_item(client, item_id)
        assert second.status_code == 202, second.text
        assert second.json()["item"]["status"] == "working"

        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "reviewed"
        assert len(calls) == 1, f"the item was converted {len(calls)} times"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_background_failure_records_failed_with_error_code(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes,
        "convert_pdf_to_markdown",
        _conversion_stand_in(0.0, calls, failure=ValueError("conversion blew up")),
    )
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Async 3 page 1"]), name="broken.pdf")
        item_id = created.json()["items"][0]["id"]

        assert (await run_item(client, item_id)).status_code == 202
        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "failed"
        assert ran["error_code"] == "convert_failed"
        assert ran["has_markdown"] is False
        detail = await client.get(f"/api/document-conversions/{job_id}")
        assert detail.json()["job"]["status"] == "failed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_fresh_working_is_not_restarted_but_a_stale_row_is(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes, "convert_pdf_to_markdown", _conversion_stand_in(0.2, calls)
    )
    d1 = FakeD1()
    client, _app = await build_client(d1=d1)
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Async 4 page 1"]), name="restart.pdf")
        item_id = created.json()["items"][0]["id"]

        # A fresh working row belongs to a run this process is driving: no restart.
        d1.conn.execute(
            "UPDATE document_convert_items SET status = 'working' WHERE id = ?", (item_id,)
        )
        fresh = await run_item(client, item_id)
        assert fresh.status_code == 202, fresh.text
        assert fresh.json()["item"]["status"] == "working"
        await asyncio.sleep(0.35)
        assert calls == [], "a fresh working row must not start a second conversion"

        # A row stuck working past the restart deadline (host restart, crash)
        # belongs to no one: the next run takes it over.
        d1.conn.execute(
            "UPDATE document_convert_items SET status = 'working', "
            "updated_at = '2026-01-01T00:00:00.000Z' WHERE id = ?",
            (item_id,),
        )
        stale = await run_item(client, item_id)
        assert stale.status_code == 202, stale.text
        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "reviewed"
        assert len(calls) == 1, f"the stale row was converted {len(calls)} times"
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# #7543 S09 — two run requests for one item start one conversion.
#
# The route reads the item, looks up the owner's grade and only then writes
# ``working``. Two requests that both read before either wrote used to both
# write, both take a daily allowance and both convert — on one worker process,
# and all the more on two. The ledger claim lets exactly one of them through.
# ---------------------------------------------------------------------------

#: Counts every row that actually changes to ``working``, in the database
#: itself, so the assertion does not depend on what the route reports.
WORKING_TRANSITIONS = """
CREATE TABLE working_transitions (item_id TEXT NOT NULL);
CREATE TRIGGER count_working_transitions
AFTER UPDATE OF status ON document_convert_items
WHEN NEW.status = 'working'
BEGIN
  INSERT INTO working_transitions (item_id) VALUES (NEW.id);
END;
"""


class _Allowance:
    """The daily conversion allowance, reduced to a counter and a verdict."""

    def __init__(self, *, allowed: bool = True):
        self.allowed = allowed
        self.takes = 0

    async def authorize_conversion(self, *, user_id, grade):
        self.takes += 1
        if not self.allowed:
            return UsageDecision(
                allowed=False, code="conversion_quota_exhausted", status_code=429,
                subject_type="user", bucket_type=CONVERSION_BUCKET_TYPE, limit=2,
            )
        return UsageDecision(
            allowed=True, subject_type="user", bucket_type=CONVERSION_BUCKET_TYPE,
            count=self.takes, limit=10,
        )


def _hold_between_read_and_write(monkeypatch, seconds: float) -> None:
    """Keep every run request between its read of the item and its write.

    The grade lookup is the await that sits there; in production it is a
    membership read. Holding it is what lets two requests overlap for sure.
    """

    async def slow_grade(_request, _user_id):
        await asyncio.sleep(seconds)
        return "free"

    monkeypatch.setattr(document_convert_routes, "_conversion_grade", slow_grade)


def _working_transitions(connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM working_transitions").fetchone()[0]


@pytest.mark.asyncio
async def test_two_simultaneous_runs_change_the_item_to_working_once(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes, "convert_pdf_to_markdown", _conversion_stand_in(0.1, calls)
    )
    _hold_between_read_and_write(monkeypatch, 0.2)
    d1 = FakeD1()
    d1.conn.executescript(WORKING_TRANSITIONS)
    client, app = await build_client(d1=d1)
    allowance = _Allowance()
    app.state.usage_gate = allowance
    app.state.usage_gate_enforced = True
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Race page 1"]), name="race.pdf")
        item_id = created.json()["items"][0]["id"]

        answers = await asyncio.gather(run_item(client, item_id), run_item(client, item_id))
        assert [answer.status_code for answer in answers] == [202, 202]
        assert [answer.json()["item"]["status"] for answer in answers] == ["working", "working"]
        # Only the request that started the run reports the allowance it took.
        assert sorted("conversion" in answer.json() for answer in answers) == [False, True]

        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "reviewed"
        assert _working_transitions(d1.conn) == 1
        assert len(calls) == 1, f"the item was converted {len(calls)} times"
        assert allowance.takes == 1, f"the allowance was taken {allowance.takes} times"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_refused_allowance_leaves_the_item_exactly_as_it_was(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes, "convert_pdf_to_markdown", _conversion_stand_in(0.0, calls)
    )
    d1 = FakeD1()
    client, app = await build_client(d1=d1)
    allowance = _Allowance(allowed=False)
    app.state.usage_gate = allowance
    app.state.usage_gate_enforced = True

    def row():
        return dict(d1.conn.execute(
            "SELECT status, updated_at, error_code, markdown_key "
            "FROM document_convert_items WHERE id = ?", (item_id,)
        ).fetchone())

    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Quota page 1"]), name="quota.pdf")
        item_id = created.json()["items"][0]["id"]
        before = row()
        assert before["status"] == "queued"

        denied = await run_item(client, item_id)
        assert denied.status_code == 429, denied.text
        assert denied.json() == {
            "error": {
                "code": "conversion_quota_exhausted",
                "message": "오늘 변환 한도를 다 썼어요. 내일 다시 이용해 주세요.",
            },
            "conversion": {"daily_limit": 2, "remaining": 0},
        }
        assert row() == before
        await asyncio.sleep(0.2)
        assert calls == [], "a refused run must not convert"

        # Once the allowance returns, the same item starts like any other.
        allowance.allowed = True
        started = await run_item(client, item_id)
        assert started.status_code == 202, started.text
        assert (await wait_item_terminal(client, item_id))["status"] == "reviewed"
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_run_claim_is_won_by_exactly_one_of_two_connections(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    connections = [connect(str(database)) for _ in range(2)]
    try:
        connections[0].execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        connections[0].execute(
            "INSERT INTO users (id, email) VALUES (?, ?)", (OWNER, "owner@example.test")
        )
        connections[0].executescript(MIGRATION.read_text(encoding="utf8"))
        connections[0].executescript(WORKING_TRANSITIONS)
        stores = [
            D1DocumentConvertStore(SqliteD1(connection, threaded=True))
            for connection in connections
        ]
        job = await stores[0].create_job(OWNER, mode="fast")
        item = await stores[0].add_item(OWNER, job.id, name="claim.pdf")
        observed = await stores[1].get_item(OWNER, item.id)

        claims = await asyncio.gather(
            *(stores[index % 2].claim_item_run(OWNER, observed) for index in range(8))
        )
        winners = [claim for claim in claims if claim is not None]
        assert len(winners) == 1
        assert winners[0].status == "working"
        assert _working_transitions(connections[1]) == 1
        # Another owner's id never matches the row.
        assert await stores[1].claim_item_run("usr_" + "c" * 32, observed) is None

        # Only the exact claim can be put back, and it restores what it replaced.
        assert not await stores[1].release_item_run(OWNER, observed, observed)
        assert await stores[0].release_item_run(OWNER, winners[0], observed)
        back = await stores[1].get_item(OWNER, item.id)
        assert (back.status, back.updated_at) == (observed.status, observed.updated_at)
        # A row that already holds a result is never claimed.
        await stores[0].complete_item(
            OWNER, item.id, status="reviewed", page_count=1, character_count=1,
            markdown_key="documents/x.md", report=None, error_code=None,
        )
        finished = await stores[1].get_item(OWNER, item.id)
        assert await stores[1].claim_item_run(OWNER, finished) is None
    finally:
        for connection in connections:
            connection.close()


@pytest.mark.asyncio
async def test_claim_in_the_same_millisecond_is_still_its_own_row(monkeypatch):
    """CI 2026-11-12: upload and claim landed in one millisecond.

    The claim then wrote the timestamp it had read, so a release handed the
    observed row matched a claim it did not own. The clock is frozen here so
    that millisecond happens every time.
    """

    from app import document_convert_store

    monkeypatch.setattr(document_convert_store, "_now_iso", lambda: "2026-11-12T09:00:00.000Z")
    d1 = FakeD1()
    store = D1DocumentConvertStore(d1)
    job = await store.create_job(OWNER, mode="fast")
    item = await store.add_item(OWNER, job.id, name="same-ms.pdf")
    observed = await store.get_item(OWNER, item.id)
    assert observed.updated_at == "2026-11-12T09:00:00.000Z"

    claimed = await store.claim_item_run(OWNER, observed)
    assert claimed is not None and claimed.status == "working"
    assert claimed.updated_at == "2026-11-12T09:00:00.001Z"
    assert await store.claim_item_run(OWNER, observed) is None
    # Only the claim itself can be put back.
    assert not await store.release_item_run(OWNER, observed, observed)
    assert await store.release_item_run(OWNER, claimed, observed)
    back = await store.get_item(OWNER, item.id)
    assert (back.status, back.updated_at) == ("queued", observed.updated_at)


def _worker_environment() -> dict[str, str]:
    environment = dict(os.environ)
    # All subprocess traffic is in-process ASGI; never inherit a proxy.
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        environment.pop(name, None)
    # The workers must import exactly the tree under test, whatever else is
    # installed in this interpreter.
    environment["PYTHONPATH"] = os.pathsep.join(item for item in sys.path if item)
    environment["PADIEM_CHAT_SESSION_USER_ROW_CHECK"] = "false"
    return environment


def test_two_processes_running_the_same_item_change_it_to_working_once(tmp_path):
    database = tmp_path / "chat.sqlite3"
    objects = tmp_path / "objects"
    conversions = tmp_path / "conversions.log"
    allowances = tmp_path / "allowances.log"
    start = tmp_path / "start"
    ready = [tmp_path / f"ready-{index}" for index in range(2)]

    # The host's startup path: every shipped migration, then one queued item.
    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        apply_migrations(connection, MIGRATIONS)
        connection.executescript(WORKING_TRANSITIONS)
        connection.execute(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name,"
            " picture_url, created_at, updated_at) VALUES (?, 'google', ?, ?, '', '', ?, ?)",
            (OWNER, "issue7543-owner", "owner@example.test",
             "2026-11-12T00:00:00Z", "2026-11-12T00:00:00Z"),
        )

        async def seed() -> str:
            ledger = D1DocumentConvertStore(SqliteD1(connection))
            job = await ledger.create_job(OWNER, mode="fast")
            item = await ledger.add_item(OWNER, job.id, name="two-workers.pdf")
            LocalDiskR2(objects).put(
                item.original_key, pdf_bytes(texts=["Two workers page 1"]),
                {"contentType": "application/pdf"},
            )
            return item.id

        item_id = asyncio.run(seed())

        processes = [
            subprocess.Popen(
                [sys.executable, str(RUN_CLAIM_WORKER), str(database), str(objects),
                 str(conversions), str(allowances), str(marker), str(start), item_id, "0.5"],
                env=_worker_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8",
            )
            for marker in ready
        ]
        try:
            until = time.monotonic() + 60
            while not all(marker.exists() for marker in ready):
                assert all(process.poll() is None for process in processes), [
                    process.communicate()[1] for process in processes if process.poll() is not None
                ]
                assert time.monotonic() < until, "worker subprocess did not become ready"
                time.sleep(0.02)
            start.touch()
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=90)
                assert process.returncode == 0, stderr
                results.append(json.loads(stdout.strip().splitlines()[-1]))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

        assert [result["status"] for result in results] == [202, 202]
        assert [result["final"] for result in results] == ["reviewed", "reviewed"]
        assert _working_transitions(connection) == 1
        converted_by = conversions.read_text(encoding="utf-8").split()
        assert len(converted_by) == 1, f"the item was converted {len(converted_by)} times"
        took_allowance = allowances.read_text(encoding="utf-8").split()
        assert took_allowance == converted_by, (
            f"the allowance was taken {len(took_allowance)} times"
        )
        stored = connection.execute(
            "SELECT status, markdown_key FROM document_convert_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert stored["status"] == "reviewed" and stored["markdown_key"]
    finally:
        connection.close()
