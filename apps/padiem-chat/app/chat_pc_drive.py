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

from .auth_routes import auth_ready, current_user_id
from .b14_client import B14Client, ChatRuntimeError
from .control_plane_identity_shadow import resolve_refreshed_session
from .history import (
    HistoryForbidden,
    HistoryStore,
    PRODUCT_SCOPE_CHAT,
)
from .central_model_route_runtime import chat_request_tier_context
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

CHAT_PC_DRIVE_COMMAND = (
    "Get-PSDrive -PSProvider FileSystem | "
    "Select-Object Name,Root,Used,Free | ConvertTo-Json"
)
CHAT_PC_QUERY_AGENT_ID = "agent:padiem:chat-pc-query@1"
CHAT_PC_QUERY_TOOL_ID = "claw.pc.query_drives"
CHAT_PC_RUN_PREFIX = "chat_pcq_"

_SUBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class ChatPCDriveError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.status_code = status_code


def _error_response(exc: ChatPCDriveError) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": exc.code, "message": exc.user_message}},
        status_code=exc.status_code,
        headers=dict(_NO_STORE_HEADERS),
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
        "steps": (
            {
                "step_id": "query_drives",
                "objective": "Query verified PC filesystem drives",
                "tool_id": CHAT_PC_QUERY_TOOL_ID,
            },
        ),
    }


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
    """b62 canonical session, subject and tenant workspace for this lane.

    Same fail-closed shape as the memory workspace rule
    (claw_memory_routes._resolve_memory_workspace): both identity components
    absent keeps the legacy owner namespace; a partial setup or a
    failed/inactive session is unavailable, never a fallback identity.
    """
    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if shadow_store is None and authority is None:
        return None, "", f"owner:{uid}"
    if shadow_store is None or authority is None:
        raise ChatPCDriveError(
            "chat_pc_identity_unavailable",
            "사용자 확인 정보를 사용할 수 없습니다.",
        )
    try:
        session = await resolve_refreshed_session(
            authority=authority,
            store=shadow_store,
            product_user_id=uid,
        )
    except Exception as exc:
        raise ChatPCDriveError(
            "chat_pc_identity_unavailable",
            "사용자 확인 정보를 사용할 수 없습니다.",
        ) from exc
    subject_id = getattr(getattr(session, "subject", None), "subject_id", None)
    tenant_id = getattr(session, "tenant_id", None)
    if (
        not isinstance(subject_id, str)
        or _SUBJECT_RE.fullmatch(subject_id) is None
        or not isinstance(tenant_id, str)
        or not tenant_id
    ):
        raise ChatPCDriveError(
            "chat_pc_identity_unavailable",
            "사용자 확인 정보를 사용할 수 없습니다.",
        )
    return session, subject_id, tenant_id


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


async def _complete_with_model(
    request: Request, *, user_text: str, skill: Any,
    tier: str, system_contract: str,
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
                ({"role": "user", "content": user_text},),
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
    skill: Any,
    model_id: str,
    conversation_id: str | None,
    tier: str,
    device_id: str | None = None,
) -> tuple[str, str | None] | None:
    """Run the lane and return ``(answer, conversation_id)``.

    Returns None to fall through to the existing general Chat path
    (anonymous user, no drive detector match). Raises ChatPCDriveError for
    every handled failure. History writes happen here, so both the JSON and
    the SSE call sites share them.
    """
    from .orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError

    uid = current_user_id(request) if auth_ready(request) else None
    if not uid:
        return None
    if not is_chat_pc_drive_query(user_text):
        return None
    store: HistoryStore | None = getattr(request.app.state, "history_store", None)
    if store is None:
        raise ChatPCDriveError(
            "chat_pc_store_unavailable",
            "대화 기록을 현재 사용할 수 없습니다.",
        )
    if device_id is not None and (
        not isinstance(device_id, str) or not _DEVICE_ID_RE.fullmatch(device_id)
    ):
        raise ChatPCDriveError(
            "chat_pc_target_invalid",
            "선택한 PC 정보가 유효하지 않습니다.",
            422,
        )
    session, subject_id, workspace_id = await _resolve_chat_owner(request, uid)
    from .pc_work_context import (
        SAVED_SELECTION_SELECTED, SAVED_SELECTION_UNAVAILABLE,
        read_saved_device_selection,
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
    if not await _check_mesh_grant(request, session, device_id=device_id):
        answer = _no_pc_answer()
        saved_id = await _save_pair(
            store, uid=uid, conversation_id=conversation_id,
            user_text=user_text, answer=answer,
        )
        if saved_id is None:
            raise ChatPCDriveError("conversation_not_found", "대화를 찾을 수 없습니다.", 404)
        return answer, saved_id

    # #5015: the decision model receives the same server-verified PC context
    # the general Chat path gets. It reads both the Broker directory and the
    # Mesh execution target, so an online badge never becomes tool permission.
    from .pc_work_context import render_pc_work_context, resolve_pc_work_context

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
    pc_work_text = render_pc_work_context(pc_context)
    decision_contract = _decision_contract(user_text)
    decision_raw = await _complete_with_model(
        request, user_text=user_text, skill=skill,
        tier=tier,
        system_contract=(
            pc_work_text + "\n\n" + decision_contract
            if pc_work_text else decision_contract
        ),
    )
    decision = parse_chat_pc_tool_decision(decision_raw)
    if decision.get("action") == "complete":
        answer = str(decision["answer"]).strip()
        if not answer:
            return None
        saved_id = await _save_pair(
            store, uid=uid, conversation_id=conversation_id,
            user_text=user_text, answer=answer,
        )
        if saved_id is None:
            raise ChatPCDriveError("conversation_not_found", "대화를 찾을 수 없습니다.", 404)
        return answer, saved_id

    bridge = getattr(request.app.state, "orchestration_bridge", None)
    if not isinstance(bridge, B62EngineOrchestrationBridge) or not bridge.ready:
        raise ChatPCDriveError(
            "chat_pc_drive_unavailable",
            "PC 드라이브 조회 기능을 현재 사용할 수 없습니다.",
        )
    lane_run_id = CHAT_PC_RUN_PREFIX + uuid.uuid4().hex
    try:
        staged_conversation_id = await store.record_chat_pc_drive_run(
            user_id=uid, run_id=lane_run_id, workspace_id=workspace_id,
            user_text=user_text, conversation_id=conversation_id,
        )
    except HistoryForbidden as exc:
        raise ChatPCDriveError("conversation_not_found", "대화를 찾을 수 없습니다.", 404) from exc
    except Exception as exc:
        raise ChatPCDriveError(
            "chat_pc_store_unavailable",
            "대화 기록을 현재 사용할 수 없습니다.",
        ) from exc
    try:
        outcome = await bridge.start(
            user_id=uid,
            messages=({"role": "user", "content": user_text},),
            skill=skill,
            model_id=model_id,
            user_text=user_text,
            conversation_id=staged_conversation_id,
            subject_id=subject_id,
            session_id=lane_run_id,
            agent_plan=build_chat_pc_agent_plan(),
            additional_system_context=pc_work_text,
            tool_arguments=(
                {"query_drives": {"device_id": device_id}}
                if device_id is not None else None
            ),
        )
    except B62OrchestrationError as exc:
        await _append_lane_notice(
            request, store, uid=uid, run_id=lane_run_id,
            content=(
                "PC 드라이브 조회를 완료하지 못했습니다. "
                "같은 요청을 반복하기 전에 PC 연결 상태를 확인해 주세요."
            ),
            status="failed",
        )
        raise ChatPCDriveError("chat_pc_engine_unavailable", exc.user_message, exc.status_code) from exc
    answer = outcome.answer if isinstance(outcome.answer, str) else None
    if not answer or not answer.strip():
        await _append_lane_notice(
            request, store, uid=uid, run_id=lane_run_id,
            content=(
                "PC 드라이브 조회를 완료하지 못했습니다. "
                "같은 요청을 반복하기 전에 PC 연결 상태를 확인해 주세요."
            ),
            status="failed",
        )
        raise ChatPCDriveError(
            "chat_pc_engine_unavailable",
            "AI가 표시할 답변을 만들지 못했습니다.",
            502,
        )
    # The Engine step driver already re-fed the verified tool observation to
    # the model and composed this answer there; the lane records it verbatim
    # instead of adding a second model paraphrase (and a second hallucination
    # surface) on top.
    composed = answer.strip()
    saved = await _append_lane_answer(
        request, store, uid=uid, run_id=lane_run_id, content=composed,
    )
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
    skill: Any,
    model_id: str,
    conversation_id: str | None,
    tier: str,
    device_id: str | None = None,
) -> JSONResponse | None:
    """JSON wrapper of :func:`execute_chat_pc_drive_lane` for /api/chat."""
    try:
        result = await execute_chat_pc_drive_lane(
            request, user_text=user_text, skill=skill, model_id=model_id,
            conversation_id=conversation_id, tier=tier, device_id=device_id,
        )
    except ChatPCDriveError as exc:
        return _error_response(exc)
    if result is None:
        return None
    answer, saved_id = result
    return JSONResponse(public_chat_result({"answer": answer, "conversation_id": saved_id}))


async def _append_lane_answer(
    request: Request, store: HistoryStore, *, uid: str, run_id: str,
    content: str,
) -> bool:
    """Append the lane's final answer beside the verified output message.

    The executor result leg already stored the verified output under this
    run's summary; reusing that stored summary plus a lane-suffixed message
    id keeps the exactly-once and terminal-immutability guards intact while
    adding the model-composed answer to the same conversation.
    """
    _ = request
    try:
        run_row = await store.get_claw_run(uid, run_id)
    except Exception:
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
        appended = await store.append_local_task_result(
            user_id=uid, run_id=run_id, message_id=message_id,
            summary=summary, content=content, status="completed",
        )
        return bool(appended)
    except Exception:
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
        if isinstance(stored, str) and stored:
            appended = await store.append_local_task_result(
                user_id=uid, run_id=run_id, message_id=message_id,
                summary=stored, content=content, status=status,
            )
        else:
            appended = await store.append_local_task_result(
                user_id=uid, run_id=run_id, message_id=message_id,
                summary="failed", content=content, status=status,
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
    "run_chat_pc_drive_lane",
]
