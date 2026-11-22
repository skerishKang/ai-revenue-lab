"""#8061 14차: shared setup for the document-conversion route tests."""
from __future__ import annotations

import asyncio
import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app

MIGRATION = Path(__file__).parents[2] / "migrations" / "066_document_convert_jobs.sql"
# 116 adds the scan page rows the item delete now clears in the same call.
SCAN_PAGES_MIGRATION = (
    Path(__file__).parents[2] / "migrations" / "116_document_convert_scan_pages.sql"
)
SESSION_SECRET = "phase5568-convert-session-secret-not-a-real-key-000000"
BASE = "https://chat.example.test"
PDF_MEDIA = "application/pdf"
ZIP_MEDIA = "application/zip"
OWNER = "usr_" + "a" * 32
INTRUDER = "usr_" + "c" * 32
STRANGER = "usr_" + "d" * 32
SEEDED = (OWNER, INTRUDER, STRANGER, "usr_x")


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
        # The operating 컴2 host answers .all() with a bare list of rows. A fake that
        # answers only the Cloudflare `{results: […]}` shape lets a shape-specific
        # reader pass here and return zero rows in Production (#5568 follow-on).
        rows = self.db.conn.execute(self.sql, self.params).fetchall()
        return [dict(row) for row in rows]

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
        self.conn.executescript(SCAN_PAGES_MIGRATION.read_text(encoding="utf8"))

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
        SESSION_COOKIE, create_session_token(cfg, profile.id, canonical_session_id="session_test_a"), domain="chat.example.test", path="/"
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


async def run_item(client, item_id):
    """Start one conversion; the route answers 202 with the working item."""
    return await client.post(f"/api/document-conversions/items/{item_id}/run")


async def wait_item_terminal(client, item_id, timeout=10.0):
    """Follow one item's detail until its background conversion settles."""

    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        response = await client.get(f"/api/document-conversions/items/{item_id}")
        assert response.status_code == 200, response.text
        item = response.json()["item"]
        if item["status"] in ("reviewed", "done", "failed"):
            return item
        assert asyncio.get_event_loop().time() < deadline, "conversion did not settle"
        await asyncio.sleep(0.05)

