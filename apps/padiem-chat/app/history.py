from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

MAX_HISTORY_MESSAGE_CHARS = 8000
MAX_HISTORY_TITLE_CHARS = 80
MAX_RECENT_CONVERSATIONS = 30


class HistoryError(RuntimeError):
    pass


class HistoryForbidden(HistoryError):
    pass


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: str
    email: str
    display_name: str
    picture_url: str

    def public_dict(self) -> dict[str, str]:
        return {
            "email": self.email,
            "name": self.display_name,
            "picture": self.picture_url,
        }


class HistoryStore(Protocol):
    async def upsert_google_user(self, subject: str, email: str, name: str, picture: str) -> UserProfile: ...
    async def get_user(self, user_id: str) -> UserProfile | None: ...
    async def list_conversations(self, user_id: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]: ...
    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None: ...
    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str) -> str: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _user_id(subject: str) -> str:
    digest = hashlib.sha256(("google:" + subject).encode("utf-8")).hexdigest()[:32]
    return "usr_" + digest


def _chat_id() -> str:
    return "chat_" + uuid.uuid4().hex


def _message_id() -> str:
    return "msg_" + uuid.uuid4().hex


def validate_conversation_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("conversation_id 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) != 37 or not text.startswith("chat_"):
        raise ValueError("conversation_id 형식이 올바르지 않습니다.")
    tail = text[5:]
    if any(ch not in "0123456789abcdef" for ch in tail):
        raise ValueError("conversation_id 형식이 올바르지 않습니다.")
    return text


def _bounded_text(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise HistoryError(f"{label} is empty")
    if len(text) > MAX_HISTORY_MESSAGE_CHARS:
        text = text[:MAX_HISTORY_MESSAGE_CHARS]
    return text


def _title_from_user_text(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line[:MAX_HISTORY_TITLE_CHARS] or "새 대화"


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
    converted: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row)
        if item is not None:
            converted.append(item)
    return converted


class D1HistoryStore:
    """Cloudflare D1 adapter. All dynamic values use prepared statement binds."""

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

    async def upsert_google_user(self, subject: str, email: str, name: str, picture: str) -> UserProfile:
        uid = _user_id(subject)
        now = _now_iso()
        display = (name.strip() or email.split("@", 1)[0])[:160]
        pic = picture.strip()[:1000]
        await self._run(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
            "VALUES (?, 'google', ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(auth_provider, provider_subject) DO UPDATE SET "
            "email=excluded.email, display_name=excluded.display_name, picture_url=excluded.picture_url, updated_at=excluded.updated_at",
            uid, subject, email, display, pic, now, now,
        )
        return UserProfile(uid, email, display, pic)

    async def get_user(self, user_id: str) -> UserProfile | None:
        row = await self._first(
            "SELECT id, email, display_name, picture_url FROM users WHERE id=? AND auth_provider='google'",
            user_id,
        )
        if not row:
            return None
        return UserProfile(
            str(row.get("id", "")),
            str(row.get("email", "")),
            str(row.get("display_name", "")),
            str(row.get("picture_url", "")),
        )

    async def list_conversations(self, user_id: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), MAX_RECENT_CONVERSATIONS))
        rows = await self._all(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            user_id, bounded,
        )
        return [
            {
                "id": str(row.get("id", "")),
                "title": str(row.get("title", "")),
                "created_at": str(row.get("created_at", "")),
                "updated_at": str(row.get("updated_at", "")),
            }
            for row in rows
        ]

    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        conv = await self._first(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id=? AND user_id=?",
            conversation_id, user_id,
        )
        if not conv:
            return None
        messages = await self._all(
            "SELECT role, content, sequence_number, created_at FROM messages "
            "WHERE conversation_id=? ORDER BY sequence_number ASC",
            conversation_id,
        )
        return {
            "id": str(conv.get("id", "")),
            "title": str(conv.get("title", "")),
            "created_at": str(conv.get("created_at", "")),
            "updated_at": str(conv.get("updated_at", "")),
            "messages": [
                {"role": str(row.get("role", "")), "content": str(row.get("content", ""))}
                for row in messages
                if row.get("role") in {"user", "assistant"}
            ],
        }

    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str) -> str:
        user_content = _bounded_text(user_text, "user_text")
        assistant_content = _bounded_text(assistant_text, "assistant_text")
        now = _now_iso()
        cid = conversation_id
        if cid is None:
            cid = _chat_id()
            await self._run(
                "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                cid, user_id, _title_from_user_text(user_content), now, now,
            )
            sequence = 0
        else:
            owned = await self._first("SELECT id FROM conversations WHERE id=? AND user_id=?", cid, user_id)
            if not owned:
                raise HistoryForbidden("conversation is not owned by current user")
            row = await self._first(
                "SELECT MAX(sequence_number) AS max_sequence FROM messages WHERE conversation_id=?",
                cid,
            )
            raw_seq = None if row is None else row.get("max_sequence")
            sequence = int(raw_seq) + 1 if raw_seq is not None else 0

        await self._run(
            "INSERT INTO messages (id, conversation_id, sequence_number, role, content, created_at) VALUES (?, ?, ?, 'user', ?, ?)",
            _message_id(), cid, sequence, user_content, now,
        )
        await self._run(
            "INSERT INTO messages (id, conversation_id, sequence_number, role, content, created_at) VALUES (?, ?, ?, 'assistant', ?, ?)",
            _message_id(), cid, sequence + 1, assistant_content, now,
        )
        await self._run("UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?", now, cid, user_id)
        return cid
