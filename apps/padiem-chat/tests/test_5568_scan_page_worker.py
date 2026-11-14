"""S3 regression: one page at a time, resume, threshold, allowance, images.

No model call and no platform credential leaves this process: the reader is a
local fake, the ledger is in memory, and the bucket is a dict. The last test
drives the route's request-free half with no scan model, which is the shape the
conversion has when the switch is off.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace

from app.document_convert_scan import (
    DEFAULT_SCAN_DAILY_PAGES,
    ERROR_DAILY_LIMIT,
    ERROR_FAILURE_THRESHOLD,
    SCAN_PAGE_TIMEOUT_SECONDS,
    assemble_markdown,
    run_scan_pages,
    scan_daily_page_limit,
    scan_page_ceiling,
)
from app.document_convert_store import (
    JOB_STATUS_FAILED,
    JOB_STATUS_REVIEWED,
    PAGE_STATUS_FAILED,
    PAGE_STATUS_OK,
    PAGE_STATUS_PENDING,
    PAGE_STATUS_WORKING,
    ScanPageRecord,
    markdown_object_key,
    scan_page_markdown_key,
)
from app.pdfmd_scan_ocr import (
    PAGE_KIND_SCAN,
    READ_STATUS_FAILED,
    READ_STATUS_OK,
    READ_STATUS_PARTIAL_LENGTH,
    PageReadResult,
    ScanPage,
)

BASE = (
    "<!-- padiem:page 1 -->\nbase one\n\n"
    "<!-- padiem:page 2 -->\nbase two\n\n"
    "<!-- padiem:page 3 -->\nbase three\n"
)


def _plan(count: int) -> SimpleNamespace:
    pages = tuple(
        ScanPage(
            number=number,
            kind=PAGE_KIND_SCAN,
            text_characters=0,
            image_jpeg=b"\xff\xd8\xff" + bytes([number]),
        )
        for number in range(1, count + 1)
    )
    return SimpleNamespace(page_count=count, scan_pages=pages)


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, key: str, data: bytes, **_kwargs) -> None:
        self.objects[key] = bytes(data)

    async def get(self, key: str):
        if key not in self.objects:
            return None
        return SimpleNamespace(body=self.objects[key])

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


class FakeLedger:
    def __init__(self, item_id: str = "item1", job_id: str = "job1") -> None:
        self.item_id = item_id
        self.job_id = job_id
        self.rows: dict[int, dict] = {}
        self.ensure_calls = 0
        self.item_state: dict | None = None
        self.refreshed = 0
        self.extra_used = 0

    def seed(
        self,
        number: int,
        status: str,
        *,
        markdown_key: str | None = None,
        attempts: int = 1,
    ) -> None:
        self.rows[number] = {
            "id": f"p{number}",
            "item_id": self.item_id,
            "page_number": number,
            "kind": PAGE_KIND_SCAN,
            "status": status,
            "attempts": attempts,
            "prompt_tokens": None,
            "reasoning_tokens": None,
            "completion_tokens": None,
            "seconds": None,
            "error_code": None,
            "markdown_key": markdown_key,
            "completed_at": "2026-11-14T00:00:00.000Z",
        }

    def _record(self, row: dict) -> ScanPageRecord:
        return ScanPageRecord(
            id=row["id"],
            item_id=row["item_id"],
            page_number=row["page_number"],
            kind=row["kind"],
            status=row["status"],
            attempts=row["attempts"],
            prompt_tokens=row["prompt_tokens"],
            reasoning_tokens=row["reasoning_tokens"],
            completion_tokens=row["completion_tokens"],
            seconds=row["seconds"],
            error_code=row["error_code"],
            markdown_key=row["markdown_key"],
            completed_at=row["completed_at"],
        )

    async def ensure_scan_pages(self, user_id, item_id, pages) -> None:
        self.ensure_calls += 1
        for number, kind in pages:
            self.rows.setdefault(number, {
                "id": f"p{number}", "item_id": item_id, "page_number": number,
                "kind": kind, "status": PAGE_STATUS_PENDING, "attempts": 0,
                "prompt_tokens": None, "reasoning_tokens": None,
                "completion_tokens": None, "seconds": None, "error_code": None,
                "markdown_key": None, "completed_at": None,
            })

    async def reset_working_scan_pages(self, user_id, item_id) -> None:
        for row in self.rows.values():
            if row["status"] == PAGE_STATUS_WORKING:
                row["status"] = PAGE_STATUS_PENDING

    async def list_scan_pages(self, user_id, item_id) -> list[ScanPageRecord]:
        return [self._record(row) for row in sorted(self.rows.values(), key=lambda r: r["page_number"])]

    async def claim_scan_page(self, user_id, item_id, page_number):
        row = self.rows[page_number]
        if row["status"] != PAGE_STATUS_PENDING:
            return None
        row["status"] = PAGE_STATUS_WORKING
        row["attempts"] += 1
        return self._record(row)

    async def complete_scan_page(
        self, user_id, item_id, page_number, *, status, attempts,
        prompt_tokens=None, reasoning_tokens=None, completion_tokens=None,
        seconds=None, error_code=None, markdown_key=None,
    ):
        row = self.rows[page_number]
        row.update(
            status=status, attempts=attempts, prompt_tokens=prompt_tokens,
            reasoning_tokens=reasoning_tokens, completion_tokens=completion_tokens,
            seconds=seconds, error_code=error_code, markdown_key=markdown_key,
            completed_at="2026-11-14T10:00:00.000Z",
        )
        return self._record(row)

    async def count_scan_pages_since(self, user_id, since_iso) -> int:
        finished = sum(
            1 for row in self.rows.values()
            if row["status"] in (PAGE_STATUS_OK, "partial_length", PAGE_STATUS_FAILED)
        )
        return finished + self.extra_used

    async def complete_item(self, user_id, item_id, **fields):
        self.item_state = {"user_id": user_id, "item_id": item_id, **fields}

    async def refresh_job(self, user_id, job_id):
        self.refreshed += 1


class FakeReader:
    def __init__(self, statuses: list[str], *, delay: float = 0.0, tracker=None):
        self.statuses = statuses
        self.delay = delay
        self.calls: list[int] = []
        self.tracker = tracker

    def read_page(self, image: bytes) -> PageReadResult:
        index = len(self.calls)
        self.calls.append(image[3])
        if self.tracker is not None:
            self.tracker["active"] += 1
            self.tracker["max"] = max(self.tracker["max"], self.tracker["active"])
        if self.delay:
            time.sleep(self.delay)
        if self.tracker is not None:
            self.tracker["active"] -= 1
        status = self.statuses[index]
        markdown = f"PAGE-{image[3]}" if status != READ_STATUS_FAILED else ""
        return PageReadResult(
            status=status,
            markdown=markdown,
            requested_model="test/model",
            served_model="test/model" if status != READ_STATUS_FAILED else None,
            model_matches=status != READ_STATUS_FAILED,
            attempts=1,
            seconds=0.5,
            prompt_tokens=100,
            reasoning_tokens=20,
            completion_tokens=30,
            total_tokens=150,
            finish_reason="length" if status == READ_STATUS_PARTIAL_LENGTH else "stop",
            http_status=200 if status != READ_STATUS_FAILED else 504,
            error_code=None if status != READ_STATUS_FAILED else "upstream_timeout",
        )


def _item(item_id: str = "item1") -> SimpleNamespace:
    return SimpleNamespace(id=item_id, name="scan.pdf")


def _job(job_id: str = "job1") -> SimpleNamespace:
    return SimpleNamespace(id=job_id)


async def _run(ledger, bucket, reader, plan, *, base=BASE, daily_limit=20):
    return await run_scan_pages(
        ledger=ledger,
        bucket=bucket,
        user_id="user1",
        item=_item(),
        job=_job(),
        plan=plan,
        reader=reader,
        base_markdown=base,
        daily_limit=daily_limit,
        now=lambda: datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
    )


def test_the_page_ceiling_is_150_seconds() -> None:
    assert SCAN_PAGE_TIMEOUT_SECONDS == 150.0


def test_the_daily_default_is_twenty_and_env_is_bounded(monkeypatch) -> None:
    assert DEFAULT_SCAN_DAILY_PAGES == 20
    assert scan_daily_page_limit({}) == 20
    assert scan_daily_page_limit({"PADIEM_PDFMD_SCAN_DAILY_PAGES": "5"}) == 5
    assert scan_daily_page_limit({"PADIEM_PDFMD_SCAN_DAILY_PAGES": "0"}) == 1
    assert scan_daily_page_limit({"PADIEM_PDFMD_SCAN_DAILY_PAGES": "nope"}) == 20
    assert scan_page_ceiling(None) == 20
    assert scan_page_ceiling(10) == 10


def test_assembly_replaces_only_the_named_pages() -> None:
    merged = assemble_markdown(BASE, {2: "PAGE-2"})
    assert "base one" in merged and "base three" in merged
    assert "base two" not in merged and "PAGE-2" in merged
    assert merged.count("<!-- padiem:page ") == 3


async def test_a_finished_page_is_not_read_again_after_a_restart() -> None:
    ledger = FakeLedger()
    bucket = FakeBucket()
    ledger.seed(1, PAGE_STATUS_OK, markdown_key=scan_page_markdown_key("user1", "job1", "item1", 1))
    bucket.objects[scan_page_markdown_key("user1", "job1", "item1", 1)] = b"PAGE-1"
    reader = FakeReader([READ_STATUS_OK])

    await _run(ledger, bucket, reader, _plan(2))

    assert reader.calls == [2]
    assert ledger.item_state is not None
    assert ledger.item_state["status"] == JOB_STATUS_REVIEWED
    merged = bucket.objects[markdown_object_key("user1", "job1", "item1")].decode()
    assert "PAGE-1" in merged and "PAGE-2" in merged


async def test_more_than_half_failed_fails_the_document_and_keeps_read_pages() -> None:
    ledger = FakeLedger()
    bucket = FakeBucket()
    reader = FakeReader([READ_STATUS_FAILED, READ_STATUS_FAILED, READ_STATUS_OK])

    outcome = await _run(ledger, bucket, reader, _plan(3))

    assert reader.calls == [1, 2]
    assert outcome["status"] == JOB_STATUS_FAILED
    assert outcome["error_code"] == ERROR_FAILURE_THRESHOLD
    assert ledger.item_state["markdown_key"] is not None
    merged = bucket.objects[ledger.item_state["markdown_key"]].decode()
    assert "base three" in merged


async def test_the_daily_allowance_stops_before_reading() -> None:
    ledger = FakeLedger()
    ledger.extra_used = 19
    bucket = FakeBucket()
    reader = FakeReader([READ_STATUS_OK, READ_STATUS_OK])

    outcome = await _run(ledger, bucket, reader, _plan(2), daily_limit=20)

    assert reader.calls == []
    assert outcome["status"] == JOB_STATUS_FAILED
    assert outcome["error_code"] == ERROR_DAILY_LIMIT
    assert ledger.item_state["markdown_key"] is not None


async def test_one_page_is_read_at_a_time_across_two_documents() -> None:
    tracker = {"active": 0, "max": 0}
    first_ledger = FakeLedger(item_id="item1", job_id="job1")
    second_ledger = FakeLedger(item_id="item2", job_id="job1")
    bucket = FakeBucket()
    first_reader = FakeReader([READ_STATUS_OK, READ_STATUS_OK], delay=0.02, tracker=tracker)
    second_reader = FakeReader([READ_STATUS_OK, READ_STATUS_OK], delay=0.02, tracker=tracker)

    await asyncio.gather(
        run_scan_pages(
            ledger=first_ledger, bucket=bucket, user_id="user1", item=_item("item1"),
            job=_job(), plan=_plan(2), reader=first_reader, base_markdown=BASE,
            daily_limit=20, now=lambda: datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
        ),
        run_scan_pages(
            ledger=second_ledger, bucket=bucket, user_id="user1", item=_item("item2"),
            job=_job(), plan=_plan(2), reader=second_reader, base_markdown=BASE,
            daily_limit=20, now=lambda: datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
        ),
    )

    assert tracker["max"] == 1
    assert first_reader.calls == [1, 2]
    assert second_reader.calls == [1, 2]


async def test_page_images_are_deleted_when_the_page_ends() -> None:
    ledger = FakeLedger()
    bucket = FakeBucket()

    await _run(ledger, bucket, FakeReader([READ_STATUS_OK]), _plan(1))

    assert not [key for key in bucket.objects if key.endswith(".jpg")]
    assert any(key.endswith("pages/1.jpg") for key in bucket.deleted)


async def test_a_partial_page_counts_as_read_and_keeps_its_text() -> None:
    ledger = FakeLedger()
    bucket = FakeBucket()

    outcome = await _run(ledger, bucket, FakeReader([READ_STATUS_PARTIAL_LENGTH]), _plan(1))

    assert outcome["status"] == JOB_STATUS_REVIEWED
    assert ledger.rows[1]["status"] == "partial_length"
    assert ledger.rows[1]["reasoning_tokens"] == 20
    assert "PAGE-1" in bucket.objects[markdown_object_key("user1", "job1", "item1")].decode()


async def test_the_switch_off_path_never_touches_page_state(monkeypatch) -> None:
    from app import document_convert_routes as routes

    ledger = FakeLedger()
    bucket = FakeBucket()
    item = SimpleNamespace(id="item1", name="text.pdf", original_key="orig", page_count=1)
    job = SimpleNamespace(id="job1", mode="fast")
    calls = {"convert": 0}

    def fake_convert(**_kwargs):
        calls["convert"] += 1
        return SimpleNamespace(markdown="# text\n", page_count=1, public_dict=dict)

    monkeypatch.setattr(routes, "convert_pdf_to_markdown", fake_convert)
    bucket.objects["orig"] = b"%PDF-fake"

    from app.pdfmd_scan_ocr import scan_ocr_enabled

    assert scan_ocr_enabled({}) is False
    await routes._run_conversion(ledger, bucket, "user1", item, job)

    assert calls["convert"] == 1
    assert ledger.ensure_calls == 0
    assert ledger.item_state["status"] == JOB_STATUS_REVIEWED


# -- the real 116 schema, through SQLite -------------------------------------
#
# The worker tests above use an in-memory ledger. This one applies the shipped
# migrations and drives the D1 store, so a column or statement that does not
# match migration 116 fails here rather than on the host.

import sqlite3
from pathlib import Path

from app.document_convert_store import D1DocumentConvertStore


class _SqliteStatement:
    def __init__(self, connection, sql: str, params: tuple = ()) -> None:
        self.connection = connection
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return _SqliteStatement(self.connection, self.sql, params)

    async def first(self):
        row = self.connection.execute(self.sql, self.params).fetchone()
        return dict(row) if row is not None else None

    async def all(self):
        return [dict(row) for row in self.connection.execute(self.sql, self.params).fetchall()]

    async def run(self):
        cursor = self.connection.execute(self.sql, self.params)
        self.connection.commit()
        return cursor


class _SqliteD1:
    def __init__(self, connection) -> None:
        self.connection = connection

    def prepare(self, sql: str) -> _SqliteStatement:
        return _SqliteStatement(self.connection, sql)


def _migrated_sqlite() -> _SqliteD1:
    migrations = Path(__file__).parents[1] / "migrations"
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    for name in ("066_document_convert_jobs.sql", "116_document_convert_scan_pages.sql"):
        connection.executescript((migrations / name).read_text(encoding="utf-8"))
    return _SqliteD1(connection)


async def test_the_116_store_claims_once_and_counts_finished_pages() -> None:
    store = D1DocumentConvertStore(_migrated_sqlite())
    job = await store.create_job("user1", mode="fast")
    item = await store.add_item("user1", job.id, name="scan.pdf", page_count=2)

    await store.ensure_scan_pages("user1", item.id, [(1, PAGE_KIND_SCAN), (2, PAGE_KIND_SCAN)])
    first = await store.claim_scan_page("user1", item.id, 1)
    second = await store.claim_scan_page("user1", item.id, 1)
    assert first is not None and first.attempts == 1
    assert second is None

    await store.complete_scan_page(
        "user1", item.id, 1, status=PAGE_STATUS_OK, attempts=1,
        prompt_tokens=10, reasoning_tokens=5, completion_tokens=7,
        seconds=1.25, markdown_key="page-1.md",
    )
    claimed_two = await store.claim_scan_page("user1", item.id, 2)
    assert claimed_two is not None
    await store.reset_working_scan_pages("user1", item.id)
    page_two = await store.get_scan_page("user1", item.id, 2)
    assert page_two is not None
    assert (page_two.status, page_two.attempts) == (PAGE_STATUS_PENDING, 1)

    assert await store.count_scan_pages_since("user1", "2000-01-01T00:00:00.000Z") == 1
    assert await store.count_scan_pages_since("someone-else", "2000-01-01T00:00:00.000Z") == 0

    await store.delete_item("user1", item.id)
    assert await store.list_scan_pages("user1", item.id) == []
