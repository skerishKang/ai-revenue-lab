"""MCP-to-existing Chat/Engine PC adapter; no new PC authority or transport.

pc_shell uses the existing Chat oracle_mesh command lane instead of adding a
model-driven Engine tool; its owner/device/grant checks still run here first.
"""
from collections.abc import Mapping
import base64
import json
import re
import uuid

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError
from .mcp_gateway_shell import (
    PC_SHELL_READ_TOOL_NAME, PC_SHELL_START_TOOL_NAME, PC_SHELL_STOP_TOOL_NAME,
    PC_SHELL_TOOL_NAME, PC_SHELL_TOOL_NAMES, execute_pc_shell,
    execute_pc_shell_read, execute_pc_shell_start, execute_pc_shell_stop,
    normalize_pc_shell_arguments, normalize_pc_shell_read_arguments,
    normalize_pc_shell_start_arguments, normalize_pc_shell_stop_arguments,
    validate_shell_tool_arguments,
)
from .claw_pc_read_command import PC_READ_CHUNK_MAX_BYTES as _PC_READ_CHUNK_MAX_BYTES
from .claw_pc_read_command import PC_READ_OFFSET_MAX as _PC_READ_OFFSET_MAX
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


def _invalid_engine_answer() -> dict:
    """An engine answer that is not a closed status: name that branch."""
    return {"status": "unavailable", "code": "pc_engine_result_invalid",
            "answer": "PC 작업 결과를 확인하지 못했습니다."}


#: The file tools whose ``path`` argument names something inside an approved
#: folder. ``pc_devices`` and the browser tools are not in this set.
_PC_FILE_PATH_TOOLS = frozenset({
    "pc_list", "pc_read", "pc_search", "pc_write", "pc_edit", "pc_move", "pc_delete",
    "pc_mkdir",
    # The read-only additions carry a path too, so they pass the same
    # registered-folder check as every other file tool.
    "pc_search_contents", "pc_file_info",
})
#: Asking for the approved folders themselves, not for one folder's contents.
_PC_ROOT_LIST_PATHS = frozenset({"", "/"})
#: The read-only file tools whose running answer may be continued by job id.
_PC_FILE_JOB_TOOLS = frozenset({"pc_list", "pc_read"})
#: #7065: pc_edit's only optional argument. Naming it alone is a complete call:
#: replace_all absent means false, exactly as the Engine reads it.
_PC_EDIT_OPTIONAL_KEYS = frozenset({"path", "old_text", "new_text", "replace_all"})
#: The only spelling a continuation may name: one common dispatch id.
_JOB_RECEIPT_ID = re.compile(r"dsp_[0-9a-f]{32}\Z")


def _pc_absolute_path(value) -> str | None:
    """``value`` in ``X:/...`` spelling when it names an absolute PC path."""
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\\", "/")
    if not text or any(ord(ch) < 32 for ch in text):
        return None
    if text.startswith("/"):
        return text
    if len(text) >= 2 and text[0].isalpha() and text[1] == ":":
        return text
    return None


def _registered_folder_rows(roots) -> list[dict]:
    """The approved folders as the one ``[{name, path}]`` list both answers use."""
    rows: list[dict] = []
    for root in roots or ():
        if not isinstance(root, Mapping):
            continue
        label, path = root.get("label"), root.get("path")
        if isinstance(label, str) and label and isinstance(path, str) and path:
            rows.append({"name": label, "path": path})
    return rows


def _pc_relative_inside_roots(value, roots) -> tuple[str | None, str | None]:
    """Where an absolute path lands against this account's approved folders.

    ``("label/rest", "inside")`` for a path below a grant, ``(None, "root")``
    when it names the grant itself (a folder, not a file), ``(None, "outside")``
    for an absolute path no grant covers, and ``(None, None)`` when the value is
    already relative and must stay untouched.
    """
    text = _pc_absolute_path(value)
    if text is None:
        return None, None
    folded = text.rstrip("/").casefold()
    best = None
    for root in roots or ():
        base = str(root["path"]).replace("\\", "/").rstrip("/")
        if not base:
            continue
        if folded == base.casefold():
            return None, "root"
        if folded.startswith(base.casefold() + "/"):
            rest = text[len(base) + 1:].strip("/")
            if rest and (best is None or len(base) > best[0]):
                best = (len(base), root["name"], rest)
    if best is None:
        return None, "outside"
    return best[1] + "/" + best[2], "inside"


def _registered_folders_answer(roots: list[dict]) -> dict:
    """The folder list a caller needs before it can name a relative path."""
    if not roots:
        return {"status": "unavailable", "code": "pc_registered_folders_unavailable",
                "answer": "이 PC에 등록된 폴더를 확인하지 못했습니다."}
    names = ", ".join(row["name"] for row in roots)
    return {"status": "completed", "folders": roots,
            "output": {"ok": True, "folders": roots, "entry_count": len(roots)},
            "answer": "이 PC에 등록된 폴더입니다: " + names +
                      ". path에는 표시 이름으로 시작하는 상대 경로를 넣으세요."}


def _outside_registered_roots_answer(roots: list[dict]) -> dict:
    """Refuse a path no grant covers, and hand back the grants it may use."""
    return {"status": "failed", "code": "pc_path_outside_registered_roots",
            "folders": roots,
            "answer": "등록된 폴더 밖의 경로입니다. 등록된 폴더: " +
                      ", ".join(row["name"] for row in roots) + "."}


async def _registered_pc_folders(request, *, session, user_id, device_id) -> list[dict]:
    """The owner's approved folders, from the authority the engine also asks.

    Chat resolves the same target and the same folder set the signed context
    call returns to the Engine, so the folders a caller sees here and the one a
    dispatch lands in cannot drift apart. A resolution that fails keeps the
    previous behaviour: a relative path is staged exactly as it was sent.
    """
    try:
        from .oracle_mesh_read_return_routes import _engine_pc_files_target

        resolved, error = await _engine_pc_files_target(
            request, session=session, selected_device_id=device_id, user_id=user_id,
        )
    except Exception:
        return []
    if error is not None or not isinstance(resolved, Mapping):
        return []
    return _registered_folder_rows(resolved.get("roots"))


_TOOLS = {
    "pc_list": ("files_list", "claw.pc.list_files", {"path", "job_id"}),
    "pc_search": ("files_list", "claw.pc.list_files", {"path", "query"}),
    "pc_read": ("files", "claw.pc.read_file", {"path", "job_id", "offset", "length"}),
    # Read-only additions. Each reuses the Engine tool that already does the
    # work; nothing here widens what those tools may touch.
    "pc_search_contents": ("files_list", "claw.pc.search_contents", {"path", "query"}),
    # A one-row listing is the listing tool itself, and the Engine refuses a
    # gateway tool that is not one of the plan's steps, so the plan carries it.
    "pc_file_info": ("files_list", "claw.pc.list_files", {"path"}),
    # The optional mode travels with the rest of the arguments into the request
    # digest, so an overwrite approval can never run an append and the other
    # way around. Absent mode is the only behavior this tool ever had.
    "pc_write": ("files_write", "claw.pc.write_file", {"path", "content", "mode"}),
    # #7065: the same write lane, with the part of the file named instead of the
    # whole new content. pc_write's approval, backup, scope check and account
    # line all apply unchanged.
    "pc_edit": ("files_write", "claw.pc.edit_file", {
        "path", "old_text", "new_text", "replace_all"}),
    # One folder. The same write lane, approval and scope check; there is no
    # original to back up, so the command's backup leg answers none.
    "pc_mkdir": ("files_write", "claw.pc.mkdir", {"path"}),
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


async def _pc_system_mode_allowed(request, *, uid: str, device_id: str) -> bool:
    """SYSTEM execution needs an administrator AND a managed PC (2026-11-08).

    Fail-closed: no authority, no pairing store, a missing link or any error is
    a refusal. It never switches the caller to the user lane; a caller who asked
    for SYSTEM gets SYSTEM or an explicit denial.
    """
    from .platform_admin_authority import platform_authority_for
    try:
        admin = await platform_authority_for(request).is_global_model_admin(user_id=uid)
    except Exception:
        admin = False
    if admin is not True:
        return False
    store = getattr(request.app.state, "pc_device_pairing_store", None)
    reader = getattr(store, "is_managed_link", None)
    if not callable(reader):
        return False
    try:
        return await reader(user_id=uid, mesh_node_id=device_id) is True
    except Exception:
        return False


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
    settings = getattr(request.app.state, "settings", None)
    shell_enabled = bool(getattr(settings, "mcp_pc_shell_enabled", False))
    shell_user_enabled = bool(getattr(settings, "mcp_pc_shell_user_mode_enabled", False))
    if shell:
        if not validate_shell_tool_arguments(tool_name, arguments):
            raise ValueError("Invalid MCP PC arguments")
        if tool_name in {PC_SHELL_TOOL_NAME, PC_SHELL_START_TOOL_NAME}:
            arguments = _SHELL_TOOLS[tool_name](
                arguments, user_mode_enabled=shell_user_enabled,
            )
        else:
            arguments = _SHELL_TOOLS[tool_name](arguments)
        scope, tool_id, keys = None, None, set()
        browser = False
    else:
        scope, tool_id, keys = _TOOLS[tool_name]
        browser = scope == "browser"
        arguments = dict(arguments)
        arguments.pop("device", None)
        if tool_name in ("pc_search", "pc_search_contents") and "path" not in arguments:
            # No folder named means every approved folder, which is what the
            # existing name search already does with ".".
            arguments["path"] = "."
        if browser:
            from .claw_pc_browser_command import browser_arguments
            arguments = browser_arguments(tool_id.removeprefix("claw.pc."), arguments)
        elif "job_id" in keys and set(arguments) == {"job_id"}:
            # A continuation names the dispatch that is already running. It
            # stages nothing; ownership is checked against that dispatch below.
            pass
        elif (set(arguments) not in (keys - {"job_id"}, keys - {"replace_all"},
                                     keys - {"job_id", "mode"},
                                     keys - {"offset"}, keys - {"length"},
                                     keys - {"offset", "length"},
                                     keys - {"offset", "length", "job_id"})
                and not (tool_name == "pc_list" and not arguments)) or any(
                not ((isinstance(value, str) or (
                        tool_name == "pc_edit" and key == "replace_all"
                        and isinstance(value, bool)))
                     or (tool_name == "pc_read" and key == "offset"
                         and type(value) is int and not isinstance(value, bool)
                         and 0 <= value <= _PC_READ_OFFSET_MAX)
                     or (tool_name == "pc_read" and key == "length"
                         and type(value) is int and not isinstance(value, bool)
                         and 0 < value <= _PC_READ_CHUNK_MAX_BYTES))
                for key, value in arguments.items()):
            # The job id is an alternative to the target path, never an extra
            # field: a new call names the path and nothing else. pc_list alone
            # may name nothing, which asks for the approved folder list.
            # #7065: pc_edit may omit replace_all, and when it carries it the
            # value is a real boolean, not the string "false".
            raise ValueError("Invalid MCP PC arguments")
    # #7065: replace_all is the one optional argument in the closed table, and
    # its value is a real boolean. An absent flag means false; the string
    # "false" is a caller mistake, not a flag, so it is refused here rather
    # than silently treated as true downstream.
    if tool_name == "pc_edit" and "replace_all" in arguments and (
            not isinstance(arguments["replace_all"], bool)):
        raise ValueError("Invalid MCP PC arguments")
    # The write mode is one of two spellings. The digest binds whatever the
    # caller sent, and an unknown value is a caller mistake, not a mode to
    # guess: refusing here keeps it from ever reaching the engine.
    if tool_name == "pc_write" and arguments.get("mode", "overwrite") not in (
            "overwrite", "append"):
        raise ValueError("Invalid MCP PC arguments")
    # A range read names both ends or neither: an offset alone would silently
    # become "offset 0", and a length alone has no start to read from.
    if tool_name == "pc_read" and (("offset" in arguments) != ("length" in arguments)):
        raise ValueError("Invalid MCP PC arguments")
    # #7565: the SYSTEM rule follows the mode the command will actually run in,
    # not the user-mode switch. With the switch off the normalizer's default is
    # SYSTEM, so an omitted mode is a SYSTEM run and gets the same check.
    if (shell_enabled
            and tool_name in {PC_SHELL_TOOL_NAME, PC_SHELL_START_TOOL_NAME}
            and isinstance(arguments, Mapping) and arguments.get("mode", "system") != "user"
            and not await _pc_system_mode_allowed(request, uid=uid, device_id=device_id)):
        return {"status": "denied",
                "answer": "SYSTEM 실행은 관리자와 관리(계약) PC에서만 허용됩니다.",
                "deny_reason": "pc_shell_system_denied"}
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

    identity = {"user_id": uid, "device_id": device_id, "token_id": token_id}
    if shell and not shell_enabled:
        if tool_name != PC_SHELL_STOP_TOOL_NAME:
            return {"status": "tool_not_enabled", "answer": "이 도구는 현재 배포에서 꺼져 있습니다."}
        return await execute_pc_shell_stop(
            request, identity=identity, job_id=arguments["job_id"],
        )
    if shell and isinstance(arguments, Mapping) and arguments.get("mode") == "user" and not shell_user_enabled:
        return {"status": "tool_not_enabled", "answer": "이 모드는 현재 환경에서 사용할 수 없습니다.",
                "deny_reason": "pc_shell_user_mode_disabled"}

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
    # A caller that has never seen this PC's folders cannot name a relative
    # path, and one it does know the spelling of is absolute. Both are answered
    # from the same approved set the Engine's signed context call receives.
    folders: list[dict] = []
    if tool_name in _PC_FILE_PATH_TOOLS:
        folders = await _registered_pc_folders(
            request, session=session, user_id=uid, device_id=device_id,
        )
    if tool_name == "pc_list" and "job_id" not in arguments:
        requested = arguments.get("path")
        text = requested.strip().replace("\\", "/") if isinstance(requested, str) else ""
        # No path and "/" name no folder at all; "." names one only when the
        # account has a single grant. Anything else would be a guess.
        if text in _PC_ROOT_LIST_PATHS or (text == "." and len(folders) > 1):
            return _registered_folders_answer(folders)
    if folders:
        for key in ("path", "destination"):
            if key not in arguments:
                continue
            relative, where = _pc_relative_inside_roots(arguments[key], folders)
            if where == "outside":
                return _outside_registered_roots_answer(folders)
            if where == "root":
                if tool_name == "pc_list" and key == "path":
                    return _registered_folders_answer(folders)
                return _outside_registered_roots_answer(folders)
            if relative is not None:
                arguments[key] = relative
    if "job_id" in keys and set(arguments) == {"job_id"}:
        # 2026-11-04: the first call may hand the dispatch back instead of
        # holding the MCP request open. The same tool continues it, and the
        # Engine still receives only that dispatch id on its signed wire.
        return await _resume_pc_files(
            request, uid=uid, subject_id=subject_id, device_id=device_id,
            token_id=token_id, tool_name=tool_name, scope=scope, tool_id=tool_id,
            job_id=arguments["job_id"], plan_builder=chat_pc_plan_for_tool,
            plan_arguments=_tool_arguments_for_plan,
        )
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
    # #7065: pc_edit is the one tool whose plan is narrower than its scope, so
    # the plan is chosen by the tool that was asked for. Every other tool keeps
    # the scope's plan exactly as before (files_write still stages the three
    # write steps).
    plan_key = {"pc_edit": "files_edit", "pc_mkdir": "files_mkdir",
                "pc_search_contents": "files_search_contents",
                "pc_file_info": "files_info"}.get(tool_name, scope)
    if tool_name == "pc_read" and ("offset" in arguments or "length" in arguments):
        # A range read is the Engine's own chunk tool. Without the two
        # arguments this stays exactly the whole-file read it always was.
        plan_key, tool_id = "files_chunk", "claw.pc.read_file_chunk"
    plan = chat_pc_plan_for_tool(plan_key)
    wire_arguments = {key: value for key, value in arguments.items() if key != "query"}
    if tool_name == "pc_read" and tool_id == "claw.pc.read_file_chunk":
        chunk = {"path": arguments["path"], "offset": arguments.get("offset", 0)}
        if "length" in arguments:
            chunk["length"] = arguments["length"]
        wire_arguments = chunk
    gateway = {"version": 1, "source": "mcp", "token_id": token_id,
        "request_id": "mcp_" + uuid.uuid4().hex, "tool_id": tool_id, "arguments": wire_arguments}
    if browser_context is not None:
        gateway["browser_context"] = {"url": browser_context["url"]}
    if approval_id is not None:
        gateway["approval_id"] = approval_id
    if tool_name in ("pc_search", "pc_search_contents"):
        # The gateway admits a search only with the query beside the tool id;
        # the query itself never travels as a path argument.
        gateway["search_query"] = arguments["query"]
    from .model_policy import resolve_model_policy
    from .task_modes import get_task_mode
    # Reuse the configured product profile required by admission. The gateway
    # driver is deterministic and never dispatches a model selection call.
    messages = [{"role": "assistant", "content": "External MCP transport request; not user speech."}]
    policy = resolve_model_policy(messages)
    try:
        outcome = await bridge.start(user_id=uid, messages=messages, skill=get_task_mode("auto"),
            model_id=policy.model_id, user_text=label, conversation_id=conversation_id,
            subject_id=subject_id, session_id=run_id, agent_plan=plan,
            tool_arguments=_tool_arguments_for_plan(plan, device_id),
            pc_action_context=[], pc_delegation=await load_pc_delegation(request, uid),
            pc_gateway=gateway)
    except B62OrchestrationError as exc:
        # The engine refused or could not be reached: no PC work was
        # dispatched, so the branch is named, not answered as unknown.
        raise ChatPCDriveError("chat_pc_engine_unavailable", exc.user_message,
                               exc.status_code, cause=exc.code) from exc
    try:
        result = json.loads(outcome.answer)
    except (TypeError, ValueError):
        result = _invalid_engine_answer()
    if not isinstance(result, dict) or result.get("status") not in {
        "completed", "running", "queued", "confirmation_required", "failed",
        "unavailable",
    }:
        result = _invalid_engine_answer()
    # 2026-11-04: a file tool may answer "running" and hand the dispatch back,
    # and the same tool then continues it with that job id. The continuation is
    # authorized by the audit receipt, so the receipt is attached here and
    # nowhere else: a browser or write answer carrying one would have its audit
    # refused and the run cancelled (_record_outcome's guard).
    receipt = result.get("job_id")
    if (tool_name in _PC_FILE_JOB_TOOLS and result["status"] in {"running", "queued"}
            and isinstance(receipt, str) and _JOB_RECEIPT_ID.fullmatch(receipt)):
        result["_job_receipt"] = receipt
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
                          "code": "pc_browser_capture_unreadable",
                          "answer": "브라우저 캡처의 실제 이미지를 확인하지 못했습니다."}
    # The normal PC run already stores signed observations. Add a normal
    # dialogue notice, preserving unsuccessful postcondition evidence.
    # A running answer is not a terminal notice: the run is still working on the
    # PC and the continuation reads it through the same tool.
    if result["status"] not in {"running", "queued"}:
        await _append_lane_notice(request, store, uid=uid, run_id=run_id,
            content=str(result.get("answer", "")),
            status="completed" if result["status"] in {"completed", "confirmation_required"} else "failed")
    return {**result, "run_id": run_id}


async def _resume_pc_files(
    request, *, uid, subject_id, device_id, token_id, tool_name, scope, tool_id,
    job_id, plan_builder, plan_arguments,
):
    """Continue the PC file dispatch an earlier call left running.

    The ownership rule is the one pc_shell_read already uses: the dispatch must
    belong to this user, to this MCP token (its audit receipt) and to the PC that
    ran it. Nothing new is staged, and the Engine is handed that dispatch id
    only, on the run it already owns - so the signed wire keeps its existing
    shape and the Chat route keeps its existing checks.
    """
    store = getattr(request.app.state, "history_store", None)
    mcp_store = getattr(request.app.state, "mcp_gateway_store", None)
    reader = getattr(store, "get_pc_output_dispatch_for_owner", None)
    owns = getattr(mcp_store, "owns_job_receipt", None)
    unavailable = {"status": "unavailable", "code": "pc_job_status_unavailable",
                   "answer": "PC 작업 상태를 확인하지 못했습니다."}
    if not callable(reader) or not callable(owns):
        return unavailable
    try:
        row = await reader(user_id=uid, dispatch_id=job_id)
    except Exception:
        return unavailable
    if (
        not isinstance(row, dict)
        or row.get("dispatch_id") != job_id
        or row.get("user_id") != uid
        or row.get("device_id") != device_id
        or row.get("kind") not in {"command", "read"}
    ):
        return {"status": "denied", "code": "pc_job_not_owned",
                "answer": "이 작업을 확인할 수 없습니다."}
    try:
        owned = await owns(
            identity={"user_id": uid, "device_id": device_id, "token_id": token_id},
            job_id=job_id,
        )
    except Exception:
        owned = False
    if not owned:
        # Another token's job is not this caller's work, even when the account
        # and the PC happen to match.
        return {"status": "denied", "code": "pc_job_not_owned",
                "answer": "이 작업을 확인할 수 없습니다."}
    run_id = row.get("run_id")
    run_reader = getattr(store, "get_claw_run", None)
    try:
        run = await run_reader(uid, run_id) if callable(run_reader) else None
    except Exception:
        run = None
    conversation_id = run.get("conversation_id") if isinstance(run, dict) else None
    bridge = getattr(request.app.state, "orchestration_bridge", None)
    if (
        not isinstance(run_id, str) or not run_id
        or not isinstance(conversation_id, str) or not conversation_id
        or not isinstance(bridge, B62EngineOrchestrationBridge) or not bridge.ready
    ):
        return {**unavailable, "code": "pc_engine_unavailable"}
    from .model_policy import resolve_model_policy
    from .task_modes import get_task_mode
    plan = plan_builder(scope)
    gateway = {"version": 1, "source": "mcp", "token_id": token_id,
        "request_id": "mcp_" + uuid.uuid4().hex, "tool_id": tool_id,
        "arguments": {"job_id": job_id}}
    messages = [{"role": "assistant", "content": "External MCP transport request; not user speech."}]
    policy = resolve_model_policy(messages)
    try:
        try:
            outcome = await bridge.start(
                user_id=uid, messages=messages, skill=get_task_mode("auto"),
                model_id=policy.model_id, user_text="외부 AI 도구 요청: " + tool_name,
                conversation_id=conversation_id, subject_id=subject_id, session_id=run_id,
                agent_plan=plan, tool_arguments=plan_arguments(plan, device_id),
                pc_action_context=[], pc_delegation=await load_pc_delegation(request, uid),
                pc_gateway=gateway,
            )
        except B62OrchestrationError as exc:
            # The engine refused or could not be reached: no PC work was
            # dispatched, so the branch is named, not answered as unknown.
            raise ChatPCDriveError("chat_pc_engine_unavailable", exc.user_message,
                                   exc.status_code, cause=exc.code) from exc
    except Exception:
        return unavailable
    try:
        result = json.loads(outcome.answer)
    except (TypeError, ValueError):
        return unavailable
    if not isinstance(result, dict) or result.get("status") not in {
        "completed", "running", "queued", "failed", "unavailable",
    }:
        return unavailable
    return result
