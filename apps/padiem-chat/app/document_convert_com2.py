"""#5568 — the COM2 authoritative execution and storage for PDF→Markdown.

The representative decision moved the execution and data authority for the
PDF→Markdown service to COM2; Cloudflare keeps the security gate, external
ingress and the preserved D1/R2 backup. The #5710 pause on new uploads stays
until this authority is verified end to end.

This module is the COM2-side authority built from the reviewed existing
parts, deliberately mirroring the Cloudflare contracts:

- ``Com2SqliteLedger`` — the same async method surface and owner-scoped SQL
  semantics as ``D1DocumentConvertStore``, on a local sqlite file using the
  shipped migration 066 schema unchanged.
- ``Com2ObjectStore`` — local files under a root directory, keyed exactly
  like the R2 objects (``documents/{user_id}/convert/{job}/{item}.pdf|.md``),
  so the stored keys in the ledger stay meaningful on either side.
- :func:`run_item_conversion` — one original → Core's reviewed
  ``convert_pdf_to_markdown`` (the same pypdf boundary the Worker uses) →
  markdown saved → ledger completed, with the failure path recorded as
  ``failed`` + ``error_code`` rather than swallowed.

No new server, storage engine or task framework is introduced: the ledger is
the same schema, the files are the same keys, the converter is the same Core
function.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from padiem_ai_core.pdf_markdown import convert_pdf_to_markdown

from .document_convert_store import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_WORKING,
    MAX_REPORT_JSON_CHARS,
    ConvertItemRecord,
    ConvertJobRecord,
    _DOCUMENT_STATUSES,
    _item_from_row,
    _item_id,
    _job_from_row,
    _job_id,
    _now_iso,
    markdown_object_key,
    original_object_key,
)

_MIGRATION = Path(__file__).resolve().parent.parent.joinpath("migrations").joinpath("066_document_convert_jobs.sql")


class QueuedClaim:
    """A claimed item plus its owner id (ConvertItemRecord has no user_id)."""

    __slots__ = ("item", "user_id")

    def __init__(self, item: ConvertItemRecord, user_id: str) -> None:
        self.item = item
        self.user_id = user_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Com2SqliteLedger:
    """The document conversion ledger on a local sqlite file.

    Same method surface and owner-scoped SQL semantics as
    ``D1DocumentConvertStore``; the schema is the shipped migration 066, so a
    D1 export can be replayed here without reshaping.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._write_lock = asyncio.Lock()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_MIGRATION.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _exec_sync(self, sql: str, values: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            conn.execute(sql, values)
            conn.commit()

    def _query_sync(self, sql: str, values: tuple[Any, ...]) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, values).fetchall()

    async def _run(self, sql: str, *values: Any) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._exec_sync, sql, values)

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        rows = await asyncio.to_thread(self._query_sync, sql, values)
        return dict(rows[0]) if rows else None

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(self._query_sync, sql, values)
        return [dict(row) for row in rows]

    async def create_job(self, user_id: str, *, mode: str) -> ConvertJobRecord:
        now = _now_iso()
        record_id = _job_id()
        await self._run(
            "INSERT INTO document_convert_jobs "
            "(id, user_id, mode, status, item_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            record_id,
            user_id,
            mode,
            JOB_STATUS_QUEUED,
            now,
            now,
        )
        return ConvertJobRecord(
            id=record_id,
            mode=mode,
            status=JOB_STATUS_QUEUED,
            item_count=0,
            created_at=now,
            updated_at=now,
        )

    async def add_item(
        self,
        user_id: str,
        job_id: str,
        *,
        name: str,
        page_count: int = 0,
        probe: dict[str, Any] | None = None,
    ) -> ConvertItemRecord:
        now = _now_iso()
        record_id = _item_id()
        key = original_object_key(user_id, job_id, record_id)
        await self._run(
            "INSERT INTO document_convert_items "
            "(id, job_id, user_id, name, status, page_count, character_count, "
            "original_key, markdown_key, report_json, error_code, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, NULL, ?, NULL, ?, ?)",
            record_id,
            job_id,
            user_id,
            name[:120],
            JOB_STATUS_QUEUED,
            max(page_count, 0),
            key,
            None if probe is None else json.dumps(probe, ensure_ascii=False)[:MAX_REPORT_JSON_CHARS],
            now,
            now,
        )
        await self._run(
            "UPDATE document_convert_jobs SET item_count = item_count + 1, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            now,
            job_id,
            user_id,
        )
        return ConvertItemRecord(
            id=record_id,
            job_id=job_id,
            name=name[:120],
            status=JOB_STATUS_QUEUED,
            page_count=max(page_count, 0),
            character_count=0,
            original_key=key,
            markdown_key=None,
            report=probe,
            error_code=None,
            created_at=now,
            updated_at=now,
        )

    async def get_job(self, user_id: str, job_id: str) -> ConvertJobRecord | None:
        row = await self._first(
            "SELECT id, mode, status, item_count, created_at, updated_at "
            "FROM document_convert_jobs WHERE id = ? AND user_id = ?",
            job_id,
            user_id,
        )
        return _job_from_row(row) if row is not None else None

    async def list_jobs(self, user_id: str, *, limit: int) -> list[ConvertJobRecord]:
        rows = await self._all(
            "SELECT id, mode, status, item_count, created_at, updated_at "
            "FROM document_convert_jobs WHERE user_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            user_id,
            limit,
        )
        return [_job_from_row(row) for row in rows]

    async def get_item(self, user_id: str, item_id: str) -> ConvertItemRecord | None:
        row = await self._first(
            "SELECT id, job_id, user_id, name, status, page_count, character_count, "
            "original_key, markdown_key, report_json, error_code, created_at, updated_at "
            "FROM document_convert_items WHERE id = ? AND user_id = ?",
            item_id,
            user_id,
        )
        return _item_from_row(row) if row is not None else None

    async def list_items(self, user_id: str, job_id: str) -> list[ConvertItemRecord]:
        rows = await self._all(
            "SELECT id, job_id, user_id, name, status, page_count, character_count, "
            "original_key, markdown_key, report_json, error_code, created_at, updated_at "
            "FROM document_convert_items WHERE job_id = ? AND user_id = ? ORDER BY rowid",
            job_id,
            user_id,
        )
        return [_item_from_row(row) for row in rows]

    async def set_item_status(
        self, user_id: str, item_id: str, status: str
    ) -> ConvertItemRecord | None:
        if status not in _DOCUMENT_STATUSES:
            raise ValueError("변환 상태 값이 올바르지 않습니다.")
        await self._run(
            "UPDATE document_convert_items SET status = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            status,
            _now_iso(),
            item_id,
            user_id,
        )
        return await self.get_item(user_id, item_id)

    async def complete_item(
        self,
        user_id: str,
        item_id: str,
        *,
        status: str,
        page_count: int,
        character_count: int,
        markdown_key: str | None,
        report: dict[str, Any] | None,
        error_code: str | None,
    ) -> ConvertItemRecord | None:
        if status not in _DOCUMENT_STATUSES:
            raise ValueError("변환 상태 값이 올바르지 않습니다.")
        encoded = None if report is None else json.dumps(report, ensure_ascii=False)[:MAX_REPORT_JSON_CHARS]
        await self._run(
            "UPDATE document_convert_items SET status = ?, page_count = ?, "
            "character_count = ?, markdown_key = ?, report_json = ?, error_code = ?, "
            "updated_at = ? WHERE id = ? AND user_id = ?",
            status,
            max(page_count, 0),
            max(character_count, 0),
            markdown_key,
            encoded,
            error_code,
            _now_iso(),
            item_id,
            user_id,
        )
        return await self.get_item(user_id, item_id)

    async def delete_item(self, user_id: str, item_id: str) -> bool:
        before = await self.get_item(user_id, item_id)
        if before is None:
            return False
        await self._run(
            "DELETE FROM document_convert_items WHERE id = ? AND user_id = ?",
            item_id,
            user_id,
        )
        await self._run(
            "UPDATE document_convert_jobs SET item_count = "
            "MAX(item_count - 1, 0), updated_at = ? WHERE id = ? AND user_id = ?",
            _now_iso(),
            before.job_id,
            user_id,
        )
        return True

    async def claim_next_queued_item(self) -> ConvertItemRecord | None:
        """Atomically move the oldest queued item to ``working`` and return it.

        #5568 U2: the worker loop must never process the same item twice. The
        claim is one ``BEGIN IMMEDIATE`` transaction — the queued→working flip
        is conditioned on the status staying ``queued``, so a second worker
        (or a restarted loop racing a live one) cannot claim the same row.
        Returns ``None`` when the queue is empty.
        """

        def _claim_sync() -> dict[str, Any] | None:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT id, job_id, user_id, name, status, page_count, character_count, "
                    "original_key, markdown_key, report_json, error_code, created_at, updated_at "
                    "FROM document_convert_items WHERE status = ? "
                    "ORDER BY created_at, rowid LIMIT 1",
                    (JOB_STATUS_QUEUED,),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None
                now = _now_iso()
                conn.execute(
                    "UPDATE document_convert_items SET status = ?, updated_at = ? "
                    "WHERE id = ? AND status = ?",
                    (JOB_STATUS_WORKING, now, row["id"], JOB_STATUS_QUEUED),
                )
                conn.commit()
                return dict(row)
            finally:
                conn.close()

        row = await asyncio.to_thread(_claim_sync)
        return QueuedClaim(_item_from_row(row), row["user_id"]) if row is not None else None

    async def working_items(self) -> list[ConvertItemRecord]:
        """Items a previous worker left in ``working`` (crash recovery input)."""
        rows = await self._all(
            "SELECT id, job_id, user_id, name, status, page_count, character_count, "
            "original_key, markdown_key, report_json, error_code, created_at, updated_at "
            "FROM document_convert_items WHERE status = ? ORDER BY updated_at",
            JOB_STATUS_WORKING,
        )
        return [QueuedClaim(_item_from_row(row), row["user_id"]) for row in rows]

    async def refresh_job(self, user_id: str, job_id: str) -> ConvertJobRecord | None:
        """Roll the item states up into the job state the owner sees."""
        items = await self.list_items(user_id, job_id)
        if not items:
            status = JOB_STATUS_QUEUED
        elif any(item.status == JOB_STATUS_FAILED for item in items) and not any(
            item.status == JOB_STATUS_DONE for item in items
        ):
            status = JOB_STATUS_FAILED
        elif all(item.status == JOB_STATUS_DONE for item in items):
            status = JOB_STATUS_DONE
        elif any(item.status == JOB_STATUS_WORKING for item in items):
            status = JOB_STATUS_WORKING
        else:
            status = JOB_STATUS_QUEUED
        await self._run(
            "UPDATE document_convert_jobs SET status = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            status,
            _now_iso(),
            job_id,
            user_id,
        )
        return await self.get_job(user_id, job_id)


class Com2ObjectStore:
    """Local files keyed exactly like the R2 conversion objects."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = Path(key)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError("invalid object key")
        return self._root / safe

    def put(self, key: str, payload: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return path.read_bytes()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        return True


class Com2ConversionEngine:
    """The Core's reviewed pypdf boundary, run natively on COM2."""

    def convert(self, *, name: str, payload: bytes, mode: str = "fast") -> dict[str, Any]:
        """The Core conversion, returning the markdown BODY plus the report.

        ``public_dict()`` is the bounded report-only projection (it omits the
        markdown body on purpose), so the body comes from the dataclass field
        directly and the report goes through that projection.
        """
        result = convert_pdf_to_markdown(
            name=name,
            media_type="application/pdf",
            payload=payload,
            mode=mode,
        )
        return {
            "markdown": result.markdown,
            "page_count": result.page_count,
            "agreement": [item.public_dict() for item in result.agreement],
            "warnings": list(result.warnings),
        }


async def run_item_conversion(
    *,
    ledger: Com2SqliteLedger,
    objects: Com2ObjectStore,
    engine: Com2ConversionEngine,
    user_id: str,
    job_id: str,
    item_id: str,
    mode: str = "fast",
) -> ConvertItemRecord | None:
    """One item's full authority path: original → Core conversion → markdown.

    The ledger records the outcome either way: ``done`` with the markdown key
    and the bounded report, or ``failed`` with the error code — never a
    silently missing conversion.
    """
    item = await ledger.get_item(user_id, item_id)
    if item is None:
        return None
    await ledger.set_item_status(user_id, item_id, JOB_STATUS_WORKING)
    original = await asyncio.to_thread(objects.get, item.original_key)
    if original is None:
        record = await ledger.complete_item(
            user_id,
            item_id,
            status=JOB_STATUS_FAILED,
            page_count=0,
            character_count=0,
            markdown_key=None,
            report=None,
            error_code="original_object_missing",
        )
        await ledger.refresh_job(user_id, job_id)
        return record
    try:
        result = await asyncio.to_thread(
            engine.convert, name=item.name, payload=original, mode=mode
        )
    except Exception:
        record = await ledger.complete_item(
            user_id,
            item_id,
            status=JOB_STATUS_FAILED,
            page_count=0,
            character_count=0,
            markdown_key=None,
            report=None,
            error_code="conversion_failed",
        )
        await ledger.refresh_job(user_id, job_id)
        return record
    markdown_key = markdown_object_key(user_id, job_id, item_id)
    objects.put(markdown_key, result.get("markdown", "").encode("utf-8"))
    report: dict[str, Any] | None = None
    if result.get("agreement"):
        report = {"agreement": [result["agreement"][0]] if isinstance(result["agreement"], list) else result["agreement"]}
    record = await ledger.complete_item(
        user_id,
        item_id,
        status=JOB_STATUS_DONE,
        page_count=result.get("page_count", 0),
        character_count=len(result.get("markdown", "")),
        markdown_key=markdown_key,
        report=report,
        error_code=None,
    )
    await ledger.refresh_job(user_id, job_id)
    return record
