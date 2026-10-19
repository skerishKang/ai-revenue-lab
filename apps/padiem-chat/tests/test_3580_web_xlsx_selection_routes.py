"""#3580 WEB-FIRST selection: real SQL + HTTP, no Engine/permission minting."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_sources import harness, request, workbook, OWNER, FOREIGN
from app.claw_web_xlsx_selection_store import D1WebXlsxSelectionStore

ENDPOINT = "/api/claw/office/web-selections"


class RealSQLiteD1:
    def __init__(self, conn):
        self.conn = conn

    def prepare(self, query):
        return D1Statement(self.conn, query)


class D1Statement:
    def __init__(self, conn, query):
        self.conn, self.query, self.args = conn, query, ()
    def bind(self, *args):
        self.args = args
        return self
    async def run(self):
        self.conn.execute(self.query, self.args)
        return {}
    async def first(self):
        row = self.conn.execute(self.query, self.args).fetchone()
        return dict(row) if row else None
    async def all(self):
        return [dict(row) for row in self.conn.execute(self.query, self.args).fetchall()]


def setup():
    app, settings, metadata, r2, source = harness()
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "029_claw_web_xlsx_selection.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    app.state.claw_web_xlsx_selection_store = D1WebXlsxSelectionStore(RealSQLiteD1(conn))
    return app, settings, metadata, r2, source, conn


async def upload(app, settings, name="safe.xlsx"):
    resp = await request(app, settings, method="POST",
                         payload={"name": name, "base64": base64.b64encode(workbook()).decode()})
    assert resp.status_code == 201, resp.text
    return resp.json()["file"]


async def selected(app, settings, document_id, *, owner=OWNER, data=None):
    return await request(
        app, settings, path=ENDPOINT, method="POST", owner=owner,
        payload=data if data is not None else {"document_id": document_id},
    )


@pytest.mark.asyncio
async def test_authenticated_exact_original_selection_is_durable_after_store_restart_without_reading_r2():
    app, settings, meta, r2, storage, conn = setup()
    file = await upload(app, settings)
    # Selection never opens workbook bytes; it only uses D1 trusted metadata.
    async def cannot_read(_key):
        raise AssertionError("P01 has not approved reading R2 bytes")
    r2.get = cannot_read
    response = await selected(app, settings, file["document_id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["p01_approval_started"] is False
    assert body["processing_started"] is False
    assert body["workcopy_created"] is False
    assert body["drive_uploaded"] is False
    row = body["selection"]
    assert row["status"] == "source_selected_p01_not_started"
    assert row["source_sha256"] == file["source_sha256"]
    assert row["document_id"] == file["document_id"]
    assert row["expires_at"] <= file["expires_at"]
    assert "sel_" in row["selection_ref"]
    # Recreate application state projection against the *same* D1.
    app.state.claw_web_xlsx_selection_store = D1WebXlsxSelectionStore(RealSQLiteD1(conn))
    listing = await request(app, settings, path=ENDPOINT)
    assert listing.status_code == 200
    assert listing.json()["selections"] == [row]
    detail = await request(app, settings,
                           path=ENDPOINT + "/" + row["selection_ref"])
    assert detail.status_code == 200
    assert detail.json()["selection"] == row
    conn.close()


@pytest.mark.asyncio
async def test_foreign_and_anonymous_owner_do_not_see_or_select_another_source():
    app, settings, meta, r2, storage, conn = setup()
    file = await upload(app, settings)
    saved = await selected(app, settings, file["document_id"])
    token = saved.json()["selection"]["selection_ref"]
    assert (await selected(app, settings, file["document_id"], owner=None)).status_code == 401
    assert (await selected(app, settings, file["document_id"], owner=FOREIGN)).status_code == 404
    assert (await request(app, settings, path=ENDPOINT, owner=FOREIGN)).json()["selections"] == []
    assert (await request(app, settings,
              path=ENDPOINT + "/" + token, owner=FOREIGN)).status_code == 404
    assert (await request(app, settings,
              path=ENDPOINT + "/" + token, owner=None)).status_code == 401
    assert len(list(conn.execute("SELECT * FROM claw_web_xlsx_selections"))) == 1
    conn.close()


@pytest.mark.asyncio
async def test_no_browser_supplied_authority_and_corrupt_document_metadata_not_selected():
    app, settings, meta, r2, storage, conn = setup()
    file = await upload(app, settings)
    for extra in (
        {"decision": "approve"},
        {"p01_approved": True},
        {"owner_id": OWNER},
        {"source_sha256": file["source_sha256"]},
        {"run_id": "foreign-run"},
        {"workspace_id": "owner:foreign"},
        {"local_file_path": "C:\\secrets.xlsx"},
    ):
        p = {"document_id": file["document_id"], **extra}
        assert (await selected(app, settings, file["document_id"], data=p)).status_code == 400
    assert (await selected(app, settings, "doc_" + "f"*32)).status_code == 404
    doc = file["document_id"]
    from dataclasses import replace
    meta.rows[doc] = replace(meta.rows[doc], expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert (await selected(app, settings, doc)).status_code == 404
    assert not list(conn.execute("SELECT * FROM claw_web_xlsx_selections"))
    conn.close()


@pytest.mark.asyncio
async def test_no_selection_store_fail_closed_without_writing_or_processing():
    app, settings, meta, r2, storage, conn = setup()
    file = await upload(app, settings)
    app.state.claw_web_xlsx_selection_store = None
    assert (await request(app, settings, path=ENDPOINT)).status_code == 503
    assert (await selected(app, settings, file["document_id"])).status_code == 503
    assert len(r2.objects) == 1  # immutable original stored only by earlier explicit upload
    conn.close()


@pytest.mark.asyncio
async def test_ttl_and_bounded_selection_count_rejects_extra():
    app, settings, meta, r2, storage, conn = setup()
    file = await upload(app, settings)
    for _ in range(20):
        assert (await selected(app, settings, file["document_id"])).status_code == 201
    assert (await selected(app, settings, file["document_id"])).status_code == 409
    listing = await request(app, settings, path=ENDPOINT)
    assert len(listing.json()["selections"]) == 20
    conn.execute("UPDATE claw_web_xlsx_selections SET expires_at='2000-01-01T00:00:00+00:00'")
    assert (await request(app, settings, path=ENDPOINT)).json()["selections"] == []
    conn.close()
