"""#7500: the Util Excel open & review route over the shared XLSX authority.

The route must reuse the repository's one XLSX reading authority
(``read_xlsx_table``) and the other Util gates (signed-in session, verified
grade for the size cap, the conversion usage bucket when enforced), refusing
encrypted and malformed workbooks with the shipped Korean guidance copy. These
tests pin that contract at the HTTP boundary: a normal workbook, an empty
sheet, the large-file boundary (grade cap + row bound), a password-protected
file, a malformed format and a signed-out request.
"""
from __future__ import annotations

import asyncio
import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.usage_gate import InMemoryUsageCounterStore

MIGRATION = Path(__file__).parents[1] / "migrations" / "066_document_convert_jobs.sql"
SESSION_SECRET = "util-excel-session-secret-not-a-real-key-0000000000"
QUOTA_SALT = "util-excel-quota-salt-not-a-real-secret-0000000000"
BASE = "https://chat.example.test"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OWNER = "usr_" + "b" * 32
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

SMALL_BYTES = {"free": 2048, "plus": 8192, "pro": 8192, "max": 8192, "admin": 8192}
DEFAULT_BYTES = {grade: 8 * 1024 * 1024 for grade in ("free", "plus", "pro", "max", "admin")}


def _settings(**overrides) -> Settings:
    overrides.setdefault("conversion_max_bytes", DEFAULT_BYTES)
    overrides.setdefault("conversion_daily_limits",
                         {"free": 5, "plus": 5, "pro": 5, "max": 5, "admin": 5})
    return Settings.from_values(
        runtime_mode="b14",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="util-excel.apps.googleusercontent.com",
        google_client_secret="unit-secret",
        session_secret=SESSION_SECRET,
        b14_base_url="https://b14.example.test",
        quota_salt=QUOTA_SALT,
        **overrides,
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
        return [dict(row) for row in self.db.conn.execute(self.sql, self.params).fetchall()]

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return {"meta": {"changes": cursor.rowcount}}


class SqliteD1:
    """D1-shaped facade over SQLite running the shipped 066 migration."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        self.conn.executemany(
            "INSERT INTO users (id, email) VALUES (?, ?)",
            [(OWNER, f"{OWNER}@example.test")],
        )
        self.conn.executescript(MIGRATION.read_text(encoding="utf8"))

    def prepare(self, sql):
        return _Statement(self, sql)


class _History:
    def __init__(self, user_ids=(OWNER,)):
        self.users = {user_id: SimpleNamespace(id=user_id) for user_id in user_ids}

    async def get_user(self, user_id):
        return self.users.get(user_id)


class _MemberStore:
    """The member-admin authority surface member_grade_access consumes."""

    def __init__(self, tiers=None, admins=(), fail=False):
        self.tiers = dict(tiers or {})
        self.admins = set(admins)
        self.fail = fail

    async def is_google_admin(self, user_id):
        if self.fail:
            raise RuntimeError("membership unavailable")
        return user_id in self.admins


# runtime_access keeps `verified_member_grade` on its reviewed path when the
# mock runtime would otherwise certify every user as the top grade.
async def _runtime_access(self, user_id):
    if self.fail:
        raise RuntimeError("membership unavailable")
    tier = self.tiers.get(user_id)
    if tier is None:
        return None
    return {"status": "approved", "tier": tier}


_MemberStore.runtime_access = _runtime_access


async def build_client(*, settings=None, signed_in=True, store=None, member_store=None):
    cfg = settings or _settings()
    app = create_app(
        cfg,
        history_store=_History(),
        d1_binding=SqliteD1(),
        usage_store=store or InMemoryUsageCounterStore(),
    )
    app.state.b66_member_admin_store = member_store or _MemberStore()
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE,
        follow_redirects=True, headers={"Origin": BASE},
    )
    if signed_in:
        profile = SimpleNamespace(id=OWNER, email=f"{OWNER}@example.test")
        client.cookies.set(
            SESSION_COOKIE, create_session_token(cfg, profile.id),
            domain="chat.example.test", path="/",
        )
    return client, app


def xlsx_bytes(sheets: list[tuple[str, list[list]]]) -> bytes:
    """One real workbook; ``None`` rows mark a sheet left fully empty."""
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets:
        sheet = workbook.create_sheet(title=title)
        for row in rows or []:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def _review(client, payload: bytes, *, name="book.xlsx",
                  media=XLSX_MEDIA, goal=None):
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Padiem-Filename": quote(name),
    }
    if media is not None:
        headers["X-Padiem-Media-Type"] = media
    url = "/api/util/excel/review"
    if goal:
        url += "?goal=" + quote(goal)
    return await client.post(url, content=payload, headers=headers)


def test_signed_out_request_is_refused() -> None:
    async def case():
        client, _ = await build_client(signed_in=False)
        try:
            response = await _review(client, b"PK\x03\x04stub")
            assert response.status_code == 401, response.text
            body = response.json()
            assert body["error"]["code"] == "unauthorized"
            assert body["error"]["message"] == "로그인이 필요합니다."
        finally:
            await client.aclose()

    asyncio.run(case())


def test_normal_workbook_returns_sheets_preview_and_summary() -> None:
    payload = xlsx_bytes([
        ("데이터", [
            ["품목", "수량", "단가", "합계"],
            ["A품", 3, 1000, 3000],
            ["B품", 2, 2500, 5000],
            ["C품", 1, 700, 700],
        ]),
        ("요약", [["구분", "값"], ["합계", 8700], ["품목수", 3]]),
    ])

    async def case():
        client, _ = await build_client()
        try:
            response = await _review(client, payload, goal="합계와 단가 확인")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["ok"] is True
            review = body["review"]
            assert review["file_name"] == "book.xlsx"
            assert len(review["sheets"]) == 2
            assert review["sheets"][0] == {"index": 0, "title": "데이터", "rows": 3,
                                           "columns": 4, "truncated": False, "empty": False}
            assert review["sheets"][1]["title"] == "요약"
            assert review["sheets"][1]["rows"] == 2
            assert review["preview"]["sheet_title"] == "데이터"
            assert review["preview"]["headers"] == ["품목", "수량", "단가", "합계"]
            assert len(review["preview"]["rows"]) == 3
            assert review["preview"]["rows"][0] == ["A품", "3", "1000", "3000"]
            assert review["summary"]["sheet_count"] == 2
            assert review["summary"]["readable_sheet_count"] == 2
            assert review["summary"]["empty_sheet_indices"] == []
            assert review["summary"]["total_data_rows"] == 5
            assert review["summary"]["review_note"] == "합계와 단가 확인"
        finally:
            await client.aclose()

    asyncio.run(case())


def test_empty_sheet_is_listed_and_neighbour_sheets_still_review() -> None:
    payload = xlsx_bytes([("빈시트", None), ("자료", [["키", "값"], ["a", 1]])])

    async def case():
        client, _ = await build_client()
        try:
            response = await _review(client, payload)
            assert response.status_code == 200, response.text
            review = response.json()["review"]
            assert review["sheets"][0]["empty"] is True
            assert review["sheets"][0]["rows"] == 0
            assert review["sheets"][1]["title"] == "자료"
            assert review["preview"]["sheet_title"] == "자료"
            assert review["summary"]["empty_sheet_indices"] == [0]
            assert review["summary"]["readable_sheet_count"] == 1
        finally:
            await client.aclose()

    asyncio.run(case())


def test_workbook_with_only_empty_sheets_refuses_with_existing_copy() -> None:
    payload = xlsx_bytes([("빈시트", None)])

    async def case():
        client, _ = await build_client()
        try:
            response = await _review(client, payload)
            assert response.status_code == 422, response.text
            body = response.json()
            assert body["error"]["message"] == "XLSX에서 읽을 값을 찾지 못했습니다."
        finally:
            await client.aclose()

    asyncio.run(case())


def test_file_past_the_grade_cap_refuses_with_the_grade_sentence() -> None:
    # A workbook over the free grade's 2048-byte cap: plenty of padding rows.
    rows = [["품목", "설명", "비고"]]
    rows += [[f"항목-{i}", "설명을 위한 여백 텍스트입니다" * 4, i] for i in range(80)]
    payload = xlsx_bytes([("큰시트", rows)])

    async def case():
        client, _ = await build_client(settings=_settings(conversion_max_bytes=SMALL_BYTES))
        try:
            assert len(payload) > 2048
            response = await _review(client, payload)
            assert response.status_code == 413, response.text
            body = response.json()
            assert body["error"]["code"] == "document_size_limit"
            assert "변환 크기 상한(0MB)" in body["error"]["message"] or \
                "변환 크기 상한" in body["error"]["message"]
        finally:
            await client.aclose()

    asyncio.run(case())


def test_rows_past_the_bound_are_marked_truncated() -> None:
    rows = [["번호", "메모"]] + [[i, f"메모-{i}"] for i in range(1, 506)]
    payload = xlsx_bytes([("많은행", rows)])

    async def case():
        client, _ = await build_client()
        try:
            response = await _review(client, payload)
            assert response.status_code == 200, response.text
            review = response.json()["review"]
            sheet = review["sheets"][0]
            assert sheet["rows"] == 500
            assert sheet["truncated"] is True
            assert len(review["preview"]["rows"]) == 8
            assert review["summary"]["truncated_sheet_titles"] == ["많은행"]
        finally:
            await client.aclose()

    asyncio.run(case())


def test_password_protected_file_refuses_with_the_existing_copy() -> None:
    # An encrypted workbook is the OLE wrapper around an EncryptedPackage; the
    # archive gate refuses it before any parse. The marker rides as UTF-16-LE,
    # exactly as the Office writer lays it down.
    payload = (_OLE_MAGIC + b"\x00" * 16
               + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 16)

    async def case():
        client, _ = await build_client()
        try:
            response = await _review(client, payload)
            assert response.status_code == 422, response.text
            body = response.json()
            assert body["error"]["code"] == "ooxml_encrypted"
            assert body["error"]["message"] == \
                "암호화된 문서라 열 수 없습니다. 암호를 풀고 다시 올려 주세요."
        finally:
            await client.aclose()

    asyncio.run(case())


def test_malformed_format_refuses_with_the_existing_copy() -> None:
    async def case():
        client, _ = await build_client()
        try:
            response = await _review(client, b"this is not a spreadsheet")
            assert response.status_code == 422, response.text
            body = response.json()
            assert body["error"]["message"] in (
                "XLSX 압축 구조를 안전하게 읽지 못했습니다.",
                "XLSX 파일을 안전하게 읽지 못했습니다.",
            )
        finally:
            await client.aclose()

    asyncio.run(case())


def test_non_xlsx_media_header_refuses() -> None:
    payload = xlsx_bytes([("자료", [["a"], [1]])])

    async def case():
        client, _ = await build_client()
        try:
            response = await _review(client, payload, media="application/pdf")
            assert response.status_code == 422, response.text
            assert response.json()["error"]["message"] == "XLSX 파일만 업로드할 수 있습니다."
        finally:
            await client.aclose()

    asyncio.run(case())


def test_exhausted_daily_usage_refuses_before_reading() -> None:
    settings = _settings(
        conversion_daily_limits={"free": 1, "plus": 1, "pro": 1, "max": 1, "admin": 1},
    )
    payload = xlsx_bytes([("자료", [["a"], [1]])])

    async def case():
        client, _ = await build_client(settings=settings)
        try:
            first = await _review(client, payload)
            assert first.status_code == 200, first.text
            second = await _review(client, payload)
            assert second.status_code == 429, second.text
            body = second.json()
            assert body["error"]["code"]
            assert body["error"]["message"]
        finally:
            await client.aclose()

    asyncio.run(case())
