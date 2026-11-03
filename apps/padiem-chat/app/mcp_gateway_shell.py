"""One-shot PC shell tool over the existing oracle_mesh command lane.

The PC-side wait limit, output cap with a head/tail notice, and process-tree
termination follow the MIT-licensed DesktopCommanderMCP design
(https://github.com/wonderwhy-er/DesktopCommanderMCP): no shell command is
kept in a server log, output is bounded, and a timed-out command ends its
whole process tree instead of being reported as a clean exit. No third-party
source file is copied into this repository.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from collections.abc import Mapping

PC_SHELL_TOOL_NAME = "pc_shell"
PC_SHELL_SHELLS = ("powershell", "cmd", "bash")
PC_SHELL_DEFAULT_TIMEOUT_SECONDS = 120
PC_SHELL_MAX_TIMEOUT_SECONDS = 600
PC_SHELL_MAX_COMMAND_CHARS = 50_000
PC_SHELL_MAX_CWD_CHARS = 2_048
PC_SHELL_OUTPUT_CAP_BYTES = 12_000
PC_SHELL_POLL_GRACE_SECONDS = 15
PC_SHELL_POLL_SECONDS = 0.5
PC_SHELL_TRUNCATION_MARKER = "\n...[중간 생략]...\n"
_DISPATCH_ID = re.compile(r"oracle_mesh_cmd_[0-9a-f]{32}\Z")
_PC_SHELL_ERRORS = frozenset({
    "command_empty", "cwd_invalid", "shell_invalid", "shell_unavailable",
    "start_failed",
})
_NOW = time.monotonic

PC_SHELL_PROPERTIES = {
    "command": {
        "type": "string",
        "minLength": 1,
        "maxLength": PC_SHELL_MAX_COMMAND_CHARS,
        "description": (
            "연결된 내 PC에서 한 번 실행할 명령입니다. 사전 위임된 PC에서만 실행하며, "
            "비밀번호 입력·계정 권한 변경·되돌릴 수 없는 삭제·외부 발송은 실행 전에 "
            "PADIEM 대화에서 확인합니다."
        ),
    },
    "cwd": {
        "type": "string",
        "minLength": 1,
        "maxLength": PC_SHELL_MAX_CWD_CHARS,
        "description": "실행 폴더입니다. 생략하면 PC의 기본 작업 폴더를 씁니다.",
    },
    "shell": {
        "type": "string",
        "enum": list(PC_SHELL_SHELLS),
        "description": "사용할 셸입니다. 기본값은 powershell입니다.",
    },
    "timeout_seconds": {
        "type": "integer",
        "minimum": 1,
        "maximum": PC_SHELL_MAX_TIMEOUT_SECONDS,
        "description": "기다릴 최대 시간(초)입니다. 기본 120초, 최대 600초입니다.",
    },
}


def validate_pc_shell_arguments(arguments) -> bool:
    """Closed schema: only these keys, only these types and bounds."""
    if not isinstance(arguments, Mapping) or not set(arguments) <= set(PC_SHELL_PROPERTIES):
        return False
    if "command" not in arguments:
        return False
    command = arguments["command"]
    if (not isinstance(command, str) or not command or "\x00" in command
            or len(command) > PC_SHELL_MAX_COMMAND_CHARS):
        return False
    if "cwd" in arguments and arguments["cwd"] is not None:
        cwd = arguments["cwd"]
        if (not isinstance(cwd, str) or not cwd or len(cwd) > PC_SHELL_MAX_CWD_CHARS
                or any(ord(char) < 32 for char in cwd)):
            return False
    if "shell" in arguments and arguments["shell"] not in PC_SHELL_SHELLS:
        return False
    if "timeout_seconds" in arguments:
        timeout = arguments["timeout_seconds"]
        if (not isinstance(timeout, int) or isinstance(timeout, bool)
                or not 1 <= timeout <= PC_SHELL_MAX_TIMEOUT_SECONDS):
            return False
    return True


def normalize_pc_shell_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_arguments(arguments):
        raise ValueError("Invalid MCP PC shell arguments")
    return {
        "command": arguments["command"],
        "cwd": arguments.get("cwd"),
        "shell": arguments.get("shell", "powershell"),
        "timeout_seconds": arguments.get("timeout_seconds", PC_SHELL_DEFAULT_TIMEOUT_SECONDS),
    }


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


# Static PowerShell 5.1 worker. The caller's command, cwd, shell and bounds
# travel as environment variables so the one-line dispatch command never
# contains the raw command. The worker starts the child with its two output
# streams in separate files, waits only within the caller's limit, ends the
# whole tree on timeout (DesktopCommanderMCP's force_terminate design), and
# prints one bounded JSON object.
_PC_SHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$errorCode = $null
$timedOut = $false
$exitCode = $null
$durationMs = 0
$cap = 12000
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$process = $null
$dir = $null
function Read-PadiemStream([string]$Path, [int]$Limit) {
  if (-not (Test-Path -LiteralPath $Path)) {
    return [pscustomobject]@{ text = ''; bytes = 0; truncated = $false }
  }
  $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
  try {
    $length = $stream.Length
    if ($length -le $Limit) {
      $buffer = New-Object byte[] ([int]$length)
      $offset = 0
      while ($offset -lt $buffer.Length) {
        $read = $stream.Read($buffer, $offset, $buffer.Length - $offset)
        if ($read -le 0) { break }
        $offset += $read
      }
      return [pscustomobject]@{ text = [Text.Encoding]::UTF8.GetString($buffer, 0, $offset); bytes = $length; truncated = $false }
    }
    $half = [int][Math]::Floor($Limit / 2)
    $head = New-Object byte[] $half
    $headRead = 0
    while ($headRead -lt $half) {
      $read = $stream.Read($head, $headRead, $half - $headRead)
      if ($read -le 0) { break }
      $headRead += $read
    }
    [void]$stream.Seek(-$half, [IO.SeekOrigin]::End)
    $tail = New-Object byte[] $half
    $tailRead = 0
    while ($tailRead -lt $half) {
      $read = $stream.Read($tail, $tailRead, $half - $tailRead)
      if ($read -le 0) { break }
      $tailRead += $read
    }
    $text = [Text.Encoding]::UTF8.GetString($head, 0, $headRead) + "`n...[중간 생략]...`n" + [Text.Encoding]::UTF8.GetString($tail, 0, $tailRead)
    return [pscustomobject]@{ text = $text; bytes = $length; truncated = $true }
  } finally {
    $stream.Dispose()
  }
}
try {
  $command = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$env:PADIEM_PC_SHELL_COMMAND_B64))
  $cwd = $null
  if (-not [string]::IsNullOrEmpty([string]$env:PADIEM_PC_SHELL_CWD_B64)) {
    $cwd = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$env:PADIEM_PC_SHELL_CWD_B64))
  }
  $shell = [string]$env:PADIEM_PC_SHELL
  $timeoutMs = [int]$env:PADIEM_PC_SHELL_TIMEOUT_MS
  $cap = [int]$env:PADIEM_PC_SHELL_CAP_BYTES
  if (-not $command.Trim()) { $errorCode = 'command_empty'; throw 'command_empty' }
  if ($cwd -and -not (Test-Path -LiteralPath $cwd -PathType Container)) {
    $errorCode = 'cwd_invalid'; throw 'cwd_invalid'
  }
  $id = [Guid]::NewGuid().ToString('N')
  $dir = Join-Path ([IO.Path]::GetTempPath()) ('padiem-pc-shell-' + $id)
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $outFile = Join-Path $dir 'stdout.log'
  $errFile = Join-Path $dir 'stderr.log'
  $codeFile = Join-Path $dir 'exit-code.txt'
  $wrapperOut = Join-Path $dir 'wrapper-out.txt'
  $wrapperErr = Join-Path $dir 'wrapper-err.txt'
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  $file = $null
  $invocation = $null
  if ($shell -eq 'powershell') {
    $file = 'powershell.exe'
    $script = Join-Path $dir 'command.ps1'
    $inner = "[Console]::OutputEncoding=[Text.Encoding]::UTF8`r`n`$OutputEncoding=[Text.Encoding]::UTF8`r`n" + $command + "`r`nif (`$null -ne `$LASTEXITCODE) { exit `$LASTEXITCODE }; if (-not `$?) { exit 1 }; exit 0"
    $bomUtf8 = New-Object System.Text.UTF8Encoding($true)
    [IO.File]::WriteAllText($script, $inner, $bomUtf8)
    $invocation = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $script + '"'
  } elseif ($shell -eq 'cmd') {
    $file = 'cmd.exe'
    $script = Join-Path $dir 'command.cmd'
    [IO.File]::WriteAllText($script, "@echo off`r`n@chcp 65001 >nul`r`n" + $command, $utf8)
    $invocation = 'cmd.exe /d /s /c ""' + $script + '""'
  } elseif ($shell -eq 'bash') {
    $file = 'bash.exe'
    $script = Join-Path $dir 'command.sh'
    [IO.File]::WriteAllText($script, $command, $utf8)
    $invocation = 'bash.exe "' + $script + '"'
  } else {
    $errorCode = 'shell_invalid'; throw 'shell_invalid'
  }
  if (-not (Get-Command $file -ErrorAction SilentlyContinue)) {
    $errorCode = 'shell_unavailable'; throw 'shell_unavailable'
  }
  # The wrapper cmd writes the child's exit code after it ended, with delayed
  # expansion so an explicit `exit N` in the command is observed. The shell's
  # own streams go to files, and the wrapper's streams go to separate files so
  # the only bytes this worker prints are its JSON line.
  $line = $invocation + ' > "' + $outFile + '" 2> "' + $errFile + '" & echo !ERRORLEVEL! > "' + $codeFile + '"'
  $startArgs = @{
    FilePath = 'cmd.exe'
    ArgumentList = '/v:on /d /s /c "' + $line + '"'
    RedirectStandardOutput = $wrapperOut
    RedirectStandardError = $wrapperErr
    NoNewWindow = $true
    PassThru = $true
  }
  if ($cwd) { $startArgs.WorkingDirectory = $cwd }
  $process = Start-Process @startArgs
  if (-not $process.WaitForExit($timeoutMs)) {
    $timedOut = $true
    try { & taskkill.exe /T /F /PID $process.Id | Out-Null } catch { }
    try { [void]$process.WaitForExit(5000) } catch { }
  }
  if (-not $timedOut) {
    $codeText = $null
    try { $codeText = [IO.File]::ReadAllText($codeFile, $utf8).Trim() } catch { }
    $parsedCode = 0
    if ($codeText -and [int]::TryParse($codeText, [ref]$parsedCode)) {
      $exitCode = $parsedCode
    } else {
      $errorCode = 'start_failed'
    }
  }
} catch {
  if (-not $errorCode) { $errorCode = 'start_failed' }
} finally {
  $stopwatch.Stop()
  $durationMs = [int]$stopwatch.ElapsedMilliseconds
  $stdout = [pscustomobject]@{ text = ''; bytes = 0; truncated = $false }
  $stderr = [pscustomobject]@{ text = ''; bytes = 0; truncated = $false }
  if ($dir) {
    try { $stdout = Read-PadiemStream (Join-Path $dir 'stdout.log') $cap } catch { }
    try { $stderr = Read-PadiemStream (Join-Path $dir 'stderr.log') $cap } catch { }
  }
  $result = [ordered]@{
    exit_code = $exitCode
    timed_out = $timedOut
    stdout = $stdout.text
    stderr = $stderr.text
    stdout_bytes = [int]$stdout.bytes
    stderr_bytes = [int]$stderr.bytes
    stdout_truncated = [bool]$stdout.truncated
    stderr_truncated = [bool]$stderr.truncated
    duration_ms = $durationMs
  }
  if ($errorCode) { $result.error = $errorCode }
  [Console]::Out.Write((ConvertTo-Json -InputObject $result -Compress -Depth 3))
  [Console]::Out.Flush()
  if ($dir) {
    try { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue } catch { }
  }
}
exit 0
"""


def build_pc_shell_command(arguments: Mapping) -> str:
    """One-line dispatch command; the caller's command is base64 only."""
    normalized = normalize_pc_shell_arguments(arguments)
    encoded_script = base64.b64encode(
        _PC_SHELL_SCRIPT.encode("utf-16-le")
    ).decode("ascii")
    cwd_b64 = _b64(normalized["cwd"]) if normalized["cwd"] else ""
    timeout_ms = normalized["timeout_seconds"] * 1000
    return (
        "$env:PADIEM_PC_SHELL_COMMAND_B64='" + _b64(normalized["command"]) + "';"
        "$env:PADIEM_PC_SHELL_CWD_B64='" + cwd_b64 + "';"
        "$env:PADIEM_PC_SHELL='" + normalized["shell"] + "';"
        "$env:PADIEM_PC_SHELL_TIMEOUT_MS='" + str(timeout_ms) + "';"
        "$env:PADIEM_PC_SHELL_CAP_BYTES='" + str(PC_SHELL_OUTPUT_CAP_BYTES) + "';"
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
        "-EncodedCommand " + encoded_script
    )


def parse_pc_shell_result(raw: str) -> dict:
    """Validate the PC worker's bounded JSON; never pass its text to a log."""
    if not isinstance(raw, str) or not raw or len(raw) > 200_000:
        raise ValueError("Invalid PC shell result")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid PC shell result")
    exit_code = data.get("exit_code")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        raise ValueError("Invalid PC shell exit code")
    if not isinstance(data.get("timed_out"), bool):
        raise ValueError("Invalid PC shell timeout flag")
    for key in ("stdout", "stderr"):
        if not isinstance(data.get(key), str) or len(data[key]) > 100_000:
            raise ValueError("Invalid PC shell output")
    for key in ("stdout_bytes", "stderr_bytes", "duration_ms"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Invalid PC shell size")
    for key in ("stdout_truncated", "stderr_truncated"):
        if not isinstance(data.get(key), bool):
            raise ValueError("Invalid PC shell truncation flag")
    error = data.get("error")
    if error is not None and error not in _PC_SHELL_ERRORS:
        raise ValueError("Invalid PC shell error")
    return data


def shell_audit_metadata(result: Mapping, *, duration_ms: int) -> dict:
    """Closed numeric metadata for the existing MCP audit; no command/output."""
    exit_code = result.get("exit_code")
    return {
        "exit_code": exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
        "duration_ms": max(0, int(duration_ms)),
        "output_bytes": int(result.get("stdout_bytes", 0)) + int(result.get("stderr_bytes", 0)),
        "output_truncated": bool(result.get("stdout_truncated")) or bool(result.get("stderr_truncated")),
    }


async def _dispatch_command(request, *, command, run_id, device_id, trusted_owner, ttl_seconds):
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent
    return await dispatch_oracle_mesh_command_intent(
        request,
        command=command,
        wire={"run_id": run_id, "device_id": device_id, "confirmed": True},
        trusted_owner=trusted_owner,
        ttl_seconds=ttl_seconds,
    )


async def _dispatch_row(request, *, uid, dispatch_id):
    store = getattr(request.app.state, "history_store", None)
    reader = getattr(store, "get_oracle_mesh_dispatch_for_owner", None)
    if not callable(reader):
        return None
    try:
        return await reader(user_id=uid, dispatch_id=dispatch_id)
    except Exception:
        return None


async def _read_original(request, *, uid, dispatch_id, conversation_id, message_id):
    store = getattr(request.app.state, "history_store", None)
    reader = getattr(store, "read_oracle_mesh_original", None)
    if not callable(reader):
        return None
    try:
        return await reader(user_id=uid, dispatch_id=dispatch_id,
                            conversation_id=conversation_id, message_id=message_id)
    except Exception:
        return None


async def _cancel_run(request, *, uid, run_id):
    store = getattr(request.app.state, "history_store", None)
    canceller = getattr(store, "cancel_oracle_mesh_dispatches_for_run", None)
    if not callable(canceller):
        return 0
    try:
        return await canceller(user_id=uid, run_id=run_id)
    except Exception:
        return 0


def _dispatch_payload(response):
    body = getattr(response, "body", b"")
    try:
        payload = json.loads(bytes(body).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _failure(code, answer, *, duration_ms, result=None):
    result = result if isinstance(result, Mapping) else {}
    audit = shell_audit_metadata(result, duration_ms=duration_ms)
    stdout = result.get("stdout") if isinstance(result.get("stdout"), str) else ""
    stderr = result.get("stderr") if isinstance(result.get("stderr"), str) else ""
    stdout_bytes = result.get("stdout_bytes")
    stderr_bytes = result.get("stderr_bytes")
    return {"status": "failed", "code": code, "answer": answer,
            "exit_code": None, "timed_out": bool(result.get("timed_out")),
            "stdout": stdout, "stderr": stderr,
            "stdout_bytes": stdout_bytes if isinstance(stdout_bytes, int) else 0,
            "stderr_bytes": stderr_bytes if isinstance(stderr_bytes, int) else 0,
            "truncated": audit["output_truncated"], "duration_ms": audit["duration_ms"],
            "audit": audit}


async def execute_pc_shell(request, *, session, uid, workspace_id, device_id,
                           run_id, conversation_id, arguments):
    """Dispatch one bounded command and return its verified result.

    The command reaches the PC through the same oracle_mesh command lane the
    desktop lane uses. The MCP audit receives numbers only; neither the command
    nor the output is written by this module to a log.
    """
    normalized = normalize_pc_shell_arguments(arguments)
    timeout_seconds = normalized["timeout_seconds"]
    started = _NOW()
    command_text = build_pc_shell_command(normalized)
    response = await _dispatch_command(
        request, command=command_text, run_id=run_id, device_id=device_id,
        trusted_owner=(session, uid, workspace_id),
        ttl_seconds=min(3600, timeout_seconds + 60),
    )
    payload = _dispatch_payload(response)
    dispatch = payload.get("dispatch") if isinstance(payload, dict) else None
    dispatch_id = dispatch.get("dispatch_id") if isinstance(dispatch, dict) else None
    if (getattr(response, "status_code", None) != 200 or not isinstance(dispatch_id, str)
            or _DISPATCH_ID.fullmatch(dispatch_id) is None):
        code = "pc_shell_dispatch_refused"
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            reason = payload["error"].get("code")
            if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]{1,80}", reason):
                code = "pc_shell_" + reason
        return _failure(code, "PC 명령을 시작하지 못했습니다.", duration_ms=round((_NOW() - started) * 1000))

    deadline = started + timeout_seconds + PC_SHELL_POLL_GRACE_SECONDS
    row = None
    while True:
        row = await _dispatch_row(request, uid=uid, dispatch_id=dispatch_id)
        if not isinstance(row, dict):
            return _failure("pc_shell_state_unavailable", "PC 명령 상태를 확인하지 못했습니다.",
                            duration_ms=round((_NOW() - started) * 1000))
        state = row.get("state")
        if state == "done":
            break
        if state == "failed":
            return _failure("pc_shell_execution_failed", "PC 명령을 완료하지 못했습니다.",
                            duration_ms=round((_NOW() - started) * 1000))
        if state not in ("pending", "received", "store_failed"):
            return _failure("pc_shell_state_unavailable", "PC 명령 상태를 확인하지 못했습니다.",
                            duration_ms=round((_NOW() - started) * 1000))
        if _NOW() >= deadline:
            await _cancel_run(request, uid=uid, run_id=run_id)
            return _failure("pc_shell_timeout", "PC 명령이 제한 시간을 넘어 중지되었습니다.",
                            duration_ms=round((_NOW() - started) * 1000))
        await asyncio.sleep(PC_SHELL_POLL_SECONDS)

    if row.get("termination") == "cancelled":
        return _failure("pc_shell_cancelled", "PC 명령이 취소되었습니다.",
                        duration_ms=round((_NOW() - started) * 1000))
    if row.get("termination") not in ("exited", "no_exit_code", "output_too_large"):
        return _failure("pc_shell_execution_failed", "PC 명령의 실제 결과를 확인하지 못했습니다.",
                        duration_ms=round((_NOW() - started) * 1000))
    command_id = row.get("command_id")
    revision_ref = row.get("revision_ref")
    if not isinstance(command_id, str) or not isinstance(revision_ref, str):
        return _failure("pc_shell_output_unavailable", "PC 명령 결과를 확인하지 못했습니다.",
                        duration_ms=round((_NOW() - started) * 1000))
    from .claw_local_task_result_projection import result_message_id
    message_id = result_message_id(conversation_id=conversation_id,
                                   command_id=command_id, revision_ref=revision_ref)
    stored = await _read_original(request, uid=uid, dispatch_id=dispatch_id,
                                  conversation_id=conversation_id, message_id=message_id)
    if not stored or not isinstance(stored, tuple) or len(stored) != 2 or not isinstance(stored[0], (bytes, bytearray)):
        return _failure("pc_shell_output_unavailable", "PC 명령 결과를 확인하지 못했습니다.",
                        duration_ms=round((_NOW() - started) * 1000))
    try:
        envelope = parse_pc_shell_result(bytes(stored[0]).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return _failure("pc_shell_output_unavailable", "PC 명령 결과를 확인하지 못했습니다.",
                        duration_ms=round((_NOW() - started) * 1000))

    duration_ms = round((_NOW() - started) * 1000)
    audit = shell_audit_metadata(envelope, duration_ms=duration_ms)
    if envelope.get("error"):
        return _failure("pc_shell_" + envelope["error"], "PC 명령을 실행하지 못했습니다.",
                        duration_ms=duration_ms, result=envelope)
    exit_code = envelope.get("exit_code")
    if envelope.get("timed_out"):
        return {
            "status": "failed", "code": "pc_shell_timeout",
            "answer": "PC 명령이 제한 시간을 넘어 중지되었습니다.",
            "exit_code": None, "timed_out": True,
            "stdout": envelope["stdout"], "stderr": envelope["stderr"],
            "stdout_bytes": envelope["stdout_bytes"], "stderr_bytes": envelope["stderr_bytes"],
            "truncated": audit["output_truncated"], "duration_ms": duration_ms,
            "pc_duration_ms": envelope["duration_ms"], "shell": normalized["shell"],
            **({"cwd": normalized["cwd"]} if normalized["cwd"] else {}),
            "audit": audit,
        }
    answer = ("PC 명령이 끝났습니다." if exit_code in (0, None)
              else "PC 명령이 종료 코드 " + str(exit_code) + "로 끝났습니다.")
    return {
        "status": "completed", "answer": answer,
        "exit_code": exit_code, "timed_out": False,
        "stdout": envelope["stdout"], "stderr": envelope["stderr"],
        "stdout_bytes": envelope["stdout_bytes"], "stderr_bytes": envelope["stderr_bytes"],
        "truncated": audit["output_truncated"], "duration_ms": duration_ms,
        "pc_duration_ms": envelope["duration_ms"], "shell": normalized["shell"],
        **({"cwd": normalized["cwd"]} if normalized["cwd"] else {}),
        "audit": audit,
    }
