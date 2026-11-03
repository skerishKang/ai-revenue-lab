"""MCP-to-existing Chat/Engine PC adapter; no new PC authority or transport.

pc_shell uses the existing Chat oracle_mesh command lane instead of adding a
model-driven Engine tool; its owner/device/grant checks still run here first.
"""
from collections.abc import Mapping
import base64
import json
import uuid

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .orchestration_bridge import B62EngineOrchestrationBridge
from .mcp_gateway_shell import (
    PC_SHELL_READ_TOOL_NAME, PC_SHELL_START_TOOL_NAME, PC_SHELL_STOP_TOOL_NAME,
    PC_SHELL_TOOL_NAME, PC_SHELL_TOOL_NAMES, execute_pc_shell,
    execute_pc_shell_read, execute_pc_shell_start, execute_pc_shell_stop,
    normalize_pc_shell_arguments, normalize_pc_shell_read_arguments,
    normalize_pc_shell_start_arguments, normalize_pc_shell_stop_arguments,
    validate_shell_tool_arguments,
)
from .pc_delegation_routes import load_pc_delegation
from .pc_work_context import resolve_pc_work_context


PC_DEVICES_TOOL_NAME = "pc_devices"


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
    "pc_browser_open": ("browser", "claw.pc.browser_open", {"url"}),
    "pc_browser_read": ("browser", "claw.pc.browser_read", set()),
    "pc_browser_screenshot": ("browser", "claw.pc.browser_screenshot", set()),
    "pc_browser_act": ("browser", "claw.pc.browser_act", {"action", "text", "role", "name", "value"}),
}

_SHELL_TOOLS = {
    PC_SHELL_TOOL_NAME: normalize_pc_shell_arguments,
    PC_SHELL_START_TOOL_NAME: normalize_pc_shell_start_arguments,
    PC_SHELL_READ_TOOL_NAME: normalize_pc_shell_read_arguments,
    PC_SHELL_STOP_TOOL_NAME: normalize_pc_shell_stop_arguments,
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
    if (not isinstance(arguments, Mapping)
            or (tool_name not in _TOOLS and tool_name not in PC_SHELL_TOOL_NAMES
                and tool_name != PC_DEVICES_TOOL_NAME)):
        raise ValueError("Unsupported MCP PC tool")
    if tool_name == PC_DEVICES_TOOL_NAME:
        # The one tool that answers for every linked PC instead of one target.
        # The caller chose nothing here; device selection happens per call.
        from .mcp_device_selection import list_owner_devices
        devices = await list_owner_devices(request, owner_id=uid, principal=principal)
        return {"status": "completed", "devices": devices,
                "answer": "연결된 PC 목록입니다. 다른 pc_* 도구의 device 인자에 표시 이름이나 id6를 넣어 PC를 고를 수 있습니다."}
    shell = tool_name in PC_SHELL_TOOL_NAMES
    raw_arguments = dict(arguments) if shell else None
    original_arguments = dict(arguments)
    # `device` was resolved to principal.device_id in dispatch before the first
    # audit write. Here it only has to leave the wire arguments: the plan, the
    # shell command and the browser call all take their PC from the principal.
    chosen_device = arguments.get("device") if isinstance(arguments, Mapping) else None
    device_chosen = isinstance(chosen_device, str) and bool(chosen_device.strip())
    if shell:
        if not validate_shell_tool_arguments(tool_name, arguments):
            raise ValueError("Invalid MCP PC arguments")
        arguments = _SHELL_TOOLS[tool_name](arguments)
        scope, tool_id, keys = None, None, set()
        browser = False
    else:
        scope, tool_id, keys = _TOOLS[tool_name]
        browser = scope == "browser"
        arguments = dict(arguments)
        arguments.pop("device", None)
        if tool_name == "pc_search" and "path" not in arguments:
            arguments["path"] = "."
        if browser:
            from .claw_pc_browser_command import browser_arguments
            arguments = browser_arguments(tool_id.removeprefix("claw.pc."), arguments)
        elif set(arguments) != keys or any(not isinstance(value, str) for value in arguments.values()):
            raise ValueError("Invalid MCP PC arguments")
    approval_id = None
    if approval is not None:
        if browser:
            raise ValueError("Browser confirmation must use ordinary first-party conversation")
        from .mcp_gateway_store import mcp_request_digest
        if (not isinstance(approval, Mapping) or set(approval) != {"approval_id", "request_digest"}
                or approval["request_digest"] != mcp_request_digest(
                    tool_name, raw_arguments if shell else original_arguments)
                or not isinstance(approval["approval_id"], str)):
            raise ValueError("MCP approval does not match this request")
        approval_id = approval["approval_id"]

    settings = getattr(request.app.state, "settings", None)
    shell_enabled = bool(getattr(settings, "mcp_pc_shell_enabled", False))
    identity = {"user_id": uid, "device_id": device_id, "token_id": token_id}
    if shell and not shell_enabled:
        if tool_name != PC_SHELL_STOP_TOOL_NAME:
            return {"status": "tool_not_enabled", "answer": "이 도구는 현재 배포에서 꺼져 있습니다."}
        return await execute_pc_shell_stop(
            request, identity=identity, job_id=arguments["job_id"],
        )

    session, subject_id, workspace_id = await _resolve_chat_owner(request, uid)
    if session is None or not subject_id:
        raise ChatPCDriveError("chat_pc_identity_unavailable", "사용자 정보를 확인하지 못했습니다.")
    bridge = getattr(request.app.state, "orchestration_bridge", None)
    store = getattr(request.app.state, "history_store", None)
    if store is None:
        raise ChatPCDriveError("chat_pc_files_unavailable", "PC 파일 도구를 현재 사용할 수 없습니다.")
    if shell and tool_name in {PC_SHELL_READ_TOOL_NAME, PC_SHELL_STOP_TOOL_NAME}:
        if tool_name == PC_SHELL_READ_TOOL_NAME:
            result = await execute_pc_shell_read(
                request, identity=identity, subject_id=subject_id, arguments=arguments,
            )
        else:
            result = await execute_pc_shell_stop(
                request, identity=identity, job_id=arguments["job_id"],
            )
        return result
    if shell:
        # #6717 후속: MCP는 토큰에 묶인 PC를 실행 대상으로 확정한다 — 저장된
        # 선택(다른 PC)과 토큰 device가 달라도 이 요청의 PC는 토큰이 증명한
        # 것이다. pc_work_context의 일반 핀 인자(#6793이 호출마다 고른 PC를
        # 넘길 때도 사용). 소유자 활성 링크·온라인·도구 가능·mesh grant는
        # 아래와 pc_work_context 내부에서 그대로 검사된다.
        context = await resolve_pc_work_context(
            request, owner_id=uid, workspace_id=workspace_id,
            session_id=session.session_id, selected_device_id=device_id,
            execution_device_id=device_id,
        )
        if context.selection_offline or context.selected_device_id != device_id:
            return {"status": "unavailable",
                    "code": "device_offline" if device_chosen else "pc_offline",
                    "answer": "선택한 PC가 꺼져 있음"}
        denial: list[str] = []
        if (not context.selected_confirmed or not context.tool_available
                or context.execution_device_id != device_id
                or not await _check_mesh_grant(request, session, device_id=device_id,
                                               owner_ref=uid, denied_reason=denial)):
            raise ChatPCDriveError("chat_pc_target_unavailable", "이 토큰의 PC에 접근할 수 없습니다.", 403,
                                   cause=denial[0] if denial else None)
        run_id = _new_lane_run_id()
        label = "외부 AI 도구 요청: " + tool_name
        conversation_id = await store.record_chat_pc_drive_run(user_id=uid, run_id=run_id,
            workspace_id=workspace_id, user_text=label, conversation_id=None,
            action="pc_files_query", title_prefix="외부 AI PC 작업: ")
        # 2026-11-04: the dispatch session is the connector's own Chat login
        # session (product b62) — the ownership-map lanes' identity RPC admits
        # it after the reviewed same-user bridge
        # (docs/operations/CONNECTOR_ENROLLMENT_CHAT_SESSION_BRIDGE_REVIEW_261104.md),
        # so the earlier b54-session requirement is no longer needed here.
        if tool_name == PC_SHELL_TOOL_NAME:
            result = await execute_pc_shell(
                request, session=session, uid=uid, subject_id=subject_id,
                workspace_id=workspace_id, device_id=device_id, token_id=token_id,
                run_id=run_id, conversation_id=conversation_id, arguments=arguments,
            )
        else:
            result = await execute_pc_shell_start(
                request, session=session, uid=uid, workspace_id=workspace_id,
                device_id=device_id, run_id=run_id, conversation_id=conversation_id,
                arguments=arguments,
            )
        result = {**result, "run_id": run_id}
        if result.get("status") not in {"running", "queued", "completed"}:
            await _append_lane_notice(request, store, uid=uid, run_id=run_id,
                content=str(result.get("answer", "")), status="failed")
        return result
    context = await resolve_pc_work_context(request, owner_id=uid, workspace_id=workspace_id,
        session_id=session.session_id, selected_device_id=device_id,
        execution_device_id=device_id)
    denial: list[str] = []
    if device_chosen and context.selection_offline:
        return {"status": "unavailable", "code": "device_offline",
                "answer": "선택한 PC가 꺼져 있음"}
    if (not context.selected_confirmed or not context.tool_available
            or context.execution_device_id != device_id
            or not await _check_mesh_grant(request, session, device_id=device_id,
                                           owner_ref=uid, denied_reason=denial)):
        raise ChatPCDriveError("chat_pc_target_unavailable", "이 토큰의 PC에 접근할 수 없습니다.", 403,
                               cause=denial[0] if denial else None)
    if not isinstance(bridge, B62EngineOrchestrationBridge) or not bridge.ready:
        raise ChatPCDriveError("chat_pc_files_unavailable", "PC 파일 도구를 현재 사용할 수 없습니다.")
    browser_context = None
    if browser:
        from .mcp_browser_context import load_browser_context
        try:
            browser_context = await load_browser_context(store, principal)
        except Exception:
            browser_context = None
        if tool_name != "pc_browser_open" and browser_context is None:
            return {"status": "confirmation_required", "answer": "먼저 어느 웹페이지를 열까요? 주소를 알려 주세요.",
                    "confirmation_kind": "conversation", "browser_context_available": False}
    run_id = _new_lane_run_id()
    # This history label is explicitly an external-tool event; it is never
    # submitted as user intent to the first-stage harness.
    label = "외부 AI 도구 요청: " + tool_name
    conversation_id = await store.record_chat_pc_drive_run(user_id=uid, run_id=run_id,
        workspace_id=workspace_id, user_text=label,
        conversation_id=browser_context["conversation_id"] if browser_context else None,
        action="pc_browser_query" if browser else "pc_files_query", title_prefix="외부 AI PC 작업: ")
    plan = chat_pc_plan_for_tool(scope)
    wire_arguments = {key: value for key, value in arguments.items() if key != "query"}
    gateway = {"version": 1, "source": "mcp", "token_id": token_id,
        "request_id": "mcp_" + uuid.uuid4().hex, "tool_id": tool_id, "arguments": wire_arguments}
    if browser_context is not None:
        gateway["browser_context"] = {"url": browser_context["url"]}
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
    if browser:
        result["conversation_id"] = conversation_id
        if result["status"] == "confirmation_required":
            result["confirmation_kind"] = "conversation"
        verified_context = result.get("browser_context")
        if result["status"] == "completed" and isinstance(verified_context, Mapping):
            from .mcp_browser_context import save_browser_context
            try:
                result["browser_context_saved"] = await save_browser_context(
                    store, principal, url=verified_context.get("url"), conversation_id=conversation_id)
            except Exception:
                result["browser_context_saved"] = False
            if not result["browser_context_saved"]:
                result["continuity_note"] = "페이지 작업은 확인했지만 다음 작업에 이어 쓸 주소를 저장하지 못했습니다. 다음에는 주소부터 다시 열어 주세요."
        if tool_name == "pc_browser_screenshot" and result["status"] == "completed":
            output = result.get("output")
            capture = output.get("browser_capture") if isinstance(output, Mapping) else None
            try:
                from .claw_pc_browser_routes import read_browser_capture
                image, digest = await read_browser_capture(store, user_id=uid,
                    dispatch_id=capture["dispatch_id"], device_id=device_id)
                if digest != capture.get("sha256") or len(image) != capture.get("bytes"):
                    raise ValueError("Browser capture receipt differs from stored original")
                # This private projection becomes one MCP image block, never
                # text in the model context or a public local-PC file path.
                result["_browser_image"] = {"type": "image", "mimeType": "image/png",
                    "data": base64.b64encode(image).decode("ascii")}
            except Exception:
                result = {**result, "status": "unavailable",
                          "answer": "브라우저 캡처의 실제 이미지를 확인하지 못했습니다."}
    # The normal PC run already stores signed observations. Add a normal
    # dialogue notice, preserving unsuccessful postcondition evidence.
    await _append_lane_notice(request, store, uid=uid, run_id=run_id,
        content=str(result.get("answer", "")),
        status="completed" if result["status"] in {"completed", "confirmation_required"} else "failed")
    return {**result, "run_id": run_id}
