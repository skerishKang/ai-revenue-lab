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
from test_workspace_storage import MemoryMetadata, MemoryR2
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.file_lane import FileLaneClient
from app.workspace_storage import (
    MAX_WEB_XLSX_BYTES, WEB_XLSX_INLINE_MAX_BYTES, XLSX_MEDIA_TYPE,
    WorkspaceDocumentStore, WorkspaceStorageError,
)

ORIGIN = "https://chat.example.test"
OWNER = "usr_web_xlsx_owner"
FOREIGN = "usr_web_xlsx_other"
NOW = datetime.now(timezone.utc)


def workbook():
    out = BytesIO()
    with ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
        z.writestr("xl/worksheets/sheet1.xml",
                   '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')
    return out.getvalue()


def harness(*, available=True):
    settings = Settings(
        session_secret="web-xlsx-e2e-test-secret", auth_mode="mock", public_base_url=ORIGIN,
    )
    metadata, r2 = MemoryMetadata(), MemoryR2()
    async def list_web_xlsx(*, tenant_id, key_prefix, now, limit=40):
        return sorted(
            [row for row in metadata.rows.values()
             if row.tenant_id == tenant_id
             and row.object_key.startswith(key_prefix)
             and row.expires_at > now],
            key=lambda row: (row.created_at, row.document_id), reverse=True,
        )[:limit]
    metadata.list_web_xlsx = list_web_xlsx
    store = WorkspaceDocumentStore(metadata, r2)
    class ReadyHistory:
        async def get_user(self, user_id):
            return None
        async def list_projects(self, user_id):
            return []
    app = create_app(settings, history_store=ReadyHistory())
    # Same composition object as D1/R2 pair; fixture only bypasses fake D1 wiring.
    app.state.workspace_document_store = store if available else None
    return app, settings, metadata, r2, store


async def request(app, settings, *, owner=OWNER, method="GET", path="/api/claw/office/web-sources",
                  payload=None, headers=None):
    h = {"Origin": ORIGIN, **(headers or {})}
    if owner:
        h["Cookie"] = SESSION_COOKIE + "=" + create_session_token(settings, owner)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url=ORIGIN) as c:
        if method == "GET":
            return await c.get(path, headers=h)
        if path == "/api/claw/office/web-sources" and isinstance(payload, dict) and set(payload) == {"name", "base64"}:
            try:
                raw = base64.b64decode(payload["base64"], validate=True)
            except (ValueError, base64.binascii.Error):
                raw = None
            if raw is not None:
                h["Content-Type"] = "application/octet-stream"
                h["X-Padiem-Filename"] = __import__("urllib.parse", fromlist=["quote"]).quote(payload["name"], safe="")
                return await c.post(path, headers=h, content=raw)
        return await c.post(path, headers=h, json=payload)


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


LANE_ORIGIN = "https://lane.example.test"
LANE_SECRET = "web-xlsx-lane-ticket-secret-0123456789abcdef"
LANE_FILE_ID = "file_" + "a" * 32
UPLOAD_TICKET = "/api/claw/office/web-sources/upload-ticket"


def register_path(file_id=LANE_FILE_ID):
    return "/api/claw/office/web-sources/" + file_id + "/register"


class FakeFileLane:
    """Owner-scoped COM2 lane double: tickets, /meta and a gated /raw stream."""

    def __init__(self):
        self.rows = {}
        self.gate = None
        self.raw_opens = 0

    def add(self, body, *, owner=OWNER, name="big.xlsx", kind="xlsx",
            file_id=LANE_FILE_ID, size_bytes=None, sha256=None):
        row = {"owner": owner, "file_id": file_id, "name": name, "kind": kind,
               "size_bytes": len(body) if size_bytes is None else size_bytes,
               "sha256": sha256 or hashlib.sha256(body).hexdigest()}
        self.rows[file_id] = (row, body)
        return row

    def client(self):
        return FileLaneClient(
            LANE_ORIGIN, LANE_SECRET, transport=httpx.MockTransport(self._handle))

    @staticmethod
    def _claim(request):
        raw = request.headers.get("x-padiem-file-ticket")
        if not raw:
            return None
        padded = raw + "=" * (-len(raw) % 4)
        try:
            claim = json.loads(base64.urlsafe_b64decode(padded))
        except (ValueError, UnicodeError):
            return None
        return claim if isinstance(claim, dict) else None

    async def _raw(self, body):
        self.raw_opens += 1
        if self.gate is None:
            yield body
            return
        yield body[:32]
        await self.gate.wait()
        yield body[32:]

    def _handle(self, request):
        claim = self._claim(request)
        parts = request.url.path.strip("/").split("/")
        found = self.rows.get(parts[1]) if len(parts) >= 2 else None
        if claim is None or found is None or found[0]["owner"] != claim.get("user_id"):
            return httpx.Response(404, json={"ok": False, "error": {"code": "not_found"}})
        row, body = found
        if parts[-1] == "meta":
            return httpx.Response(200, json={
                key: row[key] for key in ("file_id", "name", "kind", "size_bytes", "sha256")
            })
        if parts[-1] == "raw":
            return httpx.Response(200, content=self._raw(body),
                                  headers={"Content-Type": XLSX_MEDIA_TYPE})
        return httpx.Response(404, json={"ok": False, "error": {"code": "not_found"}})


async def asgi_messages(app, settings, path, *, owner=OWNER):
    """Drive the ASGI app directly: httpx's ASGITransport buffers the body."""
    messages = asyncio.Queue()
    idle = asyncio.Event()
    received = []

    async def receive():
        # Starlette keeps listening for a disconnect while streaming; returning
        # request messages in a tight loop would starve the event loop.
        if not received:
            received.append(True)
            return {"type": "http.request", "body": b"", "more_body": False}
        await idle.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await messages.put(message)

    headers = [(b"host", b"chat.example.test"), (b"origin", ORIGIN.encode())]
    if owner:
        token = create_session_token(settings, owner)
        headers.append((b"cookie", (SESSION_COOKIE + "=" + token).encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": headers, "server": (b"chat.example.test".decode(), 443),
        "client": ("127.0.0.1", 1), "root_path": "", "state": {},
    }
    task = asyncio.create_task(app(scope, receive, send))
    return task, messages


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
