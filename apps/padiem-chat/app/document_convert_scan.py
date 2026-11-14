"""S3: read scan pages one at a time and keep every finished page.

Why a page worker beside the conversion route
---------------------------------------------
#7711 decided which pages need reading and how to read one page, but one
document still ran as one all-or-nothing call. A long scan that stopped at page
14 had done thirteen pages of work and kept none of it, and a restart started
again from page 1.

This module gives the conversion a page-level shape:

* the existing ledger gains one sub-row per page (migration 116), carrying the
  state, attempt count, separated token counts and seconds for that page;
* exactly one page is read at a time, and one document at a time, so a slow
  page cannot multiply its own spend;
* the assembled Markdown is stored after every finished page, so a host that
  stops mid-document resumes at the first page without a terminal state;
* a page image is written only for the page being read and removed in the same
  ``finally``, whether the read succeeded or not;
* more than half of the scan pages failing fails the document, and the pages
  already read stay in the stored Markdown;
* a per-owner daily page ceiling (default 20) stops a document before it reads
  past the day's allowance.

Text pages are untouched: the base conversion is the existing Core conversion,
and only the scan pages' sections are replaced.

Off by design
-------------
Nothing here runs while ``PADIEM_PDFMD_SCAN_OCR_ENABLED`` is not exactly
``true``. The route calls this module only then; with the switch off the
conversion is byte-for-byte the one that existed before this slice.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from .document_convert_store import (
    JOB_STATUS_FAILED,
    JOB_STATUS_REVIEWED,
    PAGE_STATUS_FAILED,
    ScanPageRecord,
    markdown_object_key,
    scan_page_image_key,
    scan_page_markdown_key,
)
from .pdfmd_scan_ocr import (
    DEFAULT_MAX_SCAN_PAGES,
    READ_STATUS_OK,
    READ_STATUS_PARTIAL_LENGTH,
    PageReadResult,
    ScanPage,
)
from .pdfmd_scan_ocr import (
    PAGE_KIND_SCAN as PLAN_PAGE_KIND_SCAN,
)

#: Per-owner page allowance. The default is deliberately the conservative free
#: figure from the product decision; a deployment may raise it up to the hard
#: ceiling without a code change.
SCAN_DAILY_PAGES_ENV = "PADIEM_PDFMD_SCAN_DAILY_PAGES"
DEFAULT_SCAN_DAILY_PAGES = 20
HARD_SCAN_DAILY_PAGES = 500

#: One page may spend at most this long. The adapter's own client timeout is
#: set to the same number; the outer guard only stops a stuck thread from
#: holding the one-at-a-time lane forever.
SCAN_PAGE_TIMEOUT_SECONDS = 150.0
SCAN_PAGE_HARD_STOP_SECONDS = SCAN_PAGE_TIMEOUT_SECONDS + 5.0

ERROR_DAILY_LIMIT = "scan_page_daily_limit"
ERROR_FAILURE_THRESHOLD = "scan_page_failure_threshold"
ERROR_PAGE_TIMEOUT = "scan_page_timeout"
ERROR_EMPTY_MARKDOWN = "scan_page_empty"
ERROR_UNEXPECTED = "scan_page_failed"

#: The Core conversion marks each page with this anchor. Splitting on it keeps
#: the review UI's page addressing intact while one page's body is replaced.
_PAGE_ANCHOR = re.compile(r"(?m)^<!-- padiem:page (\d+) -->[ \t]*\r?\n?")


def scan_daily_page_limit(environ: Mapping[str, str] | None = None) -> int:
    """Read the day's page allowance; anything unusable keeps the default."""

    source = os.environ if environ is None else environ
    raw = source.get(SCAN_DAILY_PAGES_ENV)
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_SCAN_DAILY_PAGES
    return max(1, min(value, HARD_SCAN_DAILY_PAGES))


def scan_page_ceiling(page_limit: int | None) -> int:
    """The planner's ceiling is the product's, never wider than the grade's."""

    ceiling = DEFAULT_MAX_SCAN_PAGES
    if isinstance(page_limit, int) and not isinstance(page_limit, bool) and page_limit > 0:
        ceiling = min(ceiling, page_limit)
    return max(1, ceiling)


def assemble_markdown(base_markdown: str, replacements: dict[int, str]) -> str:
    """Replace only the named page bodies and keep every anchor and text page.

    A page with no replacement keeps the base conversion's own section, which
    is how a failed scan page still says it could not be read rather than
    silently disappearing from the document.
    """

    if not replacements:
        return base_markdown
    parts = _PAGE_ANCHOR.split(base_markdown)
    if len(parts) < 3:
        # No anchors: never drop converted text. Append the read pages in page
        # order so the result is longer, not shorter, than the base.
        extra = "\n\n".join(
            text.strip() for _, text in sorted(replacements.items()) if text.strip()
        )
        if not extra:
            return base_markdown
        return base_markdown.rstrip() + "\n\n" + extra + "\n"
    pieces = [parts[0]]
    for index in range(1, len(parts), 2):
        try:
            number = int(parts[index])
        except ValueError:
            continue
        section = parts[index + 1] if index + 1 < len(parts) else ""
        pieces.append(f"<!-- padiem:page {number} -->\n")
        replaced = replacements.get(number)
        if replaced is None:
            pieces.append(section)
        else:
            pieces.append(replaced.strip() + "\n\n")
    return "".join(pieces).rstrip() + "\n"


def _utc_day_start(now: datetime) -> str:
    start = now.astimezone(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start.isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _bucket_call(bucket: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Call an R2 binding method the way both the Worker and host expose it."""

    result = getattr(bucket, method)(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def _object_bytes(obj: Any) -> bytes:
    if obj is None:
        return b""
    body = getattr(obj, "body", None)
    if hasattr(body, "__aiter__"):
        chunks = [bytes(chunk) async for chunk in body]
        return b"".join(chunks)
    if body is not None:
        return bytes(body)
    return bytes(obj)


def _read_status(result: PageReadResult) -> str:
    if result.status in (READ_STATUS_OK, READ_STATUS_PARTIAL_LENGTH):
        return result.status
    return PAGE_STATUS_FAILED


def _page_report(rows: list[ScanPageRecord], total: int, page_count: int) -> dict[str, Any]:
    read = sum(1 for row in rows if row.read)
    failed = sum(1 for row in rows if row.status == PAGE_STATUS_FAILED)
    return {
        "scan_pages": {
            "page_count": page_count,
            "scan_page_count": total,
            "read_pages": read,
            "failed_pages": failed,
            "pages": [row.public_dict() for row in rows],
        }
    }


class _ScanRun:
    """One document's page loop. Holds no state beyond this run."""

    def __init__(
        self,
        *,
        ledger: Any,
        bucket: Any,
        user_id: str,
        item: Any,
        job: Any,
        plan: Any,
        reader: Any,
        base_markdown: str,
        daily_limit: int,
        now: Callable[[], datetime],
    ) -> None:
        self.ledger = ledger
        self.bucket = bucket
        self.user_id = user_id
        self.item = item
        self.job = job
        self.plan = plan
        self.reader = reader
        self.base_markdown = base_markdown
        self.daily_limit = daily_limit
        self.now = now
        self.scan_pages: tuple[ScanPage, ...] = tuple(plan.scan_pages)
        self.markdown_key = markdown_object_key(user_id, job.id, item.id)
        self.rows: dict[int, ScanPageRecord] = {}
        self.replacements: dict[int, str] = {}

    async def prepare(self) -> None:
        await self.ledger.ensure_scan_pages(
            self.user_id,
            self.item.id,
            [(page.number, PLAN_PAGE_KIND_SCAN) for page in self.scan_pages],
        )
        await self.ledger.reset_working_scan_pages(self.user_id, self.item.id)
        self.rows = {
            row.page_number: row
            for row in await self.ledger.list_scan_pages(self.user_id, self.item.id)
        }
        for row in self.rows.values():
            if row.read and row.markdown_key:
                fragment = await _bucket_call(self.bucket, "get", row.markdown_key)
                self.replacements[row.page_number] = (
                    await _object_bytes(fragment)
                ).decode("utf-8", errors="replace")

    def failures(self) -> int:
        return sum(1 for row in self.rows.values() if row.status == PAGE_STATUS_FAILED)

    def over_threshold(self) -> bool:
        return self.failures() * 2 > len(self.scan_pages)

    async def store_draft(self) -> str:
        markdown = assemble_markdown(self.base_markdown, self.replacements)
        await _bucket_call(
            self.bucket,
            "put",
            self.markdown_key,
            markdown.encode("utf-8"),
            httpMetadata={"contentType": "text/markdown"},
        )
        return markdown

    async def finish(self, *, failed: bool, error_code: str | None) -> dict[str, Any]:
        markdown = await self.store_draft()
        rows = sorted(self.rows.values(), key=lambda row: row.page_number)
        report = _page_report(rows, len(self.scan_pages), self.plan.page_count)
        await self.ledger.complete_item(
            self.user_id,
            self.item.id,
            status=JOB_STATUS_FAILED if failed else JOB_STATUS_REVIEWED,
            page_count=self.plan.page_count,
            character_count=len(markdown),
            markdown_key=self.markdown_key,
            report=report,
            error_code=error_code,
        )
        await self.ledger.refresh_job(self.user_id, self.job.id)
        # The whole Markdown now holds every read page, so the per-page copies
        # are only cleanup. A failed delete must not change the item's state.
        for row in rows:
            if row.markdown_key:
                try:
                    await _bucket_call(self.bucket, "delete", row.markdown_key)
                except Exception:  # noqa: BLE001, S110 - cleanup never changes the item state
                    pass
        return {
            "status": JOB_STATUS_FAILED if failed else JOB_STATUS_REVIEWED,
            "error_code": error_code,
            "page_count": self.plan.page_count,
            "scan_page_count": len(self.scan_pages),
            "read_pages": sum(1 for row in rows if row.read),
            "failed_pages": sum(
                1 for row in rows if row.status == PAGE_STATUS_FAILED
            ),
            "pages": [row.public_dict() for row in rows],
        }

    async def read_one(self, page: ScanPage, row: ScanPageRecord) -> ScanPageRecord:
        image_key = scan_page_image_key(
            self.user_id, self.job.id, self.item.id, page.number
        )
        image = page.image_jpeg or b""
        await _bucket_call(
            self.bucket,
            "put",
            image_key,
            image,
            httpMetadata={"contentType": "image/jpeg"},
        )
        result: PageReadResult | None = None
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self.reader.read_page, image),
                timeout=SCAN_PAGE_HARD_STOP_SECONDS,
            )
        except TimeoutError:
            result = None
        finally:
            # The image exists only for this page's read. Its removal is not
            # allowed to turn a successful read into a failed one.
            try:
                await _bucket_call(self.bucket, "delete", image_key)
            except Exception:  # noqa: BLE001, S110 - cleanup never changes the item state
                pass
        if result is None:
            return await self.ledger.complete_scan_page(
                self.user_id,
                self.item.id,
                page.number,
                status=PAGE_STATUS_FAILED,
                attempts=row.attempts + 1,
                error_code=ERROR_PAGE_TIMEOUT,
            )
        status = _read_status(result)
        markdown = result.markdown or ""
        if status != PAGE_STATUS_FAILED and not markdown.strip():
            status = PAGE_STATUS_FAILED
            error_code = ERROR_EMPTY_MARKDOWN
        else:
            error_code = result.error_code
        fragment_key = None
        if status != PAGE_STATUS_FAILED:
            fragment_key = scan_page_markdown_key(
                self.user_id, self.job.id, self.item.id, page.number
            )
            await _bucket_call(
                self.bucket,
                "put",
                fragment_key,
                markdown.encode("utf-8"),
                httpMetadata={"contentType": "text/markdown"},
            )
            self.replacements[page.number] = markdown
        return await self.ledger.complete_scan_page(
            self.user_id,
            self.item.id,
            page.number,
            status=status,
            attempts=result.attempts,
            prompt_tokens=result.prompt_tokens,
            reasoning_tokens=result.reasoning_tokens,
            completion_tokens=result.completion_tokens,
            seconds=result.seconds,
            error_code=error_code,
            markdown_key=fragment_key,
        )

    async def run(self) -> dict[str, Any]:
        await self.prepare()
        # A resume can already be over the line: more than half failed before
        # this process started, so reading the rest would only spend more.
        if self.over_threshold():
            return await self.finish(failed=True, error_code=ERROR_FAILURE_THRESHOLD)
        remaining = [
            page
            for page in self.scan_pages
            if not self.rows[page.number].read
            and self.rows[page.number].status != PAGE_STATUS_FAILED
        ]
        used = await self.ledger.count_scan_pages_since(
            self.user_id, _utc_day_start(self.now())
        )
        if remaining and used + len(remaining) > self.daily_limit:
            return await self.finish(failed=True, error_code=ERROR_DAILY_LIMIT)
        for page in self.scan_pages:
            row = self.rows[page.number]
            if row.read or row.status == PAGE_STATUS_FAILED:
                continue
            claimed = await self.ledger.claim_scan_page(
                self.user_id, self.item.id, page.number
            )
            if claimed is None:
                # Another claimant already owns this page; leave it and its
                # document to that run rather than reading it twice.
                continue
            updated = await self.read_one(page, claimed)
            if updated is not None:
                self.rows[page.number] = updated
            await self.store_draft()
            if self.over_threshold():
                return await self.finish(
                    failed=True, error_code=ERROR_FAILURE_THRESHOLD
                )
        return await self.finish(failed=False, error_code=None)


_SCAN_DOCUMENT_LOCK = asyncio.Lock()


async def run_scan_pages(
    *,
    ledger: Any,
    bucket: Any,
    user_id: str,
    item: Any,
    job: Any,
    plan: Any,
    reader: Any,
    base_markdown: str,
    daily_limit: int | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Read this document's scan pages sequentially and finalize the item.

    The lock is module-wide on purpose: one page at a time across every scan
    document the process serves. A per-document lock would still let two
    documents double the page spend.
    """

    if not plan.scan_pages:
        return await _ScanRun(
            ledger=ledger,
            bucket=bucket,
            user_id=user_id,
            item=item,
            job=job,
            plan=plan,
            reader=reader,
            base_markdown=base_markdown,
            daily_limit=daily_limit or scan_daily_page_limit(),
            now=now or (lambda: datetime.now(UTC)),
        ).finish(failed=False, error_code=None)
    async with _SCAN_DOCUMENT_LOCK:
        return await _ScanRun(
            ledger=ledger,
            bucket=bucket,
            user_id=user_id,
            item=item,
            job=job,
            plan=plan,
            reader=reader,
            base_markdown=base_markdown,
            daily_limit=daily_limit or scan_daily_page_limit(),
            now=now or (lambda: datetime.now(UTC)),
        ).run()


__all__ = [
    "DEFAULT_SCAN_DAILY_PAGES",
    "ERROR_DAILY_LIMIT",
    "ERROR_FAILURE_THRESHOLD",
    "SCAN_DAILY_PAGES_ENV",
    "SCAN_PAGE_TIMEOUT_SECONDS",
    "assemble_markdown",
    "run_scan_pages",
    "scan_daily_page_limit",
    "scan_page_ceiling",
]
