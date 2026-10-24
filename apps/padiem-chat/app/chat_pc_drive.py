"""b62 Chat product thin lane for verified PC drive inventory (#5015 review).

The Chat product reaches the SAME shared tool contract as Claw — the Core
ToolRuntime PC drive tool, the same Mesh command, the same deployment
ownership grant, verification, pin/store and termination truthfulness — but
under its own product identity, user, permissions and conversation context:

* Engine app id ``padiem-chat`` (the exact caller identity the existing B62
  Chat Engine bridge already presents; no Claw ``b54-padiem-claw`` claim);
* Chat agent id ``agent:padiem:chat-pc-query@1`` (a Claw agent id is never
  accepted on this lane and vice versa);
* b62 canonical subject resolved server-side for the signed-in Chat user;
* the existing ``PRODUCT_SCOPE_CHAT`` (``b62-chat``) conversation scope.

No separate execution engine or permission system is introduced: the lane
delegates to the existing B62 Engine orchestration bridge (extended
additively with agent-plan support) and to the existing Mesh dispatch,
verification and result helpers. Anything unconfigured fails closed with an
explicit code; nothing is ever claimed about an unverified PC.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .auth_routes import auth_ready, current_user_id
from .b14_client import B14Client, ChatRuntimeError
from .history import (
    HistoryForbidden,
    HistoryStore,
    PRODUCT_SCOPE_CHAT,
    is_multi_command_action,
    validate_chat_pc_run_id,
)
from .central_model_route_runtime import chat_request_tier_context
from .pc_work_context import build_pc_work_context_text
from .public_chat import public_chat_result

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

# Drive-only natural-language detector. Mirrors the drive branch of
# claw_general_routes._natural_pc_query_command/_requested_natural_pc_query
# without importing the Claw composer: a backtick command is the explicit
# lane and never this one, and DB/hostname nouns are out of scope here.
_CHAT_PC_MARKERS = (
    "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "com1", "mypc", "mycomputer",
)
_CHAT_PC_DRIVE_NOUNS = (
    "드라이브", "디스크", "drive", "disk",
)
_CHAT_PC_VERBS = (
    "있", "뭐", "무엇", "확인", "조회", "목록", "리스트", "검색", "찾",
    "보여", "알려", "인벤토리", "어떻",
)
_CHAT_PC_FILE_NOUNS = ("파일", "폴더", "디렉터리", "디렉토리", "txt", "문서")
_CHAT_PC_FILE_VERBS = ("목록", "리스트", "보여", "읽", "내용", "설명", "찾", "열어")

CHAT_PC_DRIVE_COMMAND = (
    "Get-PSDrive -PSProvider FileSystem | "
    "Select-Object Name,Root,Used,Free | ConvertTo-Json"
)
CHAT_PC_QUERY_AGENT_ID = "agent:padiem:chat-pc-query@1"
CHAT_PC_QUERY_TOOL_ID = "claw.pc.query_drives"
CHAT_PC_RUN_PREFIX = "chat_pcq_"

_SUBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


def _safe_pc_exception_cause(exc: BaseException) -> str:
    """Public diagnostic only: class plus a redacted first-line message."""
    name = type(exc).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name) is None:
        name = "Exception"
    try:
        message = str(exc).splitlines()[0][:8192]
    except Exception:
        message = "[message unavailable]"
    # Redact before truncation so a cut-off credential cannot escape a match.
    message = re.sub(r"(?i)\b(?:authorization|proxy-authorization|cookie|set-cookie|"
                     r"password|passwd|secret|token|api[ _-]?key|credential|"
                     r"access[_-]?token|refresh[_-]?token|client[_-]?secret|"
                     r"session[_-]?id|private[_-]?key|signature)\b"
                     r"\s*[:=]\s*.*", "[redacted]", message)
    message = re.sub(r"(?i)\b(?:bearer|basic)\s+\S+", "[redacted]", message)
    message = re.sub(r"https?://[^\s]+", "[url redacted]", message, flags=re.I)
    message = re.sub(r"""(["']).*?\1""", "[value redacted]", message)
    message = re.sub(r"[A-Za-z]:[\\/][^\s,;]+|/(?:[^\s/]+/)+[^\s,;]*",
                     "[path redacted]", message)
    message = re.sub(r"[^\s@]+@[^\s@]+", "[email redacted]", message)
    message = re.sub(r"[A-Za-z0-9_+/=.-]{24,}", "[value redacted]", message)
    message = re.sub(r"[^\S ]+|[\x00-\x1f\x7f]", " ", message)
    return name + ": " + message[:120]


class ChatPCDriveError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 503, *, cause: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.status_code = status_code
        self._cause = cause if isinstance(cause, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", cause) else None

    @property
    def cause(self) -> str | None:
        # Exception chaining is attached after construction, so inspect it
        # when the HTTP boundary serializes the error.
        if self.status_code == 503 and self.code.startswith("chat_pc_"):
            diagnostic = _safe_pc_exception_cause(self.__cause__ or self)
            if self._cause is not None:
                name, message = diagnostic.split(": ", 1)
                return name + ": " + self._cause + ": " + message
            return diagnostic
        return self._cause

    def public_error(self) -> dict:
        error = {"code": self.code, "message": self.user_message}
        if self.cause is not None:
            error["cause"] = self.cause
        return error


def _error_response(exc: ChatPCDriveError) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": exc.public_error()},
        status_code=exc.status_code,
        headers=dict(_NO_STORE_HEADERS),
    )


def _client_lane_run_id(value: object) -> str | None:
    """Accept only the canonical Chat PC run id grammar.

    A browser may send a run-scoped recovery handle before the long PC turn.
    The id is not an execution grant and never selects a target; it only lets
    the same signed owner address the run after a transport drop. Anything
    outside the existing ``chat_pcq_`` grammar is refused before staging.
    """
    if value is None:
        return None
    try:
        return validate_chat_pc_run_id(value)
    except ValueError as exc:
        raise ChatPCDriveError(
            "chat_pc_run_id_invalid",
            "PC 작업 실행 ID가 올바르지 않습니다.",
            422,
        ) from exc


def _new_lane_run_id() -> str:
    return CHAT_PC_RUN_PREFIX + uuid.uuid4().hex


async def _refuse_existing_client_run_id(
    store: HistoryStore, *, uid: str, client_run_id: str | None,
) -> None:
    """A client handle may address a new run only, never rewrite an old one."""
    if client_run_id is None:
        return
    getter = getattr(store, "get_claw_run", None)
    if not callable(getter):
        return
    try:
        existing = await getter(uid, client_run_id)
    except Exception as exc:
        raise ChatPCDriveError(
            "chat_pc_run_id_unavailable",
            "PC 작업 실행 ID 상태를 확인할 수 없습니다.",
            503,
        ) from exc
    if existing is not None:
        raise ChatPCDriveError(
            "chat_pc_run_id_conflict",
            "이미 사용 중인 PC 작업 실행 ID입니다.",
            409,
        )


def is_chat_pc_drive_query(user_text: str) -> bool:
    """Narrow drive-only natural question for the verified owner PC."""
    if not isinstance(user_text, str) or not user_text:
        return False
    if "`" in user_text:
        return False
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if not any(marker in compact for marker in _CHAT_PC_MARKERS):
        return False
    if not any(noun in lowered for noun in _CHAT_PC_DRIVE_NOUNS):
        return False
    if not any(verb in lowered for verb in _CHAT_PC_VERBS):
        return False
    return True


def build_chat_pc_agent_plan() -> dict[str, Any]:
    """Thin Chat adapter: the shared drive tool under the Chat agent id."""
    return {
        "agent_id": CHAT_PC_QUERY_AGENT_ID,
        "steps": [
            {
                "step_id": "query_drives",
                "objective": "Query verified PC filesystem drives",
                "tool_id": CHAT_PC_QUERY_TOOL_ID,
            },
        ],
    }


def is_chat_pc_files_query(user_text: str) -> bool:
    """Natural-language PC folder/file task for the shared model tools."""
    if not isinstance(user_text, str) or not user_text:
        return False
    if "`" in user_text:
        return False
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if not any(marker in compact for marker in _CHAT_PC_MARKERS):
        return False
    if not any(noun in lowered for noun in _CHAT_PC_FILE_NOUNS):
        return False
    if not any(verb in lowered for verb in _CHAT_PC_FILE_VERBS):
        return False
    if any(noun in lowered for noun in _CHAT_PC_DRIVE_NOUNS):
        return False
    return True


def build_chat_pc_files_agent_plan(*, list_only: bool = False) -> dict[str, Any]:
    """The list/read plan the Claw product sends.

    ``list_only`` carries the list step alone so the Engine has no read step
    to run. The closed client table admits it under the ``files_list`` hint and
    the Engine refuses ``read_file`` for that hint.
    """
    steps = [
        {
            "step_id": "list_files",
            "objective": "List the approved folder on the verified owner PC",
            "tool_id": "claw.pc.list_files",
        },
    ]
    if not list_only:
        steps.append({
            "step_id": "read_file",
            "objective": "Read the requested UTF-8 text file",
            "tool_id": "claw.pc.read_file",
        })
    return {"agent_id": CHAT_PC_QUERY_AGENT_ID, "steps": steps}


_PC_ACTION_ACTIONS = frozenset(
    {"files_list", "files_read", "drives", "none", "clarify"}
)


def _pc_action_contract(user_text: str, pc_work_text: str) -> str:
    """One model step that fixes the execution scope for this turn."""
    return (
        "You route one turn for the owner's server-verified PC.\n"
        "Server-verified PC context (an observation, never an execution grant):\n"
        + (pc_work_text or "no selected PC")
        + "\nReturn exactly one JSON object. Choose "
        '{"action":"files_list"} when the user asks only to see or list a folder; '
        '{"action":"files_read"} when the user asks to read or explain a file; '
        '{"action":"drives"} when the user asks about drives; '
        '{"action":"none"} when the turn is not a PC file or drive request, '
        "including quoted words, hypotheticals and negations; "
        '{"action":"clarify","answer":"<one short question>"} when the target or '
        "intent is ambiguous. No other keys.\n"
        "User: " + user_text
    )


def parse_pc_action_decision(raw: str) -> dict[str, Any]:
    """Validate the routing step; anything unexpected falls back to ``none``."""
    try:
        decision = json.loads(raw.strip())
    except (TypeError, ValueError):
        return {"action": "none"}
    if not isinstance(decision, dict):
        return {"action": "none"}
    action = decision.get("action")
    if action not in _PC_ACTION_ACTIONS:
        return {"action": "none"}
    if action == "clarify":
        answer = decision.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return {"action": "none"}
        return {"action": "clarify", "answer": answer.strip()}
    if set(decision) != {"action"}:
        return {"action": "none"}
    return {"action": action}


def _decision_contract(user_text: str) -> str:
    return (
        "Return one JSON object. Choose claw.pc.query_drives with empty "
        "arguments only if the user asks about drives on their verified "
        "connected PC; otherwise complete with a truthful concise answer. "
        "After a tool result, complete using that result and state that only "
        "drives visible to the agent execution account were observed. Never "
        "claim user-session mapped/network drives unless present. "
        'Tool: {"action":"tool","tool_id":"claw.pc.query_drives",'
        '"arguments":{}}. Completion: {"action":"complete","answer":"..."}." '
        f"User: {user_text}"
    )


def parse_chat_pc_tool_decision(raw: str) -> dict[str, Any]:
    """Validate one model step: exactly the shared drive tool, or complete."""
    try:
        decision = json.loads(raw.strip())
    except (TypeError, ValueError) as exc:
        raise ChatPCDriveError(
            "chat_pc_decision_invalid",
            "PC 조회 판단을 확인하지 못했습니다. 다시 시도해 주세요.",
        ) from exc
    if not isinstance(decision, dict):
        raise ChatPCDriveError(
            "chat_pc_decision_invalid",
            "PC 조회 판단을 확인하지 못했습니다. 다시 시도해 주세요.",
        )
    if decision.get("action") == "complete" and isinstance(decision.get("answer"), str):
        return decision
    if (
        decision.get("action") == "tool"
        and decision.get("tool_id") == CHAT_PC_QUERY_TOOL_ID
        and decision.get("arguments") == {}
    ):
        return decision
    raise ChatPCDriveError(
        "chat_pc_decision_invalid",
        "PC 조회 판단을 확인하지 못했습니다. 다시 시도해 주세요.",
    )


async def _resolve_chat_owner(request: Request, uid: str) -> tuple[Any, str, str]:
    """b62 canonical session, subject and workspace for this lane.

    Uses the same authority call as the signed Chat PC endpoint
    (``resolve_current_auth_session(product_id="b62")``), so the lane's
    session id is the canonical one the Control Plane owner-scope lookup
    accepts. The former shadow-session path could resolve a different
    session value and fail the owner scope even for the signed-in owner.
    """
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if authority is None:
        return None, "", f"owner:{uid}"
    if not callable(getattr(authority, "resolve_current_auth_session", None)):
        raise ChatPCDriveError(
            "chat_pc_identity_unavailable",
            "사용자 확인 정보를 사용할 수 없습니다.",
        )
    try:
        session = await authority.resolve_current_auth_session(
            product_id="b62", product_user_id=uid,
        )
    except Exception as exc:
        raise ChatPCDriveError(
            "chat_pc_identity_unavailable",
            "사용자 확인 정보를 사용할 수 없습니다.",
        ) from exc
    from datetime import datetime, timezone

    subject_id = getattr(getattr(session, "subject", None), "subject_id", None)
    tenant_id = getattr(session, "tenant_id", None)
    if (
        session is None
        or getattr(session, "product_id", None) != "b62"
        or not session.is_active(now=datetime.now(timezone.utc))
        or not isinstance(subject_id, str)
        or _SUBJECT_RE.fullmatch(subject_id) is None
        or not isinstance(tenant_id, str)
        or not tenant_id
    ):
        raise ChatPCDriveError(
            "chat_pc_identity_unavailable",
            "사용자 확인 정보를 사용할 수 없습니다.",
        )
    # #5088/#5015: the Control Plane owner-scope lookup accepts the shared
    # B54 canonical session, not a product-local shadow session. Resolve the
    # same bridge the signed Claw/Chat endpoint uses; the Chat product identity
    # above and the b62 subject sent to the Engine stay unchanged.
    from padiem_control_plane.b54_identity_bridge import (
        resolve_current_b54_canonical_session as resolve_b54_session,
    )

    try:
        bridged = await resolve_b54_session(authority, uid)
    except Exception as exc:
        raise ChatPCDriveError(
            "chat_pc_identity_unavailable",
            "사용자 확인 정보를 사용할 수 없습니다.",
        ) from exc
    if (
        bridged is None
        or bridged.auth_session.subject.subject_id != subject_id
        or not isinstance(bridged.auth_session.tenant_id, str)
        or not bridged.auth_session.tenant_id
    ):
        raise ChatPCDriveError(
            "chat_pc_identity_unavailable",
            "사용자 확인 정보를 사용할 수 없습니다.",
        )
    session = bridged.auth_session
    tenant_id = session.tenant_id
    from .claw_memory_routes import _resolve_memory_workspace

    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace_id = None
    if not isinstance(workspace_id, str) or not workspace_id:
        workspace_id = tenant_id
    return session, subject_id, workspace_id


_MESH_GRANT_LOG = logging.getLogger(__name__)


def _mesh_grant_denied(reason: str) -> bool:
    """Log a fixed internal reason only; never include owner, session, or grant data."""
    _MESH_GRANT_LOG.warning("chat_pc_mesh_grant_denied=%s", reason)
    return False


async def _check_mesh_grant(
    request: Request, session: Any, *, device_id: str | None = None,
) -> bool:
    """Check the existing shared deployment grant without changing its semantics.

    Each denial logs only a fixed diagnostic code. The user sees the same
    generic refusal, so account existence, mapping, and authorization remain
    private.
    """
    from .oracle_mesh_read_return_routes import EXECUTION_MODE_MESH

    if session is None:
        return _mesh_grant_denied("canonical_session_absent")
    mesh_source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if mesh_source is None or getattr(mesh_source, "configured", True) is False:
        return _mesh_grant_denied("mesh_source_unconfigured")
    if getattr(mesh_source, "execution_mode", None) != EXECUTION_MODE_MESH:
        return _mesh_grant_denied("mesh_mode_unavailable")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return _mesh_grant_denied("identity_authority_unavailable")
    try:
        scope = await identity.resolve_connector_owner_scope(session_id=session.session_id)
    except Exception:
        return _mesh_grant_denied("owner_scope_resolution_failed")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    if not isinstance(account_ref, str) or not account_ref:
        return _mesh_grant_denied("owner_scope_account_unavailable")
    try:
        target = mesh_source.command_target(account_ref=account_ref, device_id=device_id)
    except Exception:
        return _mesh_grant_denied("mesh_command_target_lookup_failed")
    if target is None:
        return _mesh_grant_denied("mesh_command_target_not_unique")
    return True

def _no_pc_answer() -> str:
    return (
        "검증된 PC 연결을 확인하지 못해 드라이브를 조회할 수 없습니다. "
        "PC 연결을 먼저 확인한 뒤 다시 요청해 주세요. "
        "연결되지 않은 PC의 드라이브를 추측해서 안내하지 않았습니다."
    )


def _no_pc_lane_answer(files_only: bool) -> str:
    """Truthful refusal for a PC request that has no verified target (pre-#5574 wording)."""
    if files_only:
        return (
            "검증된 PC 연결을 확인하지 못해 파일 목록을 조회할 수 없습니다. "
            "PC 연결을 먼저 확인한 뒤 다시 요청해 주세요. "
            "연결되지 않은 PC의 파일을 추측해서 안내하지 않았습니다."
        )
    return _no_pc_answer()


def _conversation_history(messages: Any, user_text: str) -> tuple[dict[str, str], ...]:
    """Prior user/assistant turns, bounded, for the scope decision."""
    if not isinstance(messages, (list, tuple)):
        return ()
    history: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            history.append({"role": role, "content": content.strip()})
    if (
        history
        and history[-1]["role"] == "user"
        and history[-1]["content"] == user_text.strip()
    ):
        history = history[:-1]
    return tuple(history[-8:])


def _conversation_transcript(messages: Any) -> str:
    """The prior turns as plain text for the Engine system context."""
    history = _conversation_history(messages, "")
    if not history:
        return ""
    return "\n".join(
        ("User: " if item["role"] == "user" else "Assistant: ") + item["content"]
        for item in history
    )


async def _complete_with_model(
    request: Request, *, user_text: str, skill: Any,
    tier: str, system_contract: str, history: Any = None,
) -> str:
    """One bounded B14 text turn under the existing Chat model policy."""
    client: B14Client | None = getattr(request.app.state, "b14_client", None)
    if client is None:
        raise ChatPCDriveError(
            "chat_pc_model_unavailable",
            "AI 모델을 현재 사용할 수 없습니다.",
        )
    try:
        async with chat_request_tier_context(request, tier):
            result = await client.complete(
                tuple(history or ()) + ({"role": "user", "content": user_text},),
                skill,
                additional_system_context=system_contract,
            )
    except ChatRuntimeError as exc:
        raise ChatPCDriveError("chat_pc_model_unavailable", exc.user_message, exc.status_code) from exc
    except Exception as exc:
        raise ChatPCDriveError(
            "chat_pc_model_unavailable",
            "AI 모델을 현재 사용할 수 없습니다.",
        ) from exc
    answer = result.get("answer") if isinstance(result, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise ChatPCDriveError(
            "chat_pc_model_unavailable",
            "AI 모델이 표시할 답변을 만들지 못했습니다.",
            502,
        )
    return answer.strip()


async def _save_pair(
    store: HistoryStore, *, uid: str, conversation_id: str | None,
    user_text: str, answer: str,
) -> str | None:
    try:
        return await store.append_exchange(
            uid, conversation_id, user_text, answer,
            product_scope=PRODUCT_SCOPE_CHAT,
        )
    except HistoryForbidden:
        return None
    except Exception:
        return conversation_id


async def execute_chat_pc_drive_lane(
    request: Request,
    *,
    user_text: str,
    execution_user_text: str | None = None,
    skill: Any,
    model_id: str,
    conversation_id: str | None,
    tier: str,
    device_id: str | None = None,
    run_id: str | None = None,
    conversation_messages: Any = None,
) -> tuple[str, str | None] | None:
    """Run the lane and return ``(answer, conversation_id)``.

    Returns None to fall through to the existing general Chat path
    (anonymous user, or the one model scope step says this is not a PC turn). Raises ChatPCDriveError for
    every handled failure. History writes happen here, so both the JSON and
    the SSE call sites share them.

    ``user_text`` remains the stored user turn. ``execution_user_text`` is the
    resolved policy text used for model and Engine prompts, so a hidden alias
    removed by the policy never reaches the model; absent, it falls back to
    ``user_text`` for existing callers.
    """
    from .orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError

    uid = current_user_id(request) if auth_ready(request) else None
    if not uid:
        return None
    execution_text = (
        execution_user_text
        if isinstance(execution_user_text, str) and execution_user_text.strip()
        else user_text
    )
    # Lane entry (restored 2026-10-24, interim until the tool-calling entry
    # lands): only a PC drive/file request enters this lane; every other turn
    # keeps the ordinary streaming path and pays no extra call. The AI still
    # selects the tool itself inside the Engine step (#5573).
    drive_requested = is_chat_pc_drive_query(execution_text)
    files_requested = is_chat_pc_files_query(execution_text)
    if not drive_requested and not files_requested:
        return None
    files_only = files_requested and not drive_requested
    list_only = False
    client_run_id = _client_lane_run_id(run_id)
    store: HistoryStore | None = getattr(request.app.state, "history_store", None)
    if store is None:
        raise ChatPCDriveError(
            "chat_pc_store_unavailable",
            "대화 기록을 현재 사용할 수 없습니다.",
        )
    if device_id is not None and not is_pc_device_id(device_id):
        raise ChatPCDriveError(
            "chat_pc_target_invalid",
            "선택한 PC 정보가 유효하지 않습니다.",
            422,
        )
    await _refuse_existing_client_run_id(
        store, uid=uid, client_run_id=client_run_id,
    )
    try:
        session, subject_id, workspace_id = await _resolve_chat_owner(request, uid)
    except ChatPCDriveError:
        # No PC authority means no verified PC context. An ordinary turn keeps
        # its existing path and pays no extra call; a PC request cannot be
        # distinguished without a context and falls through (documented).
        return None
    from .pc_work_context import (
        SAVED_SELECTION_SELECTED, SAVED_SELECTION_UNAVAILABLE,
        read_saved_device_selection, render_pc_work_context,
        resolve_pc_work_context,
    )

    saved_selection = await read_saved_device_selection(
        request, owner_id=uid, workspace_id=workspace_id,
    )
    if device_id is not None:
        if (
            saved_selection.status == SAVED_SELECTION_SELECTED
            and saved_selection.device_id != device_id
        ):
            raise ChatPCDriveError(
                "chat_pc_selection_stale",
                "저장된 작업 대상과 화면 선택이 다릅니다. 내 컴퓨터에서 대상을 다시 선택해 주세요.",
                409,
            )
    elif saved_selection.status == SAVED_SELECTION_SELECTED:
        # New session/reload: the saved target is the account's default.
        device_id = saved_selection.device_id
    elif saved_selection.status == SAVED_SELECTION_UNAVAILABLE:
        # A failed lookup is not "no selection"; never execute on another PC.
        raise ChatPCDriveError(
            "chat_pc_selection_unavailable",
            "저장된 PC 작업 대상을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            503,
        )

    # #5015: one server-verified context for both the drive and file lanes.
    pc_context = await resolve_pc_work_context(
        request, owner_id=uid, workspace_id=workspace_id,
        session_id=getattr(session, "session_id", None),
        selected_device_id=device_id,
    )
    if device_id is not None:
        selected_row = next(
            (device for device in pc_context.devices
             if device.device_id == device_id),
            None,
        )
        if selected_row is not None and selected_row.state == "REVOKED":
            raise ChatPCDriveError(
                "chat_pc_selection_revoked",
                "선택한 PC의 연결이 해제되었습니다. 작업 대상을 다시 선택해 주세요.",
                409,
            )
        if not pc_context.selected_confirmed:
            if not pc_context.execution.ready:
                raise ChatPCDriveError(
                    "chat_pc_target_unavailable",
                    "선택한 PC의 서버 실행 대상을 확인할 수 없습니다. 작업 대상을 다시 확인해 주세요.",
                    409,
                )
            raise ChatPCDriveError(
                "chat_pc_target_mismatch",
                "선택한 PC가 서버 실행 대상과 일치하지 않습니다. 작업 대상을 다시 선택해 주세요.",
                403,
            )
    if not pc_context.devices and not pc_context.tool_available:
        # Neither a Broker device nor a usable server-owned Mesh target: this
        # PC request has nothing to run on, so answer truthfully instead of
        # letting the general model guess. An empty Broker list alone never
        # demotes a working Mesh target (pc_work_context contract; the
        # 2026-10-22 list/read baseline ran Mesh-only).
        answer = _no_pc_lane_answer(files_only)
        saved_id = await _save_pair(
            store, uid=uid, conversation_id=conversation_id,
            user_text=user_text, answer=answer,
        )
        if saved_id is None:
            raise ChatPCDriveError("conversation_not_found", "대화를 찾을 수 없습니다.", 404)
        return answer, saved_id
    if not await _check_mesh_grant(request, session, device_id=device_id):
        answer = _no_pc_lane_answer(files_only)
        saved_id = await _save_pair(
            store, uid=uid, conversation_id=conversation_id,
            user_text=user_text, answer=answer,
        )
        if saved_id is None:
            raise ChatPCDriveError("conversation_not_found", "\ub300\ud654\ub97c \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.", 404)
        return answer, saved_id

    pc_work_text = render_pc_work_context(pc_context)

    # #5573 / Option A: one Engine call for every PC request with a verified
    # PC context (the entry pre-check above keeps ordinary turns on the
    # streaming path). The Engine's existing step driver selects the tool
    # (drives, list, read); the Chat app runs no separate classification
    # call. Prior turns travel in the system context so the same call can
    # resolve "그 폴더" and similar follow-ups.
    transcript = _conversation_transcript(conversation_messages)
    additional_context = pc_work_text if not transcript else (
        pc_work_text + "\n\nRecent conversation:\n" + transcript
    )
    return await _execute_chat_pc_files_lane(
        request, store=store, uid=uid, subject_id=subject_id,
        workspace_id=workspace_id, user_text=user_text,
        execution_user_text=execution_text, skill=skill,
        model_id=model_id, conversation_id=conversation_id,
        device_id=device_id, additional_system_context=additional_context,
        run_id=client_run_id, list_only=False,
    )


async def _execute_chat_pc_files_lane(
    request: Request,
    *,
    store: HistoryStore,
    uid: str,
    subject_id: str,
    workspace_id: str,
    user_text: str,
    execution_user_text: str | None = None,
    skill: Any,
    model_id: str,
    conversation_id: str | None,
    device_id: str | None,
    additional_system_context: str | None = None,
    run_id: str | None = None,
    list_only: bool = False,
) -> tuple[str, str | None]:
    """Stage and run the list/read plan on the Chat product.

    The model decisions and both tool executions happen in the Engine's PC
    step driver; this lane only stages the Chat run, passes the server-owned
    device hint and records the final answer in the original conversation.
    ``user_text`` remains the stored user turn; the Engine prompt uses the
    policy-cleaned ``execution_user_text`` when supplied.
    """
    from .orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError

    bridge = getattr(request.app.state, "orchestration_bridge", None)
    if not isinstance(bridge, B62EngineOrchestrationBridge) or not bridge.ready:
        raise ChatPCDriveError(
            "chat_pc_files_unavailable",
            "PC 파일 도구를 현재 사용할 수 없습니다.",
        )
    lane_run_id = run_id or _new_lane_run_id()
    try:
        staged_conversation_id = await store.record_chat_pc_drive_run(
            user_id=uid, run_id=lane_run_id, workspace_id=workspace_id,
            user_text=user_text, conversation_id=conversation_id,
            action="pc_files_query", title_prefix="PC 파일 탐색: ",
        )
    except HistoryForbidden as exc:
        raise ChatPCDriveError(
            "conversation_not_found", "대화를 찾을 수 없습니다.", 404,
        ) from exc
    except Exception as exc:
        raise ChatPCDriveError(
            "chat_pc_store_unavailable",
            "대화 기록을 현재 사용할 수 없습니다.",
        ) from exc
    tool_arguments = (
        (
            {"files_list": {"device_id": device_id}}
            if list_only else {"files": {"device_id": device_id}}
        )
        if device_id is not None else None
    )
    engine_text = (
        execution_user_text
        if isinstance(execution_user_text, str) and execution_user_text.strip()
        else user_text
    )
    try:
        outcome = await bridge.start(
            user_id=uid,
            messages=({"role": "user", "content": engine_text},),
            skill=skill,
            model_id=model_id,
            user_text=user_text,
            conversation_id=staged_conversation_id,
            subject_id=subject_id,
            session_id=lane_run_id,
            agent_plan=build_chat_pc_files_agent_plan(list_only=list_only),
            additional_system_context=additional_system_context,
            tool_arguments=tool_arguments,
        )
    except B62OrchestrationError as exc:
        await _append_lane_notice(
            request, store, uid=uid, run_id=lane_run_id,
            content=(
                "PC 파일 작업을 완료하지 못했습니다. "
                "같은 요청을 반복하기 전에 PC 연결 상태를 확인해 주세요."
            ),
            status="failed",
        )
        raise ChatPCDriveError(
            "chat_pc_engine_unavailable", exc.user_message, exc.status_code, cause=exc.code,
        ) from exc
    answer = outcome.answer if isinstance(outcome.answer, str) else None
    if not answer or not answer.strip():
        await _append_lane_notice(
            request, store, uid=uid, run_id=lane_run_id,
            content=(
                "PC 파일 작업을 완료하지 못했습니다. "
                "같은 요청을 반복하기 전에 PC 연결 상태를 확인해 주세요."
            ),
            status="failed",
        )
        raise ChatPCDriveError(
            "chat_pc_engine_unavailable",
            "AI가 표시할 답변을 만들지 못했습니다.",
            502,
        )
    composed = answer.strip()
    try:
        saved = await _append_lane_answer(
            request, store, uid=uid, run_id=lane_run_id, content=composed,
            raise_errors=True,
        )
    except Exception as exc:
        raise ChatPCDriveError(
            "chat_pc_store_unavailable", "대화 기록을 현재 사용할 수 없습니다.",
        ) from exc
    if not saved:
        raise ChatPCDriveError(
            "chat_pc_store_unavailable",
            "대화 기록을 현재 사용할 수 없습니다.",
        )
    return composed, staged_conversation_id


async def run_chat_pc_drive_lane(
    request: Request,
    *,
    user_text: str,
    execution_user_text: str | None = None,
    skill: Any,
    model_id: str,
    conversation_id: str | None,
    tier: str,
    device_id: str | None = None,
    run_id: str | None = None,
) -> JSONResponse | None:
    """JSON wrapper of :func:`execute_chat_pc_drive_lane` for /api/chat."""
    try:
        result = await execute_chat_pc_drive_lane(
            request, user_text=user_text, execution_user_text=execution_user_text,
            skill=skill, model_id=model_id,
            conversation_id=conversation_id, tier=tier, device_id=device_id,
            run_id=run_id,
        )
    except ChatPCDriveError as exc:
        return _error_response(exc)
    if result is None:
        return None
    answer, saved_id = result
    payload: dict[str, Any] = {"answer": answer, "conversation_id": saved_id}
    notice = await pc_scope_notice_for_run(request, run_id=run_id)
    if notice is not None:
        # #5573: the notice was pinned before dispatch and is shown live as a
        # separate line; it is never folded into the answer.
        payload["scope_notice"] = notice
    return JSONResponse(public_chat_result(payload))


async def pc_scope_notice_for_run(request: Request, *, run_id: object) -> str | None:
    """The pinned PC scope notice for this run, or None when unavailable.

    Display-only: an unreadable request, store or record is simply "no notice",
    so a notice lookup can never turn a completed PC answer into a failure.
    """
    if not isinstance(run_id, str) or not run_id:
        return None
    try:
        uid = current_user_id(request) if auth_ready(request) else None
        store = getattr(request.app.state, "history_store", None)
        reader = getattr(store, "get_pc_run_scope_notice", None)
        if not isinstance(uid, str) or not uid or not callable(reader):
            return None
        notice = await reader(user_id=uid, run_id=run_id)
    except Exception:
        return None
    return notice if isinstance(notice, str) and notice else None


async def _append_lane_answer(
    request: Request, store: HistoryStore, *, uid: str, run_id: str,
    content: str, raise_errors: bool = False,
) -> bool:
    """Append the lane's final answer beside the verified output message.

    The executor result leg already stored the verified output under this
    run's summary; reusing that stored summary plus a lane-suffixed message
    id keeps the exactly-once and terminal-immutability guards intact while
    adding the model-composed answer to the same conversation.

    #5015: a run that held more than one PC tool call already stored each
    command's own result, so the answer is the run's overall completion. The
    lane seals that completion through the run's own terminal, never through a
    command result: the seal is refused while a command is still pending or
    has failed, so the work can never read as completed when it was not.
    """
    _ = request
    try:
        run_row = await store.get_claw_run(uid, run_id)
    except Exception:
        if raise_errors:
            raise
        return False
    if not isinstance(run_row, dict):
        return False
    summary = run_row.get("result_summary")
    conversation_id = run_row.get("conversation_id")
    if not isinstance(summary, str) or not summary:
        return False
    if not isinstance(conversation_id, str) or not conversation_id:
        return False
    message_id = run_id + "_answer"
    if len(message_id) > 128:
        return False
    try:
        if is_multi_command_action(run_row.get("action")):
            # #5015: the run's own final answer carries its own message id, so
            # the answer of a multi-command run is never confused with the
            # answer of a single-command run that shares the same prefix.
            sealed = await store.seal_run_terminal(
                user_id=uid, run_id=run_id, message_id=run_id + "_final",
                summary=summary, content=content, status="completed",
            )
            return bool(sealed)
        appended = await store.append_local_task_result(
            user_id=uid, run_id=run_id, message_id=message_id,
            summary=summary, content=content, status="completed",
        )
        return bool(appended)
    except Exception:
        if raise_errors:
            raise
        return False


async def _append_lane_notice(
    request: Request, store: HistoryStore, *, uid: str, run_id: str,
    content: str, status: str,
) -> bool:
    """Best-effort terminal notice for a staged lane run with no answer."""
    _ = request
    try:
        run_row = await store.get_claw_run(uid, run_id)
    except Exception:
        return False
    if not isinstance(run_row, dict):
        return False
    stored = run_row.get("result_summary")
    message_id = run_id + "_notice"
    if len(message_id) > 128:
        return False
    try:
        notice_summary = stored if isinstance(stored, str) and stored else "failed"
        if is_multi_command_action(run_row.get("action")):
            # #5015: the notice is the run's own terminal, so it is sealed as
            # such. A run that already carries a failed command stays failed.
            sealed = await store.seal_run_terminal(
                user_id=uid, run_id=run_id, message_id=message_id,
                summary=notice_summary, content=content, status=status,
            )
            return bool(sealed)
        appended = await store.append_local_task_result(
            user_id=uid, run_id=run_id, message_id=message_id,
            summary=notice_summary, content=content, status=status,
        )
        return bool(appended)
    except Exception:
        return False


__all__ = [
    "CHAT_PC_DRIVE_COMMAND",
    "CHAT_PC_QUERY_AGENT_ID",
    "CHAT_PC_QUERY_TOOL_ID",
    "ChatPCDriveError",
    "build_chat_pc_agent_plan",
    "execute_chat_pc_drive_lane",
    "is_chat_pc_drive_query",
    "parse_chat_pc_tool_decision",
    "pc_scope_notice_for_run",
    "run_chat_pc_drive_lane",
]
