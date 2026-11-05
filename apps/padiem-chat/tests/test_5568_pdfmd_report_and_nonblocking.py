"""#5568 follow-up — report_json stays valid JSON and converts do not block.

Covers the two guarantees added by #6946: a 100-page verify report is stored
as valid JSON <= 12,000 chars on both the D1 and COM2 ledgers (never cut,
never None), and a slow conversion does not delay other HTTP requests
(nonblocking IO, in the style of test_com2_nonblocking_io.py).
"""

from __future__ import annotations

import asyncio
import json
import threading
import sqlite3

import pytest

from app.document_convert_com2 import Com2SqliteLedger
from app.document_convert_store import D1DocumentConvertStore, MAX_REPORT_JSON_CHARS

from test_5568_document_convert_routes import (
    FakeD1,
    MemoryR2,
    OWNER,
    build_client,
    open_job,
    pdf_bytes,
    upload,
)


def _hundred_page_report() -> dict:
    return {
        "name": "long.pdf",
        "media_type": "application/pdf",
        "byte_size": 123456,
        "page_count": 100,
        "mode": "verify",
        "character_count": 50000,
        "line_count": 900,
        "pages": [
            {
                "number": page,
                "start_line": (page - 1) * 9 + 1,
                "end_line": page * 9,
                "native_text_present": True,
                "rotated_text": False,
                "character_count": 500,
            }
            for page in range(1, 101)
        ],
        "agreement": [
            {
                "page": page,
                "character_coverage": 0.5 if page % 3 == 0 else 1.0,
                "digit_preservation": 0.9,
                "reading_order": 0.98,
                "rotated_text": False,
            }
            for page in range(1, 101)
        ],
        "mismatches": [
            {"page": page, "kind": "unit-mismatch", "detail": "x" * 200}
            for page in range(1, 11)
        ],
        "warnings": ["w"] * 20,
    }


def _assert_valid_bounded_report(raw: str | None) -> dict:
    assert raw is not None
    assert len(raw) <= MAX_REPORT_JSON_CHARS
    parsed = json.loads(raw)
    assert parsed is not None
    assert parsed["agreement_summary"]["summarized"] is True
    assert parsed["agreement_summary"]["page_count"] == 100
    assert parsed["agreement_summary"]["min_character_coverage"] == 0.5
    assert parsed["agreement_summary"]["review_page_count"] == 33
    return parsed


@pytest.mark.asyncio
async def test_hundred_page_verify_report_json_is_valid_bounded_and_descriptive_on_d1():
    d1 = FakeD1()
    store = D1DocumentConvertStore(d1)
    job = await store.create_job(OWNER, mode="verify")
    item = await store.add_item(OWNER, job.id, name="long.pdf", page_count=100)
    done = await store.complete_item(
        OWNER,
        item.id,
        status="reviewed",
        page_count=100,
        character_count=50000,
        markdown_key="k.md",
        report=_hundred_page_report(),
        error_code=None,
    )
    assert done is not None
    assert done.report is not None
    assert done.report["agreement_summary"]["page_count"] == 100

    raw = d1.conn.execute(
        "SELECT report_json FROM document_convert_items WHERE id = ?", (item.id,)
    ).fetchone()[0]
    _assert_valid_bounded_report(raw)


@pytest.mark.asyncio
async def test_hundred_page_verify_report_json_is_valid_bounded_and_descriptive_on_com2(tmp_path):
    path = tmp_path / "chat.sqlite3"
    store = Com2SqliteLedger(path)
    job = await store.create_job(OWNER, mode="verify")
    item = await store.add_item(OWNER, job.id, name="long.pdf", page_count=100)
    done = await store.complete_item(
        OWNER,
        item.id,
        status="reviewed",
        page_count=100,
        character_count=50000,
        markdown_key="k.md",
        report=_hundred_page_report(),
        error_code=None,
    )
    assert done is not None
    assert done.report is not None
    assert done.report["agreement_summary"]["page_count"] == 100

    with sqlite3.connect(path) as conn:
        raw = conn.execute(
            "SELECT report_json FROM document_convert_items WHERE id = ?", (item.id,)
        ).fetchone()[0]
    _assert_valid_bounded_report(raw)


@pytest.mark.asyncio
async def test_slow_conversion_does_not_block_twenty_http_requests(monkeypatch):
    from app import document_convert_routes

    entered = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)

    real_convert = document_convert_routes.convert_pdf_to_markdown

    def slow_convert(*args, **kwargs):
        result = real_convert(*args, **kwargs)
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test timed out")
        return result

    client, _app = await build_client(r2=MemoryR2())
    try:
        job_id = await open_job(client)
        created = await upload(
            client, job_id, pdf_bytes(texts=["Slow conversion page"]), name="slow.pdf"
        )
        assert created.status_code == 201, created.text
        item_id = created.json()["items"][0]["id"]

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(document_convert_routes, "convert_pdf_to_markdown", slow_convert)
            task = asyncio.create_task(
                client.post(f"/api/document-conversions/items/{item_id}/run")
            )
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                replies = await asyncio.wait_for(
                    asyncio.gather(
                        *[
                            client.get("/api/document-conversions")
                            for _ in range(20)
                        ]
                    ),
                    1.0,
                )
                assert all(reply.status_code == 200 for reply in replies)
            finally:
                release.set()
            run = await task
        assert run.status_code == 200, run.text
    finally:
        await client.aclose()
