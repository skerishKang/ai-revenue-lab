from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

MAX_SAVED_OUTPUTS = 200
MAX_OUTPUT_LIST = 100
MAX_OUTPUT_TITLE_CHARS = 100
MAX_OUTPUT_CONTENT_CHARS = 32_000


class SavedOutputError(RuntimeError):
    pass


class SavedOutputLimitError(SavedOutputError):
    pass


@dataclass(frozen=True, slots=True)
class SavedOutputRecord:
    id: str
    title: str
    content_text: str = field(repr=False)
    conversation_id: str | None = None
    project_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def summary_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def detail_dict(self) -> dict[str, Any]:
        return {**self.summary_dict(), "content": self.content_text}


class SavedOutputStore(Protocol):
    async def list_outputs(self, user_id: str, limit: int = MAX_OUTPUT_LIST) -> list[SavedOutputRecord]: ...
    async def get_output(self, user_id: str, output_id: str) -> SavedOutputRecord | None: ...
    async def create_output(
        self,
        user_id: str,
        title: str,
        content: str,
        conversation_id: str | None = None,
        project_id: str | None = None,
    ) -> SavedOutputRecord: ...
    async def update_output_title(self, user_id: str, output_id: str, title: str) -> SavedOutputRecord | None: ...
    async def delete_output(self, user_id: str, output_id: str) -> bool: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _output_id() -> str:
    return "out_" + uuid.uuid4().hex


def validate_output_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("output_id 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) != 36 or not text.startswith("out_"):
        raise ValueError("output_id 형식이 올바르지 않습니다.")
    if any(ch not in "0123456789abcdef" for ch in text[4:]):
        raise ValueError("output_id 형식이 올바르지 않습니다.")
    return text


def validate_output_title(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("저장한 답변 제목 형식이 올바르지 않습니다.")
    title = " ".join(value.split())
    if not 1 <= len(title) <= MAX_OUTPUT_TITLE_CHARS:
        raise ValueError("저장한 답변 제목은 1자 이상 100자 이하로 입력해 주세요.")
    return title


def validate_output_content(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("저장할 답변 형식이 올바르지 않습니다.")
    content = value.strip()
    if not 1 <= len(content) <= MAX_OUTPUT_CONTENT_CHARS:
        raise ValueError("저장할 답변은 1자 이상 32,000자 이하만 지원합니다.")
    if "\x00" in content:
        raise ValueError("저장할 답변에 지원하지 않는 문자가 있습니다.")
    return content


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


def _from_row(row: dict[str, Any]) -> SavedOutputRecord:
    return SavedOutputRecord(
        id=str(row.get("id", "")),
        title=str(row.get("title", "")),
        content_text=str(row.get("content_text", "")),
        conversation_id=str(row.get("conversation_id")) if row.get("conversation_id") is not None else None,
        project_id=str(row.get("project_id")) if row.get("project_id") is not None else None,
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


class D1SavedOutputStore:
    """Owner-scoped D1 Saved Outputs store. Dynamic values always use binds."""

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

    async def list_outputs(self, user_id: str, limit: int = MAX_OUTPUT_LIST) -> list[SavedOutputRecord]:
        bounded = max(1, min(int(limit), MAX_OUTPUT_LIST))
        rows = await self._all(
            "SELECT id, title, '' AS content_text, conversation_id, project_id, created_at, updated_at "
            "FROM saved_outputs WHERE user_id=? ORDER BY updated_at DESC, id DESC LIMIT ?",
            user_id, bounded,
        )
        return [_from_row(row) for row in rows]

    async def get_output(self, user_id: str, output_id: str) -> SavedOutputRecord | None:
        row = await self._first(
            "SELECT id, title, content_text, conversation_id, project_id, created_at, updated_at "
            "FROM saved_outputs WHERE id=? AND user_id=?",
            output_id, user_id,
        )
        return _from_row(row) if row else None

    async def create_output(
        self,
        user_id: str,
        title: str,
        content: str,
        conversation_id: str | None = None,
        project_id: str | None = None,
    ) -> SavedOutputRecord:
        clean_title = validate_output_title(title)
        clean_content = validate_output_content(content)
        aggregate = await self._first(
            "SELECT COUNT(*) AS output_count FROM saved_outputs WHERE user_id=?",
            user_id,
        ) or {}
        if int(aggregate.get("output_count") or 0) >= MAX_SAVED_OUTPUTS:
            raise SavedOutputLimitError("저장한 답변은 최대 200개까지 보관할 수 있습니다.")
        oid = _output_id()
        now = _now_iso()
        await self._run(
            "INSERT INTO saved_outputs (id, user_id, conversation_id, project_id, title, content_text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            oid, user_id, conversation_id, project_id, clean_title, clean_content, now, now,
        )
        return SavedOutputRecord(
            id=oid,
            title=clean_title,
            content_text=clean_content,
            conversation_id=conversation_id,
            project_id=project_id,
            created_at=now,
            updated_at=now,
        )

    async def update_output_title(self, user_id: str, output_id: str, title: str) -> SavedOutputRecord | None:
        current = await self.get_output(user_id, output_id)
        if current is None:
            return None
        clean_title = validate_output_title(title)
        now = _now_iso()
        await self._run(
            "UPDATE saved_outputs SET title=?, updated_at=? WHERE id=? AND user_id=?",
            clean_title, now, output_id, user_id,
        )
        return SavedOutputRecord(
            id=current.id,
            title=clean_title,
            content_text=current.content_text,
            conversation_id=current.conversation_id,
            project_id=current.project_id,
            created_at=current.created_at,
            updated_at=now,
        )

    async def delete_output(self, user_id: str, output_id: str) -> bool:
        existing = await self.get_output(user_id, output_id)
        if existing is None:
            return False
        await self._run("DELETE FROM saved_outputs WHERE id=? AND user_id=?", output_id, user_id)
        return True
