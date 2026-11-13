"""Detached user sessions over the existing command queue and job receipts.

The helper v1 wire is unchanged. Only input references reach durable storage;
the existing one-shot typed-text store carries the value to one executor claim.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from collections.abc import Mapping

PC_SHELL_INPUT_TOOL_NAME = "pc_shell_input"
MAX_INPUT_CHARS = 4000
MAX_READ_BYTES = 65536
MAX_WAIT_MS = 10000
# Existing helper frame bound applies to the base64 operation, not raw text.
MAX_OPERATION_CHARS = 50000
ROUNDTRIP_SECONDS = 150
_NOW = time.monotonic
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_KEYS = ("enter", "ctrl_c", "ctrl_d", "ctrl_z", "tab", "esc", "up", "down")
_JOB = {"type": "string", "minLength": 36, "maxLength": 36,
        "description": "대화형 세션을 시작할 때 받은 작업 ID입니다."}
_WAIT = {"type": "integer", "minimum": 0, "maximum": MAX_WAIT_MS,
         "description": "새 출력을 기다릴 시간(밀리초)입니다."}
_OFFSET = {"type": "integer", "minimum": 0,
           "description": "세션 출력의 UTF-8 바이트 위치입니다."}
_LENGTH = {"type": "integer", "minimum": 1, "maximum": MAX_READ_BYTES,
           "description": "읽을 최대 바이트입니다."}
PC_SHELL_INPUT_PROPERTIES = {
    "job_id": _JOB, "text": {"type": "string", "maxLength": MAX_INPUT_CHARS},
    "enter": {"type": "boolean", "default": True},
    "key": {"type": ["string", "null"], "enum": [None, *_KEYS]},
    "secret": {"type": "boolean", "default": False,
               "description": "비밀 입력입니다. 도우미가 출력 가리기를 지원할 때만 전달합니다."},
    "offset": _OFFSET, "length": _LENGTH, "wait_ms": _WAIT,
    "device": {"type": "string", "maxLength": 128},
}


def pc_session_enabled(request) -> bool:
    settings = getattr(getattr(getattr(request, "app", None), "state", None), "settings", request)
    return bool(getattr(settings, "mcp_pc_session_enabled", False))


def session_start_properties():
    return {
        "command": {"type": "string", "maxLength": 50000,
                    "description": "시작할 명령입니다. 대화형 세션에서 빈 문자열은 셸을 엽니다."},
        "interactive": {"type": "boolean", "default": False},
        "terminal": {"type": "boolean", "default": True},
        "cols": {"type": "integer", "minimum": 20, "maximum": 500},
        "rows": {"type": "integer", "minimum": 5, "maximum": 200},
        "keep_minutes": {"type": "integer", "minimum": 1, "maximum": 480},
        "input_encoding": {"type": "string", "enum": ["utf-8", "cp949"]},
        "wait_ms": _WAIT,
    }


def session_read_properties():
    return {"wait_ms": _WAIT, "status_only": {
        "type": "boolean", "default": False,
        "description": "true면 이 작업의 세션 상태와 도우미 지원 기능만 확인합니다."}}


def session_stop_properties():
    return {"offset": _OFFSET, "length": _LENGTH}


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def _range_valid(arguments):
    return (_integer(arguments.get("offset", 0), 0, 2**63 - 1)
            and _integer(arguments.get("length", 32768), 1, MAX_READ_BYTES)
            and _integer(arguments.get("wait_ms", 0), 0, MAX_WAIT_MS))


def validate_pc_session_start_arguments(arguments):
    from .mcp_gateway_shell import PC_SHELL_START_PROPERTIES, PC_SHELL_MAX_CWD_CHARS
    if not isinstance(arguments, Mapping) or not set(arguments) <= (
            set(PC_SHELL_START_PROPERTIES) | set(session_start_properties())):
        return False
    command, cwd = arguments.get("command", ""), arguments.get("cwd")
    valid = (
        arguments.get("interactive") is True
        and isinstance(command, str) and len(command) <= 50000
        and not any(c in command for c in ("\x00", "\r"))
        and (cwd is None or (isinstance(cwd, str) and 0 < len(cwd) <= PC_SHELL_MAX_CWD_CHARS
                             and not any(ord(c) < 32 for c in cwd)))
        and arguments.get("shell", "powershell") in ("powershell", "cmd", "bash")
        and arguments.get("mode", "user") in ("user", "system")
        and type(arguments.get("terminal", True)) is bool
        and _integer(arguments.get("cols", 200), 20, 500)
        and _integer(arguments.get("rows", 50), 5, 200)
        and _integer(arguments.get("keep_minutes", 60), 1, 480)
        and arguments.get("input_encoding", "utf-8") in ("utf-8", "cp949")
        and _integer(arguments.get("wait_ms", 1500), 0, MAX_WAIT_MS)
        and ("device" not in arguments or isinstance(arguments["device"], str))
    )
    if not valid:
        return False
    try:
        return len(_encode_operation(_start_operation(arguments))) <= MAX_OPERATION_CHARS
    except UnicodeError:
        return False


def validate_pc_session_input_arguments(arguments):
    from .mcp_gateway_shell import _valid_job_id
    if not isinstance(arguments, Mapping) or not set(arguments) <= set(PC_SHELL_INPUT_PROPERTIES):
        return False
    text, key = arguments.get("text"), arguments.get("key")
    if "text" in arguments and (not isinstance(text, str) or len(text) > MAX_INPUT_CHARS
                                 or "\x00" in text or "\r" in text):
        return False
    try:
        if isinstance(text, str):
            text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return (_valid_job_id(arguments.get("job_id")) and ("text" in arguments or key is not None)
            and not (text == "" and arguments.get("enter", True) is False and key is None)
            and (key is None or isinstance(key, str) and key in _KEYS)
            and type(arguments.get("enter", True)) is bool
            and type(arguments.get("secret", False)) is bool and _range_valid(arguments)
            and ("device" not in arguments or isinstance(arguments["device"], str)))


def input_marker(text, ref, *, secret):
    marker = {"ref": ref, "chars": len(text), "bytes": len(text.encode("utf-8"))}
    if not secret:
        marker["sha256_prefix"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return marker


def session_input_ref(command_text):
    """Only an actual v1 input marker may consume a one-shot value at poll."""
    try:
        frame = json.loads(command_text)
        operation = json.loads(base64.b64decode(frame["command"], validate=True).decode("utf-8"))
        marker = frame["session_input"]
        if (frame["shell"] != "session" or type(operation.get("v")) is not int or operation["v"] != 1
                or operation.get("op") != "input" or "text_b64" in operation
                or not isinstance(marker, dict) or not _HEX32.fullmatch(marker.get("ref", ""))
                or not _integer(marker.get("chars"), 1, MAX_INPUT_CHARS)
                or not _integer(marker.get("bytes"), 1, MAX_INPUT_CHARS * 4)):
            return None
        secret = operation.get("secret", False)
        if type(secret) is not bool:
            return None
        keys = {"ref", "chars", "bytes"} | (set() if secret else {"sha256_prefix"})
        if set(marker) != keys or (not secret and re.fullmatch(
                r"[0-9a-f]{8}", marker.get("sha256_prefix", "")) is None):
            return None
        return marker["ref"]
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError):
        return None


def _encode_operation(operation):
    return base64.b64encode(json.dumps(operation, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).decode("ascii")


def _start_operation(arguments):
    return {"v": 1, "op": "start", **{k: arguments[k] for k in (
        "shell", "command", "terminal", "cols", "rows", "keep_minutes", "input_encoding", "wait_ms")
        if k in arguments}}


def build_session_material(operation, *, cwd=None, marker=None, session_scope=None):
    frame = {"shell": "session", "command": _encode_operation(operation),
        "cwd": cwd, "timeout_seconds": 0, "distro": None}
    if marker is not None:
        frame["session_input"] = marker
    if session_scope is not None:
        frame["session_scope"] = session_scope
    return json.dumps(frame, separators=(",", ":"))


def _failure(code, *, status="failed"):
    return {"status": status, "code": code, "answer": "대화형 PC 세션 요청을 완료하지 못했습니다."}


def _valid_metadata(row):
    if row.get("prompt_kind") not in (None, "secret") or row.get("waiting_hint") not in (None, "input"):
        return False
    if "alive" in row and type(row["alive"]) is not bool:
        return False
    if "ends_with_newline" in row and type(row["ends_with_newline"]) is not bool:
        return False
    if row.get("ended") not in (None, "exited", "stopped", "expired"):
        return False
    if row.get("exit_code") is not None and type(row["exit_code"]) is not int:
        return False
    if "backend" in row and row["backend"] not in ("pipe", "conpty"):
        return False
    return all(key not in row or _integer(row[key], 0, 2**63 - 1)
               for key in ("offset", "next_offset", "end_offset", "dropped_bytes", "idle_ms"))


def project_session_reply(body, *, op, session_id):
    """Project v1 metadata; no foreign sessions or unknown fields escape."""
    try:
        line, _, output = body.partition("\n")
        header = json.loads(line)
        if not isinstance(header, dict):
            raise ValueError
        if "v" not in header:
            code = header.get("error_code")
            if code == "user_helper_refused":
                return _failure("pc_session_unsupported")
            if code in {"user_session_unavailable", "user_helper_timeout", "user_helper_refused",
                        "pc_session_input_uncertain", "pc_session_unsupported", "pc_session_bad_request",
                        "pc_session_user_mode_only"}:
                return _failure(code)
            raise ValueError
        if type(header.get("v")) is not int or header["v"] != 1 or header.get("op") != op or type(header.get("ok")) is not bool:
            raise ValueError
        if op == "status":
            if not header["ok"]:
                code = header.get("code")
                return _failure(code if isinstance(code, str) and re.fullmatch(
                    r"pc_session_[a-z_]+", code) else "pc_session_bad_reply")
            rows = header.get("sessions")
            if not isinstance(rows, list) or not isinstance(header.get("features", []), list):
                raise ValueError
            rows = [r for r in rows or [] if isinstance(r, dict) and r.get("session") == session_id]
            if any(not _valid_metadata(r) for r in rows):
                raise ValueError
            features = [f for f in header.get("features", []) if f in ("pipe", "conpty", "secret_mask")]
            return {"status": "completed", "ok": header["ok"], "features": features,
                    "sessions": [{k: r[k] for k in ("session", "alive", "ended", "exit_code",
                                "backend", "end_offset", "idle_ms") if k in r} for r in rows]}
        if header.get("session") not in (session_id, None):
            raise ValueError
        if header["ok"] and header.get("session") != session_id:
            raise ValueError
        fields = ("ok", "code", "op", "session", "alive", "ended", "exit_code", "offset",
                  "next_offset", "end_offset", "dropped_bytes", "idle_ms", "ends_with_newline", "backend",
                  "prompt_kind", "waiting_hint")
        result = {k: header[k] for k in fields if k in header}
        if not _valid_metadata(result):
            raise ValueError
        code = result.get("code")
        if code is not None and (not isinstance(code, str) or not re.fullmatch(r"pc_session_[a-z_]+", code)):
            raise ValueError
        for key in ("offset", "next_offset", "end_offset", "dropped_bytes", "idle_ms"):
            if key in result and not _integer(result[key], 0, 2**63 - 1):
                raise ValueError
        return {**result, "status": "completed" if header["ok"] else "failed", "output": output,
                "answer": "PC 세션 상태와 출력을 읽었습니다."}
    except (TypeError, ValueError, AttributeError):
        return _failure("pc_session_bad_reply")


async def _roundtrip(request, *, identity, session, workspace_id, operation,
                     original_job=None, cwd=None, marker=None):
    from . import mcp_gateway_shell as shell
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent
    from .mcp_gateway_execution import _new_lane_run_id
    history = request.app.state.history_store
    run_id = _new_lane_run_id()
    conversation_id = await history.record_chat_pc_drive_run(
        user_id=identity["user_id"], run_id=run_id, workspace_id=workspace_id,
        user_text="PC 세션 요청: " + operation["op"], conversation_id=None,
        action="pc_files_query", title_prefix="PC 세션: ")
    starting = operation["op"] == "start"
    response = await dispatch_oracle_mesh_command_intent(
        request, command=build_session_material(operation, cwd=cwd, marker=marker,
            session_scope=original_job[4:] if operation["op"] == "status" else None),
        wire={"run_id": run_id, "device_id": identity["device_id"], "confirmed": True},
        trusted_owner=(session, identity["user_id"], workspace_id),
        user_mode=True, background=starting,
        job_operation={"op": "session"} if starting else None,
        ttl_seconds=300,
    )
    payload = shell._response_payload(response)
    row = payload.get("dispatch") if isinstance(payload, dict) else None
    dispatch_id = row.get("dispatch_id") if isinstance(row, dict) else None
    if (getattr(response, "status_code", 0) != 200 or not shell._valid_job_id(dispatch_id)
            or row.get("run_id") != run_id or row.get("device_id") != identity["device_id"]):
        await shell._cancel_run(request, uid=identity["user_id"], run_id=run_id)
        return _failure("pc_session_input_uncertain" if operation["op"] == "input"
                        else shell._dispatch_refusal_code(payload) or "pc_session_unavailable")
    job_id = dispatch_id if starting else original_job
    session_id = job_id.removeprefix("dsp_")
    receipt = {"job_id": job_id, "_job_receipt": job_id, "run_id": run_id}
    deadline = _NOW() + ROUNDTRIP_SECONDS
    while True:
        dispatch = await shell._dispatch_row(request, uid=identity["user_id"], dispatch_id=dispatch_id)
        if isinstance(dispatch, dict) and dispatch.get("state") in {"done", "failed"}:
            body = await shell._read_original(request, uid=identity["user_id"], dispatch=dispatch,
                                              run_row={"conversation_id": conversation_id})
            if isinstance(body, str):
                result = project_session_reply(body, op=operation["op"], session_id=session_id)
                return {**result, **receipt}
            break
        if _NOW() >= deadline:
            break
        await asyncio.sleep(min(0.5, max(0, deadline - _NOW())))
    code = "pc_session_input_uncertain" if operation["op"] == "input" else "pc_session_reply_unavailable"
    return {**_failure(code), **receipt}


async def execute_session_tool(request, *, tool_name, arguments, identity,
                               session, subject_id, workspace_id):
    """Return None only when this is an ordinary, unchanged shell operation."""
    from . import mcp_gateway_shell as shell
    from .mcp_gateway_execution import _check_mesh_grant
    from .pc_work_context import resolve_pc_work_context
    starting = tool_name == "pc_shell_start" and arguments.get("interactive") is True
    input_op = tool_name == PC_SHELL_INPUT_TOOL_NAME
    if not pc_session_enabled(request):
        return _failure("pc_session_disabled", status="tool_not_enabled") if starting or input_op else None
    job_id = arguments.get("job_id")
    if not starting:
        if tool_name not in (PC_SHELL_INPUT_TOOL_NAME, "pc_shell_read", "pc_shell_stop"):
            return None
        private = await shell._authorize_job(request, identity=identity, job_id=job_id)
        if private is None:
            return _failure("pc_session_not_found", status="denied") if input_op else None
        public = await shell._dispatch_row(request, uid=identity["user_id"], dispatch_id=job_id)
        if not isinstance(public, dict) or public.get("job_operation") != {"op": "session"}:
            return _failure("pc_session_not_found", status="denied") if input_op else None
        identity = {**identity, "device_id": private["device_id"]}
    settings = getattr(request.app.state, "settings", None)
    if not (getattr(settings, "mcp_pc_shell_enabled", False)
            and getattr(settings, "mcp_pc_shell_user_mode_enabled", False)):
        return _failure("pc_session_disabled", status="tool_not_enabled")
    if starting and arguments.get("mode", "user") != "user":
        return _failure("pc_session_user_mode_only", status="denied")
    if starting and not validate_pc_session_start_arguments(arguments):
        return _failure("pc_session_bad_request")
    if input_op and not validate_pc_session_input_arguments(arguments):
        return _failure("pc_session_bad_request")
    context = await resolve_pc_work_context(
        request, owner_id=identity["user_id"], workspace_id=workspace_id,
        session_id=session.session_id, selected_device_id=identity["device_id"],
        execution_device_id=identity["device_id"])
    if (context.selection_offline or not context.selected_confirmed or not context.tool_available
            or context.selected_device_id != identity["device_id"]
            or context.execution_device_id != identity["device_id"]
            or not await _check_mesh_grant(request, session, device_id=identity["device_id"],
                                          owner_ref=identity["user_id"], denied_reason=[])):
        return _failure("pc_session_unavailable", status="denied")
    common = dict(identity=identity, session=session, workspace_id=workspace_id, original_job=job_id)
    if starting:
        operation = _start_operation(arguments)
        return await _roundtrip(request, operation=operation, cwd=arguments.get("cwd"), **common)
    if arguments.get("status_only") is True:
        return await _roundtrip(request, operation={"v": 1, "op": "status"}, **common)
    op = "input" if input_op else ("read" if tool_name == "pc_shell_read" else "stop")
    operation = {"v": 1, "op": op, "session": job_id[4:]}
    for key in ("offset", "length") + (("wait_ms",) if op != "stop" else ()):
        if key in arguments:
            operation[key] = arguments[key]
    marker = None
    if input_op:
        secret = arguments.get("secret", False)
        if secret:
            capabilities = await _roundtrip(request, operation={"v": 1, "op": "status"}, **common)
            if capabilities.get("status") != "completed" or capabilities.get("ok") is not True:
                return capabilities
            if "secret_mask" not in capabilities.get("features", []):
                return _failure("pc_session_unsupported")
            rows = capabilities.get("sessions", [])
            if len(rows) != 1 or rows[0].get("session") != job_id[4:]:
                return _failure("pc_session_not_found")
            if rows[0].get("alive") is not True:
                return _failure("pc_session_expired" if rows[0].get("ended") == "expired"
                                else "pc_session_ended")
        operation.update({k: arguments[k] for k in ("enter", "key", "secret") if k in arguments})
        text = arguments.get("text")
        # The v1 helper treats empty base64 as absent text. A blank submitted
        # line is one newline without a second automatic Enter, before any key.
        if text == "" and arguments.get("enter", True):
            text = "\n"
            operation["enter"] = False
        if text:
            from .desktop_typed_text import deposit_typed_text
            ref = await deposit_typed_text(getattr(request.app.state, "queue_client", None), text)
            if ref is None:
                return _failure("pc_session_input_uncertain")
            marker = input_marker(text, ref, secret=secret)
    return await _roundtrip(request, operation=operation, marker=marker, **common)
