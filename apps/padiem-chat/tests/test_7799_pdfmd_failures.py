"""#7799 PDF to Markdown — a text PDF converts, and every failure speaks in
user words instead of internal codes.

The production break (#7799) was not the file and not the converter: the
conversion allowance writes the `conversion_day` bucket, but the usage table
built by migration 005 only allows `minute/day/global_day`, so every
allowance failed its CHECK and every run was refused before converting. The
fix is migration 122, which rebuilds the table with the conversion bucket
admitted. These tests pin:

- migration 122 widens the CHECK and preserves the existing counters,
- the real allowance then succeeds (before 122 it raised),
- a text PDF converts end to end, a scan PDF surfaces the scan guidance,
- a broken PDF is recorded as a file-problem failure,
- a usage-check outage (503) records failed — never left `준비중` —
  while a daily-quota refusal (429) still leaves the item exactly as it was,
- the front end maps every code to a Korean sentence and shows no raw code.
"""

from __future__ import annotations

import secrets
import sqlite3

import pytest

from app.d1_sqlite import SqliteD1
from app.usage_gate import (
    CONVERSION_BUCKET_TYPE,
    D1UsageCounterStore,
    UsageDecision,
    UsageGate,
)
from _support.document_convert_routes import (
    build_client,
    open_job,
    pdf_bytes,
    run_item,
    upload,
    wait_item_terminal,
    zip_bytes,
)

# #8060: shipped reads live in _support; the contracts stay unchanged.
from _support import pdfmd_failures_source as sheets

UID = "usr_" + "a" * 32


@pytest.fixture(autouse=True)
def _legacy_conversion_contract(monkeypatch):
    """Upload and run stay testable behind the migration pause flag."""
    from app import document_convert_routes

    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)


def test_migration_122_widens_the_bucket_check_and_keeps_rows() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(sheets.migration("005_live_usage_quota.sql"))
    conn.execute(
        "INSERT INTO live_usage_buckets (subject_type, subject_key, bucket_type, bucket_start, request_count, updated_at) "
        "VALUES ('user', 'u1', 'day', '2026-11-14', 3, '2026-11-14T01:00:00Z')"
    )
    conn.executescript(sheets.migration("122_live_usage_conversion_bucket.sql"))
    conn.execute(
        "INSERT INTO live_usage_buckets (subject_type, subject_key, bucket_type, bucket_start, request_count, updated_at) "
        "VALUES ('user', 'u1', 'conversion_day', '2026-11-14', 1, '2026-11-14T01:00:00Z')"
    )
    rows = conn.execute(
        "SELECT bucket_type, request_count FROM live_usage_buckets ORDER BY bucket_type"
    ).fetchall()
    assert rows == [("conversion_day", 1), ("day", 3)]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO live_usage_buckets (subject_type, subject_key, bucket_type, bucket_start, request_count, updated_at) "
            "VALUES ('user', 'u1', 'bogus', '2026-11-14', 1, '2026-11-14T01:00:00Z')"
        )


@pytest.mark.asyncio
async def test_the_real_conversion_allowance_succeeds_after_122() -> None:
    from app.config import Settings

    conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(sheets.migration("005_live_usage_quota.sql"))
    conn.executescript(sheets.migration("122_live_usage_conversion_bucket.sql"))
    db = SqliteD1(conn, threaded=True, read_workers=0)
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="test.apps.googleusercontent.com",
        # 서명 키는 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
        google_client_secret=secrets.token_urlsafe(32),
        session_secret=secrets.token_urlsafe(32),
        quota_salt="test-quota-salt-for-7799-only-0000000",
    )
    gate = UsageGate(settings, D1UsageCounterStore(db))
    decision = await gate.authorize_conversion(user_id=UID, grade="free")
    assert decision.allowed is True, decision.code
    assert decision.bucket_type == CONVERSION_BUCKET_TYPE


@pytest.mark.asyncio
async def test_a_text_pdf_converts() -> None:
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["notice day off"]), name="notice.pdf")
        assert created.status_code == 201, created.text
        item_id = created.json()["items"][0]["id"]
        run = await run_item(client, item_id)
        assert run.status_code == 202, run.text
        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "reviewed"
        assert ran["has_markdown"] is True
        markdown = await client.get(f"/api/document-conversions/items/{item_id}/markdown")
        assert "notice day off" in markdown.text
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_scan_pdf_surfaces_the_scan_guidance() -> None:
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=[""]), name="스캔.pdf")
        assert created.status_code == 201, created.text
        item_id = created.json()["items"][0]["id"]
        run = await run_item(client, item_id)
        assert run.status_code == 202, run.text
        ran = await wait_item_terminal(client, item_id)
        # #7834: a scan is a failure with a reason, never a comparison result.
        assert ran["status"] == "failed"
        assert ran["error_code"] == "pdf_scanned_no_text"
        markdown = await client.get(f"/api/document-conversions/items/{item_id}/markdown")
        assert markdown.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_broken_pdf_is_recorded_as_a_file_problem_failure() -> None:
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        archive = zip_bytes({"bad.pdf": b"%PDF-1.4\nnot a readable body\n%%EOF\n"})
        created = await upload(
            client, job_id, archive, name="깨짐.zip", media_type="application/zip"
        )
        assert created.status_code == 201, created.text
        item_id = created.json()["items"][0]["id"]
        run = await run_item(client, item_id)
        assert run.status_code == 202, run.text
        failed = await wait_item_terminal(client, item_id)
        assert failed["status"] == "failed"
        assert failed["error_code"] == "pdf_invalid"
    finally:
        await client.aclose()


class _Gate:
    def __init__(self, **kwargs) -> None:
        self.decision = UsageDecision(**kwargs)

    async def authorize_conversion(self, *, user_id, grade):
        return self.decision


@pytest.mark.asyncio
async def test_a_usage_check_outage_records_failed_never_queued() -> None:
    client, app = await build_client()
    gate = _Gate(
        allowed=False, code="live_abuse_gate_unavailable", status_code=503,
        subject_type="user", bucket_type=CONVERSION_BUCKET_TYPE,
    )
    app.state.usage_gate = gate
    app.state.usage_gate_enforced = True
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["outage notice"]), name="outage.pdf")
        item_id = created.json()["items"][0]["id"]

        refused = await run_item(client, item_id)
        assert refused.status_code == 503, refused.text
        assert refused.json()["error"]["code"] == "live_abuse_gate_unavailable"
        assert refused.json()["item"]["status"] == "failed"
        assert refused.json()["item"]["error_code"] == "live_abuse_gate_unavailable"
        assert refused.json()["job"]["status"] == "failed"

        listed = await client.get("/api/document-conversions")
        assert listed.status_code == 200
        jobs = listed.json()["jobs"]
        assert jobs and jobs[0]["status"] == "failed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_daily_quota_refusal_still_leaves_the_item_as_it_was() -> None:
    client, app = await build_client()
    gate = _Gate(
        allowed=False, code="conversion_quota_exhausted", status_code=429,
        subject_type="user", bucket_type=CONVERSION_BUCKET_TYPE, limit=2,
    )
    app.state.usage_gate = gate
    app.state.usage_gate_enforced = True
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["quota notice"]), name="quota.pdf")
        item_id = created.json()["items"][0]["id"]

        refused = await run_item(client, item_id)
        assert refused.status_code == 429, refused.text
        assert refused.json()["error"]["code"] == "conversion_quota_exhausted"
        detail = await client.get(f"/api/document-conversions/items/{item_id}")
        assert detail.json()["item"]["status"] == "queued"
    finally:
        await client.aclose()


def test_the_front_end_speaks_in_user_words_and_shows_no_raw_code() -> None:
    js = sheets.pdfmd_js()
    # File problems, the scan guidance, and the transient outage each speak
    # Korean; the retry timing is stated for the transient family.
    assert 'pdf_encrypted: "암호가 있는 PDF는 바꿀 수 없습니다.' in js
    assert 'pdf_invalid: "PDF 형식이 아니거나 손상된 파일입니다."' in js
    assert 'live_abuse_gate_unavailable: "일시적인 오류입니다. 잠시 후(5분 뒤) 다시 시도해 주세요."' in js
    assert "스캔본이라 글자가 없어 지금은 읽을 수 없습니다." in js
    assert 'fallback || "일시적인 오류입니다. 잠시 후(5분 뒤) 다시 시도해 주세요."' in js
    # No internal code reaches the screen: neither as a title nor as a raw
    # warning list.
    assert "err.title = item.error_code" not in js
    assert "warnings.join" not in js
    assert "warnings.join(\", \")" not in js
    # #7865: the duplicated stage-line block is gone (the conversion starts
    # on upload), and the one card a still-queued row paints says so itself.
    assert "STAGE_LINES" not in js
    assert "바꾸는 중 — 잠시 후 결과가 이 자리에 생깁니다." in js
    assert "innerHTML" not in js
