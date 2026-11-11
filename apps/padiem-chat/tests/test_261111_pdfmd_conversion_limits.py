"""PDF→Markdown conversion limits — CTO policy numbers over live settings.

The dial is product policy: Core's generic document-length refusals were retired
in #5734 stage 2, so these tests pin the per-tier, per-day conversion budgets,
the per-grade size/page ceilings and the chat-bucket separation at the HTTP
boundary (plus the default numbers, which stay tunable in config).
"""
from __future__ import annotations

import asyncio
import io
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.usage_gate import InMemoryUsageCounterStore

MIGRATION = Path(__file__).parents[1] / "migrations" / "066_document_convert_jobs.sql"
SESSION_SECRET = "phase-limits-session-secret-not-a-real-key-0000000000"
BASE = "https://chat.example.test"
PDF_MEDIA = "application/pdf"
ZIP_MEDIA = "application/zip"
OWNER = "usr_" + "a" * 32
QUOTA_SALT = "quota-salt-not-a-real-secret-0000000000000000"

#: Small dial values for fast route tests; the defaults are asserted verbatim
#: against the CTO numbers in the first test, so overriding here stays honest.
SMALL = {
    "daily": {"free": 2, "plus": 3, "pro": 4, "max": 5, "admin": 6},
    "bytes": {"free": 2048, "plus": 4096, "pro": 8192, "max": 16384, "admin": 32768},
    "pages": {"free": 1, "plus": 2, "pro": 2, "max": 2, "admin": None},
}


def _settings(**overrides) -> Settings:
    return Settings.from_values(
        runtime_mode="b14",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="phase-limits.apps.googleusercontent.com",
        google_client_secret="unit-secret",
        session_secret=SESSION_SECRET,
        b14_base_url="https://b14.example.test",
        quota_salt=QUOTA_SALT,
        conversion_daily_limits=SMALL["daily"],
        conversion_max_bytes=SMALL["bytes"],
        conversion_max_pages=SMALL["pages"],
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
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


async def build_client(*, settings=None, store=None, member_store=None, r2=None):
    cfg = settings or _settings()
    app = create_app(
        cfg,
        history_store=_History(),
        d1_binding=SqliteD1(),
        usage_store=store or InMemoryUsageCounterStore(),
    )
    app.state.workspace_document_store = SimpleNamespace(r2_bucket=r2 or MemoryR2())
    if member_store is not None:
        app.state.b66_member_admin_store = member_store
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE,
        follow_redirects=True, headers={"Origin": BASE},
    )
    profile = SimpleNamespace(id=OWNER, email=f"{OWNER}@example.test")
    client.cookies.set(
        SESSION_COOKIE, create_session_token(cfg, profile.id),
        domain="chat.example.test", path="/",
    )
    return client, app


async def _open_job(client) -> str:
    response = await client.post("/api/document-conversions", json={"mode": "fast"})
    assert response.status_code == 201, response.text
    return response.json()["job"]["id"]


async def _upload(client, job_id, payload, *, name, media_type=PDF_MEDIA):
    return await client.post(
        f"/api/document-conversions/{job_id}/files",
        content=payload,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Padiem-Filename": name,
            "X-Padiem-Media-Type": media_type,
        },
    )


async def _run_item(client, item_id):
    return await client.post(f"/api/document-conversions/items/{item_id}/run")


async def _terminal_item(client, item_id, timeout=20.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        response = await client.get(f"/api/document-conversions/items/{item_id}")
        assert response.status_code == 200, response.text
        item = response.json()["item"]
        if item["status"] in ("reviewed", "done", "failed"):
            return item
        assert asyncio.get_event_loop().time() < deadline, "conversion did not settle"
        await asyncio.sleep(0.05)


@pytest.fixture(autouse=True)
def _new_work_allowed(monkeypatch):
    from app import document_convert_routes

    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)


def test_default_dial_is_the_cto_setting():
    s = Settings.from_values(runtime_mode="mock")
    assert s.conversion_daily_limits == {"free": 10, "plus": 30, "pro": 100, "max": 300, "admin": 300}
    assert s.conversion_max_bytes == {
        "free": 50 * 1024 * 1024, "plus": 200 * 1024 * 1024,
        "pro": 200 * 1024 * 1024, "max": 200 * 1024 * 1024, "admin": 1024 * 1024 * 1024,
    }
    assert s.conversion_max_pages == {"free": 80, "plus": 300, "pro": 300, "max": 300, "admin": None}


@pytest.mark.parametrize("tier,cap", [("free", 2), ("plus", 3), ("pro", 4), ("max", 5), ("admin", 6)])
async def test_per_grade_daily_cap_and_429_contract(tier, cap):
    member = _MemberStore(tiers={OWNER: tier} if tier != "admin" else {},
                          admins=(OWNER,) if tier == "admin" else ())
    client, _app = await build_client(member_store=member)
    try:
        job_id = await _open_job(client)
        items = []
        for index in range(cap):
            response = await _upload(client, job_id, pdf_bytes(texts=[f"page {index}"]), name=f"{tier}.pdf")
            assert response.status_code == 201, response.text
            items.append(response.json()["items"][0]["id"])

        first = await _run_item(client, items[0])
        assert first.status_code == 202, first.text
        body = first.json()
        assert body["conversion"] == {"daily_limit": cap, "used": 1, "remaining": cap - 1}

        for item in items[1:]:
            response = await _run_item(client, item)
            assert response.status_code == 202, response.text
            assert response.json()["conversion"]["remaining"] >= 0

        extra = await _upload(client, job_id, pdf_bytes(texts=["extra"]), name="extra.pdf")
        assert extra.status_code == 201
        denied = await _run_item(client, extra.json()["items"][0]["id"])
        assert denied.status_code == 429, denied.text
        denied_body = denied.json()
        assert denied_body["error"]["code"] == "conversion_quota_exhausted"
        assert "내일 다시 이용해 주세요" in denied_body["error"]["message"]
        assert denied_body["conversion"] == {"daily_limit": cap, "remaining": 0}
        item = await _terminal_item(client, items[0])
        assert item["status"] == "reviewed"
    finally:
        await client.aclose()


async def test_conversion_bucket_does_not_consume_chat_budget():
    store = InMemoryUsageCounterStore()
    settings = _settings(user_daily_limit=1)
    client, app = await build_client(settings=settings, store=store)
    try:
        job_id = await _open_job(client)
        uploaded = await _upload(client, job_id, pdf_bytes(texts=["separated"]), name="sep.pdf")
        item = uploaded.json()["items"][0]
        assert (await _run_item(client, item["id"])).status_code == 202

        gate = app.state.usage_gate
        chat_first = await gate.authorize(user_id=OWNER, raw_ip=None)
        assert chat_first.allowed and chat_first.count == 1
        chat_second = await gate.authorize(user_id=OWNER, raw_ip=None)
        assert not chat_second.allowed and chat_second.code == "quota_exhausted"
        conversion_keys = [key for key in store.counts if key[2] == "conversion_day"]
        assert len(conversion_keys) == 1 and store.counts[conversion_keys[0]] == 1
    finally:
        await client.aclose()


async def test_conversion_bucket_key_is_day_scoped():
    store = InMemoryUsageCounterStore()
    client, app = await build_client(store=store, member_store=_MemberStore(tiers={OWNER: "free"}))
    try:
        job_id = await _open_job(client)
        uploaded = await _upload(client, job_id, pdf_bytes(texts=["day scoped"]), name="day.pdf")
        item = uploaded.json()["items"][0]
        assert (await _run_item(client, item["id"])).status_code == 202
        keys = [key for key in store.counts if key[2] == "conversion_day"]
        assert len(keys) == 1
        _subject, subject, _bucket, day_bucket = keys[0]
        assert subject == OWNER and day_bucket.endswith("Z") and "T00:00:00" in day_bucket
    finally:
        await client.aclose()


@pytest.mark.parametrize("size_case", ["over", "exact", "under"])
async def test_single_file_size_cap_is_per_grade(size_case):
    cap = SMALL["bytes"]["free"]
    if size_case == "over":
        payload = b"%PDF-" + b"B" * (cap - 4)
    elif size_case == "exact":
        payload = b"%PDF-" + b"B" * (cap - 5)
    else:
        payload = b"%PDF-" + b"B" * 10
    if size_case == "over":
        assert len(payload) == cap + 1
    else:
        assert len(payload) <= cap
    client, _app = await build_client(member_store=_MemberStore(tiers={OWNER: "free"}))
    try:
        job_id = await _open_job(client)
        response = await _upload(client, job_id, payload, name="size.pdf")
        if size_case == "over":
            assert response.status_code == 413, response.text
            assert response.json()["error"]["code"] == "document_size_limit"
            detail = await client.get(f"/api/document-conversions/{job_id}")
            assert detail.json()["items"] == []
        else:
            assert response.status_code == 201, response.text
            assert response.json()["items"][0]["name"] == "size.pdf"
    finally:
        await client.aclose()


async def test_zip_size_cap_sums_only_pdf_members():
    client, _app = await build_client(member_store=_MemberStore(tiers={OWNER: "free"}))
    try:
        job_id = await _open_job(client)
        one = b"%PDF-" + b"A" * 1095
        two = b"%PDF-" + b"B" * 1096
        over_total = zip_bytes({"one.pdf": one, "two.pdf": two, "notes.txt": b"x" * 1000})
        rejected = await _upload(client, job_id, over_total, name="sum.zip", media_type=ZIP_MEDIA)
        assert rejected.status_code == 413, rejected.text
        assert rejected.json()["error"]["code"] == "document_size_limit"

        one_member = zip_bytes({"one.pdf": one})
        accepted = await _upload(client, job_id, one_member, name="sum-ok.zip", media_type=ZIP_MEDIA)
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["items"][0]["name"] == "one.pdf"
        assert accepted.json()["rejected"] == []
    finally:
        await client.aclose()


async def test_page_cap_rejects_only_the_over_grade_items():
    two_pages = pdf_bytes(texts=["page one", "page two"])
    free_client, _free_app = await build_client(member_store=_MemberStore(tiers={OWNER: "free"}))
    admin_client, _admin_app = await build_client(member_store=_MemberStore(admins=(OWNER,)))
    try:
        free_job = await _open_job(free_client)
        free_item = (await _upload(free_client, free_job, two_pages, name="two.pdf")).json()["items"][0]
        assert (await _run_item(free_client, free_item["id"])).status_code == 202
        failed = await _terminal_item(free_client, free_item["id"])
        assert failed["status"] == "failed"
        assert failed["error_code"] == "document_page_limit"
        assert not failed.get("markdown_key")

        admin_job = await _open_job(admin_client)
        admin_item = (await _upload(admin_client, admin_job, two_pages, name="two.pdf")).json()["items"][0]
        assert (await _run_item(admin_client, admin_item["id"])).status_code == 202
        reviewed = await _terminal_item(admin_client, admin_item["id"])
        assert reviewed["status"] == "reviewed", dict(reviewed)
        assert reviewed["page_count"] == 2
    finally:
        await free_client.aclose()
        await admin_client.aclose()


async def test_rerun_of_finished_item_does_not_take_again():
    store = InMemoryUsageCounterStore()
    client, _app = await build_client(store=store, member_store=_MemberStore(tiers={OWNER: "free"}))
    try:
        job_id = await _open_job(client)
        item = (await _upload(client, job_id, pdf_bytes(texts=["once"]), name="once.pdf")).json()["items"][0]
        assert (await _run_item(client, item["id"])).status_code == 202
        await _terminal_item(client, item["id"])
        again = await _run_item(client, item["id"])
        assert again.status_code == 200, again.text
        assert again.json()["item"]["status"] == "reviewed"
        conversion_keys = [key for key in store.counts if key[2] == "conversion_day"]
        assert sum(store.counts[key] for key in conversion_keys) == 1
    finally:
        await client.aclose()


def test_static_shell_announces_quota_and_remaining():
    static = Path(__file__).parents[1] / "static"
    js = (static / "util-pdfmd.js").read_text(encoding="utf-8")
    css = (static / "util-menu.css").read_text(encoding="utf-8")
    assert "conversion_quota_exhausted" in js
    assert "오늘 변환 한도를 다 썼어요" in js
    assert "conversion.remaining" in js
    assert "pdfmd-quota" in js and "pdfmd-quota" in css
