from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .documents import MAX_DOCUMENT_CHARS, validate_document_fields

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
BINARY_PROJECT_FILE_MEDIA = frozenset({PDF_MEDIA_TYPE, DOCX_MEDIA_TYPE})


def _extracted_media_type(original_media_type: str) -> str:
    # Canonicalize extracted media types: DOCX → extracted/docx, PDF → extracted/pdf
    ext = original_media_type.split("/")[-1]
    if ext.startswith("vnd.openxmlformats-officedocument.wordprocessingml.document"):
        return "extracted/docx"
    return "extracted/" + ext

MAX_PROJECT_FILES = 12
MAX_PROJECT_TOTAL_CHARS = 160_000

#: #4489 — the Library browses every file an owner stored, one bounded keyset page at a
#: time. These are HTTP page bounds, not a record cap: no page may grow a response.
DEFAULT_OWNER_FILES_PAGE = 50
MAX_OWNER_FILES_PAGE = 100
_OWNER_FILE_CURSOR_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class ProjectFileError(RuntimeError):
    pass


class ProjectFileFormatError(ProjectFileError):
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


@dataclass(frozen=True, slots=True)
class OwnerFileProjection:
    """One stored file plus its project label. It never carries file content."""

    id: str
    project_id: str
    project_name: str
    name: str
    media_type: str
    content_chars: int
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "name": self.name,
            "media_type": self.media_type,
            "content_chars": self.content_chars,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class OwnerFileCursorError(ValueError):
    """Raised for any cursor a caller invented, truncated or replayed across scopes."""


def encode_owner_file_cursor(record: OwnerFileProjection) -> str:
    """Keyset position ``(updated_at, id)`` as an opaque token.

    Deliberately not a caller-composable scope: it carries no user id, no project id
    list and no limit, so it can never widen whose files a page returns.
    """
    raw = f"{record.updated_at}|{record.id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_owner_file_cursor(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or not value.strip():
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) > 256:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.")
    try:
        raw = base64.urlsafe_b64decode((text + "=" * (-len(text) % 4)).encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.") from exc
    updated_at, separator, file_id = raw.partition("|")
    if not separator or _OWNER_FILE_CURSOR_TIME_RE.fullmatch(updated_at) is None:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.")
    try:
        validated = validate_file_id(file_id)
    except ValueError as exc:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.") from exc
    if validated is None:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.")
    return updated_at, validated


def _owner_projection_from_row(row: dict[str, Any]) -> OwnerFileProjection:
    return OwnerFileProjection(
        id=str(row.get("id", "")),
        project_id=str(row.get("project_id", "")),
        project_name=str(row.get("project_name") or ""),
        name=str(row.get("name", "")),
        media_type=str(row.get("media_type", "")),
        content_chars=int(row.get("content_chars") or 0),
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

    async def list_owner_files(
        self, user_id: str, *, after: tuple[str, str] | None = None, limit: int
    ) -> list[OwnerFileProjection]:
        """One keyset page over every file this owner stored, newest update first.

        The position is ``(updated_at, id)``, so a page can neither repeat nor skip a
        row when writes land between requests. Files are selected by ``f.user_id`` only;
        the project label joins on the same owner, which keeps another account's project
        name out of the result and still lists a file whose project row is missing.
        Content is never selected.
        """
        head = (
            "SELECT f.id AS id, f.project_id AS project_id, f.name AS name, "
            "f.media_type AS media_type, f.content_chars AS content_chars, "
            "f.created_at AS created_at, f.updated_at AS updated_at, "
            "COALESCE(p.name, '') AS project_name "
            "FROM project_files AS f "
            "LEFT JOIN projects AS p ON p.id = f.project_id AND p.user_id = f.user_id "
        )
        tail = " ORDER BY f.updated_at DESC, f.id DESC LIMIT ?"
        if after is None:
            rows = await self._all(head + "WHERE f.user_id = ?" + tail, user_id, limit)
            return [_owner_projection_from_row(row) for row in rows]
        after_updated_at, after_id = after
        rows = await self._all(
            head
            + "WHERE f.user_id = ? AND (f.updated_at < ? OR (f.updated_at = ? AND f.id < ?))"
            + tail,
            user_id,
            after_updated_at,
            after_updated_at,
            after_id,
            limit,
        )
        return [_owner_projection_from_row(row) for row in rows]

    async def get_file(self, user_id: str, project_id: str, file_id: str) -> ProjectFileRecord | None:
        row = await self._first(
            "SELECT id, project_id, name, media_type, content_text, content_chars, created_at, updated_at "
            "FROM project_files WHERE id=? AND user_id=? AND project_id=?",
            file_id, user_id, project_id,
        )
        return _from_row(row) if row else None

    async def create_file(
        self,
        user_id: str,
        project_id: str,
        name: str,
        media_type: str,
        text: str,
        *,
        source_media_type: str | None = None,
    ) -> ProjectFileRecord:
        if source_media_type is not None and source_media_type != media_type:
            raise ProjectFileFormatError("source_media_type must match media_type")
        if media_type.startswith("extracted/"):
            document = type("Doc", (), {"name": name, "media_type": media_type, "text": text})()
        else:
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
