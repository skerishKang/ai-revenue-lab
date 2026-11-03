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

PC_SHELL_PROPERTIES = {
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
PC_SHELL_START_PROPERTIES = {
    key: dict(PC_SHELL_PROPERTIES[key]) for key in ("command", "cwd", "shell")
}
PC_SHELL_READ_PROPERTIES = {
    "job_id": {"type": "string", "minLength": 36, "maxLength": 36,
               "description": "pc_shell 또는 pc_shell_start가 돌려준 Claw 작업 ID입니다."},
    "offset": {"type": "integer", "minimum": 0,
               "description": "출력 핸들의 시작 위치(바이트)입니다."},
    "length": {"type": "integer", "minimum": 1, "maximum": PC_SHELL_READ_MAX_BYTES,
               "description": "읽을 최대 바이트입니다."},
}
PC_SHELL_STOP_PROPERTIES = {"job_id": dict(PC_SHELL_READ_PROPERTIES["job_id"])}


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


def validate_pc_shell_arguments(arguments) -> bool:
    if not isinstance(arguments, Mapping) or not set(arguments) <= set(PC_SHELL_PROPERTIES):
        return False
    if "command" not in arguments or not _command_material(arguments):
        return False
    wait = arguments.get("wait_seconds", PC_SHELL_DEFAULT_WAIT_SECONDS)
    return isinstance(wait, int) and not isinstance(wait, bool) and 1 <= wait <= PC_SHELL_MAX_WAIT_SECONDS


def validate_pc_shell_start_arguments(arguments) -> bool:
    return (isinstance(arguments, Mapping)
            and set(arguments) <= set(PC_SHELL_START_PROPERTIES)
            and "command" in arguments and _command_material(arguments))


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
    return (isinstance(arguments, Mapping)
            and set(arguments) == {"job_id"}
            and _valid_job_id(arguments.get("job_id")))


def validate_shell_tool_arguments(tool_name: str, arguments) -> bool:
    validators = {
        PC_SHELL_TOOL_NAME: validate_pc_shell_arguments,
        PC_SHELL_START_TOOL_NAME: validate_pc_shell_start_arguments,
        PC_SHELL_READ_TOOL_NAME: validate_pc_shell_read_arguments,
        PC_SHELL_STOP_TOOL_NAME: validate_pc_shell_stop_arguments,
    }
    return tool_name in validators and validators[tool_name](arguments)


def normalize_pc_shell_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_arguments(arguments):
        raise ValueError("Invalid MCP PC shell arguments")
    return {"command": arguments["command"], "cwd": arguments.get("cwd"),
            "shell": arguments.get("shell", "powershell"),
            "wait_seconds": arguments.get("wait_seconds", PC_SHELL_DEFAULT_WAIT_SECONDS)}


def normalize_pc_shell_start_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_start_arguments(arguments):
        raise ValueError("Invalid MCP PC shell start arguments")
    return {"command": arguments["command"], "cwd": arguments.get("cwd"),
            "shell": arguments.get("shell", "powershell")}


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
$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PADIEM_MCP_COMMAND_B64))
$d=$null;if($env:PADIEM_MCP_CWD_B64){$d=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PADIEM_MCP_CWD_B64));if(-not(Test-Path -LiteralPath $d -PathType Container)){[Console]::Error.WriteLine('cwd_invalid');exit 126};Set-Location -LiteralPath $d}
try{if($env:PADIEM_MCP_SHELL -eq 'powershell'){$file='powershell.exe';if(-not(Get-Command $file -ErrorAction SilentlyContinue)){[Console]::Error.WriteLine('shell_unavailable');exit 127};$inner=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($c));& $file -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand $inner;$code=0;if($null -ne $LASTEXITCODE){$code=[int]$LASTEXITCODE};exit $code};$file='cmd.exe';$args=@('/d','/s','/c',$c);if($env:PADIEM_MCP_SHELL -eq 'bash'){$file='bash.exe';$args=@('-lc',$c)};if(-not(Get-Command $file -ErrorAction SilentlyContinue)){[Console]::Error.WriteLine('shell_unavailable');exit 127};& $file @args;$code=0;if($null -ne $LASTEXITCODE){$code=[int]$LASTEXITCODE};exit $code}catch{[Console]::Error.WriteLine($_.Exception.Message);exit 1}
""".strip()
    script_b64 = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # PowerShell command text is fixed, and user values are base64 data only.
    return (
        "$env:PADIEM_MCP_COMMAND_B64='" + command_b64 + "';"
        "$env:PADIEM_MCP_CWD_B64='" + cwd_b64 + "';"
        "$env:PADIEM_MCP_SHELL='" + shell + "';"
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
        + script_b64 + ";exit $LASTEXITCODE"
    )


async def _dispatch_command(request, *, command, run_id, device_id, trusted_owner):
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent
    return await dispatch_oracle_mesh_command_intent(
        request, command=command,
        wire={"run_id": run_id, "device_id": device_id, "confirmed": True},
        trusted_owner=trusted_owner, background=True,
        ttl_seconds=PC_SHELL_START_TTL_SECONDS,
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
    if not _valid_job_id(job_id):
        return None
    if require_receipt:
        mcp_store = getattr(request.app.state, "mcp_gateway_store", None)
        owns = getattr(mcp_store, "owns_job_receipt", None)
        if not callable(owns):
            return None
        try:
            if not await owns(identity=identity, job_id=job_id):
                return None
        except Exception:
            return None
    row = await _private_dispatch_row(request, uid=identity["user_id"], dispatch_id=job_id)
    if (not isinstance(row, dict) or row.get("dispatch_id") != job_id
            or row.get("kind") != "command" or row.get("device_id") != identity["device_id"]
            or row.get("user_id") != identity["user_id"]):
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
            device_id=identity["device_id"], dispatch_id=dispatch["dispatch_id"],
            source="mcp_shell", content=output,
        )
    except Exception:
        return None
    if (not isinstance(ref, dict) or not _OUTPUT_HANDLE.fullmatch(str(ref.get("handle", "")))
            or type(ref.get("size")) is not int or ref["size"] < 0):
        return None
    return {"handle": ref["handle"], "size": ref["size"], "truncated": ref.get("truncated") is True}


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
        return {"status": "unavailable", "answer": "PC 작업 상태를 확인하지 못했습니다."}
    ref = await _output_reference(request, identity=identity, subject_id=subject_id,
                                  dispatch=dispatch, private=private, run=run)
    if ref is None:
        if dispatch.get("termination") == "cancelled":
            return {**result, "output_ref": None}
        return {"status": "unavailable", "answer": "PC 작업 출력을 확인하지 못했습니다."}
    reader = getattr(history, "read_pc_output", None)
    if not callable(reader):
        return {"status": "unavailable", "answer": "PC 작업 출력을 확인하지 못했습니다."}
    bounded_offset = min(offset, ref["size"])
    try:
        page = await reader(user_id=identity["user_id"], subject_id=subject_id,
                            run_id=dispatch["run_id"], device_id=identity["device_id"],
                            handle=ref["handle"], offset=bounded_offset, length=length)
    except Exception:
        return {"status": "unavailable", "answer": "PC 작업 출력을 읽지 못했습니다."}
    if not isinstance(page, dict) or not isinstance(page.get("content"), str):
        return {"status": "unavailable", "answer": "PC 작업 출력을 읽지 못했습니다."}
    next_offset = min(ref["size"], bounded_offset + len(page["content"].encode("utf-8")))
    return {**result, "output": page["content"], "next_offset": next_offset,
            "output_ref": ref, "answer": "PC 작업 출력을 읽었습니다.",
            "audit": {"exit_code": (dispatch.get("exit_code")
                                     if isinstance(dispatch.get("exit_code"), int)
                                     and not isinstance(dispatch.get("exit_code"), bool)
                                     else None),
                      "output_bytes": ref["size"],
                      "output_truncated": ref["truncated"]}}


async def execute_pc_shell_start(request, *, uid, workspace_id, device_id, run_id,
                                 session, conversation_id, arguments):
    command = build_pc_shell_command(arguments)
    response = await _dispatch_command(
        request, command=command, run_id=run_id, device_id=device_id,
        trusted_owner=(session, uid, workspace_id),
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
        return {"status": "unavailable", "answer": "PC 작업을 시작하지 못했습니다."}
    return {"status": "running", "answer": "PC 작업을 시작했습니다.", "job_id": job_id,
            "_job_receipt": job_id}


async def execute_pc_shell(request, *, uid, subject_id, workspace_id, device_id,
                           run_id, session, conversation_id, arguments, token_id):
    started = await execute_pc_shell_start(
        request, uid=uid, workspace_id=workspace_id, device_id=device_id,
        run_id=run_id, session=session, conversation_id=conversation_id,
        arguments={key: arguments[key] for key in ("command", "cwd", "shell") if key in arguments},
    )
    if started.get("status") != "running":
        return started
    job_id = started["job_id"]
    deadline = _NOW() + arguments["wait_seconds"]
    snapshot = None
    while _NOW() < deadline:
        snapshot = await _job_snapshot(
            request, identity={"user_id": uid, "device_id": device_id, "token_id": token_id},
            subject_id=subject_id, job_id=job_id, offset=0,
            length=PC_SHELL_READ_DEFAULT_BYTES, require_receipt=False,
        )
        if snapshot.get("status") not in {"queued", "running"}:
            return snapshot
        await asyncio.sleep(min(PC_SHELL_POLL_SECONDS, max(0, deadline - _NOW())))
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
