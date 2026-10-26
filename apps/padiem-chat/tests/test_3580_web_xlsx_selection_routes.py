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


def test_limit_migration_preserves_rows_receipts_and_fks_in_one_transaction():
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript((migrations / "029_claw_web_xlsx_selection.sql").read_text())
    conn.executescript((migrations / "032_claw_web_xlsx_quote_edit_receipts.sql").read_text())
    row = ("sel_" + "a" * 32, OWNER, "ws", "doc_" + "b" * 32,
           "c" * 64, "safe.xlsx", 1048576,
           "source_selected_p01_not_started", "created", "expires")
    conn.execute("INSERT INTO claw_web_xlsx_selections VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    receipt = (row[0], OWNER, "ws", "run", row[3], row[4], "workcopy",
               "d" * 64, "school", 100, "confirmed", "revision", "e" * 64,
               "created", "updated")
    conn.execute("INSERT INTO claw_web_xlsx_quote_edit_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", receipt)
    conn.executescript("BEGIN;" + (migrations / "071_claw_web_xlsx_selection_limit.sql").read_text() + "COMMIT;")
    assert conn.execute("SELECT * FROM claw_web_xlsx_selections").fetchone() == row
    assert conn.execute("SELECT * FROM claw_web_xlsx_quote_edit_receipts").fetchone() == receipt
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
    conn.execute("UPDATE claw_web_xlsx_selections SET size_bytes=?", (1024 * 1024 * 1024,))
    for invalid in (0, 1024 * 1024 * 1024 + 1):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE claw_web_xlsx_selections SET size_bytes=?", (invalid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE claw_web_xlsx_selections SET source_sha256='bad'")
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_claw_web_xlsx_selections_owner'").fetchone()
    conn.close()


@pytest.mark.asyncio
async def test_xlsx_upload_above_legacy_limit_uses_new_sql_and_keeps_owner_scope():
    from io import BytesIO
    from zipfile import ZipFile
    import hashlib
    from app.workspace_storage import MAX_WEB_XLSX_BYTES
    app, settings, metadata, r2, source, conn = setup()
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    conn.executescript((migrations / "032_claw_web_xlsx_quote_edit_receipts.sql").read_text())
    conn.executescript((migrations / "071_claw_web_xlsx_selection_limit.sql").read_text())
    # Exercise real bytes with a small fixture; the 1GiB boundary is metadata-only.
    payload_size = 2 * 1024 * 1024
    assert MAX_WEB_XLSX_BYTES == 1024 * 1024 * 1024
    output = BytesIO(workbook())
    with ZipFile(output, "a") as archive:
        archive.writestr("xl/padding.bin", b"a" * (payload_size - len(workbook()) - 104))
    raw = output.getvalue()
    assert 1048576 < len(raw) <= MAX_WEB_XLSX_BYTES
    response = await request(app, settings, method="POST", payload={
        "name": "large.xlsx", "base64": base64.b64encode(raw).decode(),
    })
    assert response.status_code == 201, response.text
    file = response.json()["file"]
    selection = await selected(app, settings, file["document_id"])
    assert selection.status_code == 201, selection.text
    persisted = conn.execute("SELECT size_bytes, source_sha256 FROM claw_web_xlsx_selections").fetchone()
    assert tuple(persisted) == (len(raw), hashlib.sha256(raw).hexdigest())
    foreign = await selected(app, settings, file["document_id"], owner=FOREIGN)
    assert foreign.status_code in (403, 404)
    assert conn.execute("SELECT COUNT(*) FROM claw_web_xlsx_selections").fetchone()[0] == 1


def test_one_gib_selection_metadata_boundary_without_loading_file_contents():
    from app.claw_web_xlsx_selection_store import WebXlsxSelectionError
    from app.workspace_storage import MAX_WEB_XLSX_BYTES
    from app.attachments import MAX_IMAGE_BYTES
    from app.claw_web_xlsx_quote_editor import _SOURCE_MAX, _PACKAGE_MAX
    from padiem_ai_core.document_normalization import MAX_BINARY_DOCUMENT_BYTES
    assert MAX_WEB_XLSX_BYTES == _SOURCE_MAX == MAX_IMAGE_BYTES == MAX_BINARY_DOCUMENT_BYTES == 1024 * 1024 * 1024
    assert _PACKAGE_MAX == 32 * 1024 * 1024
    app, _, _, _, _, conn = setup()
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    conn.executescript((migrations / "032_claw_web_xlsx_quote_edit_receipts.sql").read_text())
    conn.executescript((migrations / "071_claw_web_xlsx_selection_limit.sql").read_text())
    source = {"document_id": "doc_" + "d" * 32, "source_sha256": "a" * 64,
              "filename": "metadata-only.xlsx", "size_bytes": MAX_WEB_XLSX_BYTES,
              "original_immutable": True, "processing_authorized": False,
              "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    store = app.state.claw_web_xlsx_selection_store
    selected = asyncio.run(store.select(owner_id=OWNER, workspace_id="ws", source=source))
    assert selected["size_bytes"] == MAX_WEB_XLSX_BYTES
    assert conn.execute("SELECT size_bytes FROM claw_web_xlsx_selections").fetchone()[0] == MAX_WEB_XLSX_BYTES
    for invalid in (0, MAX_WEB_XLSX_BYTES + 1):
        with pytest.raises(WebXlsxSelectionError):
            asyncio.run(store.select(owner_id=OWNER, workspace_id="ws", source={**source, "size_bytes": invalid}))
    assert conn.execute("SELECT COUNT(*) FROM claw_web_xlsx_selections").fetchone()[0] == 1
    conn.close()


@pytest.mark.asyncio
async def test_upload_above_one_gib_header_is_rejected_before_body_allocation():
    from app.workspace_storage import MAX_WEB_XLSX_BYTES
    app, settings, metadata, r2, _ = harness()
    result = await request(app, settings, method="POST", payload={
        "name": "small.xlsx", "base64": base64.b64encode(workbook()).decode(),
    }, headers={"Content-Length": str(MAX_WEB_XLSX_BYTES + 1)})
    assert result.status_code == 413
    assert result.json()["error"]["code"] == "web_xlsx_too_large"
    assert not metadata.rows
    assert not r2.objects
