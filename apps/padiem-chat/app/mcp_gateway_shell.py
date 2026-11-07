"""MCP shell adapter over Claw's common background dispatch and OutputStore.

MCP owns only a token-scoped hash receipt. The Claw dispatch owns execution,
state, cancellation and the output handle; this module never creates an
MCP-specific PC file or execution table.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from collections.abc import Mapping

from padiem_ai_core.pc_device_identity import is_pc_device_id

PC_SHELL_TOOL_NAME = "pc_shell"
PC_SHELL_START_TOOL_NAME = "pc_shell_start"
PC_SHELL_READ_TOOL_NAME = "pc_shell_read"
PC_SHELL_STOP_TOOL_NAME = "pc_shell_stop"
PC_SHELL_TOOL_NAMES = frozenset({
    PC_SHELL_TOOL_NAME, PC_SHELL_START_TOOL_NAME,
    PC_SHELL_READ_TOOL_NAME, PC_SHELL_STOP_TOOL_NAME,
})
PC_SHELL_SHELLS = ("powershell", "cmd", "bash")
PC_SHELL_DEFAULT_WAIT_SECONDS = 120
# The edge front door keeps 30 seconds of headroom under its 180-second MCP
# request ceiling. This limits only the response wait, never the PC process.
PC_SHELL_MAX_WAIT_SECONDS = 150
PC_SHELL_START_TTL_SECONDS = 3600
PC_SHELL_MAX_COMMAND_CHARS = 50_000
PC_SHELL_MAX_CWD_CHARS = 2_048
PC_SHELL_READ_DEFAULT_BYTES = 32_768
PC_SHELL_READ_MAX_BYTES = 65_536
PC_SHELL_POLL_SECONDS = 0.5
_DISPATCH_ID = re.compile(r"dsp_[0-9a-f]{32}\Z")
_OUTPUT_HANDLE = re.compile(r"[0-9a-f]{64}\Z")
_NOW = time.monotonic

PC_SHELL_DEVICE_PROPERTY = {
    "type": "string", "maxLength": 128,
    "description": "대상 PC입니다. pc_devices가 알려 준 표시 이름이나 id6를 씁니다. 비우면 연결의 기본 PC를 씁니다.",
}
PC_SHELL_MODES = ("system", "user")
PC_SHELL_MODE_PROPERTY = {
    "type": "string", "enum": list(PC_SHELL_MODES),
    "description": "실행 세션입니다. 사용자 모드가 켜진 배포에서 mode를 생략하면 user로 실행합니다. system은 mode=system으로 명시하며, 사용자 모드가 꺼진 배포의 생략 기본값은 system입니다.",
}


def _shell_base_properties():
    return {
        "device": dict(PC_SHELL_DEVICE_PROPERTY),
        "command": {
            "type": "string", "minLength": 1, "maxLength": PC_SHELL_MAX_COMMAND_CHARS,
            "description": "연결된 PC에서 실행할 명령입니다. 실행 시간 제한은 없습니다.",
        },
        "cwd": {
            "type": "string", "minLength": 1, "maxLength": PC_SHELL_MAX_CWD_CHARS,
            "description": "실행 폴더입니다. 생략하면 PC의 기본 작업 폴더를 씁니다.",
        },
        "shell": {
            "type": "string", "enum": list(PC_SHELL_SHELLS),
            "description": "사용할 셸입니다. 기본값은 powershell입니다.",
        },
        "wait_seconds": {
            "type": "integer", "minimum": 1, "maximum": PC_SHELL_MAX_WAIT_SECONDS,
            "description": "응답에서 기다릴 시간입니다. 이 시간이 지나도 PC 작업은 계속 실행됩니다.",
        },
    }


PC_SHELL_PROPERTIES = {**_shell_base_properties(), "mode": dict(PC_SHELL_MODE_PROPERTY)}
PC_SHELL_START_PROPERTIES = {
    key: dict(PC_SHELL_PROPERTIES[key]) for key in ("command", "cwd", "shell", "mode", "device")
}
PC_SHELL_READ_PROPERTIES = {
    "job_id": {"type": "string", "minLength": 36, "maxLength": 36,
               "description": "pc_shell 또는 pc_shell_start가 돌려준 Claw 작업 ID입니다."},
    "offset": {"type": "integer", "minimum": 0,
               "description": "출력 핸들의 시작 위치(바이트)입니다."},
    "length": {"type": "integer", "minimum": 1, "maximum": PC_SHELL_READ_MAX_BYTES,
               "description": "읽을 최대 바이트입니다."},
    "device": dict(PC_SHELL_DEVICE_PROPERTY),
}
PC_SHELL_STOP_PROPERTIES = {
    "job_id": dict(PC_SHELL_READ_PROPERTIES["job_id"]),
    "device": dict(PC_SHELL_DEVICE_PROPERTY),
}


def _pc_shell_user_mode_enabled(request_or_settings=None) -> bool:
    if request_or_settings is None:
        return False
    settings = getattr(request_or_settings, "app", None)
    settings = getattr(settings, "state", None)
    settings = getattr(settings, "settings", request_or_settings)
    if getattr(request_or_settings, "app", None) is None and hasattr(request_or_settings, "mcp_pc_shell_user_mode_enabled"):
        settings = request_or_settings
    return bool(getattr(settings, "mcp_pc_shell_user_mode_enabled", False))


def pc_shell_properties(*, user_mode_enabled: bool = False):
    props = _shell_base_properties()
    if user_mode_enabled:
        props["mode"] = dict(PC_SHELL_MODE_PROPERTY)
    return props


def pc_shell_start_properties(*, user_mode_enabled: bool = False):
    base = pc_shell_properties(user_mode_enabled=user_mode_enabled)
    return {key: dict(base[key]) for key in ("command", "cwd", "shell", "device") + (("mode",) if user_mode_enabled else ())}


def _command_material(arguments: Mapping) -> bool:
    command = arguments.get("command")
    if (not isinstance(command, str) or not command or "\x00" in command
            or len(command) > PC_SHELL_MAX_COMMAND_CHARS):
        return False
    cwd = arguments.get("cwd")
    if cwd is not None and (
            not isinstance(cwd, str) or not cwd or len(cwd) > PC_SHELL_MAX_CWD_CHARS
            or any(ord(char) < 32 for char in cwd)):
        return False
    shell = arguments.get("shell", "powershell")
    return isinstance(shell, str) and shell in PC_SHELL_SHELLS


def _valid_job_id(value) -> bool:
    return isinstance(value, str) and _DISPATCH_ID.fullmatch(value) is not None


def _mode_argument_valid(arguments: Mapping, *, allow_user_mode: bool) -> bool:
    if "mode" not in arguments:
        return True
    mode = arguments.get("mode")
    if not isinstance(mode, str) or mode not in PC_SHELL_MODES:
        return False
    return allow_user_mode or mode == "system"


def validate_pc_shell_arguments(arguments, *, user_mode_enabled: bool | None = None) -> bool:
    allowed = set(pc_shell_properties(user_mode_enabled=True if user_mode_enabled is None else bool(user_mode_enabled)))
    if not isinstance(arguments, Mapping) or not set(arguments) <= allowed:
        return False
    if "command" not in arguments or not _command_material(arguments):
        return False
    if not _mode_argument_valid(arguments, allow_user_mode=True if user_mode_enabled is None else bool(user_mode_enabled)):
        return False
    wait = arguments.get("wait_seconds", PC_SHELL_DEFAULT_WAIT_SECONDS)
    return isinstance(wait, int) and not isinstance(wait, bool) and 1 <= wait <= PC_SHELL_MAX_WAIT_SECONDS


def validate_pc_shell_start_arguments(arguments, *, user_mode_enabled: bool | None = None) -> bool:
    allowed = set(pc_shell_start_properties(user_mode_enabled=True if user_mode_enabled is None else bool(user_mode_enabled)))
    if not (isinstance(arguments, Mapping) and set(arguments) <= allowed
            and "command" in arguments and _command_material(arguments)):
        return False
    return _mode_argument_valid(arguments, allow_user_mode=True if user_mode_enabled is None else bool(user_mode_enabled))


def validate_pc_shell_read_arguments(arguments) -> bool:
    if not isinstance(arguments, Mapping) or not set(arguments) <= set(PC_SHELL_READ_PROPERTIES):
        return False
    offset = arguments.get("offset", 0)
    length = arguments.get("length", PC_SHELL_READ_DEFAULT_BYTES)
    return (
        _valid_job_id(arguments.get("job_id"))
        and isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0
        and isinstance(length, int) and not isinstance(length, bool)
        and 1 <= length <= PC_SHELL_READ_MAX_BYTES
    )


def validate_pc_shell_stop_arguments(arguments) -> bool:
    # The advertised schema (PC_SHELL_STOP_PROPERTIES) includes the optional
    # ``device`` selector shared by every PC tool, so an accepted call must not be
    # rejected for passing it. The job id alone names the job; ``device`` is not
    # needed to find it and is not used here.
    if not isinstance(arguments, Mapping) or not set(arguments) <= set(PC_SHELL_STOP_PROPERTIES):
        return False
    device = arguments.get("device")
    if device is not None and not isinstance(device, str):
        return False
    return "job_id" in arguments and _valid_job_id(arguments.get("job_id"))


def validate_shell_tool_arguments(tool_name: str, arguments, *, user_mode_enabled: bool | None = None) -> bool:
    if tool_name == PC_SHELL_TOOL_NAME:
        return validate_pc_shell_arguments(arguments, user_mode_enabled=user_mode_enabled)
    if tool_name == PC_SHELL_START_TOOL_NAME:
        return validate_pc_shell_start_arguments(arguments, user_mode_enabled=user_mode_enabled)
    if tool_name == PC_SHELL_READ_TOOL_NAME:
        return validate_pc_shell_read_arguments(arguments)
    if tool_name == PC_SHELL_STOP_TOOL_NAME:
        return validate_pc_shell_stop_arguments(arguments)
    return False


def _pc_shell_default_mode(user_mode_enabled: bool) -> str:
    """The one default-mode decision for pc_shell and pc_shell_start."""
    return "user" if user_mode_enabled else "system"


def normalize_pc_shell_arguments(
    arguments: Mapping, *, user_mode_enabled: bool = False,
) -> dict:
    if not validate_pc_shell_arguments(arguments):
        raise ValueError("Invalid MCP PC shell arguments")
    return {"command": arguments["command"], "cwd": arguments.get("cwd"),
            "shell": arguments.get("shell", "powershell"),
            "mode": arguments.get("mode", _pc_shell_default_mode(user_mode_enabled)),
            "wait_seconds": arguments.get("wait_seconds", PC_SHELL_DEFAULT_WAIT_SECONDS)}


def normalize_pc_shell_start_arguments(
    arguments: Mapping, *, user_mode_enabled: bool = False,
) -> dict:
    if not validate_pc_shell_start_arguments(arguments):
        raise ValueError("Invalid MCP PC shell start arguments")
    return {"command": arguments["command"], "cwd": arguments.get("cwd"),
            "shell": arguments.get("shell", "powershell"),
            "mode": arguments.get("mode", _pc_shell_default_mode(user_mode_enabled))}


def normalize_pc_shell_read_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_read_arguments(arguments):
        raise ValueError("Invalid MCP PC shell read arguments")
    return {"job_id": arguments["job_id"],
            "offset": arguments.get("offset", 0),
            "length": arguments.get("length", PC_SHELL_READ_DEFAULT_BYTES)}


def normalize_pc_shell_stop_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_stop_arguments(arguments):
        raise ValueError("Invalid MCP PC shell stop arguments")
    return {"job_id": arguments["job_id"]}


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def build_pc_shell_command(arguments: Mapping) -> str:
    """Encode command material into a static PowerShell dispatcher command.

    The command remains a parameter to the common Claw executor. Long-running
    work is supervised by RemoteBackgroundJobs, not by an MCP-side worker.
    """
    if not _command_material(arguments):
        raise ValueError("Invalid MCP PC shell arguments")
    command_b64 = _b64(arguments["command"])
    cwd_b64 = _b64(arguments["cwd"]) if arguments.get("cwd") else ""
    shell = arguments.get("shell", "powershell")
    script = r"""
$ErrorActionPreference='Continue';$ProgressPreference='SilentlyContinue'
# #7068: a Korean-locale console hands the nested process's bytes back in its
# code page, and this host's reader then fails to parse them as CliXml
# (ProcessStreamReader_CliXmlError). The console is pinned to UTF-8 so the bytes
# round-trip, and the nested call below asks for Text output explicitly.
try{[Console]::OutputEncoding=[Text.Encoding]::UTF8}catch{}
$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PADIEM_MCP_COMMAND_B64))
$d=$null;if($env:PADIEM_MCP_CWD_B64){$d=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PADIEM_MCP_CWD_B64));if(-not(Test-Path -LiteralPath $d -PathType Container)){[Console]::Error.WriteLine('cwd_invalid');exit 126};Set-Location -LiteralPath $d}
try{if($env:PADIEM_MCP_SHELL -eq 'powershell'){$file='powershell.exe';if(-not(Get-Command $file -ErrorAction SilentlyContinue)){[Console]::Error.WriteLine('shell_unavailable');exit 127};$inner=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($c));& $file -NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand $inner;$code=0;if($null -ne $LASTEXITCODE){$code=[int]$LASTEXITCODE};exit $code};$file='cmd.exe';$args=@('/d','/s','/c',$c);if($env:PADIEM_MCP_SHELL -eq 'bash'){$file='bash.exe';$args=@('-lc',$c)};if(-not(Get-Command $file -ErrorAction SilentlyContinue)){[Console]::Error.WriteLine('shell_unavailable');exit 127};& $file @args;$code=0;if($null -ne $LASTEXITCODE){$code=[int]$LASTEXITCODE};exit $code}catch{[Console]::Error.WriteLine($_.Exception.Message);exit 1}
""".strip()
    script_b64 = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # PowerShell command text is fixed, and user values are base64 data only.
    # The executor runs this command inside its own PowerShell envelope and
    # reads the reply marker from that wrapper. An outer exit here would end
    # the wrapper before the envelope is written; the nested shell's code
    # already lands in $LASTEXITCODE, which the executor's sentinel reports.
    return (
        "$env:PADIEM_MCP_COMMAND_B64='" + command_b64 + "';"
        "$env:PADIEM_MCP_CWD_B64='" + cwd_b64 + "';"
        "$env:PADIEM_MCP_SHELL='" + shell + "';"
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
        + script_b64
    )


#: #7076d/#7105 — where this tool's shell vocabulary meets the helper's.
#: ``bash`` is the same shell the helper runs inside the user's WSL, and the
#: identity probe is the one command that means the same thing in every shell,
#: so it maps to the helper's dedicated ``whoami`` shell. ``powershell`` and
#: ``cmd`` are the helper's own stage-2 shells, so they pass through as the shell
#: the user session runs. Every other name is passed through unchanged too: the
#: helper is the final allowlist authority and its own refusal is what the caller
#: must see, not a second copy of that rule.
USER_HELPER_SHELL_FOR_BASH = "wsl"
USER_HELPER_SHELL_FOR_WHOAMI = "whoami"
# #7107: request material only. 0 means the helper has no execution deadline;
# the command runs until it ends and the owner stops it through pc_shell_stop.
USER_HELPER_TIMEOUT_SECONDS = 0


def build_pc_shell_user_material(arguments: Mapping) -> str:
    """#7076d — the helper request material for one ``mode=user`` command.

    The canonical wire contract is #7065 stage-1
    (``claw_connect.user_session_helper``, ``parse_request``/``HelperRequest``):
    a JSON object carrying ``shell``/``command``/``cwd``/``timeout_seconds``/
    ``distro``. The executor unwraps exactly this shape
    (``local_agent_oracle_mesh_executor.py:1550-1570``), and the PC's pipe client
    adds ``request_id`` and the HMAC ``nonce`` because only that PC holds the
    deployment secret they are signed with.

    This is deliberately NOT ``build_pc_shell_command``: that string is the
    SYSTEM lane's PowerShell dispatcher, and sending it here is what made a
    ``mode=user`` request arrive as something the user-session helper can never
    parse.
    """
    if not _command_material(arguments):
        raise ValueError("Invalid MCP PC shell arguments")
    command = arguments["command"]
    shell = arguments.get("shell", "powershell")
    if command.strip() == "whoami":
        helper_shell = USER_HELPER_SHELL_FOR_WHOAMI
    elif shell == "bash":
        helper_shell = USER_HELPER_SHELL_FOR_BASH
    else:
        helper_shell = shell
    return json.dumps({
        "shell": helper_shell,
        "command": command,
        "cwd": arguments.get("cwd"),
        "timeout_seconds": USER_HELPER_TIMEOUT_SECONDS,
        "distro": None,
    }, ensure_ascii=True, separators=(",", ":"))


async def _dispatch_command(request, *, command, run_id, device_id, trusted_owner, user_mode=False):
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent
    return await dispatch_oracle_mesh_command_intent(
        request, command=command,
        wire={"run_id": run_id, "device_id": device_id, "confirmed": True},
        trusted_owner=trusted_owner, background=True,
        ttl_seconds=PC_SHELL_START_TTL_SECONDS,
        user_mode=user_mode,
    )


def _response_payload(response):
    try:
        payload = json.loads(bytes(getattr(response, "body", b"")).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def _dispatch_row(request, *, uid, dispatch_id):
    store = getattr(request.app.state, "history_store", None)
    reader = getattr(store, "get_oracle_mesh_dispatch_for_owner", None)
    if not callable(reader):
        return None
    try:
        return await reader(user_id=uid, dispatch_id=dispatch_id)
    except Exception:
        return None


async def _private_dispatch_row(request, *, uid, dispatch_id):
    store = getattr(request.app.state, "history_store", None)
    reader = getattr(store, "get_pc_output_dispatch_for_owner", None)
    if not callable(reader):
        return None
    try:
        return await reader(user_id=uid, dispatch_id=dispatch_id)
    except Exception:
        return None


async def _read_original(request, *, uid, dispatch, run_row):
    from .claw_local_task_result_projection import result_message_id
    from .history import validate_conversation_id
    store = getattr(request.app.state, "history_store", None)
    reader = getattr(store, "read_oracle_mesh_original", None)
    if not callable(reader):
        return None
    try:
        conversation_id = validate_conversation_id(run_row.get("conversation_id"))
        if not conversation_id:
            return None
        message_id = result_message_id(
            conversation_id=conversation_id, command_id=dispatch["command_id"],
            revision_ref=dispatch["revision_ref"],
        )
        stored = await reader(user_id=uid, dispatch_id=dispatch["dispatch_id"],
                              conversation_id=conversation_id, message_id=message_id)
    except Exception:
        return None
    if not isinstance(stored, tuple) or len(stored) != 2:
        return None
    content, digest = stored
    if (not isinstance(content, bytes) or not isinstance(digest, str)
            or hashlib.sha256(content).hexdigest() != digest
            or digest != dispatch.get("result_sha256")
            or len(content) != dispatch.get("result_bytes")):
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


async def _authorize_job(request, *, identity, job_id, require_receipt=True):
    """Bind a job to (user, token, the PC the job itself names).

    2026-11-04 multi-device: one token can start jobs on several PCs, so the
    job row - not the token's default PC - decides which PC a follow-up read
    or stop touches (the Desktop Commander #599 shape: a job id must reach the
    machine that ran it). The receipt still binds the exact start call:
    (user, token, the PC the job was started on), read from the row.
    """
    if not _valid_job_id(job_id):
        return None
    row = await _private_dispatch_row(request, uid=identity["user_id"], dispatch_id=job_id)
    if (not isinstance(row, dict) or row.get("dispatch_id") != job_id
            or row.get("kind") != "command" or row.get("user_id") != identity["user_id"]
            or not is_pc_device_id(row.get("device_id"))):
        return None
    if require_receipt:
        mcp_store = getattr(request.app.state, "mcp_gateway_store", None)
        owns = getattr(mcp_store, "owns_job_receipt", None)
        if not callable(owns):
            return None
        try:
            if not await owns(identity={**identity, "device_id": row["device_id"]},
                              job_id=job_id):
                return None
        except Exception:
            return None
    return row


async def is_active_job_for_identity(request, *, identity, job_id) -> bool:
    """Used by the transport to keep stop available while the switch is off."""
    row = await _authorize_job(request, identity=identity, job_id=job_id)
    if row is None:
        return False
    public = await _dispatch_row(request, uid=identity["user_id"], dispatch_id=job_id)
    return isinstance(public, dict) and public.get("state") == "pending"


def _status(dispatch: Mapping) -> str:
    if dispatch.get("state") in {"pending", "received"}:
        return "running" if dispatch.get("claimed") is True or dispatch.get("state") == "received" else "queued"
    if dispatch.get("state") == "done":
        return "completed"
    if dispatch.get("termination") == "cancelled":
        return "cancelled"
    return "failed"


async def _output_reference(request, *, identity, subject_id, dispatch, private, run):
    uid = identity["user_id"]
    run_id = dispatch.get("run_id")
    if (not isinstance(run_id, str) or run.get("run_id") != run_id
            or dispatch.get("state") not in {"done", "failed"}):
        return None
    output = await _read_original(request, uid=uid, dispatch=dispatch, run_row=run)
    if output is None:
        return None
    store = getattr(request.app.state, "history_store", None)
    writer = getattr(store, "store_pc_output", None)
    if not callable(writer):
        return None
    try:
        ref = await writer(
            user_id=uid, subject_id=subject_id, run_id=run_id,
            device_id=private["device_id"], dispatch_id=dispatch["dispatch_id"],
            source="mcp_shell", content=output,
        )
    except Exception:
        return None
    if (not isinstance(ref, dict) or not _OUTPUT_HANDLE.fullmatch(str(ref.get("handle", "")))
            or type(ref.get("size")) is not int or ref["size"] < 0):
        return None
    return {"handle": ref["handle"], "size": ref["size"], "truncated": ref.get("truncated") is True}


def _terminal_without_output(result: dict, code: str) -> dict:
    """A finished job keeps its status and exit code when only bytes are missing.

    "The command finished with exit 1 but its stored output cannot be read" is
    not the same fact as "the PC connection is unavailable". The store path
    (#6830/#6833) keeps small bodies for exited/no_reply, so a missing copy is
    an output-store problem, reported with its own code.
    """
    return {**result, "output": "", "output_ref": None, "code": code,
            "answer": "PC 작업이 끝났지만 출력을 읽지 못했습니다."}


async def _job_snapshot(request, *, identity, subject_id, job_id, offset, length,
                        require_receipt=True):
    private = await _authorize_job(request, identity=identity, job_id=job_id,
                                   require_receipt=require_receipt)
    if private is None:
        return {"status": "denied", "answer": "이 작업을 확인할 수 없습니다."}
    dispatch = await _dispatch_row(request, uid=identity["user_id"], dispatch_id=job_id)
    if not isinstance(dispatch, dict) or dispatch.get("run_id") != private.get("run_id"):
        return {"status": "unavailable", "answer": "PC 작업 상태를 확인하지 못했습니다."}
    state = _status(dispatch)
    result = {"status": state, "job_id": job_id, "answer": "PC 작업이 실행 중입니다." if state in {"queued", "running"} else "PC 작업이 끝났습니다.",
              "termination": dispatch.get("termination"), "exit_code": dispatch.get("exit_code"),
              "output": "", "next_offset": offset, "_job_receipt": job_id}
    if state in {"queued", "running"}:
        return result
    history = getattr(request.app.state, "history_store", None)
    run_reader = getattr(history, "get_claw_run", None)
    if not callable(run_reader):
        return {"status": "unavailable", "answer": "PC 작업 상태를 확인하지 못했습니다."}
    try:
        run = await run_reader(identity["user_id"], dispatch["run_id"])
    except Exception:
        run = None
    if not isinstance(run, dict):
        return _terminal_without_output(result, "pc_output_unavailable")
    ref = await _output_reference(request, identity=identity, subject_id=subject_id,
                                  dispatch=dispatch, private=private, run=run)
    if ref is None:
        if dispatch.get("termination") == "cancelled":
            return {**result, "output_ref": None}
        return _terminal_without_output(result, "pc_output_unavailable")
    reader = getattr(history, "read_pc_output", None)
    if not callable(reader):
        return _terminal_without_output(result, "pc_output_read_failed")
    bounded_offset = min(offset, ref["size"])
    try:
        page = await reader(user_id=identity["user_id"], subject_id=subject_id,
                            run_id=dispatch["run_id"], device_id=private["device_id"],
                            handle=ref["handle"], offset=bounded_offset, length=length)
    except Exception:
        return _terminal_without_output(result, "pc_output_read_failed")
    if not isinstance(page, dict) or not isinstance(page.get("content"), str):
        return _terminal_without_output(result, "pc_output_read_failed")
    next_offset = min(ref["size"], bounded_offset + len(page["content"].encode("utf-8")))
    return {**result, "output": page["content"], "next_offset": next_offset,
            "output_ref": ref, "answer": "PC 작업 출력을 읽었습니다.",
            "audit": {"exit_code": (dispatch.get("exit_code")
                                     if isinstance(dispatch.get("exit_code"), int)
                                     and not isinstance(dispatch.get("exit_code"), bool)
                                     else None),
                      "output_bytes": ref["size"],
                      "output_truncated": ref["truncated"]}}


def _dispatch_refusal_code(payload) -> str | None:
    """The intent route's fixed refusal code, if the payload names one."""
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,63}", code):
            return code
    return None


async def execute_pc_shell_start(request, *, uid, workspace_id, device_id, run_id,
                                 session, conversation_id, arguments):
    # The normalizer owns the default mode; this lane only consumes its result.
    user_mode = arguments.get("mode") == "user"
    # #7076d: a user-mode dispatch carries the helper's request material, which
    # is the one shape the executor and the #7065 helper both speak. The SYSTEM
    # lane keeps its PowerShell dispatcher unchanged.
    command = (build_pc_shell_user_material(arguments) if user_mode
               else build_pc_shell_command(arguments))
    response = await _dispatch_command(
        request, command=command, run_id=run_id, device_id=device_id,
        trusted_owner=(session, uid, workspace_id), user_mode=user_mode,
    )
    payload = _response_payload(response)
    dispatch = payload.get("dispatch") if isinstance(payload, dict) else None
    job_id = dispatch.get("dispatch_id") if isinstance(dispatch, dict) else None
    if (getattr(response, "status_code", 0) != 200 or not isinstance(dispatch, dict)
            or not _valid_job_id(job_id) or dispatch.get("run_id") != run_id
            or dispatch.get("device_id") != device_id):
        # The dispatch could have been created even if a malformed projection
        # came back. Cancel only this run, which contains one MCP command.
        await _cancel_run(request, uid=uid, run_id=run_id)
        # The refusal branch must reach the audit event: the intent route's
        # fixed code (oracle_mesh_* — why the dispatch did not stage) rides
        # beside the generic owner wording.
        return {"status": "unavailable", "answer": "PC 작업을 시작하지 못했습니다.",
                "deny_reason": _dispatch_refusal_code(payload) or "pc_shell_start_refused"}
    return {"status": "running", "answer": "PC 작업을 시작했습니다.", "job_id": job_id,
            "_job_receipt": job_id}


async def execute_pc_shell(request, *, uid, subject_id, workspace_id, device_id,
                           run_id, session, conversation_id, arguments, token_id):
    started = await execute_pc_shell_start(
        request, uid=uid, workspace_id=workspace_id, device_id=device_id,
        run_id=run_id, session=session, conversation_id=conversation_id,
        arguments={key: arguments[key] for key in ("command", "cwd", "shell", "mode") if key in arguments},
    )
    if started.get("status") != "running":
        return started
    job_id = started["job_id"]
    deadline = _NOW() + arguments["wait_seconds"]
    snapshot = None
    poll_seconds = PC_SHELL_POLL_SECONDS
    while _NOW() < deadline:
        snapshot = await _job_snapshot(
            request, identity={"user_id": uid, "device_id": device_id, "token_id": token_id},
            subject_id=subject_id, job_id=job_id, offset=0,
            length=PC_SHELL_READ_DEFAULT_BYTES, require_receipt=False,
        )
        if snapshot.get("status") not in {"queued", "running"}:
            return snapshot
        # 대표 결정(2026-11-07): 대기 폴링은 처음 빠르게, 점점 느리게(상한 5초).
        # 전체 대기 한도(wait_seconds)는 그대로다.
        await asyncio.sleep(min(poll_seconds, max(0, deadline - _NOW())))
        poll_seconds = min(poll_seconds * 2, 5.0)
    return {"status": "running", "answer": "응답 대기 시간이 끝났습니다. PC 작업은 계속 실행 중입니다.",
            "job_id": job_id, "output": "", "next_offset": 0,
            "_job_receipt": job_id}


async def execute_pc_shell_read(request, *, identity, subject_id, arguments):
    return await _job_snapshot(
        request, identity=identity, subject_id=subject_id, job_id=arguments["job_id"],
        offset=arguments.get("offset", 0),
        length=arguments.get("length", PC_SHELL_READ_DEFAULT_BYTES),
    )


async def execute_pc_shell_stop(request, *, identity, job_id):
    private = await _authorize_job(request, identity=identity, job_id=job_id)
    if private is None:
        return {"status": "denied", "answer": "이 작업을 중지할 수 없습니다."}
    dispatch = await _dispatch_row(request, uid=identity["user_id"], dispatch_id=job_id)
    if not isinstance(dispatch, dict) or dispatch.get("run_id") != private.get("run_id"):
        return {"status": "denied", "answer": "이 작업을 중지할 수 없습니다."}
    if dispatch.get("state") != "pending":
        return {"status": "completed", "answer": "이미 끝난 작업입니다.", "job_id": job_id,
                "_job_receipt": job_id}
    history = getattr(request.app.state, "history_store", None)
    cancel = getattr(history, "cancel_oracle_mesh_dispatches_for_run", None)
    if not callable(cancel):
        return {"status": "unavailable", "answer": "작업 중지 요청을 전달하지 못했습니다."}
    try:
        count = await cancel(user_id=identity["user_id"], run_id=private["run_id"])
    except Exception:
        count = 0
    if count:
        return {"status": "cancelled", "answer": "PC 작업 중지를 요청했습니다.",
                "job_id": job_id, "_job_receipt": job_id}
    latest = await _dispatch_row(request, uid=identity["user_id"], dispatch_id=job_id)
    if isinstance(latest, dict) and latest.get("state") != "pending":
        return {"status": "completed", "answer": "작업이 중지 요청보다 먼저 끝났습니다.",
                "job_id": job_id, "_job_receipt": job_id}
    return {"status": "unavailable", "answer": "작업 중지 요청을 확인하지 못했습니다."}


async def _cancel_run(request, *, uid, run_id):
    store = getattr(request.app.state, "history_store", None)
    cancel = getattr(store, "cancel_oracle_mesh_dispatches_for_run", None)
    if not callable(cancel):
        return 0
    try:
        return await cancel(user_id=uid, run_id=run_id)
    except Exception:
        return 0

