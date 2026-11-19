"""#7865 PDF→MD 작업 이력 목록에도 #7842 시간 초과 판정이 적용되는지 확인한다.

11-15에 끝내지 못한 작업이 작업 이력 목록에 '준비중'(queued)으로 남는다는
보고(#7865). #7842(#7834)의 판정 규칙은 ``document_convert_store`` 의
``abandoned_row → _presented_status`` 하나뿐이고, 새 판정 규칙을 만들지 않고
그 규칙 하나를 목록 경로(GET /api/document-conversions)에서도 그대로 쓰는지를
HTTP 경계에서 확인한다. 1시간이 지난 미완료 작업은 목록에서 실패
(status=failed, error_code=convert_timed_out)로 보여야 하고, 1시간이 안 된
작업은 저장된 상태(queued) 그대로여야 한다.
"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app

MIGRATION = Path(__file__).parents[1] / "migrations" / "066_document_convert_jobs.sql"
SCAN_PAGES_MIGRATION = (
    Path(__file__).parents[1] / "migrations" / "116_document_convert_scan_pages.sql"
)
SESSION_SECRET = "phase7865-history-timeout-secret-not-a-real-key-000000"
BASE = "https://chat.example.test"
OWNER = "usr_" + "a" * 32


@pytest.fixture(autouse=True)
def _legacy_conversion_contract(monkeypatch):
    """작업 생성 경로는 이행 일시정지 게이트를 통과한다(#5710). 이 시험의 대상은
    목록 경로의 시간 초과 판정이므로, 5568 계열 시험과 같은 방식으로 게이트를
    내려놓고 작업을 만든다."""

    from app import document_convert_routes
    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)


class StubHistory:
    async def get_user(self, user_id):
        return SimpleNamespace(id=user_id)


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="phase7865.apps.googleusercontent.com",
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
        self.conn.execute("INSERT INTO users (id, email) VALUES (?, ?)", (OWNER, OWNER + "@example.test"))
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
    offsets: dict[int, bytes] = {}
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


async def build_client(*, d1=None, user_id=OWNER):
    cfg = settings()
    app = create_app(cfg, history_store=StubHistory(), d1_binding=d1 if d1 is not None else FakeD1())
    app.state.workspace_document_store = SimpleNamespace(r2_bucket=MemoryR2())
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE, follow_redirects=True,
        headers={"Origin": BASE},
    )
    profile = SimpleNamespace(id=user_id, email=f"{user_id}@example.test")
    client.cookies.set(
        SESSION_COOKIE, create_session_token(cfg, profile.id, canonical_session_id="session_test_a"), domain="chat.example.test", path="/"
    )
    return client, app.state.d1_binding if hasattr(app.state, "d1_binding") else d1


async def make_started_job(client, d1) -> str:
    """One job with one uploaded (never-run) file, so the list keeps the row."""

    created = await client.post("/api/document-conversions", json={"mode": "fast"})
    assert created.status_code == 201, created.text
    job_id = created.json()["job"]["id"]
    uploaded = await client.post(
        f"/api/document-conversions/{job_id}/files",
        content=pdf_bytes(texts=[""]),
        headers={
            "Content-Type": "application/octet-stream",
            "X-Padiem-Filename": quote("11-15-끝내지-못한-문서.pdf", safe=""),
            "X-Padiem-Media-Type": "application/pdf",
        },
    )
    assert uploaded.status_code in (200, 201), uploaded.text
    return job_id


def _age_job(d1, job_id: str, *, seconds: int) -> None:
    stale = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    d1.conn.execute(
        "UPDATE document_convert_jobs SET updated_at = ? WHERE id = ?", (stale, job_id)
    )


async def _job_in_list(client, job_id: str) -> dict:
    listed = await client.get("/api/document-conversions?limit=50")
    assert listed.status_code == 200, listed.text
    jobs = listed.json()["jobs"]
    found = [job for job in jobs if job["id"] == job_id]
    assert found, "작성한 작업이 이력 목록에 없으면 이 경로 자체가 실패다"
    return found[0]


@pytest.mark.asyncio
async def test_list_shows_a_one_hour_old_unfinished_job_as_timed_out():
    """#7865: 1시간 지난 미완료 작업은 목록에서 시간 초과 판정(실패+이유)으로 나온다."""

    d1 = FakeD1()
    client, _ = await build_client(d1=d1)
    job_id = await make_started_job(client, d1)
    _age_job(d1, job_id, seconds=2 * 3600)

    job = await _job_in_list(client, job_id)
    assert job["status"] == "failed", json.dumps(job, ensure_ascii=False)
    assert job["error_code"] == "convert_timed_out", json.dumps(job, ensure_ascii=False)
    await client.aclose()


@pytest.mark.asyncio
async def test_list_keeps_a_recent_unfinished_job_queued():
    """1시간이 안 된 미완료 작업은 판정 없이 저장된 상태(준비중) 그대로다."""

    d1 = FakeD1()
    client, _ = await build_client(d1=d1)
    job_id = await make_started_job(client, d1)
    _age_job(d1, job_id, seconds=10 * 60)

    job = await _job_in_list(client, job_id)
    assert job["status"] == "queued", json.dumps(job, ensure_ascii=False)
    assert job["error_code"] is None, json.dumps(job, ensure_ascii=False)
    await client.aclose()
