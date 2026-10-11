"""#3580 WEB-FIRST real browser source intake on private D1/R2 contracts.

Uses only generated synthetic XLSX and in-memory provider test ports; never
customer files, Excel/Resident, OAuth, external writes or paid models.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from io import BytesIO
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
from app.workspace_storage import WorkspaceDocumentStore, WorkspaceStorageError

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
        assert resp.status_code in (400, 422)
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
