"""#5568 목록 읽기 — the ledger read against the real COM2 SQLite facade.

The route tests drive a D1-shaped fake whose ``all()`` already answered
``{"results": rows}``. Production does not: ``app.d1_sqlite.SqliteD1.all()`` returns a
bare list, so ``_rows_from_result`` read it as an empty ledger and the owner's history,
item list, archive and job roll-up all came back empty while every test stayed green.

Everything here runs on that real facade over the shipped 066 migration: the row-shape
normalization, the owner-facing history/item list with the reviewed roll-up, and the
screen paths (list, convert, ZIP archive). The run()-based read case is deliberately
not part of this suite.
"""
from __future__ import annotations

import sqlite3
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest

from app.d1_sqlite import SqliteD1
from app.document_convert_store import (
    JOB_STATUS_REVIEWED,
    D1DocumentConvertStore,
    markdown_object_key,
    _rows_from_result,
)

from test_5568_document_convert_routes import (
    MIGRATION,
    OWNER,
    MemoryR2,
    build_client,
    open_job,
    pdf_bytes,
    run_item,
    upload,
    wait_item_terminal,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
    connection.execute("INSERT INTO users (id, email) VALUES (?, ?)", (OWNER, f"{OWNER}@example.test"))
    connection.executescript(MIGRATION.read_text(encoding="utf8"))
    return connection


def _sqlite_d1() -> SqliteD1:
    """The same facade the CPython host binds in Production."""
    return SqliteD1(_connection())


def test_rows_from_result_accepts_both_backend_shapes():
    row = {"id": "dcj_" + "a" * 32}
    assert _rows_from_result([row]) == [row]
    assert _rows_from_result({"results": [row]}) == [row]
    assert _rows_from_result(SimpleNamespace(results=[row])) == [row]
    assert _rows_from_result([]) == []
    assert _rows_from_result(None) == []


@pytest.mark.asyncio
async def test_store_lists_jobs_and_items_on_the_sqlite_facade():
    ledger = D1DocumentConvertStore(_sqlite_d1())
    job = await ledger.create_job(OWNER, mode="verify")
    first = await ledger.add_item(OWNER, job.id, name="first.pdf")
    second = await ledger.add_item(OWNER, job.id, name="second.pdf")

    jobs = await ledger.list_jobs(OWNER, limit=50)
    assert [record.id for record in jobs] == [job.id]
    assert jobs[0].item_count == 2
    assert [record.name for record in await ledger.list_items(OWNER, job.id)] == [
        "first.pdf",
        "second.pdf",
    ]

    for record in (first, second):
        await ledger.complete_item(
            OWNER,
            record.id,
            status=JOB_STATUS_REVIEWED,
            page_count=1,
            character_count=24,
            markdown_key=markdown_object_key(OWNER, job.id, record.id),
            report=None,
            error_code=None,
        )
    refreshed = await ledger.refresh_job(OWNER, job.id)
    assert refreshed is not None and refreshed.status == JOB_STATUS_REVIEWED


@pytest.mark.asyncio
async def test_screen_paths_list_convert_and_archive_on_the_sqlite_facade(monkeypatch):
    from app import document_convert_routes

    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)
    r2 = MemoryR2()
    client, _app = await build_client(d1=_sqlite_d1(), r2=r2)
    try:
        job_id = await open_job(client, mode="verify")
        item_ids = []
        for name, marker in (("first.pdf", "First page text"), ("second.pdf", "Second page text")):
            created = await upload(client, job_id, pdf_bytes(texts=[marker]), name=name)
            assert created.status_code == 201, created.text
            item_ids.append(created.json()["items"][0]["id"])

        listing = await client.get("/api/document-conversions?limit=50")
        assert listing.status_code == 200, listing.text
        assert [record["id"] for record in listing.json()["jobs"]] == [job_id]

        detail = await client.get(f"/api/document-conversions/{job_id}")
        assert detail.status_code == 200, detail.text
        assert [record["id"] for record in detail.json()["items"]] == item_ids

        for item_id in item_ids:
            ran = await run_item(client, item_id)
            assert ran.status_code == 202, ran.text
            assert ran.json()["item"]["status"] == "working"
        for item_id in item_ids:
            assert (await wait_item_terminal(client, item_id))["status"] == "reviewed"

        rolled_up = await client.get(f"/api/document-conversions/{job_id}")
        assert rolled_up.json()["job"]["status"] == "reviewed"

        bundle = await client.get(f"/api/document-conversions/{job_id}/archive")
        assert bundle.status_code == 200, bundle.text
        with zipfile.ZipFile(BytesIO(bundle.content)) as archive:
            members = archive.namelist()
            markdown = sorted(name for name in members if name.endswith(".md"))
            assert len(markdown) == 2, members
            assert "manifest.json" in members
            manifest = archive.read("manifest.json").decode("utf-8")
        assert '"converted": 2' in manifest
        assert sum(1 for key in r2.objects if key.endswith(".md")) == 2
    finally:
        await client.aclose()
