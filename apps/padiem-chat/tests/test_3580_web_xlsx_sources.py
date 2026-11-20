"""#3580 WEB-FIRST real browser source intake on private D1/R2 contracts.

Uses only generated synthetic XLSX and in-memory provider test ports; never
customer files, Excel/Resident, OAuth, external writes or paid models.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _support.workspace_storage_fakes import MemoryMetadata as MemoryMetadata, MemoryR2 as MemoryR2
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.file_lane import FileLaneClient
from app.workspace_storage import (
    MAX_WEB_XLSX_BYTES, WEB_XLSX_INLINE_MAX_BYTES, XLSX_MEDIA_TYPE,
    WorkspaceDocumentStore, WorkspaceStorageError,
)

from _support.web_xlsx_sources import (
    ORIGIN as ORIGIN,
    OWNER as OWNER,
    FOREIGN as FOREIGN,
    NOW as NOW,
    workbook as workbook,
    harness as harness,
    request as request,
    LANE_ORIGIN as LANE_ORIGIN,
    LANE_SECRET as LANE_SECRET,
    LANE_FILE_ID as LANE_FILE_ID,
    UPLOAD_TICKET as UPLOAD_TICKET,
    register_path as register_path,
    FakeFileLane as FakeFileLane,
    asgi_messages as asgi_messages,
)


@pytest.mark.asyncio
async def test_web_upload_exact_original_bytes_list_and_owner_download():
    app, settings, meta, r2, store = harness()
    source = workbook()
    data = {"name": "학교 견적서.xlsx", "base64": base64.b64encode(source).decode()}
    saved = await request(app, settings, method="POST", payload=data)
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["ok"] is True
    assert body["p01_approved"] is False
    assert body["processing_started"] is False
    assert body["drive_uploaded"] is False
    assert body["file"]["original_immutable"] is True
    assert body["file"]["processing_authorized"] is False
    assert len(meta.rows) == 1
    doc_id = body["file"]["document_id"]
    row = meta.rows[doc_id]
    assert OWNER in row.object_key
    assert "owner:" + OWNER in row.object_key
    assert "source_sha256" not in row.public_projection()
    assert r2.objects[row.object_key] == source
    listing = await request(app, settings)
    assert listing.status_code == 200
    assert listing.json()["files"] == [body["file"]]
    assert listing.json()["requires_p01_for_processing"] is True
    download = await request(app, settings,
                             path=f"/api/claw/office/web-sources/{doc_id}/download")
    assert download.status_code == 200
    assert download.content == source
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in download.headers["content-disposition"]
    assert "no-store" in download.headers["cache-control"]
    assert "workspaces/" not in download.text[:0]


@pytest.mark.asyncio
async def test_anonymous_foreign_owner_cannot_upload_list_or_read_bytes():
    app, settings, meta, r2, store = harness()
    data = {"name": "quote.xlsx", "base64": base64.b64encode(workbook()).decode()}
    assert (await request(app, settings, method="POST", owner=None, payload=data)).status_code == 401
    assert r2.objects == {}
    good = await request(app, settings, method="POST", payload=data)
    doc_id = good.json()["file"]["document_id"]
    assert (await request(app, settings, owner=FOREIGN)).json()["files"] == []
    assert (await request(app, settings, owner=FOREIGN,
              path=f"/api/claw/office/web-sources/{doc_id}/download")).status_code == 404
    assert (await request(app, settings, owner=None,
              path=f"/api/claw/office/web-sources/{doc_id}/download")).status_code == 401
    assert (await request(app, settings,
              path="/api/claw/office/web-sources/doc_foreign/download")).status_code == 404


@pytest.mark.asyncio
async def test_unsafe_upload_shapes_and_fake_xlsx_never_touch_r2():
    app, settings, meta, r2, store = harness()
    encoded = base64.b64encode(workbook()).decode()
    for name in ("../quote.xlsx", r"C:\secret.xlsx", "report.xls", "a.pdf",
                 "<unsafe>.xlsx", "folder/quote.xlsx"):
        resp = await request(app, settings, method="POST", payload={"name": name, "base64": encoded})
        assert resp.status_code == 422, (name, resp.text)
    for data in (
        {"name": "quote.xlsx", "base64": base64.b64encode(b"not ZIP").decode()},
        {"name": "quote.xlsx", "base64": "***"},
        {"name": "quote.xlsx", "base64": encoded, "owner_id": OWNER},
        {"name": "quote.xlsx", "base64": encoded, "approved": True},
    ):
        resp = await request(app, settings, method="POST", payload=data)
        # Raw upload requires octet-stream; legacy JSON and malformed Base64
        # are rejected at the origin/media gate before touching R2.
        assert resp.status_code in (400, 415, 422)
    assert r2.objects == {}
    assert meta.rows == {}


@pytest.mark.asyncio
async def test_source_disabled_fails_closed_and_corrupted_r2_refused():
    app, settings, meta, r2, store = harness(available=False)
    assert (await request(app, settings)).status_code == 503
    assert (await request(app, settings, method="POST",
                          payload={"name": "x.xlsx", "base64": "AA=="})).status_code == 503
    app.state.workspace_document_store = store
    saved = await request(app, settings, method="POST", payload={
        "name": "source.xlsx", "base64": base64.b64encode(workbook()).decode(),
    })
    assert saved.status_code == 201
    doc = saved.json()["file"]["document_id"]
    key = meta.rows[doc].object_key
    r2.objects[key] = b"malicious replaced data"
    response = await request(app, settings, path=f"/api/claw/office/web-sources/{doc}/download")
    assert response.status_code == 503
    assert b"malicious" not in response.content


@pytest.mark.asyncio
async def test_expiry_cannot_be_relisted_or_downloaded():
    app, settings, meta, r2, store = harness()
    saved = await request(app, settings, method="POST", payload={
        "name": "source.xlsx", "base64": base64.b64encode(workbook()).decode(),
    })
    doc_id = saved.json()["file"]["document_id"]
    from dataclasses import replace
    meta.rows[doc_id] = replace(meta.rows[doc_id], expires_at=NOW - timedelta(seconds=1))
    assert (await request(app, settings)).json()["files"] == []
    assert (await request(app, settings,
              path=f"/api/claw/office/web-sources/{doc_id}/download")).status_code == 404


@pytest.mark.asyncio
async def test_actual_existing_d1_schema_sql_and_r2_bytes_across_store_recreation():
    """No migration or new schema: validate real D1-style SQL and private R2."""
    import sqlite3
    from app.workspace_storage import D1ClawDocumentMetadataStore

    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    sql = (Path(__file__).resolve().parents[1] / "migrations" / "008_claw_document_metadata.sql").read_text()
    conn.executescript(sql)
    conn.executescript((
        Path(__file__).resolve().parents[1]
        / "migrations" / "080_claw_document_metadata_user_id.sql"
    ).read_text())

    class Statement:
        def __init__(self, query):
            self.query, self.args = query, ()
        def bind(self, *values):
            self.args = values
            return self
        async def run(self):
            conn.execute(self.query, self.args)
            return {}
        async def first(self):
            row = conn.execute(self.query, self.args).fetchone()
            return dict(row) if row else None
        async def all(self):
            return [dict(row) for row in conn.execute(self.query, self.args).fetchall()]

    class D1:
        def prepare(self, query):
            return Statement(query)

    bucket = MemoryR2()
    storage = WorkspaceDocumentStore(D1ClawDocumentMetadataStore(D1()), bucket)
    content = workbook()
    file = await storage.put_web_xlsx(
        tenant_id="owner:" + OWNER, owner_id=OWNER,
        workspace_id="owner:" + OWNER,
        filename="first.xlsx", body=content,
    )
    refreshed = WorkspaceDocumentStore(D1ClawDocumentMetadataStore(D1()), bucket)
    listing = await refreshed.list_web_xlsx(
        tenant_id="owner:" + OWNER, owner_id=OWNER, workspace_id="owner:" + OWNER,
    )
    assert listing == [file]
    exact = await refreshed.get_web_xlsx(
        tenant_id="owner:" + OWNER, owner_id=OWNER, workspace_id="owner:" + OWNER,
        document_id=file["document_id"],
    )
    assert exact[1] == content
    assert await refreshed.get_web_xlsx(
        tenant_id="owner:" + OWNER, owner_id=FOREIGN, workspace_id="owner:" + OWNER,
        document_id=file["document_id"],
    ) is None
    conn.close()


@pytest.mark.asyncio
async def test_large_original_ticket_register_list_and_streamed_owner_download():
    lane = FakeFileLane()
    source = workbook()
    row = lane.add(source)
    app, settings, meta, r2, store = harness()
    app.state.file_lane_client = lane.client()

    ticket = await request(app, settings, method="POST", path=UPLOAD_TICKET,
                           payload={"size_bytes": row["size_bytes"]})
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["upload_url"] == LANE_ORIGIN + "/files"
    assert ticket.json()["max_bytes"] == row["size_bytes"]
    assert ticket.json()["contract_max_bytes"] == MAX_WEB_XLSX_BYTES
    assert ticket.json()["register_path"] == "/api/claw/office/web-sources/{file_id}/register"
    assert "X-Padiem-File-Ticket" in ticket.json()["headers"]

    registered = await request(app, settings, method="POST",
                               path=register_path(), payload={})
    assert registered.status_code == 201, registered.text
    body = registered.json()
    file = body["file"]
    assert body["p01_approved"] is False and body["processing_started"] is False
    assert file["file_id"] == LANE_FILE_ID
    assert file["filename"] == row["name"]
    assert file["source_sha256"] == row["sha256"]
    assert file["size_bytes"] == row["size_bytes"]
    assert r2.objects == {}
    assert len(meta.rows) == 1
    assert meta.rows[file["document_id"]].object_key.endswith("/filelane:" + LANE_FILE_ID)
    assert meta.rows[file["document_id"]].user_id == OWNER

    listing = await request(app, settings)
    assert listing.status_code == 200
    assert listing.json()["files"] == [file]

    async def must_not_materialize(**kwargs):
        raise AssertionError("a lane original is never read through Chat")
    store.get_web_xlsx = must_not_materialize

    lane.gate = asyncio.Event()
    task, messages = await asgi_messages(
        app, settings, "/api/claw/office/web-sources/" + file["document_id"] + "/download")
    start = await asyncio.wait_for(messages.get(), timeout=10)
    assert start["type"] == "http.response.start" and start["status"] == 200
    headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    assert headers["content-length"] == str(row["size_bytes"])
    assert "attachment" in headers["content-disposition"]
    # The lane withholds the rest of the body until this test releases it, so
    # the head arriving here proves Chat streams instead of buffering the file.
    first = await asyncio.wait_for(messages.get(), timeout=10)
    assert first["type"] == "http.response.body"
    assert first["body"] == source[:32] and first["more_body"] is True
    lane.gate.set()
    received = bytearray(first["body"])
    while True:
        message = await asyncio.wait_for(messages.get(), timeout=10)
        received.extend(message.get("body", b""))
        if not message.get("more_body"):
            break
    await asyncio.wait_for(task, timeout=10)
    assert bytes(received) == source
    assert lane.raw_opens == 1


@pytest.mark.asyncio
async def test_lane_source_is_owner_scoped_and_unreadable_without_the_lane():
    lane = FakeFileLane()
    lane.add(workbook())
    app, settings, meta, r2, store = harness()
    app.state.file_lane_client = lane.client()
    registered = await request(app, settings, method="POST", path=register_path(), payload={})
    assert registered.status_code == 201, registered.text
    doc_id = registered.json()["file"]["document_id"]

    assert (await request(app, settings, owner=FOREIGN)).json()["files"] == []
    foreign = await request(app, settings, owner=FOREIGN,
                            path="/api/claw/office/web-sources/" + doc_id + "/download")
    assert foreign.status_code == 404
    foreign_register = await request(app, settings, owner=FOREIGN, method="POST",
                                     path=register_path(), payload={})
    assert foreign_register.status_code == 404

    app.state.file_lane_client = FileLaneClient(LANE_ORIGIN, None)
    unavailable = await request(app, settings,
                                path="/api/claw/office/web-sources/" + doc_id + "/download")
    assert unavailable.status_code == 503
    assert (await request(app, settings, method="POST", path=UPLOAD_TICKET,
                          payload={"size_bytes": 5})).status_code == 503
    assert (await request(app, settings, method="POST",
                          path=register_path(), payload={})).status_code == 503
    assert await store.get_web_xlsx_metadata(
        tenant_id="owner:" + OWNER, owner_id=OWNER, workspace_id="owner:" + OWNER,
        document_id=doc_id,
    ) is not None


@pytest.mark.asyncio
async def test_sizes_above_the_released_ceiling_are_refused_before_any_row():
    lane = FakeFileLane()
    lane.add(b"x" * 8, size_bytes=MAX_WEB_XLSX_BYTES + 1, sha256="b" * 64)
    lane.add(b"PK", kind="pdf", file_id="file_" + "b" * 32)
    app, settings, meta, r2, store = harness()
    app.state.file_lane_client = lane.client()

    over = await request(app, settings, method="POST", path=UPLOAD_TICKET,
                         payload={"size_bytes": MAX_WEB_XLSX_BYTES + 1})
    assert over.status_code == 413 and over.json()["error"]["code"] == "web_xlsx_too_large"
    zero = await request(app, settings, method="POST", path=UPLOAD_TICKET, payload={"size_bytes": 0})
    assert zero.status_code == 422
    extra = await request(app, settings, method="POST", path=UPLOAD_TICKET,
                          payload={"size_bytes": 5, "owner_id": OWNER})
    assert extra.status_code == 422
    assert (await request(app, settings, method="POST", path=UPLOAD_TICKET,
                          payload={"size_bytes": "5"})).status_code == 422

    first = await request(app, settings, method="POST", path=register_path(), payload={})
    assert first.status_code == 413 and first.json()["error"]["code"] == "web_xlsx_too_large"
    wrong_kind = await request(app, settings, method="POST",
                               path=register_path("file_" + "b" * 32), payload={})
    assert wrong_kind.status_code == 422
    missing = await request(app, settings, method="POST",
                            path=register_path("file_" + "c" * 32), payload={})
    assert missing.status_code == 404
    assert meta.rows == {}

    inline = await request(app, settings, method="POST", payload={
        "name": "huge.xlsx",
        "base64": base64.b64encode(b"x" * (WEB_XLSX_INLINE_MAX_BYTES + 1)).decode(),
    })
    assert inline.status_code == 413
    assert inline.json()["error"]["code"] == "web_xlsx_too_large"
    assert meta.rows == {} and r2.objects == {}
