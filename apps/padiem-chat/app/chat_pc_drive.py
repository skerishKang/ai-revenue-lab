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

import logging
import re
import uuid
from collections.abc import Mapping
from typing import Any

from starlette.requests import Request

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.tool_channel import ToolDefinition

from .auth_routes import auth_ready, current_user_id
from .history import (
    HistoryForbidden,
    HistoryStore,
    PRODUCT_SCOPE_CHAT,
    is_multi_command_action,
    validate_chat_pc_run_id,
)

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
        """The bounded browser error: a fixed code, a fixed message, a safe cause.

        ``cause`` is carried only when it already matches the internal code
        grammar, so an engine or provider blob can never reach the browser
        through this field.
        """
        error = {"code": self.code, "message": self.user_message}
        if self.cause is not None:
            error["cause"] = self.cause
        return error


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


# #5573 (3-B-2): the closed PC tool set offered to a model on the streaming
# lane. These names mirror the canonical Engine plan keys; the model's
# arguments carry no authority, and the lane re-verifies the PC on entry.
CHAT_PC_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="query_drives",
        description=(
            "List the filesystem drives on the user's verified PC when the "
            "user asks which drives or disks exist."
        ),
    ),
    ToolDefinition(
        name="files_list",
        description=(
            "List the files and folders in one folder on the user's verified "
            "PC when the user only asks what is there."
        ),
    ),
    ToolDefinition(
        name="files",
        description=(
            "Find, list or read text files on the user's verified PC when the "
            "user asks about a file's content."
        ),
    ),
)


def chat_pc_plan_for_tool(tool_name: str) -> dict[str, Any] | None:
    """The canonical Engine plan a model-requested PC tool selects."""
    if tool_name == "query_drives":
        return build_chat_pc_agent_plan()
    if tool_name == "files_list":
        return build_chat_pc_files_agent_plan(list_only=True)
    if tool_name == "files":
        return build_chat_pc_files_agent_plan(list_only=False)
    return None


def _declared_plan_for_tool(
    tool_name: str, declared_plan: Any,
) -> dict[str, Any] | None:
    """The tool-derived plan, optionally narrowed to list-only.

    A supplied plan is not authority: it may only drop the read step of the
    ``files`` plan. Every other value falls back to the exact plan the tool
    name selects, so no caller can widen the Engine's scope.
    """
    derived = chat_pc_plan_for_tool(tool_name)
    if derived is None:
        return None
    if not isinstance(declared_plan, Mapping):
        return derived
    if dict(declared_plan) == derived:
        return derived
    if tool_name == "files":
        narrowed = chat_pc_plan_for_tool("files_list")
        if dict(declared_plan) == narrowed:
            return narrowed
    return derived


def _tool_arguments_for_plan(
    agent_plan: Mapping[str, Any], device_id: str | None,
) -> dict[str, Any] | None:
    """The closed Engine target hint for one canonical PC plan.

    The Engine accepts exactly one key per plan shape; the key is never taken
    from model output, and a plan without a known tool carries no hint.
    """
    if device_id is None:
        return None
    tool_ids = {
        step.get("tool_id")
        for step in agent_plan.get("steps", ())
        if isinstance(step, Mapping)
    }
    if "claw.pc.query_drives" in tool_ids:
        key = "query_drives"
    elif "claw.pc.read_file" in tool_ids:
        key = "files"
    elif "claw.pc.list_files" in tool_ids:
        key = "files_list"
    else:
        return None
    return {key: {"device_id": device_id}}


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


async def chat_pc_tools_available(request: Request, *, uid: str | None) -> bool:
    """Whether this account may be offered the PC tools on the stream lane.

    Applies the same server checks the PC lane applies on entry
    (``resolve_pc_work_context`` + ``tool_available`` + ``_check_mesh_grant``).
    Any failure withholds the declaration: tools are never exposed for an
    unverified PC, and no new Broker requirement is introduced.
    """
    if not uid:
        return False
    try:
        session, _subject_id, workspace_id = await _resolve_chat_owner(request, uid)
        from .pc_work_context import (
            SAVED_SELECTION_SELECTED,
            read_saved_device_selection,
            resolve_pc_work_context,
        )

        selection = await read_saved_device_selection(
            request, owner_id=uid, workspace_id=workspace_id,
        )
        device_id = (
            selection.device_id
            if selection.status == SAVED_SELECTION_SELECTED
            else None
        )
        pc_context = await resolve_pc_work_context(
            request, owner_id=uid, workspace_id=workspace_id,
            session_id=getattr(session, "session_id", None),
            selected_device_id=device_id,
        )
    except Exception:
        return False
    if not pc_context.tool_available:
        return False
    if device_id is not None and not pc_context.selected_confirmed:
        return False
    return await _check_mesh_grant(request, session, device_id=device_id)


async def resolve_chat_pc_stream_context(
    request: Request, *, uid: str, requested_device_id: str | None = None,
) -> dict | None:
    """Server-authored context only; no browser field or Broker registration grants it."""
    from .pc_work_context import (
        SAVED_SELECTION_SELECTED, SAVED_SELECTION_UNAVAILABLE,
        read_saved_device_selection, resolve_pc_work_context,
    )
    try:
        session, subject_id, workspace_id = await _resolve_chat_owner(request, uid)
        if session is None or not subject_id:
            return None
        selection = await read_saved_device_selection(request, owner_id=uid, workspace_id=workspace_id)
        if selection.status == SAVED_SELECTION_UNAVAILABLE:
            return None
        selected = selection.device_id if selection.status == SAVED_SELECTION_SELECTED else None
        context = await resolve_pc_work_context(
            request, owner_id=uid, workspace_id=workspace_id,
            session_id=session.session_id, selected_device_id=selected,
        )
        if not context.tool_available or not context.selected_confirmed:
            return None
        device_id = context.execution_device_id
        if not is_pc_device_id(device_id):
            return None
        if requested_device_id is not None and requested_device_id != device_id:
            return None
        if not await _check_mesh_grant(request, session, device_id=device_id):
            return None
        # The existing command grant allows drive inventory; file scopes also
        # require the same approved root that the signed file API resolves.
        from .oracle_mesh_read_return_routes import _engine_pc_files_target
        target, error = await _engine_pc_files_target(
            request, session=session, selected_device_id=device_id, user_id=uid,
        )
        scopes = ["query_drives"]
        if error is None and target is not None:
            scopes.extend(["files_list", "files"])
        return {"pc_tools": {"device_id": device_id, "allowed_scopes": scopes},
                "subject_id": subject_id, "workspace_id": workspace_id}
    except Exception:
        # An unreadable authority withholds tools and preserves the normal turn.
        return None


async def promote_chat_pc_stream_run(
    request: Request, *, uid: str, run_id: str, device_id: str | None, action: str,
) -> dict | None:
    """For signed Engine callbacks only; no receipt means no new run."""
    store = getattr(request.app.state, "history_store", None)
    promoter = getattr(store, "promote_chat_stream_pc_run", None)
    if not callable(promoter) or _client_lane_run_id(run_id) is None:
        return None
    session, _subject, workspace = await _resolve_chat_owner(request, uid)
    if not await _check_mesh_grant(request, session, device_id=device_id):
        return None
    return await promoter(user_id=uid, run_id=run_id, workspace_id=workspace, action=action)


async def chat_pc_route_declares_tools(request: Request, model_id: str) -> bool:
    """Whether the resolved route's B14 registration declares native tools.

    The registry is read through the existing normalized view
    (``b14_model_choice_resolver`` — the same B14 owner-allowed/live-ready
    catalog Claw and B66 consume), because B14's ``/api/pilot/models`` answers
    with an object, not a list: the raw catalog source sees no rows and would
    withhold the tools forever. An unreadable or unnormalized catalog withholds
    the declaration, a disabled or owner-excluded route withholds it, and no
    model/provider policy is copied here.
    """
    state = request.app.state
    rows: Any = None
    for name in ("b14_model_choice_resolver", "b14_catalog_source"):
        source = getattr(state, name, None)
        lister = getattr(source, "list_registered_models", None)
        if not callable(lister):
            continue
        try:
            candidate = await lister()
        except Exception:
            continue
        if isinstance(candidate, list) and candidate:
            rows = candidate
            break
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict) or row.get("model_id") != model_id:
            continue
        capabilities = row.get("capabilities")
        return (
            isinstance(capabilities, list)
            and "tools" in capabilities
            and row.get("b14_enabled") is True
            and row.get("owner_excluded") is False
        )
    return False


async def pc_tool_entry_available(
    request: Request, *, uid: str | None, model_id: str,
) -> bool:
    """Whether a model on this route can select a PC tool for this account.

    Both halves are required: a server-verified PC target and a route whose
    catalog declares ``tools``. Either one missing means no declaration, so the
    turn keeps its existing path and its existing request bytes.
    """
    if not uid:
        return False
    if not await chat_pc_route_declares_tools(request, model_id):
        return False
    return await chat_pc_tools_available(request, uid=uid)


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
    device_id: str | None = None,
    run_id: str | None = None,
    conversation_messages: Any = None,
    declared_plan: Any = None,
    selected_tool: str | None = None,
) -> tuple[str, str | None] | None:
    """Run the lane and return ``(answer, conversation_id)``.

    Returns None when the turn carries no model-selected PC tool (or the name
    is not one of the closed PC tools), so the caller keeps its ordinary path.
    Raises ChatPCDriveError for every handled failure. History writes happen
    here, so both the JSON and the SSE call sites share them.

    ``user_text`` remains the stored user turn. ``execution_user_text`` is the
    resolved policy text used for model and Engine prompts, so a hidden alias
    removed by the policy never reaches the model; absent, it falls back to
    ``user_text`` for existing callers.

    ``selected_tool`` is the tool name the model requested — the only entry
    this lane has (#5573 3-C-2). The plan is derived from the name and
    ``declared_plan`` may only narrow it. Everything else (owner, grant, PC
    context, target) is verified again below, so the model's request is never
    an execution authority.
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
    # #5573 (3-C-2): the model's tool call is the entry. No wording selects or
    # blocks this lane; a turn the model answers in text never reaches it, and
    # a synonym, a paraphrase or a "그 폴더" follow-up is no longer excluded.
    selected = selected_tool if isinstance(selected_tool, str) else None
    if selected is None:
        return None
    agent_plan = _declared_plan_for_tool(selected, declared_plan)
    if agent_plan is None:
        return None
    files_only = selected in ("files_list", "files")
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
        # The turn already carries a model-selected PC tool, so there is no
        # ordinary answer to fall back to here: a missing owner context is a
        # handled failure, never a silent no-op.
        raise
    from .pc_work_context import (
        SAVED_SELECTION_SELECTED, SAVED_SELECTION_UNAVAILABLE,
        linked_pc_targets, read_saved_device_selection, render_pc_work_context,
        resolve_pc_work_context,
    )
    from .pc_device_pairing_store import link_named_in

    saved_selection = await read_saved_device_selection(
        request, owner_id=uid, workspace_id=workspace_id,
    )
    # #5573: with more than one linked PC the request itself gets to say which
    # machine it means, in the name the owner gave that machine. Only a single
    # match decides; no match leaves the saved target in front, which is what
    # "the last PC I used" means, and the lane still says which machine ran.
    named_device_id = None
    if device_id is None:
        linked = await linked_pc_targets(request, uid)
        if linked:
            named_device_id = link_named_in(
                execution_user_text or user_text, linked,
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
    elif named_device_id is not None:
        device_id = named_device_id
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

    # #5573 / Option A: one Engine call for every model-selected PC tool with a
    # verified PC context. The Engine's existing step driver still decides and
    # runs the tool; the Chat app runs no separate classification call. Prior
    # turns travel in the system context so the same call can resolve "그 폴더"
    # and similar follow-ups.
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
        run_id=client_run_id, agent_plan=agent_plan,
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
    agent_plan: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Stage and run the model-selected plan on the Chat product.

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
    drive_only = any(
        isinstance(step, Mapping) and step.get("tool_id") == CHAT_PC_QUERY_TOOL_ID
        for step in agent_plan.get("steps", ())
    )
    try:
        staged_conversation_id = await store.record_chat_pc_drive_run(
            user_id=uid, run_id=lane_run_id, workspace_id=workspace_id,
            user_text=user_text, conversation_id=conversation_id,
            action="pc_drive_query" if drive_only else "pc_files_query",
            title_prefix="PC 드라이브 조회: " if drive_only else "PC 파일 탐색: ",
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
    tool_arguments = _tool_arguments_for_plan(agent_plan, device_id)
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
            agent_plan=agent_plan,
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
    "CHAT_PC_TOOL_DEFINITIONS",
    "ChatPCDriveError",
    "build_chat_pc_agent_plan",
    "build_chat_pc_files_agent_plan",
    "chat_pc_plan_for_tool",
    "chat_pc_route_declares_tools",
    "chat_pc_tools_available",
    "execute_chat_pc_drive_lane",
    "pc_scope_notice_for_run",
    "pc_tool_entry_available",
]
