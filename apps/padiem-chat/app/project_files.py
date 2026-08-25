from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .documents import MAX_DOCUMENT_CHARS, validate_document_fields

MAX_PROJECT_FILES = 12
MAX_PROJECT_TOTAL_CHARS = 160_000


class ProjectFileError(RuntimeError):
    pass


class ProjectFileLimitError(ProjectFileError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectFileRecord:
    id: str
    project_id: str
    name: str
    media_type: str
    content_text: str = field(repr=False)
    content_chars: int = 0
    created_at: str = ""
    updated_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "media_type": self.media_type,
            "content_chars": self.content_chars,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ProjectFileStore(Protocol):
    async def list_files(self, user_id: str, project_id: str) -> list[ProjectFileRecord]: ...
    async def get_file(self, user_id: str, project_id: str, file_id: str) -> ProjectFileRecord | None: ...
    async def create_file(self, user_id: str, project_id: str, name: str, media_type: str, text: str) -> ProjectFileRecord: ...
    async def delete_file(self, user_id: str, project_id: str, file_id: str) -> bool: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_id() -> str:
    return "file_" + uuid.uuid4().hex


def validate_file_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("file_id 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) != 37 or not text.startswith("file_"):
        raise ValueError("file_id 형식이 올바르지 않습니다.")
    if any(ch not in "0123456789abcdef" for ch in text[5:]):
        raise ValueError("file_id 형식이 올바르지 않습니다.")
    return text


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


def _from_row(row: dict[str, Any]) -> ProjectFileRecord:
    text = str(row.get("content_text", ""))
    return ProjectFileRecord(
        id=str(row.get("id", "")),
        project_id=str(row.get("project_id", "")),
        name=str(row.get("name", "")),
        media_type=str(row.get("media_type", "")),
        content_text=text,
        content_chars=int(row.get("content_chars") or len(text)),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


class D1ProjectFileStore:
    """D1-backed bounded text-file store. Dynamic values always use binds."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _rows_from_result(await statement.run())

    async def list_files(self, user_id: str, project_id: str) -> list[ProjectFileRecord]:
        rows = await self._all(
            "SELECT id, project_id, name, media_type, content_text, content_chars, created_at, updated_at "
            "FROM project_files WHERE user_id=? AND project_id=? ORDER BY created_at ASC, id ASC LIMIT ?",
            user_id, project_id, MAX_PROJECT_FILES,
        )
        return [_from_row(row) for row in rows]

    async def get_file(self, user_id: str, project_id: str, file_id: str) -> ProjectFileRecord | None:
        row = await self._first(
            "SELECT id, project_id, name, media_type, content_text, content_chars, created_at, updated_at "
            "FROM project_files WHERE id=? AND user_id=? AND project_id=?",
            file_id, user_id, project_id,
        )
        return _from_row(row) if row else None

    async def create_file(self, user_id: str, project_id: str, name: str, media_type: str, text: str) -> ProjectFileRecord:
        document = validate_document_fields(name, media_type, text)
        if len(document.text) > MAX_DOCUMENT_CHARS:
            raise ProjectFileLimitError("문서가 너무 큽니다.")
        aggregate = await self._first(
            "SELECT COUNT(*) AS file_count, COALESCE(SUM(content_chars), 0) AS total_chars "
            "FROM project_files WHERE user_id=? AND project_id=?",
            user_id, project_id,
        ) or {}
        count = int(aggregate.get("file_count") or 0)
        total = int(aggregate.get("total_chars") or 0)
        if count >= MAX_PROJECT_FILES:
            raise ProjectFileLimitError("프로젝트에는 문서를 최대 12개까지 저장할 수 있습니다.")
        if total + len(document.text) > MAX_PROJECT_TOTAL_CHARS:
            raise ProjectFileLimitError("프로젝트 문서 내용은 합계 160,000자 이하로 저장할 수 있습니다.")
        fid = _file_id()
        now = _now_iso()
        await self._run(
            "INSERT INTO project_files (id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            fid, project_id, user_id, document.name, document.media_type, document.text, len(document.text), now, now,
        )
        return ProjectFileRecord(
            id=fid, project_id=project_id, name=document.name, media_type=document.media_type,
            content_text=document.text, content_chars=len(document.text), created_at=now, updated_at=now,
        )

    async def delete_file(self, user_id: str, project_id: str, file_id: str) -> bool:
        existing = await self.get_file(user_id, project_id, file_id)
        if existing is None:
            return False
        await self._run(
            "DELETE FROM project_files WHERE id=? AND user_id=? AND project_id=?",
            file_id, user_id, project_id,
        )
        return True
