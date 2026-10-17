from __future__ import annotations

import hashlib
import inspect
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .workspace_storage import _safe_identifier

MAX_HISTORY_MESSAGE_CHARS = 8000
MAX_MODEL_CONTEXT_BYTES = 5_500_000  # bounded transport, not model token budget
MAX_HISTORY_TITLE_CHARS = 80
MAX_RECENT_CONVERSATIONS = 30
# #4471 conversation search bounds: query text, result rows, and how many
# message rows a single search may scan. These cap cost; they never truncate
# a stored conversation.
MAX_CONVERSATION_SEARCH_QUERY_CHARS = 80
MAX_CONVERSATION_SEARCH_RESULTS = 20
MAX_CONVERSATION_SEARCH_SCAN_ROWS = 2000
MAX_CONVERSATION_SEARCH_SNIPPET_CHARS = 120
MAX_PROJECT_NAME_CHARS = 80
MAX_PROJECT_INSTRUCTIONS_CHARS = 1800
MAX_PROJECTS = 50
MAX_CLAW_RUNS = 30
MAX_RUN_RESULT_SUMMARY_CHARS = 200
MAX_CLAW_HANDOFF_TRUSTED_REQUEST_CHARS = 32000

# #4657 product isolation. One account owns conversations for more than one
# product, so owner scoping alone is not visibility scoping: a B66 request would
# otherwise list, read or delete the same account's Chat/Claw dialogue.
#
# The discriminator is server-owned and stored on the row. Callers must pass the
# scope their own route is serving; it is never derived from a browser-supplied
# value (a `project_id` or a conversation id is not a product claim).
#
# `b62-chat` is the pre-existing generic scope. Every conversation created before
# this column existed is backfilled to it, which is what preserves Chat project
# semantics and Claw historical continuity. B66 dialogue lives in its own scope.
PRODUCT_SCOPE_CHAT = "b62-chat"
PRODUCT_SCOPE_B66 = "b66-quote"
KNOWN_PRODUCT_SCOPES = frozenset({PRODUCT_SCOPE_CHAT, PRODUCT_SCOPE_B66})


def _require_product_scope(value: object) -> str:
    """Fail closed: only a known server-owned scope may address conversations."""
    if not isinstance(value, str) or value not in KNOWN_PRODUCT_SCOPES:
        raise HistoryForbidden("conversation product scope is not recognized")
    return value

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


class HistoryContextIncomplete(HistoryError):
    """A legacy or missing full-text projection cannot be used as model truth."""
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
    async def list_conversations(self, user_id: str, *, product_scope: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]: ...
    async def search_conversations(self, user_id: str, query: str, *, product_scope: str, limit: int = MAX_CONVERSATION_SEARCH_RESULTS) -> list[dict[str, Any]]: ...
    async def get_conversation(self, user_id: str, conversation_id: str, *, product_scope: str) -> dict[str, Any] | None: ...
    async def delete_conversation(self, user_id: str, conversation_id: str, *, product_scope: str) -> bool: ...
    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str, project_id: str | None = None, *, product_scope: str) -> str: ...
    async def list_projects(self, user_id: str) -> list[ProjectProfile]: ...
    async def get_project(self, user_id: str, project_id: str) -> ProjectProfile | None: ...
    async def create_project(self, user_id: str, name: str, instructions: str) -> ProjectProfile: ...
    async def update_project(self, user_id: str, project_id: str, name: str, instructions: str) -> ProjectProfile | None: ...
    async def delete_project(self, user_id: str, project_id: str) -> bool: ...
    async def list_project_conversations(self, user_id: str, project_id: str, *, product_scope: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]: ...
    async def record_claw_run(self, user_id: str, run_id: str, channel: str, action: str, title: str, status: str, result_summary: str | None = None, artifact_document_id: str | None = None, artifact_filename: str | None = None, artifact_media_type: str | None = None, conversation_id: str | None = None, workspace_id: str | None = None) -> None: ...
    async def list_recent_claw_runs(self, user_id: str, limit: int = MAX_CLAW_RUNS, workspace_id: str | None = None) -> list[dict[str, Any]]: ...
    async def update_claw_run_status(self, user_id: str, run_id: str, status: str, result_summary: str | None = None) -> bool: ...
    async def record_claw_approval_handoff(self, user_id: str, run_id: str, continuation_ref: str, pause_id: str, pause_expires_at: str, trusted_request: dict[str, Any], workspace_id: str | None = None, conversation_id: str | None = None, p01_run_id: str | None = None) -> None: ...
    async def load_claw_approval_handoff(self, user_id: str, run_id: str, workspace_id: str | None = None) -> dict[str, Any] | None: ...
    async def consume_claw_approval_handoff(self, user_id: str, run_id: str, workspace_id: str | None = None) -> bool: ...


def _normalize_search_query(query: object) -> str:
    """Trim, collapse whitespace and bound the query. Returns '' when unusable."""
    if not isinstance(query, str):
        return ""
    collapsed = " ".join(query.split())
    return collapsed[:MAX_CONVERSATION_SEARCH_QUERY_CHARS]


def _escape_like(query: object) -> str:
    """Make a user query a literal LIKE substring under ESCAPE '\\'.

    The escape character is escaped first, then the LIKE wildcards.
    """
    normalized = _normalize_search_query(query)
    return normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_snippet(hit: object, query: object) -> str:
    """Short excerpt around the first literal match. '' when there is no body hit."""
    if not isinstance(hit, str) or not hit:
        return ""
    literal = _normalize_search_query(query)
    index = hit.casefold().find(literal.casefold()) if literal else -1
    if index < 0:
        index = 0
    width = MAX_CONVERSATION_SEARCH_SNIPPET_CHARS
    start = max(0, index - width // 3)
    end = min(len(hit), start + width)
    excerpt = hit[start:end].replace("\n", " ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(hit) else ""
    return prefix + excerpt + suffix


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
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
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


HISTORY_PREVIEW_SUFFIX = "\n[저장 미리보기: 전체 내용 중 일부만 저장되었습니다.]"


def _bounded_text(value: str, label: str, preserve_edges: bool = False) -> str:
    # #4139: the stored preview is edge-trimmed by default. A terminal command
    # result is the one caller that must keep the exact leading/trailing
    # whitespace the PC produced, so it opts in explicitly instead of changing
    # the shared default for every other message.
    text = value if preserve_edges else value.strip()
    if not text.strip():
        raise HistoryError(f"{label} is empty")
    # Persistence is a bounded display preview, never a model-input ceiling.
    # Mark incomplete previews explicitly so users do not mistake saved history
    # for a full transcript when a long request/answer reached the provider.
    if len(text) <= MAX_HISTORY_MESSAGE_CHARS:
        return text
    suffix = HISTORY_PREVIEW_SUFFIX
    return text[:MAX_HISTORY_MESSAGE_CHARS - len(suffix)] + suffix


def _title_from_user_text(text: str) -> str:
    """Use the first user sentence verbatim; no model call or summarization."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    one_line = " ".join(first_line.split())
    boundary = re.search(r"[.!?。！？](?=\s|$)", one_line)
    if boundary:
        one_line = one_line[:boundary.end()]
    return one_line[:MAX_HISTORY_TITLE_CHARS] or "새 대화"


def _changed_rows(result: Any) -> int:
    """How many rows one ``statement.run()`` actually changed.

    ``meta.changes`` is the D1-sanctioned counter for "rows this statement
    modified". ``rows_written`` is deliberately not used: it also counts index
    writes, so a guarded single-row UPDATE can report more than one and a real
    winner would be misread as a loser. ``0`` is the load-bearing value — a
    conditional write that matched nothing refuses here, which is how a losing
    concurrent writer never inherits someone else's row.
    """
    if result is None:
        return 0
    meta = result.get("meta") if isinstance(result, dict) else getattr(result, "meta", None)
    if meta is None:
        return 0
    changed = meta.get("changes") if isinstance(meta, dict) else getattr(meta, "changes", None)
    if isinstance(changed, bool) or not isinstance(changed, int):
        return 0
    return max(0, changed)


def _batch_returned_row(results: Any, index: int) -> dict[str, Any] | None:
    """Read one ``RETURNING`` row out of a ``db.batch()`` result.

    Mirrors the automation store's reader: ``None`` means the guarded statement
    matched no row, which is how a refused write reports itself. An INSERT that
    was ignored for any reason (duplicate id, ownership scope, constraint) also
    reports no row, so an append is only ever reported as done when it happened.
    """

    if results is None:
        return None
    try:
        if len(results) <= index:
            return None
    except TypeError:
        return None
    result = results[index]
    if isinstance(result, dict):
        rows = result.get("results")
    else:
        rows = getattr(result, "results", None)
    if rows is None:
        if isinstance(result, dict):
            meta = result.get("meta")
        else:
            meta = getattr(result, "meta", None)
        if isinstance(meta, dict):
            written = meta.get("rows_written")
        else:
            written = getattr(meta, "rows_written", None)
        if isinstance(written, int) and written > 0:
            return {"rows_written": written}
        return None
    if not rows:
        return None
    try:
        return _row_to_dict(rows[0])
    except (TypeError, IndexError, KeyError):
        return None


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

    def __init__(self, db: Any, *, full_context_bucket: Any = None):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db
        # Existing private workspace R2 binding, never an incoming browser key.
        self.full_context_bucket = full_context_bucket

    @staticmethod
    def _context_key(conversation_id: str, message_id: str) -> str:
        if validate_conversation_id(conversation_id) is None or not (
            isinstance(message_id, str) and re.fullmatch(r"msg_[0-9a-f]{32}", message_id)
        ):
            raise HistoryError("invalid canonical history object identity")
        return f"claw-model-context/v1/{conversation_id}/{message_id}.utf8"

    async def _put_full_message(self, conversation_id: str, message_id: str, raw: str) -> str | None:
        if len(raw) <= MAX_HISTORY_MESSAGE_CHARS:
            return None
        data = raw.encode("utf-8")
        if len(data) > MAX_MODEL_CONTEXT_BYTES:
            raise HistoryError("model context exceeds the bounded 5.5MB transport envelope")
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "put", None)):
            raise HistoryError("private full model-context storage is unavailable")
        key = self._context_key(conversation_id, message_id)
        result = bucket.put(key, data, httpMetadata={"contentType": "text/plain; charset=utf-8"})
        if inspect.isawaitable(result):
            await result
        return key

    async def _delete_full_keys(self, keys: list[str]) -> None:
        bucket = self.full_context_bucket
        if bucket is None:
            return
        for key in keys:
            try:
                result = bucket.delete(key)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # DB owner/row authority remains independent of R2 cleanup.
                pass

    async def _read_full_message(self, conversation_id: str, row: dict[str, Any]) -> str:
        preview = str(row.get("content", ""))
        if len(preview) != MAX_HISTORY_MESSAGE_CHARS or not preview.endswith(HISTORY_PREVIEW_SUFFIX):
            return preview
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "get", None)):
            raise HistoryContextIncomplete("full model-context storage is unavailable")
        key = self._context_key(conversation_id, row.get("id"))
        obj = bucket.get(key)
        if inspect.isawaitable(obj):
            obj = await obj
        if obj is None:
            # Never pass a truncated preview to a model as the full history.
            raise HistoryContextIncomplete("saved full model context is unavailable")
        if getattr(obj, "size", 0) > MAX_MODEL_CONTEXT_BYTES:
            raise HistoryError("saved model context exceeds transport envelope")
        from .workspace_storage import _read_r2_object_bytes
        data = await _read_r2_object_bytes(obj)
        if len(data) > MAX_MODEL_CONTEXT_BYTES:
            raise HistoryError("saved model context exceeds transport envelope")
        try:
            full = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HistoryError("saved model context is not UTF-8") from exc
        if _bounded_text(full, "saved_model_context") != preview:
            raise HistoryContextIncomplete("saved model context preview does not match")
        return full

    async def get_conversation_model_context(
        self, user_id: str, conversation_id: str, *, product_scope: str,
    ) -> dict[str, Any] | None:
        """Owner- and product-scoped full messages for model only.

        Browser APIs keep bounded previews; the canonical full-original (R2)
        restoration is only ever reachable through this product-scoped read.
        """
        owned = await self.get_conversation(
            user_id, conversation_id, product_scope=product_scope
        )
        if owned is None:
            return None
        rows = await self._all(
            "SELECT id, role, content, sequence_number FROM messages "
            "WHERE conversation_id=? ORDER BY sequence_number ASC", conversation_id,
        )
        full_messages: list[dict[str, str]] = []
        byte_total = 0
        for row in rows:
            if row.get("role") not in ("user", "assistant"):
                continue
            content = await self._read_full_message(conversation_id, row)
            byte_total += len(content.encode("utf-8"))
            if byte_total > MAX_MODEL_CONTEXT_BYTES:
                raise HistoryError("conversation context exceeds transport envelope")
            full_messages.append({"role": row["role"], "content": content})
        return {**owned, "messages": full_messages}

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

    async def list_conversations(
        self, user_id: str, *, product_scope: str, limit: int = MAX_RECENT_CONVERSATIONS,
    ) -> list[dict[str, Any]]:
        scope = _require_product_scope(product_scope)
        bounded = max(1, min(int(limit), MAX_RECENT_CONVERSATIONS))
        rows = await self._all(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE user_id=? AND product_scope=? ORDER BY updated_at DESC LIMIT ?",
            user_id, scope, bounded,
        )
        return [{
            "id": str(row.get("id", "")), "title": str(row.get("title", "")),
            "project_id": str(row.get("project_id")) if row.get("project_id") is not None else None,
            "created_at": str(row.get("created_at", "")), "updated_at": str(row.get("updated_at", "")),
        } for row in rows]

    async def search_conversations(
        self, user_id: str, query: str, *, product_scope: str,
        limit: int = MAX_CONVERSATION_SEARCH_RESULTS,
    ) -> list[dict[str, Any]]:
        """Owner-scoped search over the signed-in user's own conversations.

        Matches conversation titles and recent message text. Every value is a
        bound parameter; LIKE wildcards in the query are escaped so it is always
        a literal substring. Results and scanned rows are bounded. Stored
        conversations are never truncated.
        """
        needle = _escape_like(query)
        if not needle:
            return []
        scope = _require_product_scope(product_scope)
        bounded = max(1, min(int(limit), MAX_CONVERSATION_SEARCH_RESULTS))
        pattern = f"%{needle}%"
        rows = await self._all(
            "SELECT c.id, c.title, c.project_id, c.created_at, c.updated_at, "
            "(SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
            " AND m.content LIKE ? ESCAPE '\\' ORDER BY m.sequence_number ASC LIMIT 1) AS hit "
            "FROM conversations c "
            "WHERE c.user_id=? AND c.product_scope=? AND (c.title LIKE ? ESCAPE '\\' OR EXISTS ("
            "  SELECT 1 FROM (SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
            "  ORDER BY m.sequence_number DESC LIMIT ?) scan WHERE scan.content LIKE ? ESCAPE '\\')) "
            "ORDER BY c.updated_at DESC LIMIT ?",
            pattern, user_id, scope, pattern, MAX_CONVERSATION_SEARCH_SCAN_ROWS, pattern, bounded,
        )
        return [{
            "id": str(row.get("id", "")),
            "title": str(row.get("title", "")),
            "project_id": str(row.get("project_id")) if row.get("project_id") is not None else None,
            "created_at": str(row.get("created_at", "")),
            "updated_at": str(row.get("updated_at", "")),
            "snippet": _search_snippet(row.get("hit"), query),
        } for row in rows]

    async def list_project_conversations(
        self, user_id: str, project_id: str, *, product_scope: str,
        limit: int = MAX_RECENT_CONVERSATIONS,
    ) -> list[dict[str, Any]]:
        scope = _require_product_scope(product_scope)
        bounded = max(1, min(int(limit), MAX_RECENT_CONVERSATIONS))
        rows = await self._all(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE user_id=? AND project_id=? AND product_scope=? ORDER BY updated_at DESC LIMIT ?",
            user_id, project_id, scope, bounded,
        )
        return [{
            "id": str(row.get("id", "")), "title": str(row.get("title", "")), "project_id": project_id,
            "created_at": str(row.get("created_at", "")), "updated_at": str(row.get("updated_at", "")),
        } for row in rows]

    async def get_conversation(
        self, user_id: str, conversation_id: str, *, product_scope: str,
    ) -> dict[str, Any] | None:
        scope = _require_product_scope(product_scope)
        conv = await self._first(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE id=? AND user_id=? AND product_scope=?",
            conversation_id, user_id, scope,
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

    async def delete_conversation(
        self, user_id: str, conversation_id: str, *, product_scope: str,
    ) -> bool:
        scope = _require_product_scope(product_scope)
        owned = await self._first(
            "SELECT id FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
            conversation_id, user_id, scope,
        )
        if not owned:
            return False
        full_rows = await self._all(
            "SELECT id, content FROM messages WHERE conversation_id=?", conversation_id,
        )
        await self._run(
            "DELETE FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
            conversation_id, user_id, scope,
        )
        await self._delete_full_keys([
            self._context_key(conversation_id, row["id"])
            for row in full_rows if len(str(row.get("content", ""))) == MAX_HISTORY_MESSAGE_CHARS
            and str(row.get("content", "")).endswith(HISTORY_PREVIEW_SUFFIX)
        ])
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

    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str, project_id: str | None = None, *, product_scope: str) -> str:
        scope = _require_product_scope(product_scope)
        user_content = _bounded_text(user_text, "user_text")
        assistant_content = _bounded_text(assistant_text, "assistant_text")
        now = _now_iso()
        cid = conversation_id
        creating = cid is None
        if creating:
            if project_id is not None and await self.get_project(user_id, project_id) is None:
                raise HistoryForbidden("project is not owned by current user")
            cid = _chat_id()
            sequence = 0
        else:
            owned = await self._first(
                "SELECT id, project_id FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
                cid, user_id, scope,
            )
            if not owned:
                # Another product's conversation is not addressable here, even
                # for its own owner: the scope must match the route's product.
                # The message stays the existing contract text.
                raise HistoryForbidden("conversation is not owned by current user")
            stored_project = str(owned.get("project_id")) if owned.get("project_id") is not None else None
            if stored_project != project_id:
                raise HistoryForbidden("conversation project mismatch")
            row = await self._first("SELECT MAX(sequence_number) AS max_sequence FROM messages WHERE conversation_id=?", cid)
            raw_seq = None if row is None else row.get("max_sequence")
            sequence = int(raw_seq) + 1 if raw_seq is not None else 0

        user_msg_id, answer_msg_id = _message_id(), _message_id()
        r2_keys: list[str] = []
        try:
            for msg_id, raw in ((user_msg_id, user_text.strip()), (answer_msg_id, assistant_text.strip())):
                key = await self._put_full_message(cid, msg_id, raw)
                if key is not None:
                    r2_keys.append(key)
            if creating:
                # Store private full text first; unavailable R2 must not leave
                # a misleading, empty D1 conversation for the first turn.
                await self._run(
                    "INSERT INTO conversations (id, user_id, project_id, title, created_at, updated_at, product_scope) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    cid, user_id, project_id, _title_from_user_text(user_content), now, now, scope,
                )
            await self._run(
                "INSERT INTO messages (id, conversation_id, sequence_number, role, content, created_at) VALUES (?, ?, ?, 'user', ?, ?)",
                user_msg_id, cid, sequence, user_content, now,
            )
            await self._run(
                "INSERT INTO messages (id, conversation_id, sequence_number, role, content, created_at) VALUES (?, ?, ?, 'assistant', ?, ?)",
                answer_msg_id, cid, sequence + 1, assistant_content, now,
            )
        except Exception:
            await self._delete_full_keys(r2_keys)
            raise
        await self._run("UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?", now, cid, user_id)
        if project_id is not None:
            await self._run("UPDATE projects SET updated_at=? WHERE id=? AND user_id=?", now, project_id, user_id)
        return cid

    async def record_txt_pending_run(
        self, *, user_id: str, run_id: str, workspace_id: str,
        user_text: str, conversation_id: str | None,
    ) -> str:
        """Stage a real owner conversation + pending local run, never an answer.

        The verified Broker result alone is allowed to insert the assistant
        message later. This uses the existing conversation/messages/run tables.
        """
        workspace = _safe_identifier("workspace_id", workspace_id)
        content = _bounded_text(user_text, "user_text")
        cid = validate_conversation_id(conversation_id)
        creating = cid is None
        project_id = None
        if creating:
            cid = _chat_id()
            sequence = 0
        else:
            owned = await self._first(
                "SELECT id,project_id FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
                cid, user_id, PRODUCT_SCOPE_CHAT,
            )
            if not owned:
                raise HistoryForbidden("conversation is not owned by current user")
            project_id = owned.get("project_id")
            found = await self._first(
                "SELECT MAX(sequence_number) AS max_sequence FROM messages WHERE conversation_id=?",
                cid,
            )
            number = found.get("max_sequence") if isinstance(found, dict) else None
            sequence = int(number) + 1 if number is not None else 0
        now = _now_iso()
        msg_id = _message_id()
        key = await self._put_full_message(cid, msg_id, user_text.strip())
        try:
            if creating:
                await self._run(
                    "INSERT INTO conversations (id,user_id,project_id,title,created_at,updated_at,product_scope) "
                    "VALUES (?,?,NULL,?,?,?,?)",
                    cid, user_id, _title_from_user_text(content), now, now, PRODUCT_SCOPE_CHAT,
                )
            await self._run(
                "INSERT INTO messages (id,conversation_id,sequence_number,role,content,created_at) "
                "VALUES (?,?,?,'user',?,?)",
                msg_id, cid, sequence, content, now,
            )
            await self.record_claw_run(
                user_id=user_id, run_id=run_id, channel="web",
                action="txt_read", title=("Claw: " + content)[:MAX_HISTORY_TITLE_CHARS],
                status="pending", conversation_id=cid, workspace_id=workspace,
            )
            await self._run(
                "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                now, cid, user_id,
            )
        except Exception:
            if key is not None:
                await self._delete_full_keys([key])
            raise
        return cid

    async def create_web_xlsx_p01_run(
        self, *, user_id: str, workspace_id: str, filename: str,
        product_scope: str,
    ) -> str:
        """Create a real owner-bound conversation/run for web file approval.

        This is a metadata-only waiting workflow: no fake assistant message,
        model call, file read, or caller-supplied execution identity.
        """
        import uuid
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("authenticated owner required")
        scope = _safe_identifier("workspace_id", workspace_id)
        if not isinstance(filename, str) or not filename.lower().endswith(".xlsx"):
            raise HistoryError("XLSX filename required")
        cid = _chat_id()
        run_id = "web_p01_" + uuid.uuid4().hex
        now = _now_iso()
        await self._run(
            "INSERT INTO conversations (id,user_id,project_id,title,created_at,updated_at,product_scope) "
            "VALUES (?,?,NULL,?,?,?,?)",
            cid, user_id, ("웹 XLSX 원본 승인: " + filename)[:80], now, now,
            _require_product_scope(product_scope),
        )
        await self.record_claw_run(
            user_id=user_id, run_id=run_id, channel="web", action="xlsx_p01",
            title=("XLSX 원본 확인: " + filename)[:120], status="running",
            conversation_id=cid, workspace_id=scope,
        )
        return run_id

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

    async def verify_owner_conversation_artifacts(
        self, user_id: str, conversation_id: str,
    ) -> bool:
        """#3929: current D1 conversation ownership, no cached/browser proof."""
        cid = validate_conversation_id(conversation_id)
        if cid is None or not isinstance(user_id, str) or not user_id:
            return False
        row = await self._first(
            "SELECT id FROM conversations WHERE id=? AND user_id=?",
            cid, user_id,
        )
        return isinstance(row, dict) and row.get("id") == cid

    async def register_owner_conversation_artifact(
        self, *, user_id: str, conversation_id: str,
        workspace_ref: str, artifact: Any,
    ) -> bool:
        """Trusted host only: immutable durable record for an *already completed*
        owner/conversation/workspace-bound Claw run. Never called by user JSON.

        The INSERT is an INSERT..SELECT restricted by BOTH owner conversation
        and the completed owner run; no caller-chosen run id can grant a file.
        Existing exact-id rows are not transferable or silently overwritten.
        """
        from kagent.artifact_registration import (
            ArtifactLifecycle, CanonicalArtifactRecord,
        )
        cid = validate_conversation_id(conversation_id)
        scope = _safe_identifier("workspace_ref", workspace_ref)
        if (cid is None or not isinstance(user_id, str) or not user_id
                or not isinstance(artifact, CanonicalArtifactRecord)
                or artifact.lifecycle is not ArtifactLifecycle.DURABLE
                or artifact.durable_location is None
                or artifact.workspace_ref != scope
                or not isinstance(artifact.run_ref, str)
                or artifact.media_type not in (
                    "application/pdf",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                or not artifact.filename.lower().endswith(
                    ".pdf" if artifact.media_type == "application/pdf" else ".xlsx"
                )):
            return False
        if not await self.verify_owner_conversation_artifacts(user_id, cid):
            return False
        run = await self._first(
            "SELECT run_id FROM claw_run_history "
            "WHERE run_id=? AND user_id=? AND conversation_id=? "
            "AND workspace_id=? AND status='completed'",
            artifact.run_ref, user_id, cid, scope,
        )
        if run is None:
            return False
        existing = await self._first(
            "SELECT user_id, conversation_id, workspace_ref, source_run_ref, "
            "filename, media_type, size_bytes, integrity_ref, location_kind, "
            "location_ref FROM claw_conversation_artifact_index WHERE artifact_id=?",
            artifact.artifact_id,
        )
        location = artifact.durable_location
        expected = (
            user_id, cid, scope, artifact.run_ref, artifact.filename,
            artifact.media_type, artifact.size_bytes, artifact.integrity_ref,
            location.location_kind, location.location_ref,
        )
        columns = (
            "user_id", "conversation_id", "workspace_ref", "source_run_ref",
            "filename", "media_type", "size_bytes", "integrity_ref",
            "location_kind", "location_ref",
        )
        if existing is not None:
            return tuple(existing.get(key) for key in columns) == expected
        await self._run(
            "INSERT OR IGNORE INTO claw_conversation_artifact_index "
            "(artifact_id, user_id, conversation_id, workspace_ref, source_run_ref, "
            "filename, media_type, size_bytes, integrity_ref, location_kind, "
            "location_ref, created_at) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
            "FROM conversations c INNER JOIN claw_run_history r "
            "ON r.conversation_id=c.id AND r.user_id=c.user_id "
            "WHERE c.id=? AND c.user_id=? AND r.run_id=? "
            "AND r.workspace_id=? AND r.status='completed'",
            artifact.artifact_id, *expected, _now_iso(),
            cid, user_id, artifact.run_ref, scope,
        )
        persisted = await self._first(
            "SELECT user_id, conversation_id, workspace_ref, source_run_ref, "
            "filename, media_type, size_bytes, integrity_ref, location_kind, "
            "location_ref FROM claw_conversation_artifact_index WHERE artifact_id=?",
            artifact.artifact_id,
        )
        return persisted is not None and tuple(
            persisted.get(key) for key in columns
        ) == expected

    async def get_owner_conversation_artifact(
        self, *, user_id: str, conversation_id: str,
        workspace_ref: str, artifact_id: str,
    ) -> dict[str, Any] | None:
        """#3929: single exact durable artifact, tied to current owner and completed run.

        Never use caller-supplied provider IDs. The result is an INTERNAL row;
        public routes must never expose location_ref or raw Drive metadata.
        """
        cid = validate_conversation_id(conversation_id)
        scope = _safe_identifier("workspace_ref", workspace_ref)
        if (cid is None or not isinstance(user_id, str) or not user_id
                or not isinstance(artifact_id, str) or not artifact_id
                or len(artifact_id) > 128):
            raise HistoryError("owner-scoped artifact identity required")
        return await self._first(
            "SELECT a.ordinal, a.artifact_id, a.user_id, a.conversation_id, "
            "a.workspace_ref, a.source_run_ref, a.filename, a.media_type, "
            "a.size_bytes, a.integrity_ref, a.location_kind, a.location_ref "
            "FROM claw_conversation_artifact_index a "
            "JOIN conversations c ON c.id=a.conversation_id AND c.user_id=a.user_id "
            "JOIN claw_run_history r ON r.run_id=a.source_run_ref "
            "AND r.user_id=a.user_id AND r.conversation_id=a.conversation_id "
            "AND r.workspace_id=a.workspace_ref AND r.status='completed' "
            "WHERE a.artifact_id=? AND a.user_id=? AND a.conversation_id=? "
            "AND a.workspace_ref=?",
            artifact_id, user_id, cid, scope,
        )

    async def list_owner_conversation_artifacts(
        self, *, user_id: str, conversation_id: str,
        workspace_ref: str, limit: int = 31,
    ) -> list[dict[str, Any]]:
        """Current owner+conversation+workspace read with live run binding.

        Strictly bounded; never returns provider location to an HTTP caller
        except via the trusted private adapter that strips it.
        """
        cid = validate_conversation_id(conversation_id)
        scope = _safe_identifier("workspace_ref", workspace_ref)
        if (cid is None or not isinstance(user_id, str) or not user_id
                or type(limit) is not int or not 1 <= limit <= 31):
            raise HistoryError("bounded owner/conversation artifact lookup required")
        return await self._all(
            "SELECT a.ordinal, a.artifact_id, a.user_id, a.conversation_id, "
            "a.workspace_ref, a.source_run_ref, a.filename, a.media_type, "
            "a.size_bytes, a.integrity_ref, a.location_kind, a.location_ref "
            "FROM claw_conversation_artifact_index a "
            "JOIN conversations c ON c.id=a.conversation_id AND c.user_id=a.user_id "
            "JOIN claw_run_history r ON r.run_id=a.source_run_ref "
            "AND r.user_id=a.user_id AND r.conversation_id=a.conversation_id "
            "AND r.workspace_id=a.workspace_ref AND r.status='completed' "
            "WHERE a.user_id=? AND a.conversation_id=? AND a.workspace_ref=? "
            "ORDER BY a.ordinal DESC LIMIT ?",
            user_id, cid, scope, limit,
        )

    async def update_claw_run_status(
        self,
        user_id: str,
        run_id: str,
        status: str,
        result_summary: str | None = None,
    ) -> bool:
        """Narrow status-only update of one existing owner-scoped Claw run row (#2961).

        An owner approve/deny must not rewrite channel, action, title, session or
        workspace linkage, so this touches only ``status`` / ``updated_at`` and
        the bounded result summary. Rows are addressed by owner + run id, so a
        caller can never mutate another owner's run.
        """
        if not isinstance(user_id, str) or not user_id:
            return False
        if not isinstance(run_id, str) or not run_id:
            return False
        owned = await self._first(
            "SELECT id FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            return False
        summary = result_summary[:MAX_RUN_RESULT_SUMMARY_CHARS] if result_summary else None
        await self._run(
            "UPDATE claw_run_history SET status=?, updated_at=?, result_summary=? WHERE id=?",
            status, _now_iso(), summary, str(owned.get("id")),
        )
        return True

    async def get_claw_run(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        """#3139 — the owner-scoped origin row for one Claw run.

        The conversation this run returns to is the one already linked on the run
        row. It is read, never supplied: a browser or a device cannot choose which
        conversation receives a Local Runner result.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        return await self._first(
            "SELECT id, run_id, status, result_summary, conversation_id, workspace_id, updated_at "
            "FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )

    async def append_local_task_result(
        self,
        *,
        user_id: str,
        run_id: str,
        message_id: str,
        summary: str,
        content: str,
        status: str,
        preserve_edges: bool = False,
    ) -> bool:
        """#3139 — append one bounded Local Runner result to the run's conversation.

        Returns ``True`` when this call is the one that appended the message and
        ``False`` when the identical result was already durable, which is what an
        exact retry, a duplicate observation and a restart reread all produce.

        Two guarantees, both structural:

        * **Exactly once.** The message id is derived by the caller from the
          projection identity, and the insert is ``INSERT OR IGNORE`` against the
          ``messages.id`` primary key, so a repeat append is a no-op rather than
          a second row. The message insert is additionally scoped to a
          conversation owned by ``user_id`` through a ``SELECT`` on
          ``conversations``, so a run pointing at someone else's conversation
          inserts nothing and discloses nothing.
        * **Terminal immutability.** The run row is updated only when its stored
          summary is absent or identical, so a projected run cannot be rewritten
          with a different outcome.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
            raise HistoryError("message_id must be a bounded safe reference")
        body = _bounded_text(content, "local_task_result", preserve_edges=preserve_edges)
        if len(body) > MAX_HISTORY_MESSAGE_CHARS:
            raise HistoryError("local_task_result is not bounded")
        owned = await self._first(
            "SELECT id, conversation_id, result_summary FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        conversation_id = owned.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise HistoryError("claw run has no originating conversation")
        # A contradictory result must mutate nothing, so the refusal happens
        # before any statement is issued rather than after the batch.
        stored_summary = owned.get("result_summary")
        bounded_summary = summary[:MAX_RUN_RESULT_SUMMARY_CHARS]
        if stored_summary is not None and stored_summary != bounded_summary:
            raise HistoryError("claw run already carries a different terminal result")
        if stored_summary == bounded_summary:
            # The identical terminal result is already durable. Returning here
            # is what makes an exact retry genuinely inert: no run-row update,
            # no message, no conversation timestamp.
            already = await self._first(
                "SELECT id FROM messages WHERE id=? AND conversation_id=?",
                message_id, conversation_id,
            )
            if already is not None:
                return False
        now = _now_iso()
        statements = [
            self.db.prepare(
                "UPDATE claw_run_history SET status=?, updated_at=?, result_summary=? "
                "WHERE id=? AND (result_summary IS NULL OR result_summary=?)"
            ).bind(status, now, summary[:MAX_RUN_RESULT_SUMMARY_CHARS], str(owned.get("id")), summary[:MAX_RUN_RESULT_SUMMARY_CHARS]),
            # The message insert carries the SAME guard as the run update, so a
            # second, contradictory outcome cannot append a contradicting
            # message even if a caller hands it a fresh message id.
            self.db.prepare(
                "INSERT OR IGNORE INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
                "SELECT ?, c.id, "
                "(SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM messages WHERE conversation_id = c.id), "
                "'assistant', ?, ? FROM conversations c "
                "JOIN claw_run_history r ON r.id = ? "
                "WHERE c.id = ? AND c.user_id = ? "
                "AND (r.result_summary IS NULL OR r.result_summary = ?)"
            ).bind(message_id, body, now, str(owned.get("id")), conversation_id, user_id, bounded_summary),
        ]
        results = await self.db.batch(statements)
        appended = _batch_returned_row(results, 1) is not None
        if not appended:
            # The identical result was already durable: an exact retry touches
            # nothing at all — no message, no timestamp, no state.
            return False
        # The ordering touch runs only when a message actually landed, so a
        # retry can never reorder or restamp the conversation.
        await self._run(
            "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
            now, conversation_id, user_id,
        )
        return True

    async def record_local_task_correlation(
        self,
        *,
        user_id: str,
        run_id: str,
        command_id: str,
        tool_request_ref: str,
        request_id: str,
        revision_ref: str,
        request_fingerprint: str,
        evidence_ref: str | None = None,
    ) -> bool:
        """#3139 — bind one run to the exact command the server obtained for it.

        This is the smallest bounded server-side mapping the return leg needs:
        the canonical correlations a terminal projection must echo are written
        once, here, and never by a browser or a device. A second record for the
        same owner+run+command is a no-op; a *different* one for the same
        owner+run fails closed, because two commands claiming one run is
        precisely the confusion this mapping exists to prevent.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        for name, value in (
            ("command_id", command_id),
            ("tool_request_ref", tool_request_ref),
            ("request_id", request_id),
            ("revision_ref", revision_ref),
            ("request_fingerprint", request_fingerprint),
        ):
            if not isinstance(value, str) or not value or len(value) > 512:
                raise HistoryError(f"{name} must be a bounded reference")
        if evidence_ref is not None and (not isinstance(evidence_ref, str) or len(evidence_ref) > 512):
            raise HistoryError("evidence_ref must be a bounded reference or absent")
        owned = await self._first(
            "SELECT id FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        existing = await self.get_local_task_correlation(user_id, run_id)
        candidate = {
            "command_id": command_id,
            "tool_request_ref": tool_request_ref,
            "request_id": request_id,
            "revision_ref": revision_ref,
            "evidence_ref": evidence_ref,
            "request_fingerprint": request_fingerprint,
        }
        if existing is not None:
            # One correlation per run. An identical rebinding is a no-op; any
            # difference is two commands claiming one run, which is exactly the
            # confusion this mapping prevents.
            same = all(existing.get(name) == value for name, value in candidate.items())
            if same:
                return False
            if (
                existing.get("evidence_ref") is None
                and isinstance(candidate.get("evidence_ref"), str)
                and candidate["evidence_ref"]
                and all(
                    existing.get(name) == value
                    for name, value in candidate.items()
                    if name != "evidence_ref"
                )
            ):
                # #4139: the trigger pre-writes the correlation before Broker
                # admission mints the evidence; the first verified identity
                # afterwards fills exactly that one unknown field. Anything
                # else differing is still two commands claiming one run.
                await self._run(
                    "UPDATE claw_local_task_correlation SET evidence_ref=? "
                    "WHERE user_id=? AND run_id=? AND command_id=? AND evidence_ref IS NULL",
                    candidate["evidence_ref"], user_id, run_id, command_id,
                )
                return True
            raise HistoryError("claw run is already bound to a different command correlation")
        await self._run(
            "INSERT INTO claw_local_task_correlation "
            "(id, user_id, run_id, command_id, tool_request_ref, request_id, revision_ref, evidence_ref, request_fingerprint, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _message_id(), user_id, run_id, command_id, tool_request_ref,
            request_id, revision_ref, evidence_ref, request_fingerprint, _now_iso(),
        )
        return True

    async def get_local_task_correlation(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        """#3139 — the exact command correlation bound to one run, if any."""

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        return await self._first(
            "SELECT command_id, tool_request_ref, request_id, revision_ref, evidence_ref, request_fingerprint "
            "FROM claw_local_task_correlation WHERE user_id=? AND run_id=?",
            user_id, run_id,
        )

    async def create_oracle_mesh_dispatch(
        self,
        *,
        user_id: str,
        run_id: str,
        command_id: str,
        tool_request_ref: str,
        request_id: str,
        revision_ref: str,
        evidence_ref: str | None,
        request_fingerprint: str,
        account_ref: str,
        workspace_ref: str,
        device_id: str,
        binding_ref: str | None,
        node_ref: str,
        root_ref: str,
        path_relative: str,
        file_path: str,
        expires_at: str,
        kind: str = "read",
        command_text: str | None = None,
    ) -> dict[str, Any]:
        """#4139 — stage one Oracle management-host execution for one run.

        The row snapshots the broker-bound correlation when Broker admission
        exists, plus the deployment-verified Mesh target. One dispatch per
        owner+run: an identical pending row is reused, a terminal
        (done/failed) row refuses any second execution for the run, and an
        expired pending row is replaced. Every statement is owner-scoped;
        cross-owner existence is never disclosed.

        ``evidence_ref`` and ``binding_ref`` are nullable on purpose. A PC that
        has never completed the native PC offer has no Broker binding and no
        Broker-minted evidence, and this table stores NULL for both rather than
        inventing a reference that would read as one.
        """
        fields = {
            "user_id": user_id, "run_id": run_id, "command_id": command_id,
            "tool_request_ref": tool_request_ref, "request_id": request_id,
            "revision_ref": revision_ref, "evidence_ref": evidence_ref,
            "request_fingerprint": request_fingerprint,
            "account_ref": account_ref, "workspace_ref": workspace_ref,
            "device_id": device_id, "binding_ref": binding_ref,
            "node_ref": node_ref, "root_ref": root_ref,
            "path_relative": path_relative, "file_path": file_path,
            "kind": kind, "command_text": command_text,
        }
        if kind not in ("read", "command"):
            raise HistoryError("kind must be read or command")
        if kind == "command":
            # #4139 terminal lane: the command is the execution target, so it is
            # mandatory, single-line and bounded; the file columns carry the
            # documented sentinel instead of a bogus Windows path.
            if not isinstance(command_text, str) or not command_text.strip():
                raise HistoryError("command_text is required for a command dispatch")
            if len(command_text) > 512 or any(ord(ch) < 32 for ch in command_text):
                raise HistoryError("command_text must be a bounded single-line command")
        elif command_text is not None:
            raise HistoryError("command_text is only valid for a command dispatch")
        for name, value in fields.items():
            if value is None:
                if name not in ("evidence_ref", "binding_ref", "command_text"):
                    raise HistoryError(f"{name} must be a bounded reference")
                continue
            if not isinstance(value, str) or not value or len(value) > 1024:
                raise HistoryError(f"{name} must be a bounded reference")
        if not isinstance(expires_at, str) or not expires_at:
            raise HistoryError("expires_at must be a bounded timestamp")
        owned = await self._first(
            "SELECT id FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        existing = await self._first(
            "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
            "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
            "state, expires_at FROM oracle_mesh_dispatch WHERE user_id=? AND run_id=?",
            user_id, run_id,
        )
        now = _now_iso()
        if existing is not None:
            same = all(
                existing.get(name) == value
                for name, value in fields.items()
                if name not in ("user_id", "run_id")
            )
            if same and existing.get("state") == "pending" and existing.get("expires_at", "") > now:
                return dict(existing)
            if same and existing.get("state") in ("done", "failed"):
                raise HistoryError("oracle mesh run already executed")
            if not (existing.get("state") == "pending" and existing.get("expires_at", "") <= now):
                raise HistoryError("oracle mesh run already dispatched")
            await self._run(
                "UPDATE oracle_mesh_dispatch SET command_id=?, tool_request_ref=?, "
                "request_id=?, revision_ref=?, evidence_ref=?, request_fingerprint=?, "
                "account_ref=?, workspace_ref=?, device_id=?, binding_ref=?, node_ref=?, "
                "root_ref=?, path_relative=?, file_path=?, kind=?, command_text=?, "
                "nonce_sha256=NULL, state=?, "
                "expires_at=?, created_at=? WHERE user_id=? AND run_id=? AND state=? "
                "AND expires_at<=?",
                command_id, tool_request_ref, request_id, revision_ref,
                evidence_ref, request_fingerprint, account_ref, workspace_ref,
                device_id, binding_ref, node_ref, root_ref, path_relative,
                file_path, kind, command_text, "pending", expires_at, now,
                user_id, run_id, "pending", now,
            )
            replaced = await self._first(
                "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
                "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
                "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
                "state, expires_at FROM oracle_mesh_dispatch WHERE user_id=? AND run_id=?",
                user_id, run_id,
            )
            if replaced is None:
                raise HistoryError("oracle mesh dispatch unavailable")
            return dict(replaced)
        dispatch_id = "dsp_" + uuid.uuid4().hex
        await self._run(
            "INSERT INTO oracle_mesh_dispatch "
            "(dispatch_id, user_id, run_id, command_id, tool_request_ref, request_id, "
            "revision_ref, evidence_ref, request_fingerprint, account_ref, workspace_ref, "
            "device_id, binding_ref, node_ref, root_ref, path_relative, file_path, "
            "kind, command_text, "
            "nonce_sha256, state, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
            dispatch_id, user_id, run_id, command_id, tool_request_ref,
            request_id, revision_ref, evidence_ref, request_fingerprint,
            account_ref, workspace_ref, device_id, binding_ref, node_ref,
            root_ref, path_relative, file_path, kind, command_text,
            "pending", expires_at, now,
        )
        created = await self._first(
            "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
            "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
            "state, expires_at FROM oracle_mesh_dispatch WHERE user_id=? AND run_id=?",
            user_id, run_id,
        )
        if created is None:
            raise HistoryError("oracle mesh dispatch unavailable")
        return dict(created)

    async def oldest_pending_oracle_mesh_dispatch(self) -> dict[str, Any] | None:
        """#4139 — the single oldest claimable Oracle execution, if any.

        Claimable means pending, unexpired and never handed out (no nonce).
        The caller (the poll route, under the channel secret) atomically claims
        it before responding; this read alone hands out nothing.
        """
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at FROM oracle_mesh_dispatch "
            "WHERE state=? AND expires_at>? AND nonce_sha256 IS NULL "
            "ORDER BY created_at ASC LIMIT 1",
            "pending", _now_iso(),
        )
        return dict(row) if row is not None else None

    async def claim_oracle_mesh_dispatch(
        self, *, dispatch_id: str, nonce_sha256: str
    ) -> bool:
        """#4139 — atomically hand one pending dispatch to the executor.

        The conditional update is the single-claim gate: exactly one poll wins
        per dispatch. Returns False when another poll already claimed it, when
        it expired, or when it left pending meanwhile.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce_sha256, str) or not nonce_sha256:
            raise HistoryError("nonce_sha256 is required")
        now = _now_iso()
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET nonce_sha256=? "
            "WHERE dispatch_id=? AND state=? AND expires_at>? AND nonce_sha256 IS NULL",
            nonce_sha256, dispatch_id, "pending", now,
        )
        return _changed_rows(written) == 1

    async def consume_oracle_mesh_dispatch(
        self, *, dispatch_id: str, nonce: str
    ) -> dict[str, Any] | None:
        """#4139 — accept one result submission for one dispatch, atomically.

        Two clearly separated paths:

        * **First submission.** A conditional ``pending -> received`` update
          is the single-winner gate. Only the request whose update actually
          changed the row is accepted; every concurrent loser updates nothing
          and receives ``None`` (409), so a duplicate delivery can never look
          like the winner.
        * **Retry after a transient conversation-store failure.** A prior
          attempt parked the row in ``store_failed`` with its claim intact.
          That state is not a race — the winner already finished — so the same
          nonce is accepted again as ``claim="retry"``. The append itself is
          idempotent, so a retry can never add a second message, and the PC
          file is never read again.

        Anything else — unknown dispatch, expired claim, foreign nonce,
        already ``done``/``failed`` — is refused.
        """
        import hashlib as _hashlib
        import hmac as _hmac

        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce, str) or not nonce:
            return None
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=?",
            dispatch_id,
        )
        if row is None:
            return None
        expected = row.get("nonce_sha256")
        if (
            not isinstance(expected, str) or not expected
            or not isinstance(row.get("expires_at"), str)
            or row["expires_at"] <= _now_iso()
        ):
            return None
        presented = _hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        if not _hmac.compare_digest(presented, expected):
            return None
        state = row.get("state")
        if state == "store_failed":
            # The winner already failed to store; this is its retry. Move the
            # row back to received under a guarded update so the close below
            # stays a single uniform transition.
            written = await self._run(
                "UPDATE oracle_mesh_dispatch SET state=? "
                "WHERE dispatch_id=? AND state=? AND nonce_sha256=?",
                "received", dispatch_id, "store_failed", expected,
            )
            if _changed_rows(written) != 1:
                return None
            return {**dict(row), "state": "received", "claim": "retry"}
        if state != "pending":
            return None
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=? AND nonce_sha256=?",
            "received", dispatch_id, "pending", expected,
        )
        if _changed_rows(written) != 1:
            # A concurrent submission won this dispatch.
            return None
        accepted = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=?",
            dispatch_id,
        )
        if accepted is None or accepted.get("state") != "received":
            return None
        return {**dict(accepted), "claim": "first"}

    async def record_oracle_mesh_first_result(
        self, *, dispatch_id: str, content_sha256: str, content_bytes: int
    ) -> bool:
        """#4139 — pin the first accepted result fingerprint for one dispatch.

        A resend after a transient store failure must be the *same* result: the
        executor never re-reads the PC file, so the server pins what arrived
        first and compares every retry against it. A mismatch is refused instead
        of appending a second, different body to the same conversation.
        """
        for name, value in (("dispatch_id", dispatch_id),
                            ("content_sha256", content_sha256)):
            if not isinstance(value, str) or not value:
                raise HistoryError(f"{name} is required")
        if isinstance(content_bytes, bool) or not isinstance(content_bytes, int):
            raise HistoryError("content_bytes must be an integer")
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET result_sha256=?, result_bytes=? "
            "WHERE dispatch_id=? AND result_sha256 IS NULL",
            content_sha256, content_bytes, dispatch_id,
        )
        if _changed_rows(written) != 1:
            pinned = await self._first(
                "SELECT result_sha256, result_bytes FROM oracle_mesh_dispatch "
                "WHERE dispatch_id=?",
                dispatch_id,
            )
            return (
                pinned is not None
                and pinned.get("result_sha256") == content_sha256
                and pinned.get("result_bytes") == content_bytes
            )
        return True

    async def mark_oracle_mesh_store_failed(self, *, dispatch_id: str) -> bool:
        """#4139 — park a received dispatch so the same result can be resent.

        Only a transient conversation-store failure reaches here. The claim and
        expiry stay intact, the PC file is not read again, and the retry is
        still single-delivery because the append is idempotent.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=?",
            "store_failed", dispatch_id, "received",
        )
        parked = await self._first(
            "SELECT state FROM oracle_mesh_dispatch WHERE dispatch_id=?",
            dispatch_id,
        )
        return parked is not None and parked.get("state") == "store_failed"

    async def finish_oracle_mesh_dispatch(
        self, *, dispatch_id: str, outcome: str
    ) -> bool:
        """#4139 — close one received (or retried) dispatch, once.

        A retry submission parks the row back in ``received``, so both the
        first and the retry path close through the same guarded transition.
        """
        if outcome not in ("done", "failed"):
            raise HistoryError("outcome must be done or failed")
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=?",
            outcome, dispatch_id, "received",
        )
        return _changed_rows(written) == 1

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
        p01_run_id: str | None = None,
    ) -> None:
        """Persist one owner-scoped approval handoff under the history owner (#2956).

        Exact replay of the same owner+run identity is idempotent. A conflicting
        continuation_ref / pause_id / trusted request for the same owner+run
        fails closed with ``HistoryConflict``. Cross-owner reads never disclose
        existence because every statement is owner-scoped by ``user_id``.

        #2961: one already-consumed row may be replaced, because a second Engine
        approval pause for the same Claw run is a new continuation generation and
        must never reuse the decided identity. An active row still conflicts.
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
        # #2961: the Engine-issued P01 run identity is optional at write time so
        # a #2956-era caller stays valid, but a handoff written without it can
        # never be consumed: the decision boundary fails closed instead.
        if p01_run_id is not None:
            p01_run_id = _safe_identifier("p01_run_id", p01_run_id)
        encoded, fingerprint = _handoff_trusted_request_json(trusted_request)
        existing = await self._first(
            "SELECT id, continuation_ref, pause_id, pause_expires_at, trusted_request_fingerprint, "
            "workspace_id, conversation_id, p01_run_id, consumed_at "
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
                and existing.get("p01_run_id") == p01_run_id
            ):
                return
            consumed_at = existing.get("consumed_at")
            if consumed_at is None or str(consumed_at).startswith("decision_claim:"):
                # An in-flight Engine decision is not an already-consumed
                # generation. Never replace its pause while dispatch is unknown.
                raise HistoryConflict(
                    f"claw approval handoff for run {run_id} already exists with a different identity"
                )
            # Guard the generation transition against a simultaneous new
            # claim or competing pause replacement (no stale SELECT -> write).
            replaced = await self._first(
                "UPDATE claw_approval_handoff SET workspace_id=?, conversation_id=?, continuation_ref=?, "
                "pause_id=?, pause_expires_at=?, trusted_request_json=?, trusted_request_fingerprint=?, "
                "p01_run_id=?, consumed_at=NULL WHERE id=? AND consumed_at=? RETURNING id",
                workspace_id, conversation_id, continuation_ref,
                pause_id, pause_expires_at, encoded, fingerprint, p01_run_id,
                str(existing.get("id")), str(consumed_at),
            )
            if replaced is None:
                raise HistoryConflict(
                    f"claw approval handoff for run {run_id} changed during replacement"
                )
            return
        await self._run(
            "INSERT INTO claw_approval_handoff (id, user_id, run_id, workspace_id, conversation_id, "
            "continuation_ref, pause_id, pause_expires_at, trusted_request_json, trusted_request_fingerprint, "
            "p01_run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _handoff_id(), user_id, run_id, workspace_id, conversation_id,
            continuation_ref, pause_id, pause_expires_at, encoded, fingerprint,
            p01_run_id, _now_iso(),
        )

    async def load_claw_approval_handoff(
        self,
        user_id: str,
        run_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Load one owner+run handoff; cross-scope and expired rows are non-disclosing.

        A foreign owner or foreign workspace returns ``None`` (never an existence
        oracle). An expired pause is unusable and also returns ``None``. A
        consumed handoff (#2961) is never returned, so a decided pause cannot be
        replayed.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(run_id, str) or not run_id:
            return None
        if workspace_id is not None:
            scoped = _safe_identifier("workspace_id", workspace_id)
            row = await self._first(
                "SELECT user_id, run_id, workspace_id, conversation_id, continuation_ref, pause_id, "
                "pause_expires_at, trusted_request_json, trusted_request_fingerprint, p01_run_id, created_at "
                "FROM claw_approval_handoff WHERE user_id=? AND run_id=? AND workspace_id=? "
                "AND consumed_at IS NULL",
                user_id, run_id, scoped,
            )
        else:
            row = await self._first(
                "SELECT user_id, run_id, workspace_id, conversation_id, continuation_ref, pause_id, "
                "pause_expires_at, trusted_request_json, trusted_request_fingerprint, p01_run_id, created_at "
                "FROM claw_approval_handoff WHERE user_id=? AND run_id=? AND consumed_at IS NULL",
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
        try:
            _encoded, recomputed_fingerprint = _handoff_trusted_request_json(trusted)
        except HistoryError:
            return None
        stored_fingerprint = str(row.get("trusted_request_fingerprint") or "")
        if not stored_fingerprint or recomputed_fingerprint != stored_fingerprint:
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
            "p01_run_id": row.get("p01_run_id"),
            "created_at": str(row.get("created_at") or ""),
        }

    async def claim_claw_approval_handoff(
        self,
        *,
        user_id: str,
        run_id: str,
        workspace_id: str | None,
        continuation_ref: str,
        pause_id: str,
        trusted_request_fingerprint: str,
    ) -> str | None:
        """Atomically elect exactly one Engine decision dispatcher (#3936).

        The existing consumed_at column holds a server-minted in-flight claim;
        NULL means available, a decision_claim: token means potentially sent,
        and a normal timestamp means conclusively consumed. An ambiguous
        Engine outcome stays claimed: retrying could duplicate a side effect.
        """
        if not isinstance(user_id, str) or not user_id or not isinstance(run_id, str) or not run_id:
            return None
        if not all(isinstance(v, str) and v for v in
                   (continuation_ref, pause_id, trusted_request_fingerprint)):
            return None
        token = "decision_claim:" + uuid.uuid4().hex
        sql = (
            "UPDATE claw_approval_handoff SET consumed_at=? "
            "WHERE user_id=? AND run_id=? AND continuation_ref=? AND pause_id=? "
            "AND trusted_request_fingerprint=? AND consumed_at IS NULL "
            "AND julianday(pause_expires_at) > julianday('now') "
        )
        params: list[Any] = [token, user_id, run_id, continuation_ref, pause_id,
                             trusted_request_fingerprint]
        if workspace_id is None:
            sql += "AND workspace_id IS NULL "
        else:
            sql += "AND workspace_id=? "
            params.append(_safe_identifier("workspace_id", workspace_id))
        # SQLite / Cloudflare D1 execute the CAS and RETURNING in one statement.
        # No read-before-update check, local process lock or follow-up SELECT
        # can elect the winning dispatcher across multiple Workers.
        row = await self._first(sql + "RETURNING id", *params)
        return token if row is not None else None

    async def release_claw_approval_claim(
        self, *, user_id: str, run_id: str, workspace_id: str | None,
        claim_token: str,
    ) -> bool:
        """Release ONLY a proven NOT_DISPATCHED claim, guarded against ABA."""
        if not isinstance(claim_token, str) or not claim_token.startswith("decision_claim:"):
            return False
        sql = ("UPDATE claw_approval_handoff SET consumed_at=NULL "
               "WHERE user_id=? AND run_id=? AND consumed_at=? ")
        params: list[Any] = [user_id, run_id, claim_token]
        if workspace_id is None:
            sql += "AND workspace_id IS NULL "
        else:
            sql += "AND workspace_id=? "
            params.append(_safe_identifier("workspace_id", workspace_id))
        return await self._first(sql + "RETURNING id", *params) is not None

    async def finalize_claw_approval_claim(
        self, *, user_id: str, run_id: str, workspace_id: str | None,
        claim_token: str,
    ) -> bool:
        """Finalize a claimed handoff only after verified Engine resolution."""
        if not isinstance(claim_token, str) or not claim_token.startswith("decision_claim:"):
            return False
        sql = ("UPDATE claw_approval_handoff SET consumed_at=? "
               "WHERE user_id=? AND run_id=? AND consumed_at=? ")
        params: list[Any] = [_now_iso(), user_id, run_id, claim_token]
        if workspace_id is None:
            sql += "AND workspace_id IS NULL "
        else:
            sql += "AND workspace_id=? "
            params.append(_safe_identifier("workspace_id", workspace_id))
        return await self._first(sql + "RETURNING id", *params) is not None

    async def consume_claw_approval_handoff(
        self,
        user_id: str,
        run_id: str,
        workspace_id: str | None = None,
    ) -> bool:
        """Mark one owner+run handoff unusable after the Engine proved consumption (#2961).

        One bounded ``consumed_at`` marker under the existing history owner: no
        new store, no claim token, no Engine state. Scoped by owner (and
        workspace when supplied) so a caller can never consume another owner's
        handoff, and never overwrites an already-consumed row.
        """
        if not isinstance(user_id, str) or not user_id:
            return False
        if not isinstance(run_id, str) or not run_id:
            return False
        columns = "SELECT id FROM claw_approval_handoff WHERE user_id=? AND run_id=? AND consumed_at IS NULL"
        values: list[Any] = [user_id, run_id]
        if workspace_id is not None:
            values.append(_safe_identifier("workspace_id", workspace_id))
            columns += " AND workspace_id=?"
        else:
            # An unscoped consume must not become a cross-workspace write.
            columns += " AND workspace_id IS NULL"
        owned = await self._first(columns, *values)
        if owned is None:
            return False
        await self._run(
            "UPDATE claw_approval_handoff SET consumed_at=? WHERE id=?",
            _now_iso(), str(owned.get("id")),
        )
        return True