from __future__ import annotations

import hashlib
import inspect
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
#: #5015 the lane actions whose run may hold more than one PC tool call. The
#: 063 dispatch scope (``tool_call_ref``) is written only by the trusted PC file
#: tool lane, and that lane is this one; the marker therefore names the same
#: lane the dispatch scope names, without a second authority.
MULTI_COMMAND_RUN_ACTIONS = frozenset({"pc_files_query"})

#: #5895 — how long one executor claim is held before the same dispatch may be
#: handed out again. The Oracle executor holds a poll open for 20 seconds and
#: re-requests about a second after an empty or dead round, so a claim whose
#: response never reached it is offered again inside roughly three of those
#: rounds. This is a delivery timer, not a workload limit: it decides nothing
#: about how long a PC command may run, and the instant that ends a dispatch
#: stays the `expires_at` the poll route stamps (#4139).
ORACLE_MESH_CLAIM_LEASE_SECONDS = 60

MAX_CLAW_HANDOFF_TRUSTED_REQUEST_CHARS = 32000


def is_multi_command_action(action: object) -> bool:
    """#5015 — True when one run may store more than one PC tool-call result."""

    return isinstance(action, str) and action in MULTI_COMMAND_RUN_ACTIONS


def _merge_run_result_summaries(stored: object, addition: str) -> str:
    """#5015 — the run's aggregate summary over its commands' own summaries.

    The aggregate keeps the order the commands finished in, never repeats one
    summary, and stays inside the run summary bound. A failure is never
    dropped: the caller stores the failing command's own summary, and this
    merge keeps it in the aggregate.
    """

    parts: list[str] = []
    if isinstance(stored, str) and stored:
        parts = [part for part in stored.split("; ") if part]
    if addition and addition not in parts:
        parts.append(addition)
    return "; ".join(parts)[:MAX_RUN_RESULT_SUMMARY_CHARS]


#: #4139 mesh result originals share the private full-context R2 store with
#: chat/model full texts. The bound is the result wire envelope the server
#: already accepted and verified (6 MB), not a new trial number: the bytes are
#: already in memory, so storing adds no second buffer beyond the one UTF-8
#: encode. R2 keys stay server-derived (conversation + deterministic result
#: id); a browser can never choose an object key.
ORACLE_MESH_ORIGINAL_MAX_BYTES = 6_000_000
ORACLE_MESH_PC_READ_ORIGINAL_MAX_BYTES = 20_000_000


def _oracle_mesh_original_max_bytes(row: dict[str, Any]) -> int:
    # The persisted server dispatch owns this distinction, never a store-call
    # argument or model value. Commands and other reads retain the 6MB guard.
    if row.get("kind") == "read" and row.get("root_ref") == "pc_files_read":
        return ORACLE_MESH_PC_READ_ORIGINAL_MAX_BYTES
    return ORACLE_MESH_ORIGINAL_MAX_BYTES


#: #4139 dispatch row bounds. Each number is the ceiling of the thing it
#: describes, not a safety guess:
#: * a reference keeps the bound this table has always used;
#: * a Windows path is bounded by the documented maximum path length
#:   (32,767 characters with the extended-length prefix; Microsoft, "Maximum
#:   Path Length Limitation"), because a Korean or long PC path is ordinary
#:   input and the former 1,024-character bound rejected it;
#: * the row as a whole is bounded by Cloudflare D1's documented
#:   "Maximum string, BLOB or table row size: 2,000,000 bytes". A command carries
#:   no product length rule: it travels as a bound parameter, so the 100,000-byte
#:   SQL-statement ceiling does not apply to it, and the row it is written into
#:   is the storage boundary. The execution boundary is separate and belongs to
#:   the host (the command port refuses a wrapped command over one argv element),
#:   not to this table.
MAX_MESH_REFERENCE_CHARS = 1024
MAX_MESH_PATH_CHARS = 32_767
MAX_MESH_ROW_BYTES = 2_000_000
_MESH_PATH_FIELDS = frozenset({"path_relative", "file_path"})
#: #4139 terminal/file result ids: the deterministic `msg_ltr_<40hex>` base
#: from the result projection, plus the conversation splitter suffix.
_MESH_RESULT_MESSAGE_ID_RE = re.compile(r"msg_ltr_[0-9a-f]{40}(_p[0-9]+)?")

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

# #5226 — one statement appends a turn, and it allocates the sequence numbers
# itself. The sequence is read inside the same write transaction that performs
# the insert, so a concurrent append to the same conversation can never claim a
# sequence_number another append already took, and a turn can never be half
# written: the user row and the assistant row are the same statement, so they
# land together or not at all. The pre-existing `UNIQUE(conversation_id,
# sequence_number)` stays the schema authority; this is what stops two writers
# from racing into it.
#
# The `next_sequence` CTE is read once for the statement, so the user row takes
# `n` and the assistant row takes `n + 1` — adjacent, with no gap and no
# duplicated number. `COALESCE(MAX(...), -1) + 1` keeps a first turn at 0.
_APPEND_EXCHANGE_SQL = (
    "WITH next_sequence AS ("
    " SELECT COALESCE(MAX(sequence_number), -1) + 1 AS n"
    " FROM messages WHERE conversation_id = ?"
    ") "
    "INSERT INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
    "SELECT ?, ?, n, 'user', ?, ? FROM next_sequence "
    "UNION ALL "
    "SELECT ?, ?, n + 1, 'assistant', ?, ? FROM next_sequence"
)

#: #5226 — the same atomic sequence rule for a single stored turn (the Claw
#: pending user turn). One statement, one sequence, allocated under the write
#: lock, so two pending runs on one conversation never collide.
_APPEND_USER_MESSAGE_SQL = (
    "WITH next_sequence AS ("
    " SELECT COALESCE(MAX(sequence_number), -1) + 1 AS n"
    " FROM messages WHERE conversation_id = ?"
    ") "
    "INSERT INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
    "SELECT ?, ?, n, 'user', ?, ? FROM next_sequence"
)


def _require_product_scope(value: object) -> str:
    """Fail closed: only a known server-owned scope may address conversations."""
    if not isinstance(value, str) or value not in KNOWN_PRODUCT_SCOPES:
        raise HistoryForbidden("conversation product scope is not recognized")
    return value


#: The bounded wording of one admitted PC scope, keyed by the admission the
#: Engine already signed. It is a notice, never part of an answer.
PC_SCOPE_NOTICE_LABELS = {
    "files_list": "목록만 조회합니다. 파일 내용은 읽지 않습니다.",
    "files": "요청한 파일의 목록과 내용을 확인합니다.",
    "query_drives": "드라이브 목록만 조회합니다.",
    "none": "허용된 PC 작업 범위를 확인하지 못했습니다.",
}


def pc_scope_notice(claim: object) -> str | None:
    """The notice for a stored scope claim, or None for anything unknown."""
    if not isinstance(claim, dict):
        return None
    notice = PC_SCOPE_NOTICE_LABELS.get(claim.get("admitted"))
    return notice if isinstance(notice, str) else None

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
    async def find_password_credential_by_user_id(self, user_id: str) -> PasswordCredential | None: ...
    async def update_password_credential(self, user_id: str, password_hash: str) -> None: ...
    async def record_password_failure(self, user_id: str, failed_attempts: int, locked_until: str | None) -> None: ...
    async def reset_password_failures(self, user_id: str) -> None: ...
    async def get_user(self, user_id: str) -> UserProfile | None: ...
    async def list_conversations(self, user_id: str, *, product_scope: str, limit: int = MAX_RECENT_CONVERSATIONS) -> list[dict[str, Any]]: ...
    async def search_conversations(self, user_id: str, query: str, *, product_scope: str, limit: int = MAX_CONVERSATION_SEARCH_RESULTS) -> list[dict[str, Any]]: ...
    async def get_conversation(self, user_id: str, conversation_id: str, *, product_scope: str) -> dict[str, Any] | None: ...
    async def delete_conversation(self, user_id: str, conversation_id: str, *, product_scope: str) -> bool: ...
    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str, project_id: str | None = None, *, product_scope: str, assistant_message_id: str | None = None) -> str: ...
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


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


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


#: #5015: the run-scoped id of the assistant message that a model-only Claw run
#: stores for exactly that run. It follows the existing deterministic result-id
#: convention (``msg_ltr_<40hex>`` from a salted hash, the same shape
#: ``local_task_result_message_id`` produces), because the private full-context
#: key validator only accepts the canonical message identities. Deriving it from
#: the server-owned run id keeps the owner-scoped lookup correlatable without a
#: schema change and without ever matching a later turn's text.
GENERAL_ANSWER_MESSAGE_SALT = "claw-general-answer:v1"

#: #5015: the run action the general lane itself records. Only a run the
#: server stored under this action is a verified model-only execution; a PC,
#: desktop or staged run keeps its own action and is never answered from a
#: model reply.
MODEL_ONLY_RUN_ACTION = "general"


def general_answer_message_id(run_id: str) -> str:
    """The one message id a model-only run owns for its verified answer.

    The id must satisfy the canonical message identity the private full-context
    store accepts, otherwise a long answer (stored as a D1 preview plus an R2
    original) would fail its R2 key validation and take the whole conversation
    save down with it.
    """
    if not isinstance(run_id, str) or not run_id:
        raise HistoryError("run_id is required")
    payload = f"{GENERAL_ANSWER_MESSAGE_SALT}:{run_id}"
    message_id = "msg_ltr_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]
    if len(message_id) > 128:
        raise HistoryError("run-scoped answer message id is not bounded")
    return message_id


def _message_reference(value: object) -> str:
    """Validate a caller-supplied message id as a bounded safe reference."""
    if not isinstance(value, str) or not value or len(value) > 128:
        raise HistoryError("message id must be a bounded safe reference")
    if any(not (ch.isalnum() or ch in "_-") for ch in value):
        raise HistoryError("message id must be a bounded safe reference")
    return value


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


def validate_chat_pc_run_id(value: object) -> str | None:
    """#5015 — the canonical Chat PC run id (``chat_pcq_`` plus 32 hex).

    The same canonical id rule the conversation and project ids use, so a
    Chat PC run is addressable by its own id instead of by a widened pattern.
    """

    return _validate_hex_id(value, "chat_pcq_", "run_id")


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


def _is_bounded_preview(content: str) -> bool:
    """Whether a stored D1 row is the bounded preview of a longer original.

    A message longer than ``MAX_HISTORY_MESSAGE_CHARS`` is stored as a
    truncated preview plus the private original, and the preview is marked
    explicitly. Every read that has to return the *whole* stored text decides
    with this one predicate, so the preview can never be mistaken for the
    answer.
    """
    return (
        len(content) == MAX_HISTORY_MESSAGE_CHARS
        and content.endswith(HISTORY_PREVIEW_SUFFIX)
    )


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
        try:
            valid_conversation = validate_conversation_id(conversation_id)
        except ValueError:
            raise HistoryError("invalid canonical history object identity")
        if valid_conversation is None or not (
            isinstance(message_id, str)
            and (
                re.fullmatch(r"msg_[0-9a-f]{32}", message_id)
                or _MESH_RESULT_MESSAGE_ID_RE.fullmatch(message_id)
            )
        ):
            raise HistoryError("invalid canonical history object identity")
        return f"claw-model-context/v1/{conversation_id}/{message_id}.utf8"

    async def _put_full_message(self, conversation_id: str, message_id: str, raw: str, *, max_bytes: int = MAX_MODEL_CONTEXT_BYTES) -> str | None:
        if len(raw) <= MAX_HISTORY_MESSAGE_CHARS:
            return None
        data = raw.encode("utf-8")
        if len(data) > max_bytes:
            raise HistoryError("full text exceeds the bounded storage envelope")
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

    async def _delete_orphan_full_keys(self, keys: list[tuple[str, str]]) -> None:
        """Remove only the originals whose own message row never landed.

        A row that DID land keeps its R2 original, so a stored message never
        degrades into a preview-only row with a missing full text. The check is
        per message id, because the run-scoped answer id of #5015 is
        deterministic: a repeated completion event collides on the
        ``messages.id`` primary key, and that collision must not strip the
        original of the record that is already stored.

        A row that cannot be read is treated as landed: an original that might
        belong to a stored row is never destroyed on an unproven guess.
        """
        orphan_keys: list[str] = []
        for message_id, key in keys:
            try:
                landed = await self._first("SELECT id FROM messages WHERE id=?", message_id)
            except Exception:
                continue
            if not isinstance(landed, dict):
                orphan_keys.append(key)
        await self._delete_full_keys(orphan_keys)

    async def _read_full_message(self, conversation_id: str, row: dict[str, Any]) -> str:
        preview = str(row.get("content", ""))
        if not _is_bounded_preview(preview):
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

        #4317 perf: this used to call :meth:`get_conversation` first, which
        reads the conversation row *and* the bounded message preview, and then
        read the same message rows again for the full-original bodies. The
        preview read was pure waste on this path, so the conversation row is
        read directly here and the message rows are read once. The returned
        shape is unchanged.
        """
        scope = _require_product_scope(product_scope)
        conv = await self._first(
            "SELECT id, title, project_id, created_at, updated_at FROM conversations "
            "WHERE id=? AND user_id=? AND product_scope=?",
            conversation_id, user_id, scope,
        )
        if not conv:
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
        return {
            "id": str(conv.get("id", "")),
            "title": str(conv.get("title", "")),
            "project_id": (
                str(conv.get("project_id"))
                if conv.get("project_id") is not None
                else None
            ),
            "created_at": str(conv.get("created_at", "")),
            "updated_at": str(conv.get("updated_at", "")),
            "messages": full_messages,
        }

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

    async def find_password_credential_by_user_id(
        self, user_id: str
    ) -> PasswordCredential | None:
        """The credential row of one already known account.

        #5434: a self-service password change resolves the account from the
        signed session, never from a request-supplied identifier, so the
        lookup is keyed by the server-owned user id.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        row = await self._first(
            "SELECT u.id, u.email, u.display_name, u.picture_url, c.username, c.password_hash, "
            "c.failed_attempts, c.locked_until "
            "FROM password_credentials c JOIN users u ON u.id=c.user_id "
            "WHERE c.user_id=? LIMIT 1",
            user_id,
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

    async def update_password_credential(
        self, user_id: str, password_hash: str
    ) -> None:
        """Replace the stored hash of one account and clear its failure state.

        #5434: only the hash, the failure counter and the lock move. The
        account id, the role rows, the membership rows and every other
        account-owned record stay exactly as they were.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(password_hash, str) or not password_hash:
            raise HistoryError("password_hash is required")
        await self._run(
            "UPDATE password_credentials SET password_hash=?, failed_attempts=0, "
            "locked_until=NULL, updated_at=? WHERE user_id=?",
            password_hash,
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

    async def append_exchange(self, user_id: str, conversation_id: str | None, user_text: str, assistant_text: str, project_id: str | None = None, *, product_scope: str, assistant_message_id: str | None = None) -> str:
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

        # #5015: a model-only run stores its verified answer under a run-scoped
        # message id, so the owner-scoped lookup can correlate the stored
        # completion record with the actual message. The default stays the
        # random id, and an explicit id is never taken from a browser value.
        user_msg_id = _message_id()
        answer_msg_id = (
            _message_reference(assistant_message_id)
            if assistant_message_id is not None else _message_id()
        )
        r2_keys: list[tuple[str, str]] = []
        persisted = False
        try:
            for msg_id, raw in ((user_msg_id, user_text.strip()), (answer_msg_id, assistant_text.strip())):
                key = await self._put_full_message(cid, msg_id, raw)
                if key is not None:
                    r2_keys.append((msg_id, key))
            if creating:
                # Store private full text first; unavailable R2 must not leave
                # a misleading, empty D1 conversation for the first turn.
                await self._run(
                    "INSERT INTO conversations (id, user_id, project_id, title, created_at, updated_at, product_scope) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    cid, user_id, project_id, _title_from_user_text(user_content), now, now, scope,
                )
            # #5226: the whole exchange is one statement, so the user row and the
            # assistant row land together and the two sequence numbers are
            # allocated inside the same write transaction. Two concurrent
            # appends to one conversation therefore cannot collide on
            # `UNIQUE(conversation_id, sequence_number)` and cannot leave a
            # half-written turn behind.
            await self._run(
                _APPEND_EXCHANGE_SQL,
                cid,
                user_msg_id, cid, user_content, now,
                answer_msg_id, cid, assistant_content, now,
            )
            persisted = True
            await self._run("UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?", now, cid, user_id)
            if project_id is not None:
                await self._run("UPDATE projects SET updated_at=? WHERE id=? AND user_id=?", now, project_id, user_id)
        except Exception:
            # The R2 original is removed only when its D1 row never landed. A row
            # that DID land keeps its R2 original, so a stored message never
            # degrades into a preview-only row with a missing full text, and a
            # failed append leaves no orphan R2 object behind.
            # #5015: the run-scoped answer id is deterministic, so a repeated
            # completion event collides on the messages primary key instead of
            # appending the same answer twice. The row of the first record is
            # still there, and its original has to survive that collision.
            if not persisted:
                await self._delete_orphan_full_keys(r2_keys)
                if creating:
                    # A first turn that never landed must not leave an empty
                    # conversation behind.
                    try:
                        await self._run(
                            "DELETE FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
                            cid, user_id, scope,
                        )
                    except Exception:
                        pass
            raise
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
        else:
            owned = await self._first(
                "SELECT id,project_id FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
                cid, user_id, PRODUCT_SCOPE_CHAT,
            )
            if not owned:
                raise HistoryForbidden("conversation is not owned by current user")
            project_id = owned.get("project_id")
        now = _now_iso()
        msg_id = _message_id()
        key = await self._put_full_message(cid, msg_id, user_text.strip())
        persisted = False
        try:
            if creating:
                await self._run(
                    "INSERT INTO conversations (id,user_id,project_id,title,created_at,updated_at,product_scope) "
                    "VALUES (?,?,NULL,?,?,?,?)",
                    cid, user_id, _title_from_user_text(content), now, now, PRODUCT_SCOPE_CHAT,
                )
            # #5226: the same atomic sequence rule as a Chat exchange — the
            # turn number is allocated inside the write that stores the turn.
            await self._run(
                _APPEND_USER_MESSAGE_SQL,
                cid,
                msg_id, cid, content, now,
            )
            persisted = True
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
            # Only a turn that never landed may lose its R2 original.
            if not persisted and key is not None:
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

    async def _chat_stream_turn(self, user_id: str, run_id: str) -> dict | None:
        validate_chat_pc_run_id(run_id)
        return await self._first(
            "SELECT m.conversation_id,m.content FROM messages m "
            "JOIN conversations c ON c.id=m.conversation_id "
            "WHERE m.id=? AND m.role='user' AND c.user_id=? AND c.product_scope=? "
            "AND NOT EXISTS (SELECT 1 FROM messages a WHERE a.id IN (?,?,?))",
            general_answer_message_id(run_id + ":chat-stream-user"), user_id,
            PRODUCT_SCOPE_CHAT, general_answer_message_id(run_id + ":chat-stream-answer"),
            run_id + "_answer", run_id + "_final",
        )

    async def begin_chat_stream_turn(
        self, *, user_id: str, run_id: str, workspace_id: str,
        user_text: str, conversation_id: str | None,
    ) -> str:
        """Persist the real user turn, never a PC run before a tool is selected."""
        if (await self.get_claw_run(user_id, run_id) is not None
                or await self._first("SELECT id FROM messages WHERE id=?",
                    general_answer_message_id(run_id + ":chat-stream-user")) is not None):
            raise HistoryForbidden("Chat stream turn already exists")
        validate_chat_pc_run_id(run_id)
        return await self.record_chat_pc_drive_run(
            user_id=user_id, run_id=run_id, workspace_id=workspace_id,
            user_text=user_text, conversation_id=conversation_id, stage_run=False,
            user_message_id=general_answer_message_id(run_id + ":chat-stream-user"),
        )

    async def promote_chat_stream_pc_run(
        self, *, user_id: str, run_id: str, workspace_id: str, action: str,
    ) -> dict | None:
        """Called only after a signed Engine tool call revalidates its owner."""
        if action not in ("pc_files_query", "pc_drive_query"):
            raise HistoryForbidden("Invalid PC run action")
        turn = await self._chat_stream_turn(user_id, run_id)
        if turn is None:
            return None
        await self.record_claw_run(
            user_id=user_id, run_id=run_id, channel="web", action=action,
            title=("PC: " + turn["content"])[:MAX_HISTORY_TITLE_CHARS], status="pending",
            conversation_id=turn["conversation_id"], workspace_id=_safe_identifier("workspace_id", workspace_id),
        )
        return await self.get_claw_run(user_id, run_id)

    async def finish_chat_stream_turn(
        self, *, user_id: str, run_id: str, answer: str,
    ) -> str | None:
        """Append one answer to the already stored user turn, without duplication."""
        turn = await self._chat_stream_turn(user_id, run_id)
        if turn is None:
            raise HistoryForbidden("Chat stream turn is not pending")
        cid = turn["conversation_id"]
        run = await self.get_claw_run(user_id, run_id)
        if run is not None:
            # Reuse the existing PC completion invariants and verified summary.
            from .chat_pc_drive import _append_lane_answer
            if not await _append_lane_answer(None, self, uid=user_id, run_id=run_id, content=answer):
                return cid
        else:
            content = _bounded_text(answer, "assistant_text")
            message_id = general_answer_message_id(run_id + ":chat-stream-answer")
            key = await self._put_full_message(cid, message_id, answer.strip())
            try:
                await self._run(
                    _APPEND_USER_MESSAGE_SQL.replace("'user'", "'assistant'"),
                    cid, message_id, cid, content, _now_iso(),
                )
            except Exception:
                if key is not None:
                    await self._delete_orphan_full_keys([(message_id, key)])
                raise
        await self._run("UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                        _now_iso(), cid, user_id)
        return cid

    async def record_chat_pc_drive_run(
        self, *, user_id: str, run_id: str, workspace_id: str,
        user_text: str, conversation_id: str | None,
        action: str = "pc_drive_query",
        title_prefix: str = "PC 드라이브 조회: ",
        stage_run: bool = True, user_message_id: str | None = None,
    ) -> str:
        """Stage a real b62 Chat owner conversation + pending PC tool run.

        Chat-product twin of :meth:`record_txt_pending_run` for the #5015
        model-driven PC lanes: same conversation/user-message/run shape and
        the same PRODUCT_SCOPE_CHAT ownership, with the lane's own action and
        title so a Chat turn never reads as a Claw turn. The verified Mesh
        result alone is allowed to insert the assistant message later.
        """
        if action not in ("pc_drive_query", "pc_files_query"):
            raise HistoryError("unsupported Chat PC action")
        if not isinstance(title_prefix, str) or not title_prefix:
            raise HistoryError("Chat PC title prefix is required")
        workspace = _safe_identifier("workspace_id", workspace_id)
        content = _bounded_text(user_text, "user_text")
        cid = validate_conversation_id(conversation_id)
        creating = cid is None
        project_id = None
        if creating:
            cid = _chat_id()
        else:
            owned = await self._first(
                "SELECT id,project_id FROM conversations WHERE id=? AND user_id=? AND product_scope=?",
                cid, user_id, PRODUCT_SCOPE_CHAT,
            )
            if not owned:
                raise HistoryForbidden("conversation is not owned by current user")
            project_id = owned.get("project_id")
        now = _now_iso()
        msg_id = _message_reference(user_message_id) if user_message_id is not None else _message_id()
        key = await self._put_full_message(cid, msg_id, user_text.strip())
        persisted = False
        try:
            if creating:
                await self._run(
                    "INSERT INTO conversations (id,user_id,project_id,title,created_at,updated_at,product_scope) "
                    "VALUES (?,?,NULL,?,?,?,?)",
                    cid, user_id, _title_from_user_text(content), now, now, PRODUCT_SCOPE_CHAT,
                )
            # #5226: the same atomic sequence rule as a Chat exchange.
            await self._run(
                _APPEND_USER_MESSAGE_SQL,
                cid,
                msg_id, cid, content, now,
            )
            persisted = True
            if stage_run:
                await self.record_claw_run(
                    user_id=user_id, run_id=run_id, channel="web",
                    action=action, title=(title_prefix + content)[:MAX_HISTORY_TITLE_CHARS],
                    status="pending", conversation_id=cid, workspace_id=workspace,
                )
            await self._run(
                "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                now, cid, user_id,
            )
        except Exception:
            # Only a turn that never landed may lose its R2 original.
            if not persisted and key is not None:
                await self._delete_full_keys([key])
            raise
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
        """Narrow, guarded status-only update of one owner-scoped Claw run row (#2961). (#5015r)

        An owner approve/deny must not rewrite channel, action, title, session or
        workspace linkage, so this touches only ``status`` / ``updated_at`` and
        the bounded result summary. Rows are addressed by owner + run id, so a
        caller can never mutate another owner's run.

        The write is one atomic conditional UPDATE:

        - a row already at ``completed`` can never be overwritten by a later
          failure/cancel settle, and
        - an existing ``result_summary`` is never blanked to NULL by a
          summary-free settle call.

        ``False`` therefore also reports "the guarded write matched nothing",
        e.g. a late settle racing a verified completion.
        """
        if not isinstance(user_id, str) or not user_id:
            return False
        if not isinstance(run_id, str) or not run_id:
            return False
        summary = result_summary[:MAX_RUN_RESULT_SUMMARY_CHARS] if result_summary else None
        result = await self._run(
            "UPDATE claw_run_history SET status=?, updated_at=?, "
            "result_summary=CASE WHEN ? IS NULL THEN result_summary ELSE ? END "
            "WHERE run_id=? AND user_id=? AND status<>'completed'",
            status, _now_iso(), summary, summary, run_id, user_id,
        )
        return _changed_rows(result) > 0

    async def get_pc_run_scope(self, *, user_id: str, run_id: str) -> dict[str, Any] | None:
        """The immutable scope notice in the run's existing conversation."""
        row = await self._first(
            "SELECT m.content FROM messages m JOIN claw_run_history r "
            "ON r.conversation_id=m.conversation_id "
            "JOIN conversations c ON c.id=m.conversation_id AND c.user_id=r.user_id "
            "WHERE r.user_id=? AND r.run_id=? AND m.id=?",
            user_id, run_id, run_id + "_scope",
        )
        if row is None:
            return None
        try:
            content = row["content"]
            claim = json.loads(content.split("\n<!--pc_scope:", 1)[1].removesuffix("-->"))
            if not isinstance(claim, dict):
                raise ValueError("invalid scope")
            return claim
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HistoryError("stored PC scope is invalid") from exc

    async def get_pc_run_scope_notice(self, *, user_id: str, run_id: str) -> str | None:
        """The stored scope's notice wording, or None when nothing is pinned.

        An absent, foreign or malformed record is simply "no notice": the
        live answer and the recovery GET keep their existing shape.
        """
        try:
            claim = await self.get_pc_run_scope(user_id=user_id, run_id=run_id)
        except Exception:
            return None
        return pc_scope_notice(claim)

    async def pin_pc_run_scope(self, *, user_id: str, run_id: str, claim: dict[str, Any]) -> None:
        """Record before dispatch, once per owner/run; never alter its terminal."""
        owned = await self.get_claw_run(user_id, run_id)
        if not isinstance(owned, dict) or not owned.get("conversation_id"):
            raise HistoryForbidden("PC run is not owned")
        message_id = run_id + "_scope"
        if len(message_id) > 128:
            raise HistoryError("PC scope message id is invalid")
        encoded = json.dumps(claim, sort_keys=True, separators=(",", ":"))
        if claim.get("admitted") not in PC_SCOPE_NOTICE_LABELS or len(encoded) > 1024:
            raise HistoryError("PC scope claim is invalid")
        content = PC_SCOPE_NOTICE_LABELS[claim["admitted"]] + "\n<!--pc_scope:" + encoded + "-->"
        cid = owned["conversation_id"]
        # A concurrent conflicting admission loses INSERT OR IGNORE and the
        # read-back comparison refuses it. Existing messages carry the record;
        # no new authority table, migration, or terminal-status write is needed.
        await self._run(
            "INSERT OR IGNORE INTO messages (id,conversation_id,role,content,created_at,sequence_number) "
            "SELECT ?,c.id,'assistant',?,?,COALESCE((SELECT MAX(sequence_number) "
            "FROM messages WHERE conversation_id=c.id),0)+1 FROM conversations c "
            "JOIN claw_run_history r ON r.conversation_id=c.id AND r.user_id=c.user_id "
            "WHERE c.id=? AND r.user_id=? AND r.run_id=?",
            message_id, content, _now_iso(), cid, user_id, run_id,
        )
        if await self.get_pc_run_scope(user_id=user_id, run_id=run_id) != claim:
            raise HistoryForbidden("PC run scope is already fixed")

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
            "SELECT id, run_id, status, result_summary, conversation_id, workspace_id, "
            "updated_at, action FROM claw_run_history WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )

    async def get_claw_run_result_message(
        self, user_id: str, run_id: str, conversation_id: str,
    ) -> str | None:
        """Return only the correlated terminal message, never a later run's text."""
        from .claw_local_task_result_projection import result_message_id
        # Prefer the actual Oracle receipt. Claw may also have a preliminary
        # local correlation under the same run; it is not the completed Mesh
        # command/revision that minted the persisted assistant message.
        correlation = await self._first(
            "SELECT command_id, revision_ref FROM oracle_mesh_dispatch "
            "WHERE user_id=? AND run_id=? AND state='done'",
            user_id, run_id,
        )
        if not isinstance(correlation, dict):
            correlation = await self.get_local_task_correlation(user_id, run_id)
        if not isinstance(correlation, dict):
            return None
        command_id = correlation.get("command_id")
        revision_ref = correlation.get("revision_ref")
        if not isinstance(command_id, str) or not isinstance(revision_ref, str):
            return None
        message_id = result_message_id(
            conversation_id=conversation_id,
            command_id=command_id, revision_ref=revision_ref,
        )
        # D1 rejects a LIKE pattern longer than 50 characters as "too complex",
        # and this exact id plus the split-part marker is already 51. A prefix
        # comparison keeps the same membership without the LIKE pattern.
        part_prefix = message_id + "_p"
        # #5015: a run that held more than one PC tool call answers with its
        # own final answer beside the command outputs, so the final message of
        # such a run is read too. The id belongs to that lane alone, so a
        # single-command run reads exactly what it read before.
        final_id = run_id + "_final"
        rows = await self._all(
            "SELECT m.id, m.content FROM messages m JOIN conversations c "
            "ON c.id=m.conversation_id WHERE m.role='assistant' "
            "AND m.conversation_id=? AND c.user_id=? AND c.product_scope=? "
            "AND (m.id=? OR substr(m.id, 1, ?)=? OR m.id=?) "
            "ORDER BY m.sequence_number LIMIT 16",
            conversation_id, user_id, PRODUCT_SCOPE_CHAT,
            message_id, len(part_prefix), part_prefix, final_id,
        )
        return "\n".join(row["content"] for row in rows) if rows else None

    async def get_claw_run_result(
        self, user_id: str, run_id: str, conversation_id: str,
    ) -> dict[str, str] | None:
        """The owner's completed run result, correlated to the actual message.

        Two proven sources, and never a summary substitution:

        * a completed Mesh / Local Runner command run resolves through the
          dispatch correlation to the assistant message that holds the verified
          PC command result (``pc_command_result``);
        * a completed model-only run resolves through the run-scoped answer
          message the general lane stored for exactly that run
          (``model_reply``).

        Both branches are bounded by the owner's own run row, its conversation
        and the message row itself, so a later turn's text can never be
        returned for an older run. An unverified run returns ``None`` so the
        caller keeps its truthful state instead of claiming a success.

        A model reply is only ever returned for a run the server itself
        recorded as a model-only execution. A run with a PC execution
        correlation keeps its existing unavailable state when its own verified
        result is missing, and a run whose recorded action is not the
        model-only action is never answered from a model reply.

        A model reply is the run's *actual* stored answer: a long answer is
        kept as a bounded D1 preview plus the private original, so the
        original is restored before it is returned. The bounded preview is
        never presented as the answer.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        correlation = await self._first(
            "SELECT command_id, revision_ref FROM oracle_mesh_dispatch "
            "WHERE user_id=? AND run_id=? AND state='done'",
            user_id, run_id,
        )
        if not isinstance(correlation, dict):
            # #5015: the legacy local-runner correlation table comes from a
            # source migration that a deployment may never have applied. The
            # Mesh dispatch row above is the authority for a PC execution, so
            # an unavailable legacy table can only mean "this deployment holds
            # no local-runner correlation" - it must never turn a model-only
            # run into an unavailable result. A PC run stays unavailable
            # through its own action record instead.
            try:
                correlation = await self.get_local_task_correlation(user_id, run_id)
            except Exception:
                correlation = None
        pc_correlated = (
            isinstance(correlation, dict)
            and isinstance(correlation.get("command_id"), str)
            and isinstance(correlation.get("revision_ref"), str)
        )
        if pc_correlated:
            # #5015: a PC execution run keeps its own verified-result contract.
            # The correlation may point at a dispatch whose message is stored
            # under the dispatch identity, so the established lookup is reused
            # unchanged. A PC run without its own verified result keeps the
            # truthful unavailable state; it is never answered from a model
            # reply.
            answer = await self.get_claw_run_result_message(
                user_id, run_id, conversation_id
            )
            if isinstance(answer, str) and answer:
                return {"answer": answer, "answer_source": "pc_command_result"}
            return None
        run_row = await self._first(
            "SELECT id, action, status, conversation_id FROM claw_run_history "
            "WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if not isinstance(run_row, dict):
            return None
        # Only a run the store itself recorded as a completed model-only
        # execution may answer with a model reply. A PC, desktop or staged run
        # keeps its own action and is never answered from one.
        if run_row.get("action") != MODEL_ONLY_RUN_ACTION:
            return None
        # A run that the store did not record as completed stays unverified.
        if run_row.get("status") != "completed":
            return None
        if run_row.get("conversation_id") != conversation_id:
            return None
        message_id = general_answer_message_id(run_id)
        rows = await self._all(
            "SELECT m.id, m.content FROM messages m JOIN conversations c "
            "ON c.id=m.conversation_id WHERE m.id=? AND m.role='assistant' "
            "AND m.conversation_id=? AND c.user_id=? AND c.product_scope=? "
            "ORDER BY m.sequence_number LIMIT 16",
            message_id, conversation_id, user_id, PRODUCT_SCOPE_CHAT,
        )
        if not rows:
            return None
        # #5015: a long model answer is stored as a bounded D1 preview plus the
        # private R2 original, so the D1 row is NOT the answer. The stored
        # original is restored through the same authority the model-context
        # read uses, inside the owner / run / conversation / assistant-message
        # scope the query above already proved. A row whose original is
        # unavailable stays unverified instead of answering with a truncated
        # preview body.
        contents: list[str] = []
        for row in rows:
            content = str(row.get("content", ""))
            if _is_bounded_preview(content):
                try:
                    content = await self._read_full_message(conversation_id, row)
                except HistoryContextIncomplete:
                    return None
            contents.append(content)
        answer = "\n".join(contents)
        if not answer:
            return None
        return {
            "answer": answer,
            "answer_source": "model_reply",
        }

    async def append_command_result(
        self,
        *,
        user_id: str,
        run_id: str,
        message_id: str,
        command_id: str,
        summary: str,
        content: str,
        status: str,
        preserve_edges: bool = False,
    ) -> bool:
        """#5015 — append one bounded per-command result of a multi-tool-call run.

        A PC tool-call run stores every command it executed, correlated by the
        dispatch's existing ``command_id``. The command's own terminal record
        stays the dispatch row (state/termination/exit_code/result digest) and
        its message row; the run row carries only the aggregate. Individual
        command completion is therefore distinct from overall work completion,
        which only the run's owner may seal through :meth:`seal_run_terminal`.

        No new result store is introduced: the per-command projection is the
        message row the caller already derives from the command identity, and
        the aggregate lives on the existing run row.

        Same structural guarantees as :meth:`append_local_task_result`, scoped
        to the command rather than the run:

        * **Exactly once per command.** The message id is derived by the caller
          from the command identity and the insert is ``INSERT OR IGNORE``
          against the ``messages.id`` primary key, so a repeat append is a
          no-op rather than a second row.
        * **Per-command terminal immutability.** A command that already carries
          a different terminal outcome is refused before any statement is
          issued, so one command can never be rewritten by another outcome.
        * **Aggregate truthfulness.** A command result never seals the run:
          a completed command leaves the run ``running`` and a failed command
          leaves it ``failed``, so the overall completion stays the run
          owner's decision.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
            raise HistoryError("message_id must be a bounded safe reference")
        if not isinstance(command_id, str) or not command_id or len(command_id) > 128:
            raise HistoryError("command_id must be a bounded safe reference")
        if status not in ("completed", "failed"):
            raise HistoryError("command result status must be completed or failed")
        body = _bounded_text(content, "local_task_result", preserve_edges=preserve_edges)
        if len(body) > MAX_HISTORY_MESSAGE_CHARS:
            raise HistoryError("local_task_result is not bounded")
        owned = await self._first(
            "SELECT id, conversation_id, result_summary, status FROM claw_run_history "
            "WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        conversation_id = owned.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise HistoryError("claw run has no originating conversation")
        # The command scope must name a command this owner dispatched inside
        # this run: a result can never be attached to a command of another run
        # or of another owner.
        dispatched = await self._first(
            "SELECT dispatch_id FROM oracle_mesh_dispatch "
            "WHERE user_id=? AND run_id=? AND command_id=? LIMIT 1",
            user_id, run_id, command_id,
        )
        if dispatched is None:
            raise HistoryError("claw run command is not dispatched for this run")
        bounded_summary = summary[:MAX_RUN_RESULT_SUMMARY_CHARS]
        already = await self._first(
            "SELECT id, content FROM messages WHERE id=? AND conversation_id=?",
            message_id, conversation_id,
        )
        if already is not None:
            # The command's projection is already durable. The identical result
            # is inert; a different outcome for the same command is refused, so
            # one command can never carry two contradictory results.
            if str(already.get("content") or "") != body:
                raise HistoryError(
                    "claw run command already carries a different terminal result"
                )
            return False
        now = _now_iso()
        aggregate_status = "failed" if status == "failed" else "running"
        aggregate_summary = _merge_run_result_summaries(
            owned.get("result_summary"), bounded_summary,
        )
        statements = [
            # The message insert is scoped to a conversation owned by user_id
            # through the conversations join, so a run pointing at someone
            # else's conversation inserts nothing and discloses nothing.
            self.db.prepare(
                "INSERT OR IGNORE INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
                "SELECT ?, c.id, "
                "(SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM messages WHERE conversation_id = c.id), "
                "'assistant', ?, ? FROM conversations c "
                "JOIN claw_run_history r ON r.id = ? "
                "WHERE c.id = ? AND c.user_id = ?"
            ).bind(message_id, body, now, str(owned.get("id")),
                   conversation_id, user_id),
            # The aggregate only moves when the command's own message actually
            # landed, so a refused insert can never leave a run claiming a
            # command result that was never stored. A run that is already
            # completed keeps that terminal: a late command result never
            # reopens it.
            self.db.prepare(
                "UPDATE claw_run_history SET status=?, updated_at=?, result_summary=? "
                "WHERE id=? AND status != 'completed' "
                "AND EXISTS (SELECT 1 FROM messages WHERE id=? AND conversation_id=?)"
            ).bind(aggregate_status, now, aggregate_summary, str(owned.get("id")),
                   message_id, conversation_id),
        ]
        results = await self.db.batch(statements)
        if _batch_returned_row(results, 1) is None:
            return False
        await self._run(
            "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
            now, conversation_id, user_id,
        )
        return True

    async def seal_run_terminal(
        self,
        *,
        user_id: str,
        run_id: str,
        message_id: str | None = None,
        summary: str,
        content: str | None = None,
        status: str,
    ) -> bool:
        """#5015 — record the overall completion of a multi-command run.

        Only the run's owner may seal the aggregate, and the seal is refused
        while the run's own commands have not all reached a terminal result or
        while one of them failed. A run can therefore never read as completed
        while a command is pending, and a failed command is never reported as
        an overall success.

        An already-completed run keeps its first terminal (terminal
        immutability). A run that already failed stays failed: a later success
        never upgrades it.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if status not in ("completed", "failed"):
            raise HistoryError("run terminal status must be completed or failed")
        if message_id is not None and (
            not isinstance(message_id, str) or not message_id or len(message_id) > 128
        ):
            raise HistoryError("message_id must be a bounded safe reference")
        owned = await self._first(
            "SELECT id, conversation_id, result_summary, status FROM claw_run_history "
            "WHERE run_id=? AND user_id=?",
            run_id, user_id,
        )
        if owned is None:
            raise HistoryForbidden("claw run is not owned by current user")
        conversation_id = owned.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise HistoryError("claw run has no originating conversation")
        if str(owned.get("status") or "") == "completed":
            # The first terminal of a completed run is never rewritten.
            return False
        if status == "completed":
            if str(owned.get("status") or "") == "failed":
                # A command of this run already failed: the work can never
                # read as an overall success.
                raise HistoryError("claw run carries a failed command")
            pending = await self._first(
                "SELECT dispatch_id, state FROM oracle_mesh_dispatch "
                "WHERE user_id=? AND run_id=? AND state NOT IN ('done', 'failed') LIMIT 1",
                user_id, run_id,
            )
            if pending is not None:
                raise HistoryError("claw run has commands without a terminal result")
            failed = await self._first(
                "SELECT dispatch_id FROM oracle_mesh_dispatch "
                "WHERE user_id=? AND run_id=? AND state='failed' LIMIT 1",
                user_id, run_id,
            )
            if failed is not None:
                raise HistoryError("claw run carries a failed command")
        now = _now_iso()
        bounded_summary = summary[:MAX_RUN_RESULT_SUMMARY_CHARS]
        statements = [self.db.prepare(
            "UPDATE claw_run_history SET status=?, updated_at=?, "
            "result_summary=CASE WHEN result_summary IS NULL THEN ? ELSE result_summary END "
            "WHERE id=? AND status != 'completed'"
        ).bind(status, now, bounded_summary, str(owned.get("id")))]
        if message_id is not None and content is not None:
            body = _bounded_text(content, "local_task_result")
            if len(body) > MAX_HISTORY_MESSAGE_CHARS:
                raise HistoryError("local_task_result is not bounded")
            statements.append(self.db.prepare(
                "INSERT OR IGNORE INTO messages (id, conversation_id, sequence_number, role, content, created_at) "
                "SELECT ?, c.id, "
                "(SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM messages WHERE conversation_id = c.id), "
                "'assistant', ?, ? FROM conversations c "
                "JOIN claw_run_history r ON r.id = ? "
                "WHERE c.id = ? AND c.user_id = ?"
            ).bind(message_id, body, now, str(owned.get("id")),
                   conversation_id, user_id))
        results = await self.db.batch(statements)
        if _batch_returned_row(results, 0) is None:
            return False
        await self._run(
            "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
            now, conversation_id, user_id,
        )
        return True

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
        command_scope: str | None = None,
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

        #5015: a command scope makes this a per-command result of a
        multi-tool-call run. Such a result is stored beside the other commands
        of the same run and never seals the run row; the run's overall
        completion is the run owner's own decision, sealed through
        :meth:`seal_run_terminal`. Without a command scope the single-command
        contract above is unchanged for every other lane.
        """

        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
            raise HistoryError("message_id must be a bounded safe reference")
        if command_scope is not None:
            if (
                not isinstance(command_scope, str)
                or not command_scope
                or len(command_scope) > 128
            ):
                raise HistoryError("command_scope must be a bounded safe reference")
            return await self.append_command_result(
                user_id=user_id, run_id=run_id, message_id=message_id,
                command_id=command_scope, summary=summary, content=content,
                status=status, preserve_edges=preserve_edges,
            )
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
        tool_call_ref: str | None = None,
    ) -> dict[str, Any]:
        """#4139 — stage one Oracle management-host execution for one run.

        The row snapshots the broker-bound correlation when Broker admission
        exists, plus the deployment-verified Mesh target. An identical pending
        row is reused, a terminal (done/failed) row refuses any second
        execution of the *same* correlation, and an expired pending row is
        replaced. Every statement is owner-scoped; cross-owner existence is
        never disclosed.

        ``tool_call_ref`` narrows the correlation key from the legacy one
        dispatch per owner+run to one dispatch per tool call inside that run.
        A bounded multi-tool turn (for example list then read) therefore stages
        a distinct row for each call, while re-staging the exact same call still
        finds its terminal row and refuses a second execution.

        The stored ``tool_call_ref`` (NULL for the legacy lane) is what 063's
        indexes enforce, and it is the database — not this read-then-write —
        that decides a concurrent staging: the loser of an INSERT race re-reads
        the winner's row and returns it only when it is the same payload, never
        when a different call won. The legacy lane is correlated to the
        run-scoped rows only, so a trusted file call staged in the same run is
        never selected, reused or replaced by it; the trusted lane keeps
        correlating on ``tool_request_ref`` so a row written before 063 (which
        has no scope column) is still found and still refuses a replay.

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
        if kind not in ("read", "command", "desktop"):
            raise HistoryError("kind must be read, command or desktop")
        if kind in ("command", "desktop"):
            # #4139 terminal lane: the command is the execution target, so it is
            # mandatory and it is ordinary text — Korean, quotes, tabs and
            # several lines. There is no product length rule; the bound is the
            # row it is written into. Only the characters that break the lane
            # are refused: NUL and the other C0 controls except tab and LF
            # (CR is refused because the exit-code sentinel is parsed per line).
            # The desktop lane carries its op in the same field
            # (``desktop:<op>`` plus an optional argument line) under the same
            # text rules, verified again by the executor before the PC acts.
            if not isinstance(command_text, str) or not command_text.strip():
                raise HistoryError("command_text is required for a command dispatch")
            if any(
                ord(ch) < 32 and ch not in "\t\n" for ch in command_text
            ) or "\x7f" in command_text:
                raise HistoryError("command_text carries a control character")
        elif command_text is not None:
            raise HistoryError("command_text is only valid for a command dispatch")
        for name, value in fields.items():
            if value is None:
                if name not in ("evidence_ref", "binding_ref", "command_text"):
                    raise HistoryError(f"{name} must be a bounded reference")
                continue
            if not isinstance(value, str) or not value:
                raise HistoryError(f"{name} must be a bounded reference")
            if name in _MESH_PATH_FIELDS:
                if len(value) > MAX_MESH_PATH_CHARS:
                    raise HistoryError(f"{name} exceeds the Windows path bound")
                if any(ord(ch) < 32 for ch in value):
                    raise HistoryError(f"{name} carries a control character")
                continue
            if name == "command_text":
                continue  # text, not a reference: bounded by the row below
            if len(value) > MAX_MESH_REFERENCE_CHARS:
                raise HistoryError(f"{name} must be a bounded reference")
        row_bytes = sum(
            len(value.encode("utf-8"))
            for value in fields.values() if isinstance(value, str)
        )
        if row_bytes > MAX_MESH_ROW_BYTES:
            raise HistoryError("oracle mesh dispatch row exceeds the storage row bound")
        if not isinstance(expires_at, str) or not expires_at:
            raise HistoryError("expires_at must be a bounded timestamp")
        if tool_call_ref is not None:
            if (
                not isinstance(tool_call_ref, str)
                or not tool_call_ref
                or len(tool_call_ref) > 128
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in tool_call_ref)
            ):
                raise HistoryError(
                    "tool_call_ref must be a bounded safe reference"
                )
            correlation_sql = "user_id=? AND run_id=? AND tool_request_ref=?"
            correlation_params = (user_id, run_id, tool_call_ref)
        else:
            # The legacy single-command lane owns the run-scoped rows and
            # nothing else. Selecting by run alone would read a trusted file
            # call of the same run as if it were the legacy dispatch, and an
            # expired pending file row would then be replaced — losing the
            # file call's own replay protection.
            correlation_sql = "user_id=? AND run_id=? AND tool_call_ref IS NULL"
            correlation_params = (user_id, run_id)
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
            f"state, expires_at FROM oracle_mesh_dispatch WHERE {correlation_sql}",
            *correlation_params,
        )
        def same_payload(row: dict[str, Any]) -> bool:
            return all(
                row.get(name) == value
                for name, value in fields.items()
                if name not in ("user_id", "run_id")
            )

        now = _now_iso()
        if existing is not None:
            same = same_payload(existing)
            if same and existing.get("state") == "pending" and existing.get("expires_at", "") > now:
                return dict(existing)
            if same and existing.get("state") in ("done", "failed"):
                raise HistoryError("oracle mesh run already executed")
            if not (existing.get("state") == "pending" and existing.get("expires_at", "") <= now):
                raise HistoryError("oracle mesh run already dispatched")
            if kind in ("command", "desktop") and (
                existing.get("nonce_sha256") is not None
                or existing.get("state") in ("received", "store_failed")
            ):
                # A terminal command — or a desktop input, which also mutates
                # the PC — may ALREADY have run: the row was handed to the
                # executor (a nonce was minted) or its result was received but
                # never stored. Re-staging it would let a restart execute the
                # same action again, so the row is left exactly as it is — an
                # uncertain state, never a silent second execution.
                raise HistoryError("oracle mesh command execution is uncertain")
            await self._run(
                "UPDATE oracle_mesh_dispatch SET command_id=?, tool_request_ref=?, "
                "request_id=?, revision_ref=?, evidence_ref=?, request_fingerprint=?, "
                "account_ref=?, workspace_ref=?, device_id=?, binding_ref=?, node_ref=?, "
                "root_ref=?, path_relative=?, file_path=?, kind=?, command_text=?, "
                "tool_call_ref=?, nonce_sha256=NULL, claimed_until=NULL, state=?, "
                "expires_at=?, created_at=? WHERE "
                f"{correlation_sql} AND state=? AND expires_at<=?",
                command_id, tool_request_ref, request_id, revision_ref,
                evidence_ref, request_fingerprint, account_ref, workspace_ref,
                device_id, binding_ref, node_ref, root_ref, path_relative,
                file_path, kind, command_text, tool_call_ref,
                "pending", expires_at, now,
                *correlation_params, "pending", now,
            )
            replaced = await self._first(
                "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
                "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
                "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
                f"state, expires_at FROM oracle_mesh_dispatch WHERE {correlation_sql}",
                *correlation_params,
            )
            if replaced is None:
                raise HistoryError("oracle mesh dispatch unavailable")
            return dict(replaced)
        dispatch_id = "dsp_" + uuid.uuid4().hex
        try:
            await self._run(
                "INSERT INTO oracle_mesh_dispatch "
                "(dispatch_id, user_id, run_id, command_id, tool_request_ref, request_id, "
                "revision_ref, evidence_ref, request_fingerprint, account_ref, workspace_ref, "
                "device_id, binding_ref, node_ref, root_ref, path_relative, file_path, "
                "kind, command_text, tool_call_ref, "
                "nonce_sha256, state, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
                dispatch_id, user_id, run_id, command_id, tool_request_ref,
                request_id, revision_ref, evidence_ref, request_fingerprint,
                account_ref, workspace_ref, device_id, binding_ref, node_ref,
                root_ref, path_relative, file_path, kind, command_text,
                tool_call_ref, "pending", expires_at, now,
            )
        except Exception:
            # 063 makes the database the decider of a concurrent staging: two
            # requests can both read no row and then race to INSERT, and only
            # one of them can win. The loser resolves to the winner's row when
            # it is the exact same payload, and is refused otherwise — it never
            # reports a dispatch it did not stage, and it never retries the
            # INSERT.
            raced = await self._first(
                "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, "
                "revision_ref, evidence_ref, request_fingerprint, account_ref, workspace_ref, "
                "device_id, binding_ref, node_ref, root_ref, path_relative, file_path, "
                "nonce_sha256, state, expires_at FROM oracle_mesh_dispatch "
                f"WHERE {correlation_sql}",
                *correlation_params,
            )
            if raced is None:
                raise
            if (
                same_payload(raced)
                and raced.get("state") == "pending"
                and raced.get("expires_at", "") > now
            ):
                return dict(raced)
            if same_payload(raced) and raced.get("state") in ("done", "failed"):
                raise HistoryError("oracle mesh run already executed") from None
            raise HistoryError("oracle mesh run already dispatched") from None
        created = await self._first(
            "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
            "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
            f"state, expires_at FROM oracle_mesh_dispatch WHERE {correlation_sql}",
            *correlation_params,
        )
        if created is None:
            raise HistoryError("oracle mesh dispatch unavailable")
        return dict(created)

    async def oldest_pending_oracle_mesh_dispatch(self) -> dict[str, Any] | None:
        """#4139 — the single oldest claimable Oracle execution, if any.

        Claimable means pending, unexpired and either never handed out or handed
        out under a lease that has run out (#5895). A lease that ran out is the
        only evidence that a claim reached nobody: the poll route wrote the nonce
        and the response died before the executor could read it. The caller (the
        poll route, under the channel secret) re-claims atomically before
        responding; this read alone hands out nothing.
        """
        now = _now_iso()
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at FROM oracle_mesh_dispatch "
            "WHERE state=? AND expires_at>? "
            "AND (nonce_sha256 IS NULL OR (claimed_until IS NOT NULL AND claimed_until<=?)) "
            "ORDER BY created_at ASC LIMIT 1",
            "pending", now, now,
        )
        return dict(row) if row is not None else None

    async def claim_oracle_mesh_dispatch(
        self, *, dispatch_id: str, nonce_sha256: str
    ) -> bool:
        """#4139 — atomically hand one pending dispatch to the executor.

        The conditional update is the single-claim gate: exactly one poll wins
        one round. #5895 makes the hand-out a lease — the same UPDATE records the
        instant the claim may be handed out again, under the same condition the
        yield uses — so a claim whose response never reached the executor is not
        a permanent loss. Re-claiming rolls the nonce, so a submission still
        carrying the superseded nonce is refused by the existing nonce comparison
        instead of attaching a second result. Returns False when another poll won
        this round, when it expired, or when it left pending meanwhile.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce_sha256, str) or not nonce_sha256:
            raise HistoryError("nonce_sha256 is required")
        moment = datetime.now(timezone.utc)
        now = _iso(moment)
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET nonce_sha256=?, claimed_until=? "
            "WHERE dispatch_id=? AND state=? AND expires_at>? "
            "AND (nonce_sha256 IS NULL OR (claimed_until IS NOT NULL AND claimed_until<=?))",
            nonce_sha256,
            _iso(moment + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS)),
            dispatch_id, "pending", now, now,
        )
        return _changed_rows(written) == 1

    async def cancel_oracle_mesh_dispatches_for_run(
        self, *, user_id: str, run_id: str,
    ) -> int:
        """#5895 — stop one owner run's PC work, whether it is queued or running.

        ``pending`` with no claim nonce is exactly "no executor has ever seen
        this": stopping it removes the work from the queue, and the existing poll
        — which yields only ``pending`` rows — never hands it out again, so the
        next request the owner makes is claimed straight away instead of sitting
        behind it.

        A row that already carries a nonce is the case the owner is really asking
        about: the PC has the command and the wait has no deadline (#5995 took the
        client ceiling away, and a command the customer's shell never finishes -
        measured on 2026-10-28 - holds every later operation on that PC behind it).
        That row is not failed here. Its ``termination`` is set to ``cancelled``
        and its ``state`` stays ``pending``, so the executor can read the owner's
        stop through the existing channel, end its own child, and land its result
        through the nonce gate it already holds. The row stays submittable on
        purpose: a refused submission would be resent until quarantined, which
        holds the queue longer than the stop the owner asked for.

        The terminal row says ``cancelled`` in the column that already records how
        a command ended, so an owner's own stop is never reported back as a PC
        failure. Both the read and the write are owner-scoped in the WHERE clause,
        so another account's dispatch is not addressable, and each update is one
        conditional statement: a claim that won the race is not cancelled as
        queued work, and a cancel that won is never claimed twice.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        stopped = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=?, termination=? "
            "WHERE user_id=? AND run_id=? AND state=? AND nonce_sha256 IS NULL",
            "failed", "cancelled", user_id, run_id, "pending",
        )
        running = await self._run(
            "UPDATE oracle_mesh_dispatch SET termination=? "
            "WHERE user_id=? AND run_id=? AND state=? AND nonce_sha256 IS NOT NULL",
            "cancelled", user_id, run_id, "pending",
        )
        return _changed_rows(stopped) + _changed_rows(running)

    async def oracle_mesh_dispatch_cancellation(self, *, dispatch_id: str) -> bool:
        """Whether the owner stopped one already-claimed dispatch, for the executor.

        One bounded read on a single column, addressed only by the dispatch id the
        executor already holds. It never claims, never writes, and answers ``False``
        for anything it cannot read: an unreachable store must not look like an
        owner's stop, because ``False`` leaves the running command alone while
        ``True`` ends it.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        row = await self._first(
            "SELECT termination FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=? AND state=?",
            dispatch_id, "pending",
        )
        return isinstance(row, dict) and row.get("termination") == "cancelled"

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
        self, *, dispatch_id: str, content_sha256: str, content_bytes: int,
        termination: str | None = None, exit_code: int | None = None,
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
        if termination is not None and not isinstance(termination, str):
            raise HistoryError("termination must be a string")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise HistoryError("exit_code must be an integer or null")
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
        if termination is not None:
            # #5015: the executor-observed termination/exit_code travels with
            # the pinned result so the model lane re-feeds the exact evidence
            # instead of inventing one. The additive 049 columns must exist:
            # a missing-column failure here stays a retryable 503 upstream and
            # never a silent deploy success — apply the 049 gate first.
            await self._run(
                "UPDATE oracle_mesh_dispatch SET termination=?, exit_code=? "
                "WHERE dispatch_id=?",
                termination, exit_code, dispatch_id,
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

    async def store_oracle_mesh_original(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: str, expected_sha256: str, expected_bytes: int,
    ) -> str:
        """#4139 — keep one over-budget command output in the private R2
        original store under a server-derived key.

        The dispatch row is owner-scoped and its pin (SHA + byte length, set
        before this call) must match the presented bytes: a stored original
        that disagrees with the pin is a corruption signal, not a second
        truth. The key reuses the existing full-context layout
        (conversation + deterministic result id), so no browser-supplied key
        or foreign-account result can address it. Bytes are verified again on
        every read against the same pin.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, str) or not raw:
            raise HistoryError("original text is required")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._first(
            "SELECT user_id, result_sha256, result_bytes, kind, root_ref FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=?",
            dispatch_id,
        )
        if row is None or row.get("user_id") != user_id:
            raise HistoryForbidden("mesh dispatch is not owned by current user")
        if row.get("result_sha256") != expected_sha256 or row.get("result_bytes") != expected_bytes:
            raise HistoryError("mesh original does not match the pinned result")
        data = raw.encode("utf-8")
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        key = await self._put_full_message(
            conversation_id, message_id, raw, max_bytes=_oracle_mesh_original_max_bytes(row),
        )
        if key is None:
            # _put_full_message only skips short texts; an over-budget output
            # always exceeds one message, so a skip here means the caller
            # passed the wrong body rather than a stored one.
            raise HistoryError("mesh original was not stored")
        return key

    async def store_oracle_mesh_command_result(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: str, expected_sha256: str, expected_bytes: int,
    ) -> str:
        """#5015 — keep one small verified command output for Engine re-feed.

        Same owner/pin checks as :meth:`store_oracle_mesh_original`, but the
        short-text gate of the over-budget path does not apply: a typical
        drive inventory is a few hundred bytes and still needs exact bytes for
        the model lane. Large outputs keep using the over-budget method so the
        existing non-delivery/retry contract for ``output_too_large`` is
        unchanged. Empty bodies are never stored here; the withheld-body notice
        path owns those.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, str) or not raw:
            raise HistoryError("original text is required")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._first(
            "SELECT user_id, result_sha256, result_bytes, kind, root_ref FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=?",
            dispatch_id,
        )
        if row is None or row.get("user_id") != user_id:
            raise HistoryForbidden("mesh dispatch is not owned by current user")
        if row.get("result_sha256") != expected_sha256 or row.get("result_bytes") != expected_bytes:
            raise HistoryError("mesh original does not match the pinned result")
        data = raw.encode("utf-8")
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        if len(data) > _oracle_mesh_original_max_bytes(row):
            raise HistoryError("mesh original exceeds the bounded storage envelope")
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "put", None)):
            raise HistoryError("private full model-context storage is unavailable")
        import inspect as _inspect
        key = self._context_key(conversation_id, message_id)
        result = bucket.put(key, data, httpMetadata={"contentType": "text/plain; charset=utf-8"})
        if _inspect.isawaitable(result):
            await result
        return key

    async def store_oracle_mesh_original_bytes(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: bytes, media_type: str,
        expected_sha256: str, expected_bytes: int,
    ) -> str:
        """#4139 — keep one desktop screenshot in the private R2 original store.

        The binary twin of :meth:`store_oracle_mesh_original`: same
        server-derived key layout, same dispatch-pin verification before the
        put and the same pin check on every read. The only blob type this
        lane produces is the composited screenshot JPEG; anything else is
        refused rather than stored under an evidence key.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            raise HistoryError("original bytes are required")
        if media_type != "image/jpeg":
            raise HistoryError("unsupported mesh original media type")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._first(
            "SELECT user_id, result_sha256, result_bytes FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=?",
            dispatch_id,
        )
        if row is None or row.get("user_id") != user_id:
            raise HistoryForbidden("mesh dispatch is not owned by current user")
        if row.get("result_sha256") != expected_sha256 or row.get("result_bytes") != expected_bytes:
            raise HistoryError("mesh original does not match the pinned result")
        data = bytes(raw)
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        if len(data) > ORACLE_MESH_ORIGINAL_MAX_BYTES:
            raise HistoryError("mesh original exceeds the bounded storage envelope")
        if not data.startswith(b"\xff\xd8\xff"):
            raise HistoryError("mesh original is not a JPEG screenshot")
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "put", None)):
            raise HistoryError("private full model-context storage is unavailable")
        key = self._context_key(conversation_id, message_id)
        result = bucket.put(key, data, httpMetadata={"contentType": "image/jpeg"})
        if inspect.isawaitable(result):
            await result
        return key

    async def read_oracle_mesh_original(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str,
    ) -> tuple[bytes, str] | None:
        """#4139 — read one stored command original for its owning account.

        Unknown ids and foreign accounts return None so the route answers
        404 without disclosing which part failed. A pin with no stored
        object, or stored bytes that disagree with the dispatch pin, raises
        instead of serving missing or corrupt bytes.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        row = await self._first(
            "SELECT user_id, result_sha256, result_bytes FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=?",
            dispatch_id,
        )
        if row is None or row.get("user_id") != user_id:
            return None
        pinned_sha = row.get("result_sha256")
        pinned_bytes = row.get("result_bytes")
        if not isinstance(pinned_sha, str) or not pinned_sha:
            return None
        try:
            key = self._context_key(conversation_id, message_id)
        except HistoryError:
            return None
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "get", None)):
            raise HistoryError("private full model-context storage is unavailable")
        try:
            obj = bucket.get(key)
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                raise HistoryError("mesh original missing from store")
            from .workspace_storage import _read_r2_object_bytes
            payload = await _read_r2_object_bytes(obj)
        except HistoryError:
            raise
        except Exception as exc:
            raise HistoryError("mesh original read failed") from exc
        if len(payload) != pinned_bytes or hashlib.sha256(payload).hexdigest() != pinned_sha:
            raise HistoryError("mesh original does not match the pinned result")
        return payload, pinned_sha

    async def get_oracle_mesh_dispatch_for_owner(
        self, *, user_id: str, dispatch_id: str
    ) -> dict[str, Any] | None:
        """#4139 — one dispatch row for its owning account, or None.

        The retrieval route re-derives the conversation and the result id
        from this row; an unknown id or a foreign account both return None
        so the route answers 404 without disclosing which part failed.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(dispatch_id, str) or not dispatch_id:
            return None
        # #5015: the 049 termination/exit_code columns are required. A database
        # without them raises here and every caller fails closed (503), so a
        # missing migration can never read as a successful deploy.
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_id, revision_ref, "
            "result_sha256, result_bytes, termination, exit_code, state "
            "FROM oracle_mesh_dispatch WHERE dispatch_id=? AND user_id=?",
            dispatch_id, user_id,
        )
        if row is None:
            return None
        return dict(row)

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
