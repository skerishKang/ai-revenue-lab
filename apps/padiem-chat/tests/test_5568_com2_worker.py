"""#5568 U2 — the COM2 conversion queue worker loop.

The owner contract: reuse U1's ledger and engine, query the queue, move
items to a processing state, record the result, and make sure a failed and
restarted worker never processes the same work twice.

Everything here runs on COM2 with REAL conversions (the Core pypdf boundary
on real PDF bytes) — no Workerd, no Cloudflare credentials.
"""
from __future__ import annotations

import asyncio
import io

import pytest

from app.document_convert_com2 import (
    Com2ConversionEngine,
    Com2ObjectStore,
    Com2SqliteLedger,
)
from app.document_convert_worker import Com2ConversionWorker
from app.document_convert_store import markdown_object_key

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32


def _pdf_bytes(marker: str) -> bytes:
    import fitz
    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    doc = fitz.open(stream=buffer.getvalue(), filetype="pdf")
    doc[0].insert_text((72, 100), marker, fontsize=12)
    out = doc.tobytes()
    doc.close()
    return out


class CountingEngine(Com2ConversionEngine):
    """The real Core conversion, with an execution counter for no-double-run proofs."""

    def __init__(self) -> None:
        self.calls = 0

    def convert(self, *, name: str, payload: bytes, mode: str = "fast") -> dict:
        self.calls += 1
        return super().convert(name=name, payload=payload, mode=mode)


class RaisingEngine(Com2ConversionEngine):
    """Simulates a conversion-level failure (bad PDF, runtime fault)."""

    def convert(self, *, name: str, payload: bytes, mode: str = "fast") -> dict:
        raise ValueError("conversion fault")


@pytest.fixture()
def authority(tmp_path):
    ledger = Com2SqliteLedger(tmp_path / "convert-ledger.sqlite3")
    objects = Com2ObjectStore(tmp_path / "objects")
    return ledger, objects, tmp_path


async def _queue_item(ledger, objects, *, user_id, marker) -> tuple[str, str, bytes]:
    job = await ledger.create_job(user_id, mode="fast")
    item = await ledger.add_item(user_id, job.id, name="probe.pdf", page_count=1)
    payload = _pdf_bytes(marker)
    objects.put(item.original_key, payload)
    return job.id, item.id, payload


def test_queue_drains_exactly_once(authority) -> None:
    ledger, objects, tmp_path = authority
    engine = CountingEngine()
    worker = Com2ConversionWorker(
        ledger=ledger, objects=objects, engine=engine, batch_size=8,
    )

    async def journey():
        ids = []
        for marker in ("first", "second", "third"):
            job_id, item_id, payload = await _queue_item(
                ledger, objects, user_id=OWNER, marker=marker,
            )
            ids.append((job_id, item_id, marker, payload))
        first = await worker.run_once()
        second = await worker.run_once()
        states = []
        for job_id, item_id, marker, payload in ids:
            item = await ledger.get_item(OWNER, item_id)
            markdown = objects.get(markdown_object_key(OWNER, job_id, item_id))
            states.append((item.status, marker in markdown.decode("utf-8"), markdown))
        return first, second, states, engine.calls

    first, second, states, calls = asyncio.run(journey())
    assert first["converted"] == 3 and first["failed"] == 0
    assert second["converted"] == 0, "an empty queue must not re-process"
    assert calls == 3, "the Core conversion must run exactly once per item"
    for status, marker_found, markdown in states:
        assert status == "done"
        assert marker_found is True


def test_claim_is_atomic_under_two_workers(authority) -> None:
    ledger, objects, tmp_path = authority
    engine = CountingEngine()
    worker_a = Com2ConversionWorker(ledger=ledger, objects=objects, engine=engine)
    worker_b = Com2ConversionWorker(ledger=ledger, objects=objects, engine=engine)

    async def journey():
        await _queue_item(ledger, objects, user_id=OWNER, marker="single")
        outcomes = await asyncio.gather(
            worker_a.process_one(), worker_b.process_one()
        )
        return outcomes, engine.calls

    outcomes, calls = asyncio.run(journey())
    assert sorted(outcomes) == ["converted", "empty"]
    assert calls == 1, "one queued item must be converted exactly once"


def test_crash_resume_completes_from_the_stored_artifact_without_rerunning(
    authority,
) -> None:
    """A crash after the markdown landed completes the item without re-running."""
    ledger, objects, tmp_path = authority
    engine = CountingEngine()
    worker = Com2ConversionWorker(ledger=ledger, objects=objects, engine=engine)

    async def journey():
        job_id, item_id, payload = await _queue_item(
            ledger, objects, user_id=OWNER, marker="crash-resume",
        )
        # Simulate the crash window: the conversion output landed, the ledger
        # update did not happen. The item sits in working.
        await ledger.set_item_status(OWNER, item_id, "working")
        markdown_key = markdown_object_key(OWNER, job_id, item_id)
        objects.put(markdown_key, b"crash-resume artifact body\n")
        engine.calls = 0
        recovery = await worker.recover_interrupted()
        item = await ledger.get_item(OWNER, item_id)
        return recovery, item, engine.calls, markdown_key

    recovery, item, calls, markdown_key = asyncio.run(journey())
    assert recovery["resumed"] == 1 and recovery["requeued"] == 0
    assert item.status == "done"
    assert item.markdown_key == markdown_key
    assert calls == 0, "resume must not re-execute the conversion"


def test_crash_requeue_when_no_artifact_then_processed_once(authority) -> None:
    ledger, objects, tmp_path = authority
    engine = CountingEngine()
    worker = Com2ConversionWorker(ledger=ledger, objects=objects, engine=engine)

    async def journey():
        job_id, item_id, payload = await _queue_item(
            ledger, objects, user_id=OWNER, marker="crash-requeue",
        )
        # Simulate the crash BEFORE any output: the item is stuck in working
        # and no markdown artifact exists.
        await ledger.set_item_status(OWNER, item_id, "working")
        recovery = await worker.recover_interrupted()
        engine.calls = 0
        processed = await worker.process_one()
        item = await ledger.get_item(OWNER, item_id)
        return recovery, processed, item, engine.calls

    recovery, processed, item, calls = asyncio.run(journey())
    assert recovery["requeued"] == 1
    assert processed == "converted"
    assert item.status == "done"
    assert calls == 1, "the re-queued conversion runs exactly once"


def test_failed_conversion_is_terminal_and_never_re_processed(authority) -> None:
    ledger, objects, tmp_path = authority
    engine = RaisingEngine()
    worker = Com2ConversionWorker(ledger=ledger, objects=objects, engine=engine)

    async def journey():
        job_id, item_id, payload = await _queue_item(
            ledger, objects, user_id=OWNER, marker="faulty",
        )
        first = await worker.process_one()
        item = await ledger.get_item(OWNER, item_id)
        second = await worker.process_one()
        return first, item, second

    first, item, second = asyncio.run(journey())
    assert first == "failed"
    assert item.status == "failed"
    assert item.error_code == "conversion_failed"
    assert second == "empty", "a failed item is terminal and never re-claimed"


def test_run_forever_drains_and_stops_cleanly(authority) -> None:
    ledger, objects, tmp_path = authority
    engine = CountingEngine()
    worker = Com2ConversionWorker(
        ledger=ledger, objects=objects, engine=engine, poll_interval_seconds=0.05,
    )

    async def journey():
        job_id, item_id, _payload = await _queue_item(
            ledger, objects, user_id=OWNER, marker="loop-item",
        )
        stop = asyncio.Event()
        stopper = asyncio.get_event_loop().call_later(1.5, stop.set)
        await worker.run_forever(stop)
        item = await ledger.get_item(OWNER, item_id)
        _ = stopper
        return item

    item = asyncio.run(journey())
    assert item.status == "done"


def test_items_of_different_users_never_cross(authority) -> None:
    ledger, objects, tmp_path = authority
    engine = CountingEngine()
    worker = Com2ConversionWorker(ledger=ledger, objects=objects, engine=engine)

    async def journey():
        owner_job, owner_item, _ = await _queue_item(
            ledger, objects, user_id=OWNER, marker="owner-marker",
        )
        other_job, other_item, _ = await _queue_item(
            ledger, objects, user_id=OTHER, marker="other-marker",
        )
        await worker.run_once()
        owner_item_row = await ledger.get_item(OWNER, owner_item)
        other_item_row = await ledger.get_item(OTHER, other_item)
        return {
            "owner": owner_item_row,
            "other": other_item_row,
            "owner_markdown": objects.get(
                markdown_object_key(OWNER, owner_job, owner_item)
            ),
            "other_markdown": objects.get(
                markdown_object_key(OTHER, other_job, other_item)
            ),
        }

    result = asyncio.run(journey())
    assert result["owner"].status == "done"
    assert result["other"].status == "done"
    assert b"owner-marker" in result["owner_markdown"]
    assert b"other-marker" in result["other_markdown"]
    assert result["owner_markdown"] != result["other_markdown"]
