# check-user-helper.ps1 — one-shot READ-ONLY diagnosis of the user-session
# helper chain on a Windows PC (PS 5.1, no admin needed, changes nothing).
#
# Use it before/after swapping the scheduled task to the single-file EXE
# (the 비공개 운영 기록(거버넌스 폴더, 같은 상대 경로), PC_USER_HELPER_RELEASE_20261107.md, step 6) and whenever
# the user mode breaks: it prints where the chain is still whole and where it
# first breaks, one KEY=VALUE line at a time, with no secret material.
#
#   .\check-user-helper.ps1                          full diagnosis
#   .\check-user-helper.ps1 -DeviceId <raw id>       pin the device id explicitly
#   .\check-user-helper.ps1 -PrintPipeNameOnly -DeviceId <raw id>
#                                                    just the pipe name
#
# Sections: TASK (scheduler) -> BINARY (python -m vs EXE) -> SECRET_FILE
# (existence/size/ACL only, never content) -> INSTALL_DIR (#7564: who owns the
# helper's folder and which accounts it names) -> PIPE (device-id-derived name
# in \\.\pipe\) -> PROCESS (session/user) -> AGENT (Mesh Agent service) ->
# VERDICT (first break). Exit code: 0 OK, 1 WARN, 2 FAIL.
#
# Secret hygiene: this script NEVER reads C:\ProgramData\Padiem\helper.secret.
# It touches the file only through Test-Path / Get-Item / Get-Acl (metadata
# and ACL). The pipe name is a SHA-256 of the device id — the secret never
# enters any hash or any output.

[CmdletBinding()]
param(
    # Raw MeshCentral device id. Optional: the script reads it from the task
    # action arguments (--device-id ...) when omitted.
    [string]$DeviceId = "",
    # Print only the derived pipe name (used by tests and quick checks).
    [switch]$PrintPipeNameOnly
)

$ErrorActionPreference = 'Stop'

$Script:TaskFullPath = '\Padiem\'
$Script:TaskName = 'PadiemUserSessionHelper'
$Script:SecretPath = 'C:\ProgramData\Padiem\helper.secret'
$Script:AgentServiceName = 'Mesh Agent'
# Same prefix and shape as claw_connect.user_session_helper.pipe_name:
# padiem-user-helper-dev_<sha256(device_id utf-8) hex[:32]>.
$Script:PipePrefix = 'padiem-user-helper-'
$Script:DeviceIdPattern = '^[A-Za-z0-9_.$:@+\-]{1,256}$'

function Out-Line([string]$Key, [string]$Value) {
    Write-Output ("{0}={1}" -f $Key, $Value)
}

function Get-Sha256Hex([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-FileSha256Hex([string]$Path) {
    # Binary hash of the task's OWN executable (EXE identity), never the
    # secret file — see the hygiene note in the header.
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Test-OnlyTrustedAccounts($Acl) {
    # #7564: true when inheritance is cut, the owner is SYSTEM, the
    # Administrators group or this user, and no entry names any other account.
    # Accounts are compared as SIDs, so a localized Windows answers the same.
    $sid = [System.Security.Principal.SecurityIdentifier]
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $trusted = @('S-1-5-18', 'S-1-5-32-544', $me)
    if (-not $Acl.AreAccessRulesProtected) { return $false }
    if ($trusted -notcontains $Acl.GetOwner($sid).Value) { return $false }
    foreach ($rule in $Acl.GetAccessRules($true, $true, $sid)) {
        if ($trusted -notcontains $rule.IdentityReference.Value) { return $false }
    }
    return $true
}

function Get-HelperPipeName([string]$RawDeviceId) {
    # One definition of the derivation, mirroring the Python module:
    # sha256(utf-8(device_id)) hex, first 32 chars, 'dev_' prefixed, behind
    # the shared pipe prefix. Returns $null for anything the Python module
    # would refuse (its _DEVICE_ID_RAW shape).
    if (-not $RawDeviceId) { return $null }
    if ($RawDeviceId -notmatch $Script:DeviceIdPattern) { return $null }
    return $Script:PipePrefix + 'dev_' + (Get-Sha256Hex $RawDeviceId).Substring(0, 32)
}

function Get-DeviceIdFromTaskArguments([string]$Arguments) {
    # The install scripts write '--device-id <raw id>' into the action; the
    # raw id may contain '$' but never whitespace or quotes.
    if (-not $Arguments) { return $null }
    $match = [regex]::Match($Arguments, '--device-id\s+([^"\s]+)')
    if ($match.Success) { return $match.Groups[1].Value }
    return $null
}

function Test-PipeExists([string]$PipeName) {
    try {
        $pipes = [System.IO.Directory]::GetFiles('\\.\pipe\')
        foreach ($pipe in $pipes) {
            if ($pipe -ieq ('\\.\pipe\' + $PipeName)) { return $true }
        }
        return $false
    }
    catch {
        return $false
    }
}

function Resolve-DeviceId([string]$TaskArguments) {
    if ($DeviceId) {
        return @{ value = $DeviceId; source = 'parameter' }
    }
    $fromTask = Get-DeviceIdFromTaskArguments $TaskArguments
    if ($fromTask) {
        return @{ value = $fromTask; source = 'task_action' }
    }
    return @{ value = $null; source = 'none' }
}

# ── pipe-name-only mode (tests, quick field checks) ─────────────────────────
if ($PrintPipeNameOnly) {
    $arguments = ''
    if (-not $DeviceId) {
        # Only reach for the task when no id was pinned: a Linux pwsh (CI)
        # has no ScheduledTasks module and must not die here.
        $task = Get-ScheduledTask -TaskPath $Script:TaskFullPath -TaskName $Script:TaskName -ErrorAction SilentlyContinue
        if ($task -and $task.Actions.Count -gt 0) { $arguments = [string]$task.Actions[0].Arguments }
    }
    $resolved = Resolve-DeviceId $arguments
    if (-not $resolved.value) {
        Out-Line 'PIPE_NAME' 'unresolved (no -DeviceId and no task action)'
        exit 2
    }
    $pipe = Get-HelperPipeName $resolved.value
    if (-not $pipe) {
        Out-Line 'PIPE_NAME' 'invalid device id'
        exit 2
    }
    Out-Line 'PIPE_NAME' $pipe
    exit 0
}

# ── full diagnosis ───────────────────────────────────────────────────────────
$Script:FirstBreak = 'none'
$Script:Verdict = 'OK'

function Note-Break([string]$Section, [bool]$IsFail) {
    # The first break decides the verdict line; FAIL beats WARN.
    if ($Script:FirstBreak -eq 'none') { $Script:FirstBreak = $Section }
    if ($IsFail) { $Script:Verdict = 'FAIL' }
    elseif ($Script:Verdict -eq 'OK') { $Script:Verdict = 'WARN' }
}

# 1. TASK — the scheduled task that launches the helper in the user session.
$task = Get-ScheduledTask -TaskPath $Script:TaskFullPath -TaskName $Script:TaskName -ErrorAction SilentlyContinue
$taskArguments = ''
$taskExecute = ''
if ($null -eq $task) {
    Out-Line 'TASK_PRESENT' 'false'
    Note-Break 'TASK' $true
}
else {
    Out-Line 'TASK_PRESENT' 'true'
    Out-Line 'TASK_STATE' ("{0}" -f $task.State)
    $info = Get-ScheduledTaskInfo -TaskName $Script:TaskName -TaskPath $Script:TaskFullPath -ErrorAction SilentlyContinue
    if ($info) {
        Out-Line 'TASK_LAST_RESULT' ("0x{0:X8}" -f $info.LastTaskResult)
        Out-Line 'TASK_LAST_RUN' ('{0}' -f $info.LastRunTime.ToString('yyyy-MM-ddTHH:mm:ss'))
        if ($info.LastTaskResult -ne 0 -and $info.LastTaskResult -ne 267009 -and $task.State -eq 'Ready') {
            Note-Break 'TASK' $false   # non-zero last result is a warning, not a break
        }
    }
    $action = $task.Actions | Select-Object -First 1
    $taskExecute = [string]$action.Execute
    $taskArguments = [string]$action.Arguments
    Out-Line 'TASK_EXECUTE' $taskExecute
    # Arguments carry only the module/EXE name, the device id and the secret
    # FILE PATH — no secret content ever sits in the action.
    Out-Line 'TASK_ARGUMENTS' $taskArguments
    Out-Line 'TASK_RUN_ACCOUNT' ("{0}" -f ($task.Principal.UserId))
    if ($task.State -ne 'Ready' -and $task.State -ne 'Running') {
        Note-Break 'TASK' $false
    }
}

# 2. BINARY — python -m launcher or the single-file EXE.
$binaryKind = 'unknown'
if ($taskExecute) {
    $executePath = $taskExecute.Trim('"')
    if ($executePath -match '(?i)python[wx]?\.exe$') {
        $binaryKind = 'python'
        if ($taskArguments -match '-m\s+claw_connect\.user_helper_service') {
            Out-Line 'BINARY_KIND' 'python -m claw_connect.user_helper_service'
        }
        else {
            Out-Line 'BINARY_KIND' 'python (unexpected arguments)'
            Note-Break 'BINARY' $false
        }
    }
    else {
        $binaryKind = 'exe'
        Out-Line 'BINARY_KIND' 'exe'
        if (Test-Path -LiteralPath $executePath) {
            $item = Get-Item -LiteralPath $executePath
            Out-Line 'BINARY_FILE_VERSION' ("{0}" -f $item.VersionInfo.FileVersion)
            Out-Line 'BINARY_SHA256_12' (Get-FileSha256Hex $executePath).Substring(0, 12)
        }
        else {
            Out-Line 'BINARY_FILE_VERSION' 'missing executable'
            Note-Break 'BINARY' $true
        }
    }
}
Out-Line 'BINARY_KIND_RESOLVED' $binaryKind

# 3. SECRET_FILE — existence, size and ACL summary. NEVER the content.
if (Test-Path -LiteralPath $Script:SecretPath) {
    Out-Line 'SECRET_PRESENT' 'true'
    $secretItem = Get-Item -LiteralPath $Script:SecretPath
    Out-Line 'SECRET_SIZE_BYTES' ("{0}" -f $secretItem.Length)
    $acl = Get-Acl -LiteralPath $Script:SecretPath
    Out-Line 'SECRET_ACL_OWNER' ("{0}" -f $acl.Owner)
    $entries = @($acl.Access)
    Out-Line 'SECRET_ACL_ENTRIES' ("{0}" -f $entries.Count)
    $index = 0
    foreach ($entry in $entries) {
        $index += 1
        Out-Line ("SECRET_ACL_{0}" -f $index) ("{0}::{1}" -f $entry.IdentityReference, $entry.FileSystemRights)
    }
    # #7564: a secret another local account can reach is a warning even while
    # the chain still works - the PC needs the helper installed again.
    $secretLocked = Test-OnlyTrustedAccounts $acl
    Out-Line 'SECRET_ACL_OWNER_SID' ("{0}" -f $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value)
    Out-Line 'SECRET_ACL_INHERITANCE_CUT' ("{0}" -f $acl.AreAccessRulesProtected)
    Out-Line 'SECRET_LOCKED' ("{0}" -f $secretLocked)
    if (-not $secretLocked) { Note-Break 'SECRET_FILE' $false }
}
else {
    Out-Line 'SECRET_PRESENT' 'false'
    Note-Break 'SECRET_FILE' $true
}

# 3b. INSTALL_DIR (#7564) — who owns the helper's folder and which accounts it
# names. Metadata only; the folder's files are not opened.
$installDir = Split-Path -Parent $Script:SecretPath
if (Test-Path -LiteralPath $installDir) {
    Out-Line 'INSTALL_DIR_PRESENT' 'true'
    $dirAcl = Get-Acl -LiteralPath $installDir
    Out-Line 'INSTALL_DIR_OWNER_SID' ("{0}" -f $dirAcl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value)
    Out-Line 'INSTALL_DIR_INHERITANCE_CUT' ("{0}" -f $dirAcl.AreAccessRulesProtected)
    $dirEntries = @($dirAcl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
    Out-Line 'INSTALL_DIR_ACL_ENTRIES' ("{0}" -f $dirEntries.Count)
    $dirIndex = 0
    foreach ($dirEntry in $dirEntries) {
        $dirIndex += 1
        Out-Line ("INSTALL_DIR_ACL_{0}" -f $dirIndex) ("{0}::{1}::{2}" -f $dirEntry.IdentityReference.Value, $dirEntry.AccessControlType, $dirEntry.FileSystemRights)
    }
    $dirLocked = Test-OnlyTrustedAccounts $dirAcl
    Out-Line 'INSTALL_DIR_LOCKED' ("{0}" -f $dirLocked)
    if (-not $dirLocked) { Note-Break 'INSTALL_DIR' $false }
}
else {
    Out-Line 'INSTALL_DIR_PRESENT' 'false'
}

# 4. PIPE — the device-id-derived pipe must exist in \\.\pipe\.
$resolved = Resolve-DeviceId $taskArguments
Out-Line 'DEVICE_ID_SOURCE' $resolved.source
if ($resolved.source -eq 'task_action') {
    Out-Line 'DEVICE_ID_FROM_TASK' $resolved.value
}
$pipeName = Get-HelperPipeName $resolved.value
if (-not $pipeName) {
    Out-Line 'PIPE_NAME' 'unresolved'
    Note-Break 'PIPE' $true
}
else {
    Out-Line 'PIPE_NAME' $pipeName
    $pipeFound = Test-PipeExists $pipeName
    Out-Line 'PIPE_FOUND' ("{0}" -f $pipeFound)
    if (-not $pipeFound) { Note-Break 'PIPE' $true }
}

# 5. PROCESS — whose session and user actually runs the helper.
$helperProcesses = @()
try {
    $helperProcesses = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'python%' OR Name LIKE 'padiem-user-helper%'" |
        Where-Object { $_.CommandLine -match 'user_helper_service|padiem-user-helper' })
}
catch {
    $helperProcesses = @()
}
Out-Line 'PROCESS_COUNT' ("{0}" -f $helperProcesses.Count)
$processIndex = 0
foreach ($proc in $helperProcesses) {
    $processIndex += 1
    $owner = Invoke-CimMethod -InputObject $proc -MethodName GetOwner -ErrorAction SilentlyContinue
    $ownerName = if ($owner -and $owner.User) { "{0}\{1}" -f $owner.Domain, $owner.User } else { 'unknown' }
    Out-Line ("PROCESS_{0}_PID" -f $processIndex) ("{0}" -f $proc.ProcessId)
    Out-Line ("PROCESS_{0}_SESSION" -f $processIndex) ("{0}" -f $proc.SessionId)
    Out-Line ("PROCESS_{0}_USER" -f $processIndex) $ownerName
}
if ($helperProcesses.Count -eq 0) { Note-Break 'PROCESS' $true }

# 6. AGENT — the PADIEM PC agent (executor) service.
$agentService = Get-Service -Name $Script:AgentServiceName -ErrorAction SilentlyContinue
if ($null -eq $agentService) {
    Out-Line 'AGENT_PRESENT' 'false'
    Note-Break 'AGENT' $false   # a helper without the agent is degraded, not broken
}
else {
    Out-Line 'AGENT_PRESENT' 'true'
    Out-Line 'AGENT_STATUS' ("{0}" -f $agentService.Status)
    Out-Line 'AGENT_STARTTYPE' ("{0}" -f $agentService.StartType)
    if ($agentService.Status -ne 'Running') { Note-Break 'AGENT' $false }
}

# 7. VERDICT — OK | WARN | FAIL and the first broken point.
Out-Line 'VERDICT' $Script:Verdict
Out-Line 'VERDICT_FIRST_BREAK' $Script:FirstBreak

if ($Script:Verdict -eq 'FAIL') { exit 2 }
if ($Script:Verdict -eq 'WARN') { exit 1 }
exit 0
