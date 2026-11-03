"""PC shell tools over the existing oracle_mesh command lane, with readable jobs.

Owner decision (2026-10-24): a PC tool call has no execution deadline. A command
that outlives the caller's wait is handed over as a job the caller reads back by
offset and stops explicitly, instead of being killed and reported as a failure.

The bounded output shape, the head/tail notice and the process-tree termination
follow the MIT-licensed DesktopCommanderMCP design
(https://github.com/wonderwhy-er/DesktopCommanderMCP): no shell command is kept
in a server log, one answer is bounded, and a stopped command ends its whole
process tree rather than being reported as a clean exit. No third-party source
file is copied into this repository.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
import re
import time
from collections.abc import Mapping
from uuid import uuid4

PC_SHELL_TOOL_NAME = "pc_shell"
PC_SHELL_START_TOOL_NAME = "pc_shell_start"
PC_SHELL_READ_TOOL_NAME = "pc_shell_read"
PC_SHELL_STOP_TOOL_NAME = "pc_shell_stop"
PC_SHELL_SHELLS = ("powershell", "cmd", "bash")
# A bound on the WAIT for an answer, never on the command: past it the job keeps
# running on the PC and the caller reads it back by offset.
PC_SHELL_DEFAULT_WAIT_SECONDS = 120
PC_SHELL_MAX_WAIT_SECONDS = 600
PC_SHELL_MAX_COMMAND_CHARS = 50_000
PC_SHELL_MAX_CWD_CHARS = 2_048
PC_SHELL_OUTPUT_CAP_BYTES = 12_000
PC_SHELL_READ_DEFAULT_BYTES = 32_768
PC_SHELL_READ_MAX_BYTES = 65_536
PC_SHELL_POLL_GRACE_SECONDS = 15
PC_SHELL_POLL_SECONDS = 0.5
# read/stop are short file probes and the start ack only waits for the worker
# that detaches the child — never for the command itself.
PC_SHELL_PROBE_WAIT_SECONDS = 30
PC_SHELL_START_ACK_SECONDS = 30
PC_SHELL_PROBE_TTL_SECONDS = 120
# A queued start may be claimed when the PC returns; past this window the
# dispatch expires unclaimed and never runs.
PC_SHELL_START_TTL_SECONDS = 3600
PC_SHELL_TRUNCATION_MARKER = "\n...[중간 생략]...\n"
PC_SHELL_JOB_MAX_LOG_BYTES = 64_000_000
# The same freshness bound the server's own Mesh heartbeat uses (#5462).
PC_SHELL_PRESENCE_MAX_AGE_SECONDS = 180
# history mints dispatch ids as dsp_<32hex>; oracle_mesh_cmd_* is the command id.
_DISPATCH_ID = re.compile(r"dsp_[0-9a-f]{32}\Z")
_JOB_ID = re.compile(r"mcpjob_[0-9a-f]{32}\Z")
_PC_SHELL_ERRORS = frozenset({
    "command_empty", "cwd_invalid", "shell_invalid", "shell_unavailable",
    "start_failed", "job_id_invalid", "job_missing",
})
_SHELL_STATES = frozenset({"running", "exited", "cancelled", "lost", "missing"})
_TERMINAL_STATES = ("exited", "cancelled", "lost")
_NOW = time.monotonic

PC_SHELL_PROPERTIES = {
    "command": {
        "type": "string",
        "minLength": 1,
        "maxLength": PC_SHELL_MAX_COMMAND_CHARS,
        "description": (
            "연결된 내 PC에서 실행할 명령입니다. 사전 위임된 PC에서만 실행하며, "
            "비밀번호 입력·계정 권한 변경·되돌릴 수 없는 삭제·외부 발송은 실행 전에 "
            "PADIEM 대화에서 확인합니다. 실행 시간 제한은 없습니다."
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
    "wait_seconds": {
        "type": "integer",
        "minimum": 1,
        "maximum": PC_SHELL_MAX_WAIT_SECONDS,
        "description": (
            "결과를 기다릴 시간(초)입니다. 기본 120초, 최대 600초. 이 시간이 지나도 "
            "명령은 PC에서 계속 실행되고, 돌려받은 작업 번호를 pc_shell_read로 "
            "이어서 읽을 수 있습니다."
        ),
    },
}

PC_SHELL_START_PROPERTIES = {
    key: dict(PC_SHELL_PROPERTIES[key]) for key in ("command", "cwd", "shell")
}

PC_SHELL_READ_PROPERTIES = {
    "job_id": {
        "type": "string",
        "minLength": 8,
        "maxLength": 64,
        "description": "pc_shell 또는 pc_shell_start가 돌려준 작업 번호입니다.",
    },
    "offset": {
        "type": "integer",
        "minimum": 0,
        "description": "이어 읽을 시작 위치(바이트)입니다. 이전 응답의 next_offset을 넣습니다.",
    },
    "length": {
        "type": "integer",
        "minimum": 1,
        "maximum": PC_SHELL_READ_MAX_BYTES,
        "description": "읽을 최대 바이트입니다. 기본 32768, 최대 65536입니다.",
    },
    "stream": {
        "type": "string",
        "enum": ["stdout", "stderr"],
        "description": "어느 출력 스트림을 읽을지입니다. 기본값은 stdout입니다.",
    },
}

PC_SHELL_STOP_PROPERTIES = {"job_id": dict(PC_SHELL_READ_PROPERTIES["job_id"])}


def _check_command_material(arguments: Mapping) -> bool:
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
    return True


def _check_job_id(value) -> bool:
    return isinstance(value, str) and _JOB_ID.fullmatch(value) is not None


def validate_pc_shell_arguments(arguments) -> bool:
    """Closed schema for the waiting form: command, folder, shell, wait only."""
    if not isinstance(arguments, Mapping) or not set(arguments) <= set(PC_SHELL_PROPERTIES):
        return False
    if "command" not in arguments or not _check_command_material(arguments):
        return False
    if "wait_seconds" in arguments:
        wait = arguments["wait_seconds"]
        if (not isinstance(wait, int) or isinstance(wait, bool)
                or not 1 <= wait <= PC_SHELL_MAX_WAIT_SECONDS):
            return False
    return True


def validate_pc_shell_start_arguments(arguments) -> bool:
    if (not isinstance(arguments, Mapping)
            or not set(arguments) <= set(PC_SHELL_START_PROPERTIES)):
        return False
    return "command" in arguments and _check_command_material(arguments)


def validate_pc_shell_read_arguments(arguments) -> bool:
    if (not isinstance(arguments, Mapping)
            or not set(arguments) <= set(PC_SHELL_READ_PROPERTIES)):
        return False
    if not _check_job_id(arguments.get("job_id")):
        return False
    offset = arguments.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return False
    length = arguments.get("length", PC_SHELL_READ_DEFAULT_BYTES)
    if (not isinstance(length, int) or isinstance(length, bool)
            or not 1 <= length <= PC_SHELL_READ_MAX_BYTES):
        return False
    return arguments.get("stream", "stdout") in ("stdout", "stderr")


def validate_pc_shell_stop_arguments(arguments) -> bool:
    return (isinstance(arguments, Mapping)
            and set(arguments) <= set(PC_SHELL_STOP_PROPERTIES)
            and _check_job_id(arguments.get("job_id")))


def validate_shell_tool_arguments(tool_name: str, arguments) -> bool:
    check = {PC_SHELL_TOOL_NAME: validate_pc_shell_arguments,
             PC_SHELL_START_TOOL_NAME: validate_pc_shell_start_arguments,
             PC_SHELL_READ_TOOL_NAME: validate_pc_shell_read_arguments,
             PC_SHELL_STOP_TOOL_NAME: validate_pc_shell_stop_arguments}.get(tool_name)
    return check is not None and check(arguments)


def normalize_pc_shell_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_arguments(arguments):
        raise ValueError("Invalid MCP PC shell arguments")
    return {
        "command": arguments["command"],
        "cwd": arguments.get("cwd"),
        "shell": arguments.get("shell", "powershell"),
        "wait_seconds": arguments.get("wait_seconds", PC_SHELL_DEFAULT_WAIT_SECONDS),
    }


def normalize_pc_shell_start_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_start_arguments(arguments):
        raise ValueError("Invalid MCP PC shell start arguments")
    return {
        "command": arguments["command"],
        "cwd": arguments.get("cwd"),
        "shell": arguments.get("shell", "powershell"),
    }


def normalize_pc_shell_read_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_read_arguments(arguments):
        raise ValueError("Invalid MCP PC shell read arguments")
    return {
        "job_id": arguments["job_id"],
        "offset": arguments.get("offset", 0),
        "length": arguments.get("length", PC_SHELL_READ_DEFAULT_BYTES),
        "stream": arguments.get("stream", "stdout"),
    }


def normalize_pc_shell_stop_arguments(arguments: Mapping) -> dict:
    if not validate_pc_shell_stop_arguments(arguments):
        raise ValueError("Invalid MCP PC shell stop arguments")
    return {"job_id": arguments["job_id"]}


def new_shell_job_id() -> str:
    return "mcpjob_" + uuid4().hex


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


# One static PowerShell 5.1 worker serves the three shapes, chosen by
# PADIEM_PC_SHELL_MODE: "run" (launch detached, then wait only inside the
# caller's window), "read" (one bounded slice of a job's output file) and "stop"
# (end the whole process tree). The caller's command, folder and bounds travel as
# environment variables, so the one-line dispatch command never carries the raw
# command. A job's child writes its own two output files under
# %LOCALAPPDATA%\padiem-mcp-jobs, which is what makes an answer while the command
# is still running — and a later read by offset — possible at all.
_PC_SHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$mode = [string]$env:PADIEM_PC_SHELL_MODE
$jobId = [string]$env:PADIEM_PC_SHELL_JOB_ID
$cap = 12000
$errorCode = $null
$result = $null
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
function Get-PadiemJobDir {
  $root = [string]$env:LOCALAPPDATA
  if ([string]::IsNullOrWhiteSpace($root)) { $root = [IO.Path]::GetTempPath() }
  $dir = Join-Path $root 'padiem-mcp-jobs'
  [void](New-Item -ItemType Directory -Force -Path $dir)
  return $dir
}
function Get-PadiemUtcMs([datetime]$When) {
  return [long]([DateTimeOffset]::new($When.ToUniversalTime()).ToUnixTimeMilliseconds())
}
function Read-PadiemPreview([string]$Path, [int]$Limit) {
  if (-not (Test-Path -LiteralPath $Path)) {
    return [pscustomobject]@{ text = ''; bytes = 0; total = 0; truncated = $false }
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
      return [pscustomobject]@{ text = [Text.Encoding]::UTF8.GetString($buffer, 0, $offset); bytes = $offset; total = $length; truncated = $false }
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
    return [pscustomobject]@{ text = $text; bytes = ($headRead + $tailRead); total = $length; truncated = $true }
  } finally {
    $stream.Dispose()
  }
}
function Read-PadiemSlice([string]$Path, [long]$Offset, [int]$Limit) {
  if (-not (Test-Path -LiteralPath $Path)) {
    return [pscustomobject]@{ text = ''; bytes = 0; total = 0; next = $Offset; eof = $true }
  }
  $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
  try {
    $total = $stream.Length
    if ($Offset -ge $total) {
      return [pscustomobject]@{ text = ''; bytes = 0; total = $total; next = $Offset; eof = $true }
    }
    [void]$stream.Seek($Offset, [IO.SeekOrigin]::Begin)
    $want = $Limit
    if ($want -gt ($total - $Offset)) { $want = [int]($total - $Offset) }
    $buffer = New-Object byte[] $want
    $readTotal = 0
    while ($readTotal -lt $want) {
      $read = $stream.Read($buffer, $readTotal, $want - $readTotal)
      if ($read -le 0) { break }
      $readTotal += $read
    }
    $next = ($Offset + $readTotal)
    return [pscustomobject]@{ text = [Text.Encoding]::UTF8.GetString($buffer, 0, $readTotal); bytes = $readTotal; total = $total; next = $next; eof = ($next -ge $total) }
  } finally {
    $stream.Dispose()
  }
}
function Get-PadiemJobState([string]$Dir, [string]$Id) {
  $metaFile = Join-Path $Dir ($Id + '.meta')
  $codeFile = Join-Path $Dir ($Id + '.code')
  $killFile = Join-Path $Dir ($Id + '.killed')
  $info = [pscustomobject]@{ found = $false; state = 'missing'; exit_code = $null; elapsed_ms = [long]0; pid = 0 }
  if (-not (Test-Path -LiteralPath $metaFile)) { return $info }
  $info.found = $true
  $meta = $null
  try {
    $meta = ConvertFrom-Json ([IO.File]::ReadAllText($metaFile, (New-Object System.Text.UTF8Encoding($false))))
  } catch { }
  if ($null -eq $meta -or $null -eq $meta.started_at_ms) { $info.state = 'lost'; return $info }
  $startedMs = [long]$meta.started_at_ms
  $pidValue = 0
  if ($meta.pid) { $pidValue = [int]$meta.pid }
  $info.pid = $pidValue
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  if (Test-Path -LiteralPath $codeFile) {
    $codeText = ([IO.File]::ReadAllText($codeFile, $utf8)).Trim()
    $parsed = 0
    if ([int]::TryParse($codeText, [ref]$parsed)) { $info.exit_code = $parsed }
    $finishedMs = Get-PadiemUtcMs ((Get-Item -LiteralPath $codeFile).LastWriteTime)
    $info.elapsed_ms = [long][Math]::Max(0, ($finishedMs - $startedMs))
    $info.state = 'exited'
    return $info
  }
  if (Test-Path -LiteralPath $killFile) {
    $finishedMs = Get-PadiemUtcMs ((Get-Item -LiteralPath $killFile).LastWriteTime)
    $info.elapsed_ms = [long][Math]::Max(0, ($finishedMs - $startedMs))
    $info.state = 'cancelled'
    return $info
  }
  $alive = $false
  if ($pidValue -gt 0) {
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    $alive = ($null -ne $proc)
  }
  $nowMs = Get-PadiemUtcMs ([DateTime]::Now)
  $info.elapsed_ms = [long][Math]::Max(0, ($nowMs - $startedMs))
  if ($alive) { $info.state = 'running' } else { $info.state = 'lost' }
  return $info
}
function Remove-PadiemOldJobs([string]$Dir) {
  # Abandoned job files must not pile up forever. A job inside the retention
  # window is kept, and a process that is still running is never touched: the
  # owner decides when a command ends, not the file cleanup.
  $cutoff = [DateTime]::Now.AddDays(-30)
  foreach ($metaFile in @(Get-ChildItem -LiteralPath $Dir -Filter '*.meta' -File -ErrorAction SilentlyContinue)) {
    try {
      if (-not ((Get-Item -LiteralPath $metaFile.FullName).LastWriteTime -lt $cutoff)) { continue }
      $base = $metaFile.Name.Substring(0, $metaFile.Name.Length - 5)
      $old = Get-PadiemJobState $Dir $base
      if ($old.state -eq 'running') { continue }
      foreach ($suffix in @('.meta', '.code', '.killed', '.out', '.err', '.ps1', '.cmd', '.sh')) {
        $one = Join-Path $Dir ($base + $suffix)
        if (Test-Path -LiteralPath $one) { Remove-Item -LiteralPath $one -Force -ErrorAction SilentlyContinue }
      }
    } catch { }
  }
}
try {
  if ($jobId -notmatch '^mcpjob_[0-9a-f]{32}$') { $errorCode = 'job_id_invalid'; throw 'job_id_invalid' }
  $jobDir = Get-PadiemJobDir
  $prefix = Join-Path $jobDir $jobId
  $outFile = $prefix + '.out'
  $errFile = $prefix + '.err'
  $codeFile = $prefix + '.code'
  $metaFile = $prefix + '.meta'
  $killFile = $prefix + '.killed'
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  Remove-PadiemOldJobs $jobDir
  if ($mode -eq 'run') {
    $command = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$env:PADIEM_PC_SHELL_COMMAND_B64))
    $cwd = $null
    if (-not [string]::IsNullOrEmpty([string]$env:PADIEM_PC_SHELL_CWD_B64)) {
      $cwd = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$env:PADIEM_PC_SHELL_CWD_B64))
    }
    $shell = [string]$env:PADIEM_PC_SHELL
    $waitMs = [int]$env:PADIEM_PC_SHELL_WAIT_MS
    $cap = [int]$env:PADIEM_PC_SHELL_CAP_BYTES
    # A job id owns its files from the moment it starts: stale bytes from an
    # earlier answer would otherwise read as this command's own output or exit.
    foreach ($suffix in @('.out', '.err', '.code', '.killed', '.meta', '.ps1', '.cmd', '.sh')) {
      $one = $prefix + $suffix
      if (Test-Path -LiteralPath $one) { Remove-Item -LiteralPath $one -Force -ErrorAction SilentlyContinue }
    }
    if (-not $command.Trim()) { $errorCode = 'command_empty'; throw 'command_empty' }
    if ($cwd -and -not (Test-Path -LiteralPath $cwd -PathType Container)) {
      $errorCode = 'cwd_invalid'; throw 'cwd_invalid'
    }
    $file = $null
    $invocation = $null
    if ($shell -eq 'powershell') {
      $file = 'powershell.exe'
      $scriptFile = $prefix + '.ps1'
      $inner = "[Console]::OutputEncoding=[Text.Encoding]::UTF8`r`n`$OutputEncoding=[Text.Encoding]::UTF8`r`n" + $command + "`r`nif (`$null -ne `$LASTEXITCODE) { exit `$LASTEXITCODE }; if (-not `$?) { exit 1 }; exit 0"
      $bomUtf8 = New-Object System.Text.UTF8Encoding($true)
      [IO.File]::WriteAllText($scriptFile, $inner, $bomUtf8)
      $invocation = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $scriptFile + '"'
    } elseif ($shell -eq 'cmd') {
      $file = 'cmd.exe'
      $scriptFile = $prefix + '.cmd'
      [IO.File]::WriteAllText($scriptFile, "@echo off`r`n@chcp 65001 >nul`r`n" + $command, $utf8)
      $invocation = 'cmd.exe /d /s /c ""' + $scriptFile + '""'
    } elseif ($shell -eq 'bash') {
      $file = 'bash.exe'
      $scriptFile = $prefix + '.sh'
      [IO.File]::WriteAllText($scriptFile, $command, $utf8)
      $invocation = 'bash.exe "' + $scriptFile + '"'
    } else {
      $errorCode = 'shell_invalid'; throw 'shell_invalid'
    }
    if (-not (Get-Command $file -ErrorAction SilentlyContinue)) {
      $errorCode = 'shell_unavailable'; throw 'shell_unavailable'
    }
    # The wrapper cmd records the child's exit code with delayed expansion, so an
    # explicit `exit N` inside the command is observed. The child's own streams go
    # to the job's files: output keeps accumulating after this worker and this
    # dispatch have ended, which is the whole point of a job.
    $line = $invocation + ' > "' + $outFile + '" 2> "' + $errFile + '" & echo !ERRORLEVEL! > "' + $codeFile + '"'
    $startArgs = @{
      FilePath = 'cmd.exe'
      ArgumentList = '/v:on /d /s /c "' + $line + '"'
      WindowStyle = 'Hidden'
      PassThru = $true
    }
    if ($cwd) { $startArgs.WorkingDirectory = $cwd }
    $startedMs = Get-PadiemUtcMs ([DateTime]::Now)
    $process = Start-Process @startArgs
    if ($null -eq $process -or $process.Id -le 0) { $errorCode = 'start_failed'; throw 'start_failed' }
    [IO.File]::WriteAllText($metaFile, ('{"pid":' + $process.Id + ',"started_at_ms":' + $startedMs + '}'), $utf8)
    if ($waitMs -gt 0) {
      while (-not (Test-Path -LiteralPath $codeFile)) {
        if ($stopwatch.ElapsedMilliseconds -ge $waitMs) { break }
        Start-Sleep -Milliseconds 250
      }
    }
    $state = Get-PadiemJobState $jobDir $jobId
    if ($state.state -eq 'exited') {
      $stdout = Read-PadiemPreview $outFile $cap
      $stderr = Read-PadiemPreview $errFile $cap
      $stdoutNext = $stdout.total
      $stderrNext = $stderr.total
    } else {
      # Handing the job over: a preview from the start of each stream, because a
      # head/tail cut would break the caller's next offset.
      $outSlice = Read-PadiemSlice $outFile 0 $cap
      $errSlice = Read-PadiemSlice $errFile 0 $cap
      $stdout = [pscustomobject]@{ text = $outSlice.text; total = $outSlice.total; truncated = ($outSlice.total -gt $outSlice.bytes) }
      $stderr = [pscustomobject]@{ text = $errSlice.text; total = $errSlice.total; truncated = ($errSlice.total -gt $errSlice.bytes) }
      $stdoutNext = $outSlice.next
      $stderrNext = $errSlice.next
    }
    $result = [ordered]@{
      job_id = $jobId
      state = $state.state
      exit_code = $state.exit_code
      elapsed_ms = [long]$state.elapsed_ms
      stdout = $stdout.text
      stderr = $stderr.text
      stdout_bytes = [long]$stdout.total
      stderr_bytes = [long]$stderr.total
      stdout_truncated = [bool]$stdout.truncated
      stderr_truncated = [bool]$stderr.truncated
      stdout_next_offset = [long]$stdoutNext
      stderr_next_offset = [long]$stderrNext
      duration_ms = [int]$stopwatch.ElapsedMilliseconds
    }
  } elseif ($mode -eq 'read') {
    $offset = [long]$env:PADIEM_PC_SHELL_OFFSET
    $length = [int]$env:PADIEM_PC_SHELL_LENGTH
    $streamName = [string]$env:PADIEM_PC_SHELL_STREAM
    $state = Get-PadiemJobState $jobDir $jobId
    if (-not $state.found) { $errorCode = 'job_missing'; throw 'job_missing' }
    $path = $outFile
    if ($streamName -eq 'stderr') { $path = $errFile }
    $slice = Read-PadiemSlice $path $offset $length
    $result = [ordered]@{
      job_id = $jobId
      state = $state.state
      exit_code = $state.exit_code
      elapsed_ms = [long]$state.elapsed_ms
      stream = $streamName
      output = $slice.text
      output_bytes = [long]$slice.bytes
      total_bytes = [long]$slice.total
      next_offset = [long]$slice.next
      eof = [bool]$slice.eof
      large = [bool]($slice.total -gt 64000000)
      duration_ms = [int]$stopwatch.ElapsedMilliseconds
    }
  } elseif ($mode -eq 'stop') {
    $state = Get-PadiemJobState $jobDir $jobId
    if (-not $state.found) { $errorCode = 'job_missing'; throw 'job_missing' }
    $killed = $false
    if ($state.state -eq 'running') {
      try { & taskkill.exe /T /F /PID $state.pid | Out-Null } catch { }
      [IO.File]::WriteAllText($killFile, 'cancelled', $utf8)
      $killed = $true
      $state = Get-PadiemJobState $jobDir $jobId
      if ($state.state -eq 'lost') { $state.state = 'cancelled' }
    }
    $result = [ordered]@{
      job_id = $jobId
      state = $state.state
      exit_code = $state.exit_code
      elapsed_ms = [long]$state.elapsed_ms
      killed = [bool]$killed
      duration_ms = [int]$stopwatch.ElapsedMilliseconds
    }
  } else {
    $errorCode = 'shell_invalid'; throw 'shell_invalid'
  }
} catch {
  if (-not $errorCode) { $errorCode = 'start_failed' }
} finally {
  if ($result) {
    [Console]::Out.Write((ConvertTo-Json -InputObject $result -Compress -Depth 3))
  } else {
    [Console]::Out.Write((ConvertTo-Json -InputObject ([ordered]@{ job_id = $jobId; error = $errorCode }) -Compress -Depth 3))
  }
  [Console]::Out.Flush()
}
exit 0
"""


_WORKER_BOOTSTRAP = (
    "$p=Join-Path $env:TEMP ('padiem-mcp-shell-worker-' + [Guid]::NewGuid().ToString('N') + '.ps1');"
    "$m=New-Object IO.MemoryStream(,[Convert]::FromBase64String([string]$env:PADIEM_PC_SHELL_SCRIPT_B64));"
    "$z=New-Object IO.Compression.GzipStream($m,[IO.Compression.CompressionMode]::Decompress);"
    "$r=New-Object IO.StreamReader($z,[Text.Encoding]::UTF8);"
    "[IO.File]::WriteAllText($p,$r.ReadToEnd(),(New-Object Text.UTF8Encoding($true)));"
    "$z.Dispose();$r.Dispose();$m.Dispose();"
    "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $p;"
    "Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue"
)


def _dispatch_line(mode: str, *, job_id: str, values: dict[str, str]) -> str:
    """One-line dispatch command; every caller value is base64 or a bounded word.

    The worker travels as gzip+base64 written to a temp .ps1 and run with -File:
    a raw -EncodedCommand of this script exceeds the Windows command-line limit,
    and -File keeps the worker's own stdout the only bytes the caller reads.
    """
    assignments = ["$env:PADIEM_PC_SHELL_MODE='" + mode + "';",
                   "$env:PADIEM_PC_SHELL_JOB_ID='" + job_id + "';"]
    for name, value in values.items():
        assignments.append("$env:" + name + "='" + value + "';")
    packed = base64.b64encode(gzip.compress(_PC_SHELL_SCRIPT.encode("utf-8"))).decode("ascii")
    assignments.append("$env:PADIEM_PC_SHELL_SCRIPT_B64='" + packed + "';")
    return "".join(assignments) + _WORKER_BOOTSTRAP


def build_pc_shell_command(arguments: Mapping, *, job_id: str) -> str:
    """The waiting form: launch detached, then wait only inside the window."""
    normalized = normalize_pc_shell_arguments(arguments)
    return _run_line(normalized, job_id=job_id, wait_seconds=normalized["wait_seconds"])


def build_pc_shell_start_command(arguments: Mapping, *, job_id: str) -> str:
    """The hand-off form: launch detached and answer without waiting."""
    normalized = normalize_pc_shell_start_arguments(arguments)
    return _run_line(normalized, job_id=job_id, wait_seconds=0)


def _run_line(normalized: Mapping, *, job_id: str, wait_seconds: int) -> str:
    return _dispatch_line("run", job_id=job_id, values={
        "PADIEM_PC_SHELL_COMMAND_B64": _b64(normalized["command"]),
        "PADIEM_PC_SHELL_CWD_B64": _b64(normalized["cwd"]) if normalized["cwd"] else "",
        "PADIEM_PC_SHELL": normalized["shell"],
        "PADIEM_PC_SHELL_WAIT_MS": str(wait_seconds * 1000),
        "PADIEM_PC_SHELL_CAP_BYTES": str(PC_SHELL_OUTPUT_CAP_BYTES),
    })


def build_pc_shell_read_command(arguments: Mapping) -> str:
    normalized = normalize_pc_shell_read_arguments(arguments)
    return _dispatch_line("read", job_id=normalized["job_id"], values={
        "PADIEM_PC_SHELL_OFFSET": str(normalized["offset"]),
        "PADIEM_PC_SHELL_LENGTH": str(normalized["length"]),
        "PADIEM_PC_SHELL_STREAM": normalized["stream"],
        "PADIEM_PC_SHELL_CAP_BYTES": str(normalized["length"]),
    })


def build_pc_shell_stop_command(arguments: Mapping) -> str:
    normalized = normalize_pc_shell_stop_arguments(arguments)
    return _dispatch_line("stop", job_id=normalized["job_id"], values={})


def _error_envelope(data: dict) -> dict | None:
    error = data.get("error")
    if error is None:
        return None
    if not _JOB_ID.fullmatch(str(data.get("job_id") or "")):
        raise ValueError("Invalid PC shell job id")
    if error not in _PC_SHELL_ERRORS:
        raise ValueError("Invalid PC shell error")
    return {"job_id": data["job_id"], "error": error}


def _parse_common(data: dict) -> None:
    if not _JOB_ID.fullmatch(str(data.get("job_id") or "")):
        raise ValueError("Invalid PC shell job id")
    if data.get("state") not in _SHELL_STATES:
        raise ValueError("Invalid PC shell job state")
    exit_code = data.get("exit_code")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        raise ValueError("Invalid PC shell exit code")
    for key in ("elapsed_ms", "duration_ms"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Invalid PC shell size")


def parse_pc_shell_result(raw: str) -> dict:
    """Validate the run worker's bounded JSON; never pass its text to a log."""
    if not isinstance(raw, str) or not raw or len(raw) > 200_000:
        raise ValueError("Invalid PC shell result")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid PC shell result")
    error = _error_envelope(data)
    if error is not None:
        return error
    _parse_common(data)
    for key in ("stdout", "stderr"):
        if not isinstance(data.get(key), str) or len(data[key]) > 100_000:
            raise ValueError("Invalid PC shell output")
    for key in ("stdout_bytes", "stderr_bytes", "stdout_next_offset", "stderr_next_offset"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Invalid PC shell size")
    for key in ("stdout_truncated", "stderr_truncated"):
        if not isinstance(data.get(key), bool):
            raise ValueError("Invalid PC shell truncation flag")
    return data


def parse_pc_shell_output_result(raw: str) -> dict:
    """Validate one read worker's bounded slice for one job."""
    if not isinstance(raw, str) or not raw or len(raw) > 200_000:
        raise ValueError("Invalid PC shell result")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid PC shell result")
    error = _error_envelope(data)
    if error is not None:
        return error
    _parse_common(data)
    if data.get("stream") not in ("stdout", "stderr"):
        raise ValueError("Invalid PC shell stream")
    output = data.get("output")
    if not isinstance(output, str) or len(output) > 100_000:
        raise ValueError("Invalid PC shell output")
    for key in ("output_bytes", "total_bytes", "next_offset"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Invalid PC shell size")
    for key in ("eof", "large"):
        if not isinstance(data.get(key), bool):
            raise ValueError("Invalid PC shell flag")
    return data


def parse_pc_shell_stop_result(raw: str) -> dict:
    """Validate one stop worker's answer for one job."""
    if not isinstance(raw, str) or not raw or len(raw) > 200_000:
        raise ValueError("Invalid PC shell result")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid PC shell result")
    error = _error_envelope(data)
    if error is not None:
        return error
    _parse_common(data)
    if not isinstance(data.get("killed"), bool):
        raise ValueError("Invalid PC shell flag")
    return data


def shell_audit_metadata(result: Mapping, *, duration_ms: int) -> dict:
    """Closed numeric metadata for the existing MCP audit; no command/output."""
    exit_code = result.get("exit_code")
    output_bytes = int(result.get("stdout_bytes") or 0) + int(result.get("stderr_bytes") or 0)
    if not output_bytes:
        output_bytes = int(result.get("total_bytes") or result.get("output_bytes") or 0)
    return {
        "exit_code": exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
        "duration_ms": max(0, int(duration_ms)),
        "output_bytes": output_bytes,
        "output_truncated": (bool(result.get("stdout_truncated"))
                             or bool(result.get("stderr_truncated"))
                             or bool(result.get("large"))),
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


def _mcp_store(request):
    state = getattr(getattr(request, "app", None), "state", None)
    return getattr(state, "mcp_gateway_store", None) if state is not None else None


def _dispatch_payload(response):
    body = getattr(response, "body", b"")
    try:
        payload = json.loads(bytes(body).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _refusal_code(payload) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        reason = payload["error"].get("code")
        if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]{1,80}", reason):
            return "pc_shell_" + reason
    return "pc_shell_dispatch_refused"


async def _pc_lane_is_live(request, device_id):
    """True/false from the server's own Mesh beat, None when the lane cannot say.

    The always-connected answer today is this presence row: the connector writes
    it on every poll beat, so a fresh row means a command is claimed within
    seconds and a stale or missing row means the PC is away. The connector
    gateway WebSocket carries enrollment frames only and no command frames, so it
    is not a dispatch path yet (design memo section 12).
    """
    state = getattr(getattr(request, "app", None), "state", None)
    presence = getattr(state, "mesh_device_presence_store", None) if state is not None else None
    load = getattr(presence, "load", None)
    if not callable(load):
        return None
    try:
        row = load(device_id=device_id)
        if hasattr(row, "__await__"):
            row = await row
    except Exception:
        return None
    if not isinstance(row, dict) or row.get("connected") is not True:
        return False
    received = row.get("received_at")
    if not isinstance(received, str):
        return False
    try:
        observed = datetime.fromisoformat(received.replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - observed).total_seconds() <= PC_SHELL_PRESENCE_MAX_AGE_SECONDS


async def _stage_dispatch(request, *, command, run_id, device_id, trusted_owner, ttl_seconds):
    """Create the dispatch row and return its id, or a closed refusal code."""
    response = await _dispatch_command(request, command=command, run_id=run_id,
                                       device_id=device_id, trusted_owner=trusted_owner,
                                       ttl_seconds=ttl_seconds)
    payload = _dispatch_payload(response)
    dispatch = payload.get("dispatch") if isinstance(payload, dict) else None
    dispatch_id = dispatch.get("dispatch_id") if isinstance(dispatch, dict) else None
    if (getattr(response, "status_code", None) != 200 or not isinstance(dispatch_id, str)
            or _DISPATCH_ID.fullmatch(dispatch_id) is None):
        return None, _refusal_code(payload)
    return dispatch_id, None


async def _await_dispatch_envelope(request, *, uid, dispatch_id, conversation_id,
                                   wait_seconds, parser):
    """Poll the dispatch row for the worker's own answer, never for the command."""
    deadline = _NOW() + wait_seconds + PC_SHELL_POLL_GRACE_SECONDS
    while True:
        row = await _dispatch_row(request, uid=uid, dispatch_id=dispatch_id)
        if not isinstance(row, dict):
            return {"kind": "state_unavailable", "row": None}
        state = row.get("state")
        if state == "done":
            break
        if state == "failed":
            return {"kind": "failed", "row": row}
        if state not in ("pending", "received", "store_failed"):
            return {"kind": "state_unavailable", "row": row}
        if _NOW() >= deadline:
            return {"kind": "pending", "row": row}
        await asyncio.sleep(PC_SHELL_POLL_SECONDS)
    if row.get("termination") == "cancelled":
        return {"kind": "cancelled", "row": row}
    if row.get("termination") not in ("exited", "no_exit_code", "output_too_large"):
        return {"kind": "failed", "row": row}
    command_id = row.get("command_id")
    revision_ref = row.get("revision_ref")
    if not isinstance(command_id, str) or not isinstance(revision_ref, str):
        return {"kind": "output_unavailable", "row": row}
    from .claw_local_task_result_projection import result_message_id
    message_id = result_message_id(conversation_id=conversation_id,
                                   command_id=command_id, revision_ref=revision_ref)
    stored = await _read_original(request, uid=uid, dispatch_id=dispatch_id,
                                  conversation_id=conversation_id, message_id=message_id)
    if (not stored or not isinstance(stored, tuple) or len(stored) != 2
            or not isinstance(stored[0], (bytes, bytearray))):
        return {"kind": "output_unavailable", "row": row}
    try:
        envelope = parser(bytes(stored[0]).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return {"kind": "output_unavailable", "row": row}
    return {"kind": "envelope", "row": row, "envelope": envelope}


def _failure(code, answer, *, duration_ms, result=None):
    result = result if isinstance(result, Mapping) else {}
    audit = shell_audit_metadata(result, duration_ms=duration_ms)
    stdout = result.get("stdout") if isinstance(result.get("stdout"), str) else ""
    stderr = result.get("stderr") if isinstance(result.get("stderr"), str) else ""
    stdout_bytes = result.get("stdout_bytes")
    stderr_bytes = result.get("stderr_bytes")
    return {"status": "failed", "code": code, "answer": answer,
            "exit_code": None,
            "stdout": stdout, "stderr": stderr,
            "stdout_bytes": stdout_bytes if isinstance(stdout_bytes, int) else 0,
            "stderr_bytes": stderr_bytes if isinstance(stderr_bytes, int) else 0,
            "truncated": audit["output_truncated"], "duration_ms": audit["duration_ms"],
            "audit": audit}


def _elapsed_text(milliseconds) -> str:
    seconds = max(0, int(milliseconds or 0)) // 1000
    if seconds < 60:
        return str(seconds) + "초"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return str(minutes) + "분 " + str(rest) + "초"
    return str(minutes // 60) + "시간 " + str(minutes % 60) + "분"


def _identity(uid, device_id, token_id) -> dict:
    return {"user_id": uid, "device_id": device_id, "token_id": token_id}


def _worker_error(envelope) -> str | None:
    if not isinstance(envelope, Mapping):
        return None
    error = envelope.get("error")
    return ("pc_shell_" + error) if isinstance(error, str) and error else None


async def _finish_job(request, *, uid, job_id, state, exit_code=None):
    finish = getattr(_mcp_store(request), "finish_shell_job", None)
    if not callable(finish):
        return None
    try:
        return await finish(user_id=uid, job_id=job_id, state=state, exit_code=exit_code)
    except Exception:
        return None


async def _attach_dispatch(request, *, uid, job_id, dispatch_id):
    attach = getattr(_mcp_store(request), "attach_shell_job_dispatch", None)
    if not callable(attach):
        return False
    try:
        return bool(await attach(user_id=uid, job_id=job_id, dispatch_id=dispatch_id))
    except Exception:
        return False


async def _create_job(request, *, uid, device_id, token_id, run_id, job_id, normalized):
    """Write the job row before the command exists anywhere else.

    The row is the ownership record: a dispatch that dies mid-flight leaves a job
    the user can still see and stop, never an untracked process.
    """
    create = getattr(_mcp_store(request), "create_shell_job", None)
    if not callable(create):
        return False
    try:
        await create(identity=_identity(uid, device_id, token_id), job_id=job_id, run_id=run_id,
                     command_sha256=hashlib.sha256(normalized["command"].encode("utf-8")).hexdigest(),
                     shell=normalized["shell"])
    except Exception:
        return False
    return True


async def _load_owned_job(request, *, uid, job_id, device_id):
    """The job row for this account only, on the PC that started it only."""
    reader = getattr(_mcp_store(request), "get_shell_job", None)
    if not callable(reader) or not _JOB_ID.fullmatch(job_id):
        return None, "pc_shell_store_unavailable"
    try:
        job = await reader(user_id=uid, job_id=job_id)
    except Exception:
        return None, "pc_shell_store_unavailable"
    if not isinstance(job, dict):
        return None, "pc_shell_job_not_found"
    if job.get("device_id") != device_id:
        # Another PC of the same account gets the same answer as a foreign
        # account: a job id is not a cross-device handle.
        return None, "pc_shell_job_not_found"
    return job, None


async def execute_pc_shell(request, *, session, uid, workspace_id, device_id, token_id,
                           run_id, conversation_id, arguments):
    """Run one command and wait only within the caller's window.

    Past the window the command is neither killed nor reported as a failure: it
    stays on the PC as a job and the answer carries the job id plus the output
    produced so far. The MCP audit receives numbers only; neither the command nor
    the output is written by this module to a log.
    """
    normalized = normalize_pc_shell_arguments(arguments)
    started = _NOW()
    if await _pc_lane_is_live(request, device_id) is False:
        return _failure("pc_shell_pc_offline",
                        "연결된 PC가 지금 응답하지 않아 실행하지 않았습니다. PC를 켠 뒤"
                        " 다시 요청하거나 pc_shell_start로 대기 순으로 두세요.",
                        duration_ms=round((_NOW() - started) * 1000))
    job_id = new_shell_job_id()
    if not await _create_job(request, uid=uid, device_id=device_id, token_id=token_id,
                             run_id=run_id, job_id=job_id, normalized=normalized):
        return _failure("pc_shell_store_unavailable",
                        "작업 기록을 준비하지 못해 실행하지 않았습니다.",
                        duration_ms=round((_NOW() - started) * 1000))
    command_text = build_pc_shell_command(normalized, job_id=job_id)
    dispatch_id, refusal = await _stage_dispatch(
        request, command=command_text, run_id=run_id, device_id=device_id,
        trusted_owner=(session, uid, workspace_id),
        ttl_seconds=min(3600, normalized["wait_seconds"] + 60),
    )
    if refusal is not None:
        await _finish_job(request, uid=uid, job_id=job_id, state="lost")
        return _failure(refusal, "PC 명령을 시작하지 못했습니다.",
                        duration_ms=round((_NOW() - started) * 1000))
    await _attach_dispatch(request, uid=uid, job_id=job_id, dispatch_id=dispatch_id)
    outcome = await _await_dispatch_envelope(
        request, uid=uid, dispatch_id=dispatch_id, conversation_id=conversation_id,
        wait_seconds=normalized["wait_seconds"], parser=parse_pc_shell_result,
    )
    return await _shell_answer(request, uid=uid, outcome=outcome, job_id=job_id,
                               normalized=normalized,
                               duration_ms=round((_NOW() - started) * 1000))


async def _shell_answer(request, *, uid, outcome, job_id, normalized, duration_ms) -> dict:
    """Turn one worker answer, or its absence, into the MCP result."""
    kind = outcome.get("kind")
    if kind == "state_unavailable":
        return _failure("pc_shell_state_unavailable",
                        "PC 명령 상태를 확인하지 못했습니다. 작업 " + job_id +
                        "은 pc_shell_read로 이어 확인할 수 있습니다.", duration_ms=duration_ms)
    if kind == "pending":
        # The wait window ended while the worker was still busy or before the PC
        # claimed the command: hand the job over instead of killing it.
        state = "running" if (outcome.get("row") or {}).get("state") == "received" else "queued"
        await _mark_job_state(request, uid=uid, job_id=job_id, state=state)
        return _job_handoff(job_id=job_id, state=state, preview=None,
                            duration_ms=duration_ms, normalized=normalized)
    if kind == "failed":
        return _failure("pc_shell_execution_failed", "PC 명령을 완료하지 못했습니다.",
                        duration_ms=duration_ms)
    if kind == "cancelled":
        await _finish_job(request, uid=uid, job_id=job_id, state="cancelled")
        return _failure("pc_shell_cancelled", "PC 명령이 취소되었습니다.", duration_ms=duration_ms)
    if kind == "output_unavailable":
        return _failure("pc_shell_output_unavailable", "PC 명령 결과를 확인하지 못했습니다.",
                        duration_ms=duration_ms)
    envelope = outcome["envelope"]
    error = _worker_error(envelope)
    if error is not None:
        await _finish_job(request, uid=uid, job_id=job_id, state="lost")
        return _failure(error, "PC 명령을 실행하지 못했습니다.",
                        duration_ms=duration_ms, result=envelope)
    state = envelope.get("state")
    if state != "exited":
        await _mark_job_state(request, uid=uid, job_id=job_id, state=state)
        return _job_handoff(job_id=job_id, state=state, preview=envelope,
                            duration_ms=duration_ms, normalized=normalized)
    await _finish_job(request, uid=uid, job_id=job_id, state="exited",
                      exit_code=envelope.get("exit_code"))
    audit = shell_audit_metadata(envelope, duration_ms=duration_ms)
    exit_code = envelope.get("exit_code")
    answer = ("PC 명령이 끝났습니다." if exit_code in (0, None)
              else "PC 명령이 종료 코드 " + str(exit_code) + "로 끝났습니다.")
    return {
        "status": "completed", "answer": answer,
        "job_id": job_id, "state": "exited", "running": False,
        "exit_code": exit_code,
        "stdout": envelope["stdout"], "stderr": envelope["stderr"],
        "stdout_bytes": envelope["stdout_bytes"], "stderr_bytes": envelope["stderr_bytes"],
        "truncated": audit["output_truncated"], "duration_ms": duration_ms,
        "pc_duration_ms": envelope["elapsed_ms"], "shell": normalized["shell"],
        **({"cwd": normalized["cwd"]} if normalized["cwd"] else {}),
        "audit": audit,
    }


async def _mark_job_state(request, *, uid, job_id, state):
    """A still-running job needs a row that says so; queued stays as staged."""
    if state == "queued":
        return None
    return await _finish_job(request, uid=uid, job_id=job_id, state=state)


def _job_handoff(*, job_id: str, state: str, preview, duration_ms: int,
                 normalized: Mapping) -> dict:
    """The wait window ended: the command keeps running and becomes readable."""
    preview = preview if isinstance(preview, Mapping) else {}
    audit = shell_audit_metadata(preview, duration_ms=duration_ms)
    running = state in ("running", "queued")
    if running:
        answer = ("PC에서 계속 실행 중입니다(경과 " + _elapsed_text(duration_ms) + "). 작업 번호 "
                  + job_id + "를 pc_shell_read로 이어서 읽고, pc_shell_stop으로 중지할 수 있습니다.")
    else:
        answer = ("PC 명령이 종료된 것으로 확인되었습니다. 작업 번호 " + job_id +
                  "의 출력은 pc_shell_read로 읽으세요.")
    return {
        "status": "completed", "answer": answer,
        "job_id": job_id, "state": state, "running": running,
        "exit_code": preview.get("exit_code"),
        "stdout": preview.get("stdout", ""), "stderr": preview.get("stderr", ""),
        "stdout_bytes": int(preview.get("stdout_bytes") or 0),
        "stderr_bytes": int(preview.get("stderr_bytes") or 0),
        "next_offset": preview.get("stdout_next_offset"),
        "truncated": audit["output_truncated"], "duration_ms": duration_ms,
        "shell": normalized["shell"],
        **({"cwd": normalized["cwd"]} if normalized.get("cwd") else {}),
        "next_step": "pc_shell_read",
        "audit": audit,
    }


async def execute_pc_shell_start(request, *, session, uid, workspace_id, device_id, token_id,
                                 run_id, conversation_id, arguments):
    """Start a job and answer immediately; the command has no execution deadline."""
    normalized = normalize_pc_shell_start_arguments(arguments)
    started = _NOW()
    job_id = new_shell_job_id()
    if not await _create_job(request, uid=uid, device_id=device_id, token_id=token_id,
                             run_id=run_id, job_id=job_id, normalized=normalized):
        return _failure("pc_shell_store_unavailable",
                        "작업 기록을 준비하지 못해 실행하지 않았습니다.",
                        duration_ms=round((_NOW() - started) * 1000))
    # A start is deliberately queued rather than refused while the PC is away:
    # the claim window is the dispatch's own TTL, and the answer says so.
    command_text = build_pc_shell_start_command(normalized, job_id=job_id)
    dispatch_id, refusal = await _stage_dispatch(
        request, command=command_text, run_id=run_id, device_id=device_id,
        trusted_owner=(session, uid, workspace_id), ttl_seconds=PC_SHELL_START_TTL_SECONDS,
    )
    if refusal is not None:
        await _finish_job(request, uid=uid, job_id=job_id, state="lost")
        return _failure(refusal, "PC 명령을 시작하지 못했습니다.",
                        duration_ms=round((_NOW() - started) * 1000))
    await _attach_dispatch(request, uid=uid, job_id=job_id, dispatch_id=dispatch_id)
    outcome = await _await_dispatch_envelope(
        request, uid=uid, dispatch_id=dispatch_id, conversation_id=conversation_id,
        wait_seconds=PC_SHELL_START_ACK_SECONDS, parser=parse_pc_shell_result,
    )
    return await _shell_answer(request, uid=uid, outcome=outcome, job_id=job_id,
                               normalized={**normalized, "wait_seconds": 0},
                               duration_ms=round((_NOW() - started) * 1000))


def _job_terminal_answer(job: Mapping, *, duration_ms: int) -> dict:
    """A finished job answers from its own durable row without touching the PC."""
    state = job.get("state")
    answer = {
        "exited": "PC 작업은 이미 끝났습니다(종료 코드 " + str(job.get("exit_code")) + ").",
        "cancelled": "PC 작업은 이미 중지되었습니다.",
        "lost": "PC 작업이 PC에서 확인되지 않습니다(PC 재시작 또는 30일 정리).",
    }.get(state, "PC 작업 상태를 확인하지 못했습니다.")
    return {
        "status": "completed", "answer": answer,
        "job_id": job.get("id"), "state": state, "running": False,
        "exit_code": job.get("exit_code"),
        "output": "", "output_bytes": 0, "total_bytes": 0,
        "next_offset": None, "eof": True, "large": False,
        "duration_ms": duration_ms,
        "audit": {"exit_code": job.get("exit_code")
                  if isinstance(job.get("exit_code"), int) else None,
                  "duration_ms": duration_ms, "output_bytes": 0, "output_truncated": False},
    }


def _state_answer(state: str, envelope: Mapping) -> str:
    elapsed = _elapsed_text(envelope.get("elapsed_ms"))
    if state == "running":
        return "PC에서 실행 중입니다(경과 " + elapsed + ")."
    if state == "exited":
        return ("PC 작업이 끝났습니다(종료 코드 " + str(envelope.get("exit_code")) +
                ", 경과 " + elapsed + ").")
    if state == "cancelled":
        return "PC 작업이 중지되었습니다(경과 " + elapsed + ")."
    return "PC에서 이 작업의 프로세스를 더 이상 찾을 수 없습니다(PC 재시작 또는 정리)."


async def execute_pc_shell_read(request, *, session, uid, workspace_id, device_id, token_id,
                                run_id, conversation_id, arguments):
    """Read one job's own output slice, status and elapsed time."""
    normalized = normalize_pc_shell_read_arguments(arguments)
    started = _NOW()
    job, denial = await _load_owned_job(request, uid=uid, job_id=normalized["job_id"],
                                        device_id=device_id)
    duration_ms = round((_NOW() - started) * 1000)
    if denial is not None:
        answer = ("다른 계정이나 다른 PC의 작업 번호는 읽을 수 없습니다."
                  if denial == "pc_shell_job_not_found" else "작업 기록을 확인하지 못했습니다.")
        return _failure(denial, answer, duration_ms=duration_ms)
    if await _pc_lane_is_live(request, device_id) is False:
        # A probe would only queue behind a PC that is away, so the durable row
        # answers: status, and the caller's own offset kept for the next read.
        if job.get("state") in _TERMINAL_STATES:
            return _job_terminal_answer(job, duration_ms=duration_ms)
        return {
            "status": "completed",
            "answer": "PC가 아직 연결되지 않았습니다. 작업 " + normalized["job_id"] +
                      "은(는) " + str(job.get("state")) + " 상태이고, PC가 돌아오면 이 위치에서"
                      " 이어서 읽을 수 있습니다.",
            "job_id": normalized["job_id"], "state": job.get("state"), "running": True,
            "exit_code": None, "output": "", "output_bytes": 0, "total_bytes": 0,
            "next_offset": normalized["offset"], "eof": False, "large": False,
            "duration_ms": duration_ms,
            "audit": {"exit_code": None, "duration_ms": duration_ms,
                      "output_bytes": 0, "output_truncated": False},
        }
    command_text = build_pc_shell_read_command(normalized)
    dispatch_id, refusal = await _stage_dispatch(
        request, command=command_text, run_id=run_id, device_id=device_id,
        trusted_owner=(session, uid, workspace_id), ttl_seconds=PC_SHELL_PROBE_TTL_SECONDS,
    )
    if refusal is not None:
        return _failure(refusal, "PC 작업 상태를 확인하지 못했습니다.", duration_ms=duration_ms)
    outcome = await _await_dispatch_envelope(
        request, uid=uid, dispatch_id=dispatch_id, conversation_id=conversation_id,
        wait_seconds=PC_SHELL_PROBE_WAIT_SECONDS, parser=parse_pc_shell_output_result,
    )
    duration_ms = round((_NOW() - started) * 1000)
    error = _worker_error(outcome.get("envelope"))
    if error is not None:
        if error == "pc_shell_job_missing":
            await _finish_job(request, uid=uid, job_id=normalized["job_id"], state="lost")
        return _failure(error, "PC 작업 상태를 확인하지 못했습니다.", duration_ms=duration_ms)
    if outcome.get("kind") != "envelope":
        return _failure("pc_shell_" + str(outcome.get("kind")),
                        "PC 작업 상태를 확인하지 못했습니다.", duration_ms=duration_ms)
    envelope = outcome["envelope"]
    state = envelope["state"]
    if state in _TERMINAL_STATES:
        await _finish_job(request, uid=uid, job_id=normalized["job_id"], state=state,
                          exit_code=envelope["exit_code"])
    elif state == "running" and job.get("state") == "queued":
        await _finish_job(request, uid=uid, job_id=normalized["job_id"], state="running")
    answer = _state_answer(state, envelope)
    if state == "running" and envelope["eof"]:
        answer += " 아직 새 출력은 없습니다."
    return {
        "status": "completed", "answer": answer,
        "job_id": normalized["job_id"], "state": state, "running": state == "running",
        "exit_code": envelope["exit_code"],
        "stream": envelope["stream"], "output": envelope["output"],
        "output_bytes": envelope["output_bytes"], "total_bytes": envelope["total_bytes"],
        "next_offset": envelope["next_offset"], "eof": envelope["eof"],
        "large": envelope["large"], "elapsed_ms": envelope["elapsed_ms"],
        "duration_ms": duration_ms,
        "audit": shell_audit_metadata(envelope, duration_ms=duration_ms),
    }


async def execute_pc_shell_stop(request, *, session, uid, workspace_id, device_id, token_id,
                                run_id, conversation_id, arguments):
    """Stop one job's whole process tree, or cancel it while it waits for a PC."""
    normalized = normalize_pc_shell_stop_arguments(arguments)
    started = _NOW()
    job, denial = await _load_owned_job(request, uid=uid, job_id=normalized["job_id"],
                                        device_id=device_id)
    duration_ms = round((_NOW() - started) * 1000)
    if denial is not None:
        answer = ("다른 계정이나 다른 PC의 작업 번호는 중지할 수 없습니다."
                  if denial == "pc_shell_job_not_found" else "작업 기록을 확인하지 못했습니다.")
        return _failure(denial, answer, duration_ms=duration_ms)
    if job.get("state") in _TERMINAL_STATES:
        return _job_terminal_answer(job, duration_ms=duration_ms)
    dispatch_id = job.get("dispatch_id")
    if not isinstance(dispatch_id, str) or not dispatch_id:
        return _failure("pc_shell_state_unavailable",
                        "작업의 명령을 확인하지 못했습니다.", duration_ms=duration_ms)
    if await _pc_lane_is_live(request, device_id) is False:
        row = await _dispatch_row(request, uid=uid, dispatch_id=dispatch_id)
        if isinstance(row, dict) and row.get("state") == "pending":
            # Nothing was claimed yet: cancel the queued command so it cannot
            # fire the moment the PC comes back.
            await _cancel_run(request, uid=uid, run_id=job["run_id"])
            await _finish_job(request, uid=uid, job_id=normalized["job_id"], state="cancelled")
            return {
                "status": "completed",
                "answer": "PC가 연결되기 전에 대기 중이던 작업 " + normalized["job_id"] +
                          "을 취소했습니다.",
                "job_id": normalized["job_id"], "state": "cancelled", "running": False,
                "exit_code": None, "killed": False, "duration_ms": duration_ms,
                "audit": {"exit_code": None, "duration_ms": duration_ms,
                          "output_bytes": 0, "output_truncated": False},
            }
        return _failure("pc_shell_pc_offline",
                        "PC가 오프라인이라 실행 중인 작업을 중지할 수 없습니다. PC를 연결한"
                        " 뒤 pc_shell_stop으로 중지하세요.", duration_ms=duration_ms)
    command_text = build_pc_shell_stop_command(normalized)
    stop_dispatch_id, refusal = await _stage_dispatch(
        request, command=command_text, run_id=run_id, device_id=device_id,
        trusted_owner=(session, uid, workspace_id), ttl_seconds=PC_SHELL_PROBE_TTL_SECONDS,
    )
    if refusal is not None:
        return _failure(refusal, "PC 작업 중지 명령을 보내지 못했습니다.", duration_ms=duration_ms)
    outcome = await _await_dispatch_envelope(
        request, uid=uid, dispatch_id=stop_dispatch_id, conversation_id=conversation_id,
        wait_seconds=PC_SHELL_PROBE_WAIT_SECONDS, parser=parse_pc_shell_stop_result,
    )
    duration_ms = round((_NOW() - started) * 1000)
    error = _worker_error(outcome.get("envelope"))
    if error is not None:
        return _failure(error, "PC 작업 중지 상태를 확인하지 못했습니다.", duration_ms=duration_ms)
    if outcome.get("kind") != "envelope":
        return _failure("pc_shell_" + str(outcome.get("kind")),
                        "PC 작업 중지 상태를 확인하지 못했습니다.", duration_ms=duration_ms)
    envelope = outcome["envelope"]
    state = envelope["state"]
    if state in _TERMINAL_STATES:
        await _finish_job(request, uid=uid, job_id=normalized["job_id"], state=state,
                          exit_code=envelope["exit_code"])
    answer = ("작업 " + normalized["job_id"] + "의 프로세스 트리를 중지했습니다(경과 "
              + _elapsed_text(envelope["elapsed_ms"]) + ")." if envelope["killed"]
              else "작업 " + normalized["job_id"] + "은(는) 이미 끝나 있었습니다(상태 "
                   + str(state) + ").")
    return {
        "status": "completed", "answer": answer,
        "job_id": normalized["job_id"], "state": state, "running": state == "running",
        "exit_code": envelope["exit_code"], "killed": envelope["killed"],
        "elapsed_ms": envelope["elapsed_ms"], "duration_ms": duration_ms,
        "audit": shell_audit_metadata(envelope, duration_ms=duration_ms),
    }
