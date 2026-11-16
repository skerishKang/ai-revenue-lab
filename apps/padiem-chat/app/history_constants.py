"""상수·SQL 조각·제품·PC 범위 (#7813 H2).

`app/history.py`에서 위치만 옮긴 상수, SQL 조각, 제품·PC 범위 안내다.
동작·응답 형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는
`app/history.py`가 이 이름들을 다시 내보낸다.
"""
from __future__ import annotations

from .history_errors import HistoryForbidden

MAX_HISTORY_MESSAGE_CHARS = 8000
MAX_MODEL_CONTEXT_BYTES = 5_500_000  # bounded transport, not model token budget
MAX_HISTORY_TITLE_CHARS = 80


MAX_RECENT_CONVERSATIONS = 30


# 한 페이지 크기. 전체를 가리는 상한이 아니다 — 더 있으면 응답의 next_cursor 로
# 이어 받는다 (#5882 · #5895-D). 생성은 이 수와 무관하게 계속 허용되고, 51번째부터는
# 목록을 넘겨 보면 그대로 나온다.
MAX_PROJECTS = 50


MAX_CLAW_RUNS = 30


MAX_PROJECT_NAME_CHARS = 80


#: #5015 the lane actions whose run may hold more than one PC tool call. The
#: 063 dispatch scope (``tool_call_ref``) is written only by the trusted PC file
#: tool lane, and that lane is this one; the marker therefore names the same
#: lane the dispatch scope names, without a second authority.
MULTI_COMMAND_RUN_ACTIONS = frozenset({"pc_files_query", "pc_browser_query"})


def is_multi_command_action(action: object) -> bool:
    """#5015 — True when one run may store more than one PC tool-call result."""

    return isinstance(action, str) and action in MULTI_COMMAND_RUN_ACTIONS


#: #5895 — how long one executor claim is held before the same dispatch may be
#: handed out again. The Oracle executor holds a poll open for 20 seconds and
#: re-requests about a second after an empty or dead round, so a claim whose
#: response never reached it is offered again inside roughly three of those
#: rounds. This is a delivery timer, not a workload limit: it decides nothing
#: about how long a PC command may run, and the instant that ends a dispatch
#: stays the `expires_at` the poll route stamps (#4139).
ORACLE_MESH_CLAIM_LEASE_SECONDS = 60


#: #7562/#7602 — which handed-out rows a run-out lease may hand out again.
#:
#: A lease that ran out proves only that no renewal arrived, not that the PC did
#: nothing: an executor that restarted mid-command, or whose renewal was held
#: up, may already have run it. Handing such a row out again runs it twice. So
#: only a row the server stamped as a read — which changes nothing on the PC —
#: is re-delivered. A write (shell, and every PC file write/move/delete/edit,
#: which travel as commands) or a ``desktop`` input is settled instead (below),
#: exactly as the re-staging guard already refuses to stage them again. A row
#: the owner stopped (``termination='cancelled'``) is never handed out again
#: whatever its kind.
#:
#: #7602: ``read_only`` is the server's read/write word for the staged operation
#: (#112). The file list, search and chunk read travel as ``kind='command'``, so
#: a kind-only rule lost them on a dropped response. A row that predates the
#: column is NULL and keeps the old ``kind`` rule exactly. The two fragments
#: bind the current instant once each.
ORACLE_MESH_READ_ONLY_SQL = (
    "COALESCE(read_only, CASE WHEN kind='read' THEN 1 ELSE 0 END)"
)
ORACLE_MESH_CLAIMABLE_SQL = (
    "(nonce_sha256 IS NULL OR (claimed_until IS NOT NULL AND claimed_until<=? "
    f"AND {ORACLE_MESH_READ_ONLY_SQL}=1 AND COALESCE(termination,'')<>'cancelled'))"
)
#: A handed-out row whose lease ran out and which may not be re-delivered.
ORACLE_MESH_UNREDELIVERABLE_SQL = (
    "state='pending' AND nonce_sha256 IS NOT NULL AND claimed_until IS NOT NULL "
    f"AND claimed_until<=? AND ({ORACLE_MESH_READ_ONLY_SQL}=0 "
    "OR COALESCE(termination,'')='cancelled')"
)


#: The run actions that are a confirmation card: staged as ``waiting_approval``
#: and taken exactly once by ``consume_pc_command_confirmation`` (#7566, #7561).
PC_CONFIRMATION_CARD_ACTIONS = frozenset({"pc_command", "desktop_type", "pc_session_start", "pc_session_input"})


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
    "files_write": "요청한 파일을 만들거나 바꾸고, 옮기거나 지웁니다. 바뀌기 전 내용은 백업합니다.",
    "query_drives": "드라이브 목록만 조회합니다.",
    "browser": "연결된 PC의 작업용 브라우저에서 요청한 웹 작업을 진행합니다.",
    "none": "허용된 PC 작업 범위를 확인하지 못했습니다.",
}


def strip_pc_scope_marker(content: str) -> str:
    """#7459: 저장용 내부 마커(<!--pc_scope:{...}-->)는 화면용 본문에 싣지 않는다."""
    head, sep, _ = content.partition("\n<!--pc_scope:")
    return strip_pc_session_confirmation_marker(head if sep else content)


def strip_pc_session_confirmation_marker(content: str) -> str:
    """One-shot references and confirmation metadata stay server-side."""
    return content.partition("\n<!--pc-session-confirm:")[0]


def pc_scope_notice(claim: object) -> str | None:
    """The notice for a stored scope claim, or None for anything unknown."""
    if not isinstance(claim, dict):
        return None
    notice = PC_SCOPE_NOTICE_LABELS.get(claim.get("admitted"))
    return notice if isinstance(notice, str) else None
