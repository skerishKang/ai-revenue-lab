"""#5568 follow-on — the run route starts the work instead of waiting for it.

The front edge closes a long request with 504 while the origin is still
converting, so ``convert_item_run`` hands the conversion to a background task
and answers 202 with the working item. These tests pin the behaviour the
screen and the owner now rely on: the quick 202, the single-conversion guard,
the failure record, and the stale-working restart a host restart depends on.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app import document_convert_routes
from test_5568_document_convert_routes import (
    FakeD1,
    build_client,
    open_job,
    pdf_bytes,
    run_item,
    upload,
    wait_item_terminal,
)


@pytest.fixture(autouse=True)
def _legacy_conversion_contract(monkeypatch):
    """The run route is exercised behind the #5710 gate, like the route tests."""
    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)


def _conversion_stand_in(delay: float, calls: list, failure: Exception | None = None):
    """The real engine behind a wall-clock delay, so the answer can beat the work."""
    real = document_convert_routes.convert_pdf_to_markdown

    def convert(*args, **kwargs):
        calls.append(time.monotonic())
        time.sleep(delay)
        if failure is not None:
            raise failure
        return real(*args, **kwargs)

    return convert


@pytest.mark.asyncio
async def test_run_answers_202_before_the_conversion_finishes(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes, "convert_pdf_to_markdown", _conversion_stand_in(0.4, calls)
    )
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Async 1 page 1"]), name="async.pdf")
        item_id = created.json()["items"][0]["id"]

        started = time.monotonic()
        run = await run_item(client, item_id)
        answered_in = time.monotonic() - started
        assert run.status_code == 202, run.text
        assert run.json()["item"]["status"] == "working"
        # The whole point: the answer must not wait for the conversion.
        assert answered_in < 0.9, f"run answered in {answered_in:.2f}s"

        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "reviewed"
        assert ran["page_count"] == 1
        assert ran["has_markdown"] is True
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_second_run_while_working_does_not_start_a_second_conversion(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes, "convert_pdf_to_markdown", _conversion_stand_in(0.3, calls)
    )
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Async 2 page 1"]), name="once.pdf")
        item_id = created.json()["items"][0]["id"]

        first = await run_item(client, item_id)
        assert first.status_code == 202, first.text
        second = await run_item(client, item_id)
        assert second.status_code == 202, second.text
        assert second.json()["item"]["status"] == "working"

        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "reviewed"
        assert len(calls) == 1, f"the item was converted {len(calls)} times"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_background_failure_records_failed_with_error_code(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes,
        "convert_pdf_to_markdown",
        _conversion_stand_in(0.0, calls, failure=ValueError("conversion blew up")),
    )
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Async 3 page 1"]), name="broken.pdf")
        item_id = created.json()["items"][0]["id"]

        assert (await run_item(client, item_id)).status_code == 202
        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "failed"
        assert ran["error_code"] == "convert_failed"
        assert ran["has_markdown"] is False
        detail = await client.get(f"/api/document-conversions/{job_id}")
        assert detail.json()["job"]["status"] == "failed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_fresh_working_is_not_restarted_but_a_stale_row_is(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        document_convert_routes, "convert_pdf_to_markdown", _conversion_stand_in(0.2, calls)
    )
    d1 = FakeD1()
    client, _app = await build_client(d1=d1)
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=["Async 4 page 1"]), name="restart.pdf")
        item_id = created.json()["items"][0]["id"]

        # A fresh working row belongs to a run this process is driving: no restart.
        d1.conn.execute(
            "UPDATE document_convert_items SET status = 'working' WHERE id = ?", (item_id,)
        )
        fresh = await run_item(client, item_id)
        assert fresh.status_code == 202, fresh.text
        assert fresh.json()["item"]["status"] == "working"
        await asyncio.sleep(0.35)
        assert calls == [], "a fresh working row must not start a second conversion"

        # A row stuck working past the restart deadline (host restart, crash)
        # belongs to no one: the next run takes it over.
        d1.conn.execute(
            "UPDATE document_convert_items SET status = 'working', "
            "updated_at = '2026-01-01T00:00:00.000Z' WHERE id = ?",
            (item_id,),
        )
        stale = await run_item(client, item_id)
        assert stale.status_code == 202, stale.text
        ran = await wait_item_terminal(client, item_id)
        assert ran["status"] == "reviewed"
        assert len(calls) == 1, f"the stale row was converted {len(calls)} times"
    finally:
        await client.aclose()
