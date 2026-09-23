from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .workspace_storage import _safe_identifier

MAX_HISTORY_MESSAGE_CHARS = 8000
MAX_HISTORY_TITLE_CHARS = 80
MAX_RECENT_CONVERSATIONS = 30
MAX_PROJECT_NAME_CHARS = 80
MAX_PROJECT_INSTRUCTIONS_CHARS = 1800
MAX_PROJECTS = 50
MAX_CLAW_RUNS = 30
MAX_RUN_RESULT_SUMMARY_CHARS = 200
MAX_CLAW_HANDOFF_TRUSTED_REQUEST_CHARS = 32000

# #2956: closed server-derived trusted P01 request shape. Unknown keys fail
# closed so browser-supplied authority fields can never enter the handoff.
_CLAW_HANDOFF_TRUSTED_REQUEST_KEYS = frozenset(
    {
        "app_id",
        "agent",
        "messages",
        "session_id",
        "additional_system_context",
        "trace_id",
        "execution_context",
    }
)


class HistoryError(RuntimeError):
    pass


class HistoryForbidden(HistoryError):
    pass


class HistoryConflict(HistoryError):
    pass


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: str
    email: str
    display_name: str
    picture_url: str

    def public_dict(self) -> dict[str, str]:
        return {"email": self.email, "name": self.display_name, "picture": self.picture_url}


@dataclass(frozen=True, slots=True)
class PasswordCredential:
    user: UserProfile
    username: str
    password_hash: str
    failed_attempts: int
    locked_until: str | None


@dataclass(frozen=True, slots=True)
class ProjectProfile:
    id: str
    name: str
    instructions: str
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "instructions": self.instructions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class HistoryStore(Protocol):
    async def upsert_google_user(self, subject: str, email: str, name: str, picture: str) -> UserProfile: ...
    async def register_password_user(self, username: str, email: str, name: str, password_hash: str) -> UserProfile: ...
    async def find_password_credential(self, identifier: str) -> PasswordCredential | None: ...
    async def record_password_failure(self, user_id: str, failed_attempts: int, locked_until: str | None) -> None: ...
    async def reset_password_failures(self, user_id: str) -> None: ...
    async def get_user(self, user_id: str) -> UserProfile | None: ...
    async def list_conversations(self, user_id: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]: ...
    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None: ...
    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool: ...
    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str, project_id: str | None = None) -> str: ...
    async def list_projects(self, user_id: str) -> list[ProjectProfile]: ...
    async def get_project(self, user_id: str, project_id: str) -> ProjectProfile | None: ...
    async def create_project(self, user_id: str, name: str, instructions: str) -> ProjectProfile: ...
    async def update_project(self, user_id: str, project_id: str, name: str, instructions: str) -> ProjectProfile | None: ...
    async def delete_project(self, user_id: str, project_id: str) -> bool: ...
    async def list_project_conversations(self, user_id: str, project_id: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]: ...
    async def record_claw_run(self, user_id: str, run_id: str, channel: str, action: str, title: str, status: str, result_summary: str | None = None, artifact_document_id: str | None = None, artifact_filename: str | None = None, artifact_media_type: str | None = None, conversation_id: str | None = None, workspace_id: str | None = None) -> None: ...
    async def list_recent_claw_runs(self, user_id: str, limit: int = MAX_CLAW_RUNS, workspace_id: str | None = None) -> list[dict[str, Any]]: ...
    async def record_claw_approval_handoff(self, user_id: str, run_id: str, continuation_ref: str, pause_id: str, pause_expires_at: str, trusted_request: dict[str, Any], workspace_id: str | None = None, conversation_id: str | None = None) -> None: ...
    async def load_claw_approval_handoff(self, user_id: str, run_id: str, workspace_id: str | None = None) -> dict[str, Any] | None: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _user_id(subject: str) -> str:
    # Compatibility invariant: existing Google users keep their exact IDs.
    digest = hashlib.sha256(("google:" + subject).encode("utf-8")).hexdigest()[:32]
    return "usr_" + digest


def _password_user_id(username: str) -> str:
    digest = hashlib.sha256(("password:" + username.lower()).encode("utf-8")).hexdigest()[:32]
    return "usr_" + digest


def _chat_id() -> str:
    return "chat_" + uuid.uuid4().hex


def _message_id() -> str:
    return "msg_" + uuid.uuid4().hex


def _project_id() -> str:
    return "proj_" + uuid.uuid4().hex


def _run_history_id() -> str:
    return "crh_" + uuid.uuid4().hex


def _handoff_id() -> str:
    return "clh_" + uuid.uuid4().hex


def _handoff_trusted_request_json(trusted_request: object) -> tuple[str, str]:
    """Serialize and fingerprint the closed trusted P01 request shape (#2956)."""
    import json

    if not isinstance(trusted_request, dict):
        raise HistoryError("trusted_request must be an object")
    if set(trusted_request) - _CLAW_HANDOFF_TRUSTED_REQUEST_KEYS:
        raise HistoryError("trusted_request carries fields outside the closed handoff shape")
    if not isinstance(trusted_request.get("app_id"), str) or not trusted_request.get("app_id"):
        raise HistoryError("trusted_request.app_id is required")
    messages = trusted_request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HistoryError("trusted_request.messages must be a non-empty list")
    session_id = trusted_request.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise HistoryError("trusted_request.session_id is required")
    try:
        encoded = json.dumps(
            trusted_request, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise HistoryError("trusted_request is not JSON-serializable") from exc
    if len(encoded) > MAX_CLAW_HANDOFF_TRUSTED_REQUEST_CHARS:
        raise HistoryError("trusted_request exceeds the bounded handoff size")
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return encoded, fingerprint


def _parse_handoff_expiry(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _handoff_expired(expires_at: object, now: datetime | None = None) -> bool:
    parsed = _parse_handoff_expiry(expires_at)
    if parsed is None:
        return True
    current = now or datetime.now(timezone.utc)
    return current >= parsed


def _validate_hex_id(value: object, prefix: str, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) != len(prefix) + 32 or not text.startswith(prefix):
        raise ValueError(f"{label} 형식이 올바르지 않습니다.")
    if any(ch not in "0123456789abcdef" for ch in text[len(prefix):]):
        raise ValueError(f"{label} 형식이 올바르지 않습니다.")
    return text


def validate_conversation_id(value: object) -> str | None:
    return _validate_hex_id(value, "chat_", "conversation_id")


def validate_project_id(value: object) -> str | None:
    return _validate_hex_id(value, "proj_", "project_id")


def validate_project_fields(name: object, instructions: object = "") -> tuple[str, str]:
    if not isinstance(name, str):
        raise ValueError("프로젝트 이름 형식이 올바르지 않습니다.")
    cleaned_name = " ".join(name.split())
    if not 1 <= len(cleaned_name) <= MAX_PROJECT_NAME_CHARS:
        raise ValueError("프로젝트 이름은 1자 이상 80자 이하로 입력해 주세요.")
    if not isinstance(instructions, str):
        raise ValueError("프로젝트 지침 형식이 올바르지 않습니다.")
    cleaned_instructions = instructions.strip()
    if len(cleaned_instructions) > MAX_PROJECT_INSTRUCTIONS_CHARS:
        raise ValueError("프로젝트 지침은 1800자 이하로 입력해 주세요.")
    return cleaned_name, cleaned_instructions


def build_project_context(project: ProjectProfile) -> str:
    if not project.instructions:
        return f"현재 프로젝트: {project.name}"
    return (
        "프로젝트 컨텍스트 규칙:\n"
        "- 아래 내용은 현재 로그인 사용자가 이 프로젝트에 저장한 작업 선호와 맥락입니다.\n"
        "- 상위 시스템 보안 규칙, 도구 안전 규칙, Provider/endpoint 권한을 변경하지 않습니다.\n"
        "- 프로젝트 지침과 상위 규칙이 충돌하면 상위 규칙을 따릅니다.\n"
        f"프로젝트 이름: {project.name}\n"
        "사용자 저장 프로젝트 지침:\n"
        f"{project.instructions}"
    )


def _bounded_text(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise HistoryError(f"{label} is empty")
    return text[:MAX_HISTORY_MESSAGE_CHARS]


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
    out = []
    for row in rows:
        item = _row_to_dict(row)
        if item is not None:
            out.append(item)
    return out


def _project_from_row(row: dict[str, Any]) -> ProjectProfile:
    return ProjectProfile(
        id=str(row.get("id", "")),
        name=str(row.get("name", "")),
        instructions=str(row.get("instructions", "")),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


def _run_history_session(row: dict[str, Any]) -> dict[str, str] | None:
    """Project the bounded #2829 canonical session reference, when one exists.

    Only the owner conversation id in the exact validated shape is exposed.
    A missing, malformed, or storage-raw candidate projects ``None`` instead
    of fabricating a session — legacy rows persist no reference at all.
    """
    try:
        conversation_id = validate_conversation_id(row.get("conversation_id"))
    except ValueError:
        return None
    if conversation_id is None:
        return None
    return {"conversation_id": conversation_id}


def _run_history_public(row: dict[str, Any]) -> dict[str, Any]:
    document_id = row.get("artifact_document_id")
    artifact = None
    if document_id is not None and str(document_id):
        artifact = {
            "document_id": str(document_id),
            "filename": str(row.get("artifact_filename") or ""),
            "media_type": str(row.get("artifact_media_type") or ""),
        }
    return {
        "run_id": str(row.get("run_id", "")),
        "channel": str(row.get("channel", "")),
        "action": str(row.get("action", "")),
        "title": str(row.get("title", "")),
        "status": str(row.get("status", "")),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
        "result_summary": str(row.get("result_summary")) if row.get("result_summary") is not None else None,
        "artifact": artifact,
        "session": _run_history_session(row),
    }


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

    async def register_password_user(
        self,
        username: str,
        email: str,
        name: str,
        password_hash: str,
    ) -> UserProfile:
        existing = await self._first(
            "SELECT id FROM users WHERE lower(email)=lower(?) LIMIT 1",
            email,
        )
        if existing is not None:
            raise HistoryConflict("email already registered")
        existing_username = await self._first(
            "SELECT user_id FROM password_credentials WHERE username=? COLLATE NOCASE LIMIT 1",
            username,
        )
        if existing_username is not None:
            raise HistoryConflict("username already registered")

        uid = _password_user_id(username)
        now = _now_iso()
        display = (name.strip() or username)[:160]
        # The v1 users table has a historical google-only CHECK constraint.
        # Keep this row as storage compatibility only; password_credentials is
        # the product-local auth-method authority, while the Control Plane is
        # explicitly bridged with auth_provider='password'.
        compatibility_subject = "password:" + username
        user_statement = self.db.prepare(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
            "VALUES (?, 'google', ?, ?, ?, '', ?, ?)"
        ).bind(uid, compatibility_subject, email, display, now, now)
        credential_statement = self.db.prepare(
            "INSERT INTO password_credentials "
            "(user_id, username, password_hash, failed_attempts, locked_until, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, NULL, ?, ?)"
        ).bind(uid, username, password_hash, now, now)
        batch = getattr(self.db, "batch", None)
        if not callable(batch):
            raise HistoryError("D1 batch API is required for password registration")
        try:
            await batch([user_statement, credential_statement])
        except Exception as exc:
            raise HistoryConflict("password account registration conflict") from exc
        return UserProfile(uid, email, display, "")

    async def find_password_credential(self, identifier: str) -> PasswordCredential | None:
        if "@" in identifier:
            row = await self._first(
                "SELECT u.id, u.email, u.display_name, u.picture_url, c.username, c.password_hash, "
                "c.failed_attempts, c.locked_until "
                "FROM password_credentials c JOIN users u ON u.id=c.user_id "
                "WHERE lower(u.email)=lower(?) LIMIT 1",
                identifier,
            )
        else:
            row = await self._first(
                "SELECT u.id, u.email, u.display_name, u.picture_url, c.username, c.password_hash, "
                "c.failed_attempts, c.locked_until "
                "FROM password_credentials c JOIN users u ON u.id=c.user_id "
                "WHERE c.username=? COLLATE NOCASE LIMIT 1",
                identifier,
            )
        if row is None:
            return None
        return PasswordCredential(
            user=UserProfile(
                str(row.get("id", "")),
                str(row.get("email", "")),
                str(row.get("display_name", "")),
                str(row.get("picture_url", "")),
            ),
            username=str(row.get("username", "")),
            password_hash=str(row.get("password_hash", "")),
            failed_attempts=max(0, int(row.get("failed_attempts", 0))),
            locked_until=str(row.get("locked_until")) if row.get("locked_until") else None,
        )

    async def record_password_failure(
        self,
        user_id: str,
        failed_attempts: int,
        locked_until: str | None,
    ) -> None:
        await self._run(
            "UPDATE password_credentials SET failed_attempts=?, locked_until=?, updated_at=? WHERE user_id=?",
            failed_attempts,
            locked_until,
            _now_iso(),
            user_id,
        )

    async def reset_password_failures(self, user_id: str) -> None:
        await self._run(
            "UPDATE password_credentials SET failed_attempts=0, locked_until=NULL, updated_at=? WHERE user_id=?",
            _now_iso(),
            user_id,
        )

    async def get_user(self, user_id: str) -> UserProfile | None:
        row = await self._first(
            "SELECT id, email, display_name, picture_url FROM users "
            "WHERE id=?",
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
            "SELECT id, title, project_id, created_at, updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            user_id, bounded,
        )
        return [{
            "id": str(row.get("id", "")), "title": str(row.get("title", "")),
            "project_id": str(row.get("project_id")) if row.get("project_id") is not None else None,
            "created_at": str(row.get("created_at", "")), "updated_at": str(row.get("updated_at", "")),
        } for row in rows]

    async def list_project_conversations(self, user_id: str, project_id: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), MAX_RECENT_CONVERSATIONS))
        rows = await self._all(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE user_id=? AND project_id=? ORDER BY updated_at DESC LIMIT ?",
            user_id, project_id, bounded,
        )
        return [{
            "id": str(row.get("id", "")), "title": str(row.get("title", "")), "project_id": project_id,
            "created_at": str(row.get("created_at", "")), "updated_at": str(row.get("updated_at", "")),
        } for row in rows]

    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        conv = await self._first(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations WHERE id=? AND user_id=?",
            conversation_id, user_id,
        )
        if not conv:
            return None
        messages = await self._all(
            "SELECT role, content, sequence_number, created_at FROM messages WHERE conversation_id=? ORDER BY sequence_number ASC",
            conversation_id,
        )
        return {
            "id": str(conv.get("id", "")), "title": str(conv.get("title", "")),
            "project_id": str(conv.get("project_id")) if conv.get("project_id") is not None else None,
            "created_at": str(conv.get("created_at", "")), "updated_at": str(conv.get("updated_at", "")),
            "messages": [{"role": str(row.get("role", "")), "content": str(row.get("content", ""))} for row in messages if row.get("role") in {"user", "assistant"}],
        }

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        owned = await self._first(
            "SELECT id FROM conversations WHERE id=? AND user_id=?",
            conversation_id, user_id,
        )
        if not owned:
            return False
        await self._run(
            "DELETE FROM conversations WHERE id=? AND user_id=?",
            conversation_id, user_id,
        )
        return True

    async def list_projects(self, user_id: str) -> list[ProjectProfile]:
        rows = await self._all(
            "SELECT id, name, instructions, created_at, updated_at FROM projects WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            user_id, MAX_PROJECTS,
        )
        return [_project_from_row(row) for row in rows]

    async def get_project(self, user_id: str, project_id: str) -> ProjectProfile | None:
        row = await self._first(
            "SELECT id, name, instructions, created_at, updated_at FROM projects WHERE id=? AND user_id=?",
            project_id, user_id,
        )
        return _project_from_row(row) if row else None

    async def create_project(self, user_id: str, name: str, instructions: str) -> ProjectProfile:
        clean_name, clean_instructions = validate_project_fields(name, instructions)
        pid = _project_id()
        now = _now_iso()
        await self._run(
            "INSERT INTO projects (id, user_id, name, instructions, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            pid, user_id, clean_name, clean_instructions, now, now,
        )
        return ProjectProfile(pid, clean_name, clean_instructions, now, now)

    async def update_project(self, user_id: str, project_id: str, name: str, instructions: str) -> ProjectProfile | None:
        current = await self.get_project(user_id, project_id)
        if current is None:
            return None
        clean_name, clean_instructions = validate_project_fields(name, instructions)
        now = _now_iso()
        await self._run(
            "UPDATE projects SET name=?, instructions=?, updated_at=? WHERE id=? AND user_id=?",
            clean_name, clean_instructions, now, project_id, user_id,
        )
        return ProjectProfile(project_id, clean_name, clean_instructions, current.created_at, now)

    async def delete_project(self, user_id: str, project_id: str) -> bool:
        current = await self.get_project(user_id, project_id)
        if current is None:
            return False
        await self._run(
            "DELETE FROM projects WHERE id=? AND user_id=?",
            project_id, user_id,
        )
        return True

    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str, project_id: str | None = None) -> str:
        user_content = _bounded_text(user_text, "user_text")
        assistant_content = _bounded_text(assistant_text, "assistant_text")
        now = _now_iso()
        cid = conversation_id
        if cid is None:
            if project_id is not None and await self.get_project(user_id, project_id) is None:
                raise HistoryForbidden("project is not owned by current user")
            cid = _chat_id()
            await self._run(
                "INSERT INTO conversations (id, user_id, project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                cid, user_id, project_id, _title_from_user_text(user_content), now, now,
            )
            sequence = 0
        else:
            owned = await self._first("SELECT id, project_id FROM conversations WHERE id=? AND user_id=?", cid, user_id)
            if not owned:
                raise HistoryForbidden("conversation is not owned by current user")
            stored_project = str(owned.get("project_id")) if owned.get("project_id") is not None else None
            if stored_project != project_id:
                raise HistoryForbidden("conversation project mismatch")
            row = await self._first("SELECT MAX(sequence_number) AS max_sequence FROM messages WHERE conversation_id=?", cid)
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
        if project_id is not None:
            await self._run("UPDATE projects SET updated_at=? WHERE id=? AND user_id=?", now, project_id, user_id)
        return cid

    async def record_claw_run(
        self,
        user_id: str,
        run_id: str,
        channel: str,
        action: str,
        title: str,
        status: str,
        result_summary: str | None = None,
        artifact_document_id: str | None = None,
        artifact_filename: str | None = None,
        artifact_media_type: str | None = None,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        # #2829 Phase B: defensive shape validation at the store boundary.
        # Owner authority remains with the route-level get_conversation() lookup;
        # this only prevents malformed values from reaching persistence.
        if conversation_id is not None:
            conversation_id = validate_conversation_id(conversation_id)
        # #2833 S2F3A: workspace linkage reuses the canonical safe-id grammar.
        if workspace_id is not None:
            workspace_id = _safe_identifier("workspace_id", workspace_id)
        summary = result_summary[:MAX_RUN_RESULT_SUMMARY_CHARS] if result_summary else None
        now = _now_iso()
        existing = await self._first(
            "SELECT id, created_at, conversation_id, workspace_id FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if existing is not None:
            # #2829 Phase B: run→conversation linkage is immutable once set.
            # existing NULL + new valid id  → backfill allowed
            # existing id A + new id A      → no-op
            # existing id A + new NULL      → preserve A
            # existing id A + new id B      → fail closed (no transfer)
            existing_ref = existing.get("conversation_id")
            incoming_ref = conversation_id
            if existing_ref is not None:
                if incoming_ref is not None and incoming_ref != existing_ref:
                    raise HistoryError(
                        f"claw run {run_id} is already linked to conversation {existing_ref}; "
                        "transfer to a different conversation is not allowed"
                    )
                persisted_ref = existing_ref
            else:
                persisted_ref = incoming_ref
            # #2833 S2F3A: workspace linkage is immutable once set, mirroring the
            # conversation linkage above.
            # existing NULL + incoming workspace -> one-time backfill allowed
            # existing W + same W                -> update allowed
            # existing W + incoming None         -> preserve W (never erase to NULL)
            # existing W_A + incoming W_B        -> fail closed (no transfer)
            existing_workspace = existing.get("workspace_id")
            if existing_workspace is not None:
                if workspace_id is not None and workspace_id != existing_workspace:
                    raise HistoryError(
                        f"claw run {run_id} is already linked to workspace {existing_workspace}; "
                        "transfer to a different workspace is not allowed"
                    )
                persisted_workspace = existing_workspace
            else:
                persisted_workspace = workspace_id
            await self._run(
                "UPDATE claw_run_history SET channel=?, action=?, title=?, status=?, updated_at=?, "
                "result_summary=?, artifact_document_id=?, artifact_filename=?, artifact_media_type=?, "
                "conversation_id=?, workspace_id=? "
                "WHERE run_id=? AND user_id=?",
                channel, action, title, status, now,
                summary, artifact_document_id, artifact_filename, artifact_media_type,
                persisted_ref, persisted_workspace,
                run_id, user_id,
            )
            return
        await self._run(
            "INSERT INTO claw_run_history (id, user_id, run_id, channel, action, title, status, created_at, updated_at, result_summary, artifact_document_id, artifact_filename, artifact_media_type, conversation_id, workspace_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _run_history_id(), user_id, run_id, channel, action, title, status, now, now,
            summary, artifact_document_id, artifact_filename, artifact_media_type,
            conversation_id, workspace_id,
        )

    async def list_recent_claw_runs(
        self, user_id: str, limit: int = MAX_CLAW_RUNS, workspace_id: str | None = None
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), MAX_CLAW_RUNS))
        columns = (
            "SELECT run_id, channel, action, title, status, created_at, updated_at, result_summary, "
            "artifact_document_id, artifact_filename, artifact_media_type, conversation_id "
            "FROM claw_run_history "
        )
        if workspace_id is not None:
            # #2833 S2F3A: the tenant workspace filter is exact. A legacy row with
            # workspace_id IS NULL is never mixed into a tenant workspace result.
            scoped = _safe_identifier("workspace_id", workspace_id)
            rows = await self._all(
                columns + "WHERE user_id=? AND workspace_id=? ORDER BY created_at DESC LIMIT ?",
                user_id, scoped, bounded,
            )
        else:
            # No workspace filter: preserve the legacy user-scoped behaviour.
            rows = await self._all(
                columns + "WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                user_id, bounded,
            )
        return [_run_history_public(row) for row in rows]

    async def record_claw_approval_handoff(
        self,
        user_id: str,
        run_id: str,
        continuation_ref: str,
        pause_id: str,
        pause_expires_at: str,
        trusted_request: dict[str, Any],
        workspace_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        """Persist one owner-scoped approval handoff under the history owner (#2956).

        Exact replay of the same owner+run identity is idempotent. A conflicting
        continuation_ref / pause_id / trusted request for the same owner+run
        fails closed with ``HistoryConflict``. Cross-owner reads never disclose
        existence because every statement is owner-scoped by ``user_id``.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if not isinstance(continuation_ref, str) or not continuation_ref:
            raise HistoryError("continuation_ref is required")
        if not isinstance(pause_id, str) or not pause_id:
            raise HistoryError("pause_id is required")
        if not isinstance(pause_expires_at, str) or not pause_expires_at:
            raise HistoryError("pause_expires_at is required")
        if _parse_handoff_expiry(pause_expires_at) is None:
            raise HistoryError("pause_expires_at must be a timezone-aware ISO-8601 timestamp")
        if conversation_id is not None:
            conversation_id = validate_conversation_id(conversation_id)
        if workspace_id is not None:
            workspace_id = _safe_identifier("workspace_id", workspace_id)
        encoded, fingerprint = _handoff_trusted_request_json(trusted_request)
        existing = await self._first(
            "SELECT id, continuation_ref, pause_id, pause_expires_at, trusted_request_fingerprint, workspace_id, conversation_id "
            "FROM claw_approval_handoff WHERE user_id=? AND run_id=?",
            user_id, run_id,
        )
        if existing is not None:
            if (
                str(existing.get("continuation_ref")) == continuation_ref
                and str(existing.get("pause_id")) == pause_id
                and str(existing.get("pause_expires_at")) == pause_expires_at
                and str(existing.get("trusted_request_fingerprint")) == fingerprint
                and existing.get("workspace_id") == workspace_id
                and existing.get("conversation_id") == conversation_id
            ):
                return
            raise HistoryConflict(
                f"claw approval handoff for run {run_id} already exists with a different identity"
            )
        await self._run(
            "INSERT INTO claw_approval_handoff (id, user_id, run_id, workspace_id, conversation_id, "
            "continuation_ref, pause_id, pause_expires_at, trusted_request_json, trusted_request_fingerprint, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _handoff_id(), user_id, run_id, workspace_id, conversation_id,
            continuation_ref, pause_id, pause_expires_at, encoded, fingerprint, _now_iso(),
        )

    async def load_claw_approval_handoff(
        self,
        user_id: str,
        run_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Load one owner+run handoff; cross-scope and expired rows are non-disclosing.

        A foreign owner or foreign workspace returns ``None`` (never an existence
        oracle). An expired pause is unusable and also returns ``None``.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(run_id, str) or not run_id:
            return None
        if workspace_id is not None:
            scoped = _safe_identifier("workspace_id", workspace_id)
            row = await self._first(
                "SELECT user_id, run_id, workspace_id, conversation_id, continuation_ref, pause_id, "
                "pause_expires_at, trusted_request_json, trusted_request_fingerprint, created_at "
                "FROM claw_approval_handoff WHERE user_id=? AND run_id=? AND workspace_id=?",
                user_id, run_id, scoped,
            )
        else:
            row = await self._first(
                "SELECT user_id, run_id, workspace_id, conversation_id, continuation_ref, pause_id, "
                "pause_expires_at, trusted_request_json, trusted_request_fingerprint, created_at "
                "FROM claw_approval_handoff WHERE user_id=? AND run_id=?",
                user_id, run_id,
            )
        if row is None:
            return None
        if _handoff_expired(row.get("pause_expires_at")):
            return None
        try:
            import json

            trusted = json.loads(str(row.get("trusted_request_json") or "{}"))
        except (TypeError, ValueError):
            return None
        if not isinstance(trusted, dict):
            return None
        conversation_id = row.get("conversation_id")
        return {
            "user_id": str(row.get("user_id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "workspace_id": row.get("workspace_id"),
            "conversation_id": conversation_id,
            "continuation_ref": str(row.get("continuation_ref") or ""),
            "pause_id": str(row.get("pause_id") or ""),
            "pause_expires_at": str(row.get("pause_expires_at") or ""),
            "trusted_request": trusted,
            "trusted_request_fingerprint": str(row.get("trusted_request_fingerprint") or ""),
            "created_at": str(row.get("created_at") or ""),
        }
