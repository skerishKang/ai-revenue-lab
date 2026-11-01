"""MCP-to-existing Chat/Engine PC adapter; no alternate PC execution path."""
from collections.abc import Mapping
import json
import uuid

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .orchestration_bridge import B62EngineOrchestrationBridge
from .pc_delegation_routes import load_pc_delegation
from .pc_work_context import resolve_pc_work_context


# The interactive PC lane is resolved on first use (PEP 562), so importing
# this module — and the app factory that owns it — never pulls that lane or its
# browser-facing modules into the Worker import graph. The names stay module
# attributes, so a caller may still patch them by name.
_PC_LANE_NAMES = frozenset({
    "ChatPCDriveError", "_resolve_chat_owner", "_check_mesh_grant",
    "_tool_arguments_for_plan", "_new_lane_run_id", "_append_lane_notice",
    "chat_pc_plan_for_tool",
})


def __getattr__(name):
    if name in _PC_LANE_NAMES:
        from . import chat_pc_drive
        return getattr(chat_pc_drive, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_TOOLS = {
    "pc_list": ("files_list", "claw.pc.list_files", {"path"}),
    "pc_search": ("files_list", "claw.pc.list_files", {"path", "query"}),
    "pc_read": ("files", "claw.pc.read_file", {"path"}),
    "pc_write": ("files_write", "claw.pc.write_file", {"path", "content"}),
    "pc_move": ("files_write", "claw.pc.move_file", {"path", "destination"}),
    "pc_delete": ("files_write", "claw.pc.delete_file", {"path"}),
}


async def execute_mcp_pc_tool(request, principal, tool_name, arguments, *, approval=None):
    """Called only after PAT verification; an approval is an atomic-store result.

    principal and approval are server facts, never copied from MCP tool args.
    The external request deliberately carries an empty user-evidence list.
    Delegation is loaded afresh for this owner on every call.
    """
    # Resolve the interactive PC lane on first use. A name already patched on
    # this module wins; otherwise it is loaded here, so the app factory import
    # never pulls that lane into the Worker import graph.
    _lane = globals()

    def _pc(name):
        value = _lane.get(name)
        if value is None:
            from . import chat_pc_drive
            value = getattr(chat_pc_drive, name)
        return value

    ChatPCDriveError = _pc("ChatPCDriveError")
    _resolve_chat_owner = _pc("_resolve_chat_owner")
    _check_mesh_grant = _pc("_check_mesh_grant")
    _tool_arguments_for_plan = _pc("_tool_arguments_for_plan")
    _new_lane_run_id = _pc("_new_lane_run_id")
    _append_lane_notice = _pc("_append_lane_notice")
    chat_pc_plan_for_tool = _pc("chat_pc_plan_for_tool")
    if not isinstance(principal, Mapping):
        raise ValueError("A verified MCP principal is required")
    uid, device_id, token_id = (principal.get(key) for key in ("owner_id", "device_id", "token_id"))
    if not isinstance(uid, str) or not uid or not is_pc_device_id(device_id) or not isinstance(token_id, str):
        raise ValueError("Invalid MCP principal")
    if tool_name not in _TOOLS or not isinstance(arguments, Mapping):
        raise ValueError("Unsupported MCP PC tool")
    scope, tool_id, keys = _TOOLS[tool_name]
    arguments = dict(arguments)
    if tool_name == "pc_search" and "path" not in arguments:
        arguments["path"] = "."
    if set(arguments) != keys or any(not isinstance(value, str) for value in arguments.values()):
        raise ValueError("Invalid MCP PC arguments")
    approval_id = None
    if approval is not None:
        from .mcp_gateway_store import mcp_request_digest
        if (not isinstance(approval, Mapping) or set(approval) != {"approval_id", "request_digest"}
                or approval["request_digest"] != mcp_request_digest(tool_name, arguments)
                or not isinstance(approval["approval_id"], str)):
            raise ValueError("MCP approval does not match this request")
        approval_id = approval["approval_id"]

    session, subject_id, workspace_id = await _resolve_chat_owner(request, uid)
    if session is None or not subject_id:
        raise ChatPCDriveError("chat_pc_identity_unavailable", "사용자 정보를 확인하지 못했습니다.")
    context = await resolve_pc_work_context(request, owner_id=uid, workspace_id=workspace_id,
        session_id=session.session_id, selected_device_id=device_id)
    if (not context.selected_confirmed or not context.tool_available
            or context.execution_device_id != device_id
            or not await _check_mesh_grant(request, session, device_id=device_id)):
        raise ChatPCDriveError("chat_pc_target_unavailable", "이 토큰의 PC에 접근할 수 없습니다.", 403)
    bridge = getattr(request.app.state, "orchestration_bridge", None)
    store = getattr(request.app.state, "history_store", None)
    if not isinstance(bridge, B62EngineOrchestrationBridge) or not bridge.ready or store is None:
        raise ChatPCDriveError("chat_pc_files_unavailable", "PC 파일 도구를 현재 사용할 수 없습니다.")
    run_id = _new_lane_run_id()
    # This history label is explicitly an external-tool event; it is never
    # submitted as user intent to the first-stage harness.
    label = "외부 AI 도구 요청: " + tool_name
    conversation_id = await store.record_chat_pc_drive_run(user_id=uid, run_id=run_id,
        workspace_id=workspace_id, user_text=label, conversation_id=None,
        action="pc_files_query", title_prefix="외부 AI PC 작업: ")
    plan = chat_pc_plan_for_tool(scope)
    wire_arguments = {key: value for key, value in arguments.items() if key != "query"}
    gateway = {"version": 1, "source": "mcp", "token_id": token_id,
        "request_id": "mcp_" + uuid.uuid4().hex, "tool_id": tool_id, "arguments": wire_arguments}
    if approval_id is not None:
        gateway["approval_id"] = approval_id
    if tool_name == "pc_search":
        gateway["search_query"] = arguments["query"]
    from .model_policy import resolve_model_policy
    from .task_modes import get_task_mode
    # Reuse the configured product profile required by admission. The gateway
    # driver is deterministic and never dispatches a model selection call.
    messages = [{"role": "assistant", "content": "External MCP transport request; not user speech."}]
    policy = resolve_model_policy(messages)
    outcome = await bridge.start(user_id=uid, messages=messages, skill=get_task_mode("auto"),
        model_id=policy.model_id, user_text=label, conversation_id=conversation_id,
        subject_id=subject_id, session_id=run_id, agent_plan=plan,
        tool_arguments=_tool_arguments_for_plan(plan, device_id),
        pc_action_context=[], pc_delegation=await load_pc_delegation(request, uid),
        pc_gateway=gateway)
    try:
        result = json.loads(outcome.answer)
    except (TypeError, ValueError):
        result = {"status": "unavailable", "answer": "PC 작업 결과를 확인하지 못했습니다."}
    if not isinstance(result, dict) or result.get("status") not in {
        "completed", "confirmation_required", "failed", "unavailable",
    }:
        result = {"status": "unavailable", "answer": "PC 작업 결과를 확인하지 못했습니다."}
    # The normal PC run already stores signed observations. Add a normal
    # dialogue notice, preserving unsuccessful postcondition evidence.
    await _append_lane_notice(request, store, uid=uid, run_id=run_id,
        content=str(result.get("answer", "")),
        status="completed" if result["status"] in {"completed", "confirmation_required"} else "failed")
    return {**result, "run_id": run_id}
