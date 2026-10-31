"""#5568 PDF to Markdown utility — ledger routes over the real 066 schema.

The journey is driven from the HTTP boundary with the reviewed migration applied
to SQLite, so a statement that does not match the shipped schema fails here
rather than in Production.
"""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app

MIGRATION = Path(__file__).parents[1] / "migrations" / "066_document_convert_jobs.sql"
SESSION_SECRET = "phase5568-convert-session-secret-not-a-real-key-000000"
BASE = "https://chat.example.test"
PDF_MEDIA = "application/pdf"
ZIP_MEDIA = "application/zip"
OWNER = "usr_" + "a" * 32
INTRUDER = "usr_" + "c" * 32
STRANGER = "usr_" + "d" * 32
SEEDED = (OWNER, INTRUDER, STRANGER, "usr_x")

@pytest.fixture(autouse=True)
def _legacy_conversion_contract(monkeypatch):
    """Legacy conversion tests still exercise the engine behind the #5710 gate."""
    from app import document_convert_routes
    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)



class StubHistory:
    """The signed-in session resolver only asks whether a user row exists."""

    def __init__(self, user_ids=SEEDED):
        self.users = {user_id: SimpleNamespace(id=user_id) for user_id in user_ids}

    async def get_user(self, user_id):
        return self.users.get(user_id)


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="phase5568.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
        web_provider="off",
    )


class _Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return _Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def all(self):
        rows = self.db.conn.execute(self.sql, self.params).fetchall()
        return {"results": [dict(row) for row in rows]}

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return {"meta": {"changes": cursor.rowcount}}


class FakeD1:
    """D1-shaped facade over SQLite running the shipped 066 migration."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        self.conn.executemany(
            "INSERT INTO users (id, email) VALUES (?, ?)",
            [(user_id, f"{user_id}@example.test") for user_id in SEEDED],
        )
        self.conn.executescript(MIGRATION.read_text(encoding="utf8"))

    def prepare(self, sql):
        return _Statement(self, sql)


class _Object:
    def __init__(self, payload: bytes):
        self.body = payload


class MemoryR2:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, key, body, **kwargs):
        self.objects[key] = bytes(body)

    async def get(self, key):
        payload = self.objects.get(key)
        return None if payload is None else _Object(payload)

    async def delete(self, key):
        self.objects.pop(key, None)


def pdf_bytes(*, texts: list[str]) -> bytes:
    """A real PDF, one page per entry; an empty entry has no text operator."""

    count = len(texts)
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Kids ["
            + " ".join(f"{3 + index * 2} 0 R" for index in range(count)).encode()
            + f"] /Count {count} >>".encode()
        ),
    }
    for index, text in enumerate(texts):
        page_number = 3 + index * 2
        content_number = page_number + 1
        objects[page_number] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_number} 0 R "
            "/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>"
        ).encode("ascii")
        stream = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode("latin-1") if text else b""
        objects[content_number] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    highest = max(objects)
    for number in range(1, highest + 1):
        offsets[number] = out.tell()
        out.write(f"{number} 0 obj\n".encode("ascii"))
        out.write(objects[number])
        out.write(b"\nendobj\n")
    xref_at = out.tell()
    size = highest + 1
    out.write(f"xref\n0 {size}\n0000000000 65535 f \n".encode("ascii"))
    for number in range(1, size):
        out.write(f"{offsets[number]:010d} 00000 n \n".encode("ascii"))
    out.write(b"trailer\n<< /Size " + str(size).encode() + b" /Root 1 0 R >>\n")
    out.write(b"startxref\n" + str(xref_at).encode() + b"\n%%EOF\n")
    return out.getvalue()


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with __import__("zipfile").ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


async def build_client(*, d1=None, r2=None, user_id=OWNER):
    cfg = settings()
    app = create_app(cfg, history_store=StubHistory(), d1_binding=d1 if d1 is not None else FakeD1())
    app.state.workspace_document_store = SimpleNamespace(
        r2_bucket=r2 if r2 is not None else MemoryR2()
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE, follow_redirects=True,
        headers={"Origin": BASE},
    )
    profile = SimpleNamespace(id=user_id, email=f"{user_id}@example.test")
    client.cookies.set(
        SESSION_COOKIE, create_session_token(cfg, profile.id), domain="chat.example.test", path="/"
    )
    return client, app


async def open_job(client, mode="fast"):
    response = await client.post("/api/document-conversions", json={"mode": mode})
    assert response.status_code == 201, response.text
    return response.json()["job"]["id"]


async def upload(client, job_id, payload, *, name, media_type=PDF_MEDIA):
    return await client.post(
        f"/api/document-conversions/{job_id}/files",
        content=payload,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Padiem-Filename": quote(name, safe=""),
            "X-Padiem-Media-Type": media_type,
        },
    )

@pytest.mark.asyncio
async def test_upload_convert_review_download_journey():
    r2 = MemoryR2()
    client, _app = await build_client(r2=r2)
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Document 1 page 1"]), name="보고서.pdf")
        assert created.status_code == 201, created.text
        item = created.json()["items"][0]
        assert item["status"] == "queued"
        # The hot upload path is pypdf-free: page count and the native-text
        # probe are deferred to the conversion step, not computed at upload.
        assert item["page_count"] == 0
        assert item["report"] is None

        run = await client.post(f"/api/document-conversions/items/{item['id']}/run")
        assert run.status_code == 200, run.text
        ran = run.json()["item"]
        assert ran["status"] == "reviewed"
        assert ran["has_markdown"] is True
        # The conversion is the pypdf site: it back-fills the page count.
        assert ran["page_count"] == 1

        downloaded = await client.get(f"/api/document-conversions/items/{item['id']}/markdown")
        assert downloaded.status_code == 200
        assert "Content-Disposition" in downloaded.headers
        assert "Document 1 page 1" in downloaded.text
        assert "<!-- padiem:page 1 -->" in downloaded.text

        accepted = await client.post(f"/api/document-conversions/items/{item['id']}/review")
        assert accepted.status_code == 200
        assert accepted.json()["job"]["status"] == "done"

        keys = sorted(r2.objects)
        assert all(key.startswith(f"documents/{OWNER}/convert/{job_id}/") for key in keys)
        assert sum(1 for key in keys if key.endswith(".md")) == 1
        assert sum(1 for key in keys if key.endswith(".pdf")) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_original_pdf_is_preserved_and_streamed_back():
    client, app = await build_client()
    r2 = app.state.workspace_document_store.r2_bucket
    try:
        job_id = await open_job(client)
        payload = pdf_bytes(texts=["Document 2 page 1"])
        created = await upload(client, job_id, payload, name="원본.pdf")
        item_id = created.json()["items"][0]["id"]
        original = await client.get(f"/api/document-conversions/items/{item_id}/original")
        assert original.status_code == 200
        assert original.content == payload
        assert original.headers["content-type"] == PDF_MEDIA
        assert len(r2.objects) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_multi_pdf_zip_uploads_one_item_per_pdf_member():
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        archive = zip_bytes({
            "first.pdf": pdf_bytes(texts=["Document 3 page 1"]),
            "nested/second.pdf": pdf_bytes(texts=["Document 4 page 1", "Document 4 page 2"]),
            "notes.txt": b"not a pdf",
        })
        created = await upload(client, job_id, archive, name="자료.zip", media_type=ZIP_MEDIA)
        assert created.status_code == 201, created.text
        items = created.json()["items"]
        assert {item["name"] for item in items} == {"first.pdf", "second.pdf"}
        # Deferred inspection: uploads carry no pypdf page count.
        assert {item["name"]: item["page_count"] for item in items} == {"first.pdf": 0, "second.pdf": 0}
        assert created.json()["rejected"] == [{"name": "notes.txt", "code": "pdf_magic_mismatch"}]

        for item in items:
            run = await client.post(f"/api/document-conversions/items/{item['id']}/run")
            assert run.status_code == 200, run.text
            # The conversion back-fills the real page count.
        pages = {
            item["name"]: (await client.get(f"/api/document-conversions/items/{item['id']}")).json()["item"]["page_count"]
            for item in items
        }
        assert pages == {"first.pdf": 1, "second.pdf": 2}
        bundle = await client.get(f"/api/document-conversions/{job_id}/archive")
        assert bundle.status_code == 200
        with __import__("zipfile").ZipFile(io.BytesIO(bundle.content)) as built:
            names = set(built.namelist())
            assert {"first.md", "second.md", "manifest.json"} <= names
            manifest = json.loads(built.read("manifest.json"))
            assert manifest["converted"] == 2
            assert manifest["failed"] == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_scan_only_pdf_is_marked_unreadable_not_guessed():
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=[""]), name="스캔.pdf")
        assert created.status_code == 201, created.text
        item = created.json()["items"][0]
        # Deferred inspection: the scan-only state is no longer probed at
        # upload; it surfaces through the conversion report instead.
        assert item["report"] is None

        run = await client.post(f"/api/document-conversions/items/{item['id']}/run")
        assert run.status_code == 200, run.text
        assert run.json()["item"]["status"] == "reviewed"
        assert run.json()["item"]["report"]["warnings"] == ["unreadable_page:1"]

        markdown = await client.get(f"/api/document-conversions/items/{item['id']}/markdown")
        assert "추출 가능한 텍스트 레이어가 없습니다" in markdown.text
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_corrupt_member_fails_only_that_item_and_keeps_the_others():
    client, app = await build_client()
    r2 = app.state.workspace_document_store.r2_bucket
    try:
        job_id = await open_job(client)
        good = pdf_bytes(texts=["Document 6 page 1"])
        archive = zip_bytes({"good.pdf": good, "bad.pdf": b"%PDF-1.4\nnot a readable body\n%%EOF\n"})
        created = await upload(client, job_id, archive, name="mix.zip", media_type=ZIP_MEDIA)
        assert created.status_code == 201
        items = {item["name"]: item["id"] for item in created.json()["items"]}
        assert set(items) == {"good.pdf", "bad.pdf"}

        good_run = await client.post(f"/api/document-conversions/items/{items['good.pdf']}/run")
        assert good_run.status_code == 200
        bad_run = await client.post(f"/api/document-conversions/items/{items['bad.pdf']}/run")
        assert bad_run.status_code == 422
        assert bad_run.json()["item"]["status"] == "failed"
        assert bad_run.json()["item"]["error_code"]

        detail = await client.get(f"/api/document-conversions/{job_id}")
        by_name = {item["name"]: item for item in detail.json()["items"]}
        assert by_name["good.pdf"]["has_markdown"] is True
        assert by_name["bad.pdf"]["has_markdown"] is False

        still_readable = await client.get(
            f"/api/document-conversions/items/{items['good.pdf']}/markdown"
        )
        assert still_readable.status_code == 200
        assert "Document" in still_readable.text
        assert sum(1 for key in r2.objects if key.endswith(".md")) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_verify_mode_reports_per_page_agreement_not_accuracy():
    client, _app = await build_client()
    try:
        job_id = await open_job(client, mode="verify")
        created = await upload(client, job_id, pdf_bytes(texts=["Document 7 page 1"]), name="검증.pdf")
        item_id = created.json()["items"][0]["id"]
        run = await client.post(f"/api/document-conversions/items/{item_id}/run")
        assert run.status_code == 200, run.text
        report = run.json()["item"]["report"]
        assert len(report["pages"]) == 1
        assert report["agreement"][0]["character_coverage"] == 1.0
        assert report["agreement"][0]["digit_preservation"] == 1.0
        assert "accuracy" not in json.dumps(report)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_precise_mode_is_refused_with_the_engines_own_code():
    client, _app = await build_client()
    try:
        response = await client.post("/api/document-conversions", json={"mode": "precise"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "pdf_precise_mode_unavailable"
        assert "OCR" in response.json()["error"]["message"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_another_owner_cannot_reach_the_job_or_its_bytes():
    shared_r2 = MemoryR2()
    owner_client, _app = await build_client(r2=shared_r2, user_id=OWNER)
    intruder, _ = await build_client(r2=shared_r2, user_id=INTRUDER)
    try:
        job_id = await open_job(owner_client)
        created = await upload(owner_client, job_id, pdf_bytes(texts=["Document 8 page 1"]), name="비공개.pdf")
        item_id = created.json()["items"][0]["id"]
        await owner_client.post(f"/api/document-conversions/items/{item_id}/run")

        for method, url in (
            ("get", f"/api/document-conversions/{job_id}"),
            ("get", f"/api/document-conversions/items/{item_id}"),
            ("get", f"/api/document-conversions/items/{item_id}/markdown"),
            ("get", f"/api/document-conversions/items/{item_id}/original"),
            ("post", f"/api/document-conversions/items/{item_id}/run"),
            ("post", f"/api/document-conversions/items/{item_id}/review"),
            ("delete", f"/api/document-conversions/items/{item_id}"),
            ("get", f"/api/document-conversions/{job_id}/archive"),
            ("post", f"/api/document-conversions/{job_id}/files"),
        ):
            if url.endswith("/files"):
                response = await intruder.request(
                    method.upper(), url, content=b"x",
                    headers={"Content-Type": "application/octet-stream", "X-Padiem-Filename": "x.pdf"},
                )
            else:
                response = await intruder.request(method.upper(), url)
            assert response.status_code == 404, (method, url, response.status_code, response.text)

        listed = await intruder.get("/api/document-conversions")
        assert listed.status_code == 200
        assert listed.json()["jobs"] == []

        body = json.dumps((await owner_client.get(f"/api/document-conversions/{job_id}")).json())
        assert "documents/" not in body
        assert "original_key" not in body and "markdown_key" not in body
    finally:
        await owner_client.aclose()
        await intruder.aclose()


@pytest.mark.asyncio
async def test_unsigned_in_and_anonymous_requests_are_refused():
    cfg = settings()
    app = create_app(cfg, history_store=StubHistory(), d1_binding=FakeD1())
    app.state.workspace_document_store = SimpleNamespace(r2_bucket=MemoryR2())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
    try:
        response = await client.post("/api/document-conversions", json={"mode": "fast"})
        assert response.status_code == 401
        listed = await client.get("/api/document-conversions")
        assert listed.status_code == 401
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_work_ledger_survives_navigating_away():
    client, _app = await build_client()
    try:
        first = await open_job(client)
        created = await upload(client, first, pdf_bytes(texts=["Document 9 page 1"]), name="이전.pdf")
        item_id = created.json()["items"][0]["id"]
        await client.post(f"/api/document-conversions/items/{item_id}/run")

        listed = await client.get("/api/document-conversions")
        assert listed.status_code == 200
        jobs = listed.json()["jobs"]
        assert [job["id"] for job in jobs] == [first]
        assert jobs[0]["status"] == "reviewed"
        assert jobs[0]["item_count"] == 1

        reopened = await client.get(f"/api/document-conversions/{first}")
        assert reopened.json()["items"][0]["has_markdown"] is True
        again = await client.post(f"/api/document-conversions/items/{item_id}/run")
        assert again.status_code == 200
        assert again.json()["item"]["status"] == "reviewed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unbounded_request_is_rejected_before_the_body_is_materialized():
    from app import document_convert_routes

    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(document_convert_routes, "MAX_BINARY_DOCUMENT_BYTES", 512)
            response = await upload(client, job_id, b"%PDF-" + b"z" * 600, name="큰파일.pdf")
        assert response.status_code in (413, 422)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_migration_shape_bounds_the_ledger_itself():
    d1 = FakeD1()
    columns = {
        row["name"]: row for row in d1.conn.execute("PRAGMA table_info(document_convert_items)").fetchall()
    }
    assert set(columns) >= {"id", "job_id", "user_id", "name", "status", "original_key", "markdown_key"}
    sql = " ".join(
        str(row["sql"])
        for row in d1.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'document_convert_items'"
        ).fetchall()
    )
    assert "CHECK (status <> 'done' OR markdown_key IS NOT NULL)" in sql
    with pytest.raises(sqlite3.IntegrityError):
        d1.conn.execute(
            "INSERT INTO document_convert_items (id, job_id, user_id, name, status, original_key) "
            "VALUES ('dci_' || substr(hex(randomblob(16)),1,32), NULL, 'usr_x', 'a.pdf', 'done', 'k')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        d1.conn.execute(
            "INSERT INTO document_convert_items (id, job_id, user_id, name, status, original_key) "
            "VALUES ('dci_' || substr(hex(randomblob(16)),1,32), NULL, 'usr_x', 'a.pdf', 'invented', 'k')"
        )


@pytest.mark.asyncio
async def test_report_is_stored_bounded_and_never_carries_document_text():
    d1 = FakeD1()
    from app.document_convert_store import D1DocumentConvertStore

    store = D1DocumentConvertStore(d1)
    job = await store.create_job("usr_" + "d" * 32, mode="verify")
    item = await store.add_item("usr_" + "d" * 32, job.id, name="a.pdf", page_count=1)
    report = {"pages": [{"note": "x" * 20_000}], "mismatches": []}
    done = await store.complete_item(
        "usr_" + "d" * 32, item.id, status="reviewed", page_count=1,
        character_count=10, markdown_key="k.md", report=report, error_code=None,
    )
    raw = d1.conn.execute(
        "SELECT report_json FROM document_convert_items WHERE id = ?", (item.id,)
    ).fetchone()[0]
    assert len(raw) <= 12_000
    assert done.status == "reviewed"


@pytest.mark.asyncio
async def test_upload_is_pypdf_free_and_conversion_still_parses():
    """#5568 production 503 fix, as a load-bearing regression.

    The hot upload path must not construct a pypdf reader (that is what pushed
    the Worker past its resource budget). The conversion step remains the single
    pypdf site and must still parse.
    """
    import pypdf

    real_reader = pypdf.PdfReader
    uploads: list[int] = []
    conversions: list[int] = []

    class _Forbid:
        def __init__(self, *args, **kwargs):
            uploads.append(1)
            raise AssertionError("pypdf must not run on the upload hot path")

    class _Recording:
        def __init__(self, *args, **kwargs):
            conversions.append(1)
            self._real = real_reader(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(pypdf, "PdfReader", _Forbid)
            created = await upload(
                client, job_id, pdf_bytes(texts=["Deferred 1 page 1"]), name="defer.pdf"
            )
        assert created.status_code == 201, created.text
        assert uploads == [], "pypdf ran on the upload path"
        item = created.json()["items"][0]
        assert item["page_count"] == 0
        assert item["report"] is None

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(pypdf, "PdfReader", _Recording)
            run = await client.post(f"/api/document-conversions/items/{item['id']}/run")
        assert run.status_code == 200, run.text
        assert conversions, "conversion must still run pypdf"
        ran = run.json()["item"]
        assert ran["page_count"] == 1
        assert ran["has_markdown"] is True
        markdown = await client.get(f"/api/document-conversions/items/{item['id']}/markdown")
        assert "Deferred 1 page 1" in markdown.text
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_5710_paused_migration_blocks_new_writes_but_preserves_existing_files(monkeypatch):
    """No new D1 job or R2 writes; existing owner-scoped reads and downloads survive."""
    from app import document_convert_routes

    r2 = MemoryR2()
    client, _app = await build_client(r2=r2)
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Existing PDF"]), name="existing.pdf")
        assert created.status_code == 201
        item_id = created.json()["items"][0]["id"]
        finished = await client.post(f"/api/document-conversions/items/{item_id}/run")
        assert finished.status_code == 200
        baseline_keys = set(r2.objects)

        monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", True)
        blocked = (
            await client.post("/api/document-conversions", json={"mode": "fast"}),
            await upload(client, job_id, pdf_bytes(texts=["Attack"]), name="new.pdf"),
            await client.post(f"/api/document-conversions/items/{item_id}/run"),
        )
        assert all(resp.status_code == 503 for resp in blocked)
        assert all(resp.json()["error"]["code"] == "pdfmd_migration_paused" for resp in blocked)
        assert set(r2.objects) == baseline_keys
        assert (await client.get("/api/document-conversions")).status_code == 200
        assert (await client.get(f"/api/document-conversions/{job_id}")).status_code == 200
        assert (await client.get(f"/api/document-conversions/items/{item_id}/original")).status_code == 200
        assert (await client.get(f"/api/document-conversions/items/{item_id}/markdown")).status_code == 200
        assert (await client.get(f"/api/document-conversions/{job_id}/archive")).status_code == 200
    finally:
        await client.aclose()
