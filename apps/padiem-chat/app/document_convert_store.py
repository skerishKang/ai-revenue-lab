"""Owner-scoped work ledger for the PDF to Markdown utility (#5568).

D1 stores names, bounded status and the bounded verification report only. The
original PDF and the converted Markdown live as R2 objects under the signed-in
owner's own key prefix, so a record never carries document content and a read
cannot address another owner's bytes.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_WORKING = "working"
JOB_STATUS_REVIEWED = "reviewed"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"
#: The owner's UX vocabulary: 준비중 -> 변환중 -> 검토중 -> 완료, plus failure.
DOCUMENT_STATUS_SEQUENCE = (
    JOB_STATUS_QUEUED,
    JOB_STATUS_WORKING,
    JOB_STATUS_REVIEWED,
    JOB_STATUS_DONE,
)
_DOCUMENT_STATUSES = frozenset((*DOCUMENT_STATUS_SEQUENCE, JOB_STATUS_FAILED))

MAX_DOCUMENT_JOBS_PAGE = 50
MAX_REPORT_JSON_CHARS = 12_000


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _job_id() -> str:
    return "dcj_" + uuid.uuid4().hex


def _item_id() -> str:
    return "dci_" + uuid.uuid4().hex


def _validate_id(value: object, prefix: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{prefix} 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) != len(prefix) + 32 or not text.startswith(prefix):
        raise ValueError(f"{prefix} 형식이 올바르지 않습니다.")
    if any(ch not in "0123456789abcdef" for ch in text[len(prefix):]):
        raise ValueError(f"{prefix} 형식이 올바르지 않습니다.")
    return text


def validate_job_id(value: object) -> str | None:
    return _validate_id(value, "dcj_")


def validate_item_id(value: object) -> str | None:
    return _validate_id(value, "dci_")


def original_object_key(user_id: str, job_id: str, item_id: str) -> str:
    # Every component comes from a verified session or a validated opaque id.
    return f"documents/{user_id}/convert/{job_id}/{item_id}.pdf"


def markdown_object_key(user_id: str, job_id: str, item_id: str) -> str:
    return f"documents/{user_id}/convert/{job_id}/{item_id}.md"


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _rows_from_result(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    rows = getattr(result, "results", None)
    if rows is None and isinstance(result, dict):
        rows = result.get("results")
    if rows is None:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        converted = _row_to_dict(row)
        if converted is not None:
            out.append(converted)
    return out


@dataclass(frozen=True, slots=True)
class ConvertItemRecord:
    id: str
    job_id: str
    name: str
    status: str
    page_count: int
    character_count: int
    original_key: str
    markdown_key: str | None
    report: dict[str, Any] | None
    error_code: str | None
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "name": self.name,
            "status": self.status,
            "page_count": self.page_count,
            "character_count": self.character_count,
            "has_markdown": self.markdown_key is not None,
            "has_original": True,
            "report": self.report,
            "error_code": self.error_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class ConvertJobRecord:
    id: str
    mode: str
    status: str
    item_count: int
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "status": self.status,
            "item_count": self.item_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _item_from_row(row: dict[str, Any]) -> ConvertItemRecord:
    raw_report = row.get("report_json")
    report: dict[str, Any] | None = None
    if isinstance(raw_report, str) and raw_report:
        try:
            decoded = json.loads(raw_report)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            report = decoded
    return ConvertItemRecord(
        id=str(row.get("id", "")),
        job_id=str(row.get("job_id", "")),
        name=str(row.get("name", "")),
        status=str(row.get("status", JOB_STATUS_QUEUED)),
        page_count=int(row.get("page_count") or 0),
        character_count=int(row.get("character_count") or 0),
        original_key=str(row.get("original_key", "")),
        markdown_key=row.get("markdown_key") or None,
        report=report,
        error_code=row.get("error_code") or None,
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


def _job_from_row(row: dict[str, Any]) -> ConvertJobRecord:
    return ConvertJobRecord(
        id=str(row.get("id", "")),
        mode=str(row.get("mode", "fast")),
        status=str(row.get("status", JOB_STATUS_QUEUED)),
        item_count=int(row.get("item_count") or 0),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


class D1DocumentConvertStore:
    """D1-backed ledger. Every statement selects on the verified owner id."""

    def __init__(self, db: Any) -> None:
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        result = await statement.all()
        return _rows_from_result(result)

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

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
        """Register one uploaded document under its own original key.

        The key is derived here rather than handed in, because it needs the id
        this method mints. A caller that passed a placeholder key first would
        leave a row pointing at an object that never exists if the upload or the
        key update failed in between.
        """

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
        elif any(item.status == JOB_STATUS_REVIEWED for item in items):
            status = JOB_STATUS_REVIEWED
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
