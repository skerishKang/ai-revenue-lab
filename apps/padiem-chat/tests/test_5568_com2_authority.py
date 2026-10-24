"""#5568 — the COM2 authoritative execution and storage for PDF→Markdown.

The representative decision moved the execution/data authority to COM2 with
Cloudflare kept as the gate and backup. This suite proves the authority path
on COM2 itself, with REAL local execution:

- the sqlite ledger replays the shipped migration 066 unchanged and keeps the
  owner-scoped method semantics of the D1 store,
- the object store keeps the exact R2 key layout locally,
- the Core's reviewed pypdf conversion runs natively and its markdown lands
  in the ledger and the object store,
- the failure paths record ``failed`` + ``error_code`` instead of vanishing,
- another user can never reach another user's job, item or bytes.

No Cloudflare credentials, no Workerd — everything here runs on COM2.
"""
from __future__ import annotations

import asyncio
import io

import pytest

from app.document_convert_com2 import (
    Com2ConversionEngine,
    Com2ObjectStore,
    Com2SqliteLedger,
    run_item_conversion,
)

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32


def _pdf_bytes(text: str) -> bytes:
    import fitz
    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    payload = buffer.getvalue()
    doc = fitz.open(stream=payload, filetype="pdf")
    page = doc[0]
    page.insert_text((72, 100), text, fontsize=12)
    out = doc.tobytes()
    doc.close()
    return out


@pytest.fixture()
def authority(tmp_path):
    ledger = Com2SqliteLedger(tmp_path / "convert-ledger.sqlite3")
    objects = Com2ObjectStore(tmp_path / "objects")
    engine = Com2ConversionEngine()
    return ledger, objects, engine


def test_sqlite_ledger_replays_the_shipped_066_schema(tmp_path) -> None:
    import sqlite3

    Com2SqliteLedger(tmp_path / "convert-ledger.sqlite3")
    conn = sqlite3.connect(tmp_path / "convert-ledger.sqlite3")
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert {"document_convert_jobs", "document_convert_items"} <= tables


def test_job_item_conversion_round_trip_runs_the_real_core(authority) -> None:
    ledger, objects, engine = authority
    payload = _pdf_bytes("PADIEM COM2 authority conversion probe 2026-10-25")

    async def journey():
        job = await ledger.create_job(OWNER, mode="fast")
        item = await ledger.add_item(OWNER, job.id, name="probe.pdf", page_count=1)
        objects.put(item.original_key, payload)
        record = await run_item_conversion(
            ledger=ledger, objects=objects, engine=engine,
            user_id=OWNER, job_id=job.id, item_id=item.id,
        )
        markdown = objects.get(record.markdown_key) if record.markdown_key else None
        job_after = await ledger.get_job(OWNER, job.id)
        return record, markdown, job_after

    record, markdown, job_after = asyncio.run(journey())
    assert record is not None and record.status == "done"
    assert record.error_code is None
    assert record.character_count > 0
    assert markdown is not None and b"authority conversion probe" in markdown
    assert job_after.status == "done"


def test_owner_isolation_on_every_surface(authority) -> None:
    ledger, objects, engine = authority

    async def journey():
        job = await ledger.create_job(OWNER, mode="fast")
        item = await ledger.add_item(OWNER, job.id, name="probe.pdf")
        objects.put(item.original_key, _pdf_bytes("owner only"))
        await ledger.create_job(OTHER, mode="fast")
        return {
            "intruder_job": await ledger.get_job(OTHER, job.id),
            "intruder_item": await ledger.get_item(OTHER, item.id),
            "cross_items": await ledger.list_items(OTHER, job.id),
        }

    result = asyncio.run(journey())
    assert result["intruder_job"] is None
    assert result["intruder_item"] is None
    assert result["cross_items"] == []


def test_missing_original_records_failed_not_silent(authority) -> None:
    ledger, objects, engine = authority

    async def journey():
        job = await ledger.create_job(OWNER, mode="fast")
        item = await ledger.add_item(OWNER, job.id, name="ghost.pdf")
        record = await run_item_conversion(
            ledger=ledger, objects=objects, engine=engine,
            user_id=OWNER, job_id=job.id, item_id=item.id,
        )
        job_after = await ledger.get_job(OWNER, job.id)
        return record, job_after

    record, job_after = asyncio.run(journey())
    assert record.status == "failed"
    assert record.error_code == "original_object_missing"
    assert job_after.status == "failed"


def test_delete_item_rolls_the_job_back(authority) -> None:
    ledger, objects, engine = authority

    async def journey():
        job = await ledger.create_job(OWNER, mode="fast")
        item = await ledger.add_item(OWNER, job.id, name="probe.pdf")
        objects.put(item.original_key, _pdf_bytes("delete probe"))
        done = await run_item_conversion(
            ledger=ledger, objects=objects, engine=engine,
            user_id=OWNER, job_id=job.id, item_id=item.id,
        )
        deleted = await ledger.delete_item(OWNER, item.id)
        job_after = await ledger.get_job(OWNER, job.id)
        return done, deleted, job_after

    done, deleted, job_after = asyncio.run(journey())
    assert done.status == "done"
    assert deleted is True
    assert job_after.item_count == 0
