<#
.SYNOPSIS
  Fixture-driven selftest for com2_mesh_autostart.ps1.

.DESCRIPTION
  Evaluates recorded observations only. It never queries the host, never
  starts or stops a process, and never touches a scheduled task.

  It verifies the tri-state verdict contract, the boot/task/listener/HTTP
  checks, fault injection for each check, query-failure handling, a
  verified -> failed -> verified state transition, and the JSON CLI contract.

.PARAMETER ProbePath
  Path to com2_mesh_autostart.ps1.

.PARAMETER KeepArtifacts
  Keep the temporary directory for inspection.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_autostart_selftest.ps1
#>
[CmdletBinding()]
param(
    [string]$ProbePath = '',
    [switch]$KeepArtifacts
)

if (-not $ProbePath) { $ProbePath = Join-Path $PSScriptRoot 'com2_mesh_autostart.ps1' }

$ErrorActionPreference = 'Stop'
$script:Passes = 0
$script:Failures = 0

function Assert-Equal {
    param($Expected, $Actual, [string]$Label)
    if ([string]$Expected -eq [string]$Actual) { $script:Passes++; return }
    $script:Failures++
    Write-Output ("  FAIL {0}: expected [{1}] got [{2}]" -f $Label, $Expected, $Actual)
}

function Assert-True {
    param($Value, [string]$Label)
    if ([bool]$Value) { $script:Passes++; return }
    $script:Failures++
    Write-Output ("  FAIL {0}: expected true" -f $Label)
}

function Write-JsonFile {
    param([string]$Path, $Object)
    $json = $Object | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function New-Observation {
    return [ordered]@{
        schema = 'com2_mesh_autostart_observation/v1'
        observed_at = '2026-10-23 01:29:00'
        boot_time = '2026-10-23 00:44:45'
        boot_error = ''
        mesh_agent = [ordered]@{
            queried = $true; exists = $true; name = 'Mesh Agent'
            status = 'Running'; start_mode = 'Auto'; pid = 5180
            process_name = 'MeshAgent'; process_started = '2026-10-23 00:46:34'; error = ''
        }
        tunnel_task = [ordered]@{
            queried = $true; exists = $true; name = 'PADIEM-Mesh-Tunnel'
            enabled = $true; state = 'Ready'
            last_run = '2026-10-23 01:00:00'; last_result = 0
            next_run = '2026-10-23 01:35:00'; info_error = ''
            triggers = @(
                [ordered]@{ kind = 'boot'; enabled = $true; repetition_interval_seconds = $null; repetition_duration_seconds = $null },
                [ordered]@{ kind = 'time'; enabled = $true; repetition_interval_seconds = 300; repetition_duration_seconds = $null }
            )
            error = ''
        }
        listener = [ordered]@{
            queried = $true; listening = $true; local_address = '127.0.0.1'
            pid = 30500; process_name = 'ssh'; process_started = '2026-10-23 01:00:16'; error = ''
            parent_pid = 29000; parent_process_name = 'powershell'
            parent_command_line_observed = $true; parent_runs_supervisor = $true
            parent_error = ''
        }
        mesh_http = [ordered]@{ queried = $true; code = 200; error = '' }
    }
}

function Get-Check {
    param($Record, [string]$Name)
    return ($Record.checks | Where-Object { $_.name -eq $Name } | Select-Object -First 1)
}

function Assert-Check {
    param($Record, [string]$Name, [string]$Expected, [string]$Label)
    $check = Get-Check -Record $Record -Name $Name
    if (-not $check) {
        $script:Failures++
        Write-Output ("  FAIL {0}: check {1} is missing" -f $Label, $Name)
        return
    }
    $actual = 'unverified'
    if ($check.ok -eq $true) { $actual = 'true' }
    elseif ($check.ok -eq $false) { $actual = 'false' }
    Assert-Equal -Expected $Expected -Actual $actual -Label ("{0} {1}" -f $Label, $Name)
}

function Assert-ListContains {
    param($List, [string]$Name, [string]$Label)
    if (@($List) -contains $Name) { $script:Passes++; return }
    $script:Failures++
    Write-Output ("  FAIL {0}: missing [{1}]" -f $Label, $Name)
}

# --- setup ----------------------------------------------------------------

if (-not (Test-Path -LiteralPath $ProbePath)) {
    Write-Output ("FAIL probe not found: {0}" -f $ProbePath)
    exit 1
}

$work = Join-Path $env:TEMP ("com2-autostart-selftest-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null

. $ProbePath -FunctionsOnly

$probeConfigObject = [ordered]@{
    tunnel_task = 'PADIEM-Mesh-Tunnel'
    tunnel_local_host = '127.0.0.1'
    tunnel_local_port = 4443
    mesh_url = 'https://127.0.0.1:4443/'
}
$probeConfigPath = Join-Path $work 'config.json'
Write-JsonFile -Path $probeConfigPath -Object $probeConfigObject
$probeConfig = Get-AutostartConfig -Path $probeConfigPath
$now = [datetime]'2026-10-23 01:30:00'

# --- helpers --------------------------------------------------------------

Write-Output '-- helpers and config'
Assert-Equal -Expected 300 -Actual (ConvertFrom-IsoDurationSeconds 'PT5M') -Label 'iso minutes'
Assert-Equal -Expected 86400 -Actual (ConvertFrom-IsoDurationSeconds 'P1D') -Label 'iso days'
Assert-Equal -Expected 93600 -Actual (ConvertFrom-IsoDurationSeconds 'P1DT2H') -Label 'iso days and hours'
Assert-Equal -Expected 0 -Actual (ConvertFrom-IsoDurationSeconds 'PT0S') -Label 'iso zero'
Assert-Equal -Expected '' -Actual (ConvertFrom-IsoDurationSeconds '') -Label 'iso empty'
Assert-Equal -Expected '' -Actual (ConvertFrom-IsoDurationSeconds 'nonsense') -Label 'iso invalid'
Assert-Equal -Expected '' -Actual (ConvertTo-ObsTimeString ([datetime]'1899-12-30')) -Label 'null date is empty'
Assert-Equal -Expected '2026-10-23 00:44:45' -Actual (ConvertTo-ObsTimeString '2026-10-23 00:44:45') -Label 'time round trip'
Assert-Equal -Expected 'Mesh Agent' -Actual $probeConfig.mesh_agent_service -Label 'default agent service'
Assert-Equal -Expected 'ssh.exe' -Actual $probeConfig.tunnel_process_name -Label 'default listener process'
Assert-Equal -Expected 'com2_mesh_tunnel_supervisor.ps1' -Actual $probeConfig.tunnel_supervisor_script -Label 'default supervisor script'
Assert-Equal -Expected 120 -Actual $probeConfig.autostart_boot_tolerance_seconds -Label 'default boot tolerance'
Assert-Equal -Expected 8 -Actual $probeConfig.autostart_http_timeout_seconds -Label 'default http timeout'
Assert-Equal -Expected 2147946720 -Actual (ConvertTo-TaskResultCode ([uint32]2147946720)) -Label 'task result UInt32 above Int32'
Assert-Equal -Expected 4294967295 -Actual (ConvertTo-TaskResultCode ([uint32]::MaxValue)) -Label 'task result UInt32 max'
Assert-Equal -Expected 267009 -Actual (ConvertTo-TaskResultCode '267009') -Label 'task result numeric string'
Assert-Equal -Expected '' -Actual ([string](ConvertTo-TaskResultCode 'not a number')) -Label 'task result invalid is null'

$badConfigObject = [ordered]@{
    tunnel_local_host = '127.0.0.1'
    tunnel_local_port = 4443
    mesh_url = 'https://127.0.0.1:4443/'
}
$badConfigPath = Join-Path $work 'config-bad.json'
Write-JsonFile -Path $badConfigPath -Object $badConfigObject
$badConfigRejected = $false
try { [void](Get-AutostartConfig -Path $badConfigPath) } catch { $badConfigRejected = $true }
Assert-True -Value $badConfigRejected -Label 'missing tunnel_task rejected'

# --- host query -----------------------------------------------------------

Write-Output '-- host query above Int32'
$mockTask = [pscustomobject]@{
    Settings = [pscustomobject]@{ Enabled = $true }
    State = 4
    Triggers = @([pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskTimeTrigger' }
        Enabled = $true
        Repetition = [pscustomobject]@{ Interval = 'PT5M'; Duration = '' }
    })
}
$script:mockListenerPid = 30500
$script:mockParentPid = 29000
$script:mockChildMissing = $false
function Get-CimInstance {
    [CmdletBinding()]
    param($Namespace, $ClassName, $Filter)
    if ($ClassName -eq 'Win32_Process') {
        if ([string]$Filter -match ('ProcessId={0}$' -f $script:mockListenerPid)) {
            if ($script:mockChildMissing) { return $null }
            return [pscustomobject]@{ ProcessId = $script:mockListenerPid; ParentProcessId = $script:mockParentPid }
        }
        if ([string]$Filter -match ('ProcessId={0}$' -f $script:mockParentPid)) {
            return [pscustomobject]@{
                ProcessId = $script:mockParentPid
                Name = 'powershell.exe'
                CommandLine = 'powershell.exe -NoProfile -File C:\Padiem\com2_mesh_tunnel_supervisor.ps1'
            }
        }
        return $null
    }
    return $mockTask
}
function Get-ScheduledTaskInfo {
    [CmdletBinding()]
    param($TaskName)
    return [pscustomobject]@{
        LastRunTime = [datetime]'2026-10-23 02:41:41'
        LastTaskResult = [uint32]2147946720
        NextRunTime = [datetime]'2026-10-23 02:46:46'
    }
}
try {
    $hostObs = Get-TunnelTaskObservation -TaskName 'PADIEM-Mesh-Tunnel'
} finally {
    Remove-Item -LiteralPath function:Get-CimInstance -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath function:Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
}
Assert-Equal -Expected 2147946720 -Actual $hostObs.last_result -Label 'observed UInt32 result is kept'
Assert-Equal -Expected '' -Actual $hostObs.info_error -Label 'observed UInt32 result has no info error'
$resultType = if ($null -ne $hostObs.last_result) { $hostObs.last_result.GetType().Name } else { '' }
Assert-Equal -Expected 'Int64' -Actual $resultType -Label 'observed result is Int64'

Write-Output '-- host listener parent query'
function Get-CimInstance {
    [CmdletBinding()]
    param($Namespace, $ClassName, $Filter)
    if ($ClassName -eq 'Win32_Process') {
        if ([string]$Filter -match ('ProcessId={0}$' -f $script:mockListenerPid)) {
            if ($script:mockChildMissing) { return $null }
            return [pscustomobject]@{ ProcessId = $script:mockListenerPid; ParentProcessId = $script:mockParentPid }
        }
        if ([string]$Filter -match ('ProcessId={0}$' -f $script:mockParentPid)) {
            return [pscustomobject]@{
                ProcessId = $script:mockParentPid
                Name = 'powershell.exe'
                CommandLine = 'powershell.exe -NoProfile -File C:\Padiem\com2_mesh_tunnel_supervisor.ps1'
            }
        }
        return $null
    }
    return $null
}
function Get-Process {
    [CmdletBinding()]
    param($Id)
    return [pscustomobject]@{ ProcessName = 'ssh'; StartTime = [datetime]'2026-10-23 02:35:56' }
}
function Get-NetTCPConnection {
    [CmdletBinding()]
    param($State, $LocalPort)
    return [pscustomobject]@{ LocalAddress = '127.0.0.1'; OwningProcess = $script:mockListenerPid }
}
try {
    $listenerObs = Get-ListenerObservation -Cfg $probeConfig
    $script:mockChildMissing = $true
    $orphanObs = Get-ListenerObservation -Cfg $probeConfig
} finally {
    $script:mockChildMissing = $false
    Remove-Item -LiteralPath function:Get-CimInstance -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath function:Get-Process -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath function:Get-NetTCPConnection -ErrorAction SilentlyContinue
}
Assert-Equal -Expected 'True' -Actual ([string]$listenerObs.listening) -Label 'listener observed'
Assert-Equal -Expected 30500 -Actual $listenerObs.pid -Label 'listener child pid'
Assert-Equal -Expected 29000 -Actual $listenerObs.parent_pid -Label 'listener parent pid'
Assert-Equal -Expected 'powershell.exe' -Actual $listenerObs.parent_process_name -Label 'listener parent name'
Assert-True -Value ($listenerObs.parent_command_line_observed -eq $true) -Label 'listener parent command line observed'
Assert-True -Value ($listenerObs.parent_runs_supervisor -eq $true) -Label 'listener parent matches the supervisor'
Assert-Equal -Expected 0 -Actual @($listenerObs.Keys | Where-Object { $_ -eq 'parent_command_line' }).Count `
    -Label 'listener observation carries no raw command line'
Assert-Equal -Expected '' -Actual $listenerObs.parent_error -Label 'listener parent query has no error'
Assert-Equal -Expected 'True' -Actual ([string]$orphanObs.listening) -Label 'orphan listener still observed'
Assert-Equal -Expected 0 -Actual $orphanObs.parent_pid -Label 'orphan listener parent pid'
Assert-Equal -Expected 'False' -Actual ([string]$orphanObs.parent_command_line_observed) `
    -Label 'orphan listener observes no command line'
Assert-True -Value ([string]$orphanObs.parent_error) -Label 'orphan listener records the parent failure'

# --- verified baseline ----------------------------------------------------

Write-Output '-- verified baseline'
$baseRecord = Test-AutostartEvidence -Observation (New-Observation) -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'com2_mesh_autostart/v1' -Actual $baseRecord.schema -Label 'record schema'
Assert-Equal -Expected 'observed' -Actual $baseRecord.source -Label 'record source'
Assert-Equal -Expected 'True' -Actual ([string]$baseRecord.auto_start_verified) -Label 'baseline verified'
Assert-Equal -Expected 'verified' -Actual $baseRecord.auto_start_state -Label 'baseline state'
Assert-Equal -Expected 0 -Actual @($baseRecord.failed_checks).Count -Label 'baseline failed count'
Assert-Equal -Expected 0 -Actual @($baseRecord.unverified_checks).Count -Label 'baseline unverified count'
Assert-Equal -Expected 15 -Actual @($baseRecord.checks).Count -Label 'check count'
Assert-Equal -Expected 'running_connected' -Actual $baseRecord.supervisor.state -Label 'baseline supervisor state'
Assert-Equal -Expected 'confirmed' -Actual $baseRecord.supervisor.identity -Label 'baseline supervisor identity'
Assert-Equal -Expected 30500 -Actual $baseRecord.supervisor.child_pid -Label 'baseline supervisor child pid'
Assert-Equal -Expected 29000 -Actual $baseRecord.supervisor.parent_pid -Label 'baseline supervisor parent pid'
Assert-Equal -Expected 'succeeded' -Actual $baseRecord.last_start_attempt.outcome -Label 'baseline attempt outcome'
Assert-Equal -Expected 'observed' -Actual $baseRecord.last_start_attempt.confidence -Label 'baseline attempt confidence'
Assert-Equal -Expected 0 -Actual $baseRecord.last_start_attempt.result -Label 'baseline attempt result'
foreach ($name in @('boot_time_observed', 'mesh_agent_service_automatic', 'mesh_agent_running',
        'mesh_agent_running_since_boot', 'tunnel_task_exists', 'tunnel_task_enabled',
        'tunnel_task_autostart_trigger', 'tunnel_task_repetition_unbounded',
        'tunnel_task_next_run_present', 'tunnel_task_ran_after_boot',
        'tunnel_task_last_result_ok', 'tunnel_listener_present',
        'tunnel_listener_started_after_boot', 'tunnel_listener_process_matches', 'mesh_http_200')) {
    Assert-Check -Record $baseRecord -Name $name -Expected 'true' -Label 'baseline'
}

# --- fault injection ------------------------------------------------------

Write-Output '-- fault injection'
$expired = New-Observation
$expired.tunnel_task.next_run = ''
$expired.tunnel_task.triggers[1].repetition_duration_seconds = 86400
$expiredRecord = Test-AutostartEvidence -Observation $expired -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'False' -Actual ([string]$expiredRecord.auto_start_verified) -Label 'expired repetition not verified'
Assert-Equal -Expected 'failed' -Actual $expiredRecord.auto_start_state -Label 'expired repetition state'
Assert-Check -Record $expiredRecord -Name 'tunnel_task_repetition_unbounded' -Expected 'false' -Label 'expired'
Assert-Check -Record $expiredRecord -Name 'tunnel_task_next_run_present' -Expected 'false' -Label 'expired'
Assert-ListContains -List $expiredRecord.failed_checks -Name 'tunnel_task_repetition_unbounded' -Label 'expired failed list'
Assert-ListContains -List $expiredRecord.failed_checks -Name 'tunnel_task_next_run_present' -Label 'expired failed list'

$staleNext = New-Observation
$staleNext.tunnel_task.next_run = '2026-10-23 01:00:00'
$staleRecord = Test-AutostartEvidence -Observation $staleNext -Cfg $probeConfig -Now $now
Assert-Check -Record $staleRecord -Name 'tunnel_task_next_run_present' -Expected 'false' -Label 'stale next run'
Assert-Equal -Expected 'failed' -Actual $staleRecord.auto_start_state -Label 'stale next run state'

$neverRan = New-Observation
$neverRan.tunnel_task.last_run = '2026-10-23 00:10:00'
$neverRecord = Test-AutostartEvidence -Observation $neverRan -Cfg $probeConfig -Now $now
Assert-Check -Record $neverRecord -Name 'tunnel_task_ran_after_boot' -Expected 'false' -Label 'never ran after boot'
Assert-Equal -Expected 'failed' -Actual $neverRecord.auto_start_state -Label 'never ran state'

$notYetRun = New-Observation
$notYetRun.tunnel_task.last_run = ''
$notYetRun.tunnel_task.last_result = 267011
$notYetRecord = Test-AutostartEvidence -Observation $notYetRun -Cfg $probeConfig -Now $now
Assert-Check -Record $notYetRecord -Name 'tunnel_task_ran_after_boot' -Expected 'false' -Label 'not yet run'
Assert-Check -Record $notYetRecord -Name 'tunnel_task_last_result_ok' -Expected 'false' -Label 'not yet run'
Assert-Equal -Expected 'not_run' -Actual $notYetRecord.last_start_attempt.outcome -Label 'not yet run outcome'
Assert-Equal -Expected 'observed' -Actual $notYetRecord.last_start_attempt.confidence -Label 'not yet run confidence'

$runningTask = New-Observation
$runningTask.tunnel_task.last_result = 267009
$runningRecord = Test-AutostartEvidence -Observation $runningTask -Cfg $probeConfig -Now $now
Assert-Check -Record $runningRecord -Name 'tunnel_task_last_result_ok' -Expected 'true' -Label 'running task result'
Assert-Equal -Expected 'verified' -Actual $runningRecord.auto_start_state -Label 'running task state'
Assert-Equal -Expected 'running' -Actual $runningRecord.last_start_attempt.outcome -Label 'running task outcome'
Assert-Equal -Expected 'observed' -Actual $runningRecord.last_start_attempt.confidence -Label 'running task confidence'

$errorResult = New-Observation
$errorResult.tunnel_task.last_result = 2147946720
$errorResultRecord = Test-AutostartEvidence -Observation $errorResult -Cfg $probeConfig -Now $now
Assert-Check -Record $errorResultRecord -Name 'tunnel_task_last_result_ok' -Expected 'false' -Label 'UInt32 error result'
Assert-Equal -Expected 'False' -Actual ([string]$errorResultRecord.auto_start_verified) -Label 'UInt32 error result verified flag'
Assert-Equal -Expected 'failed' -Actual $errorResultRecord.auto_start_state -Label 'UInt32 error result state'
Assert-ListContains -List $errorResultRecord.failed_checks -Name 'tunnel_task_last_result_ok' -Label 'UInt32 error result failed list'
Assert-Equal -Expected 'LastTaskResult=2147946720 (0x800710E0)' `
    -Actual (Get-Check -Record $errorResultRecord -Name 'tunnel_task_last_result_ok').detail -Label 'UInt32 error result detail'
Assert-Equal -Expected 'running_connected' -Actual $errorResultRecord.supervisor.state -Label 'UInt32 error supervisor state'
Assert-Equal -Expected 'confirmed' -Actual $errorResultRecord.supervisor.identity -Label 'UInt32 error supervisor identity'
Assert-Equal -Expected 'suspected_refused_while_running' -Actual $errorResultRecord.last_start_attempt.outcome -Label 'UInt32 error attempt outcome'
Assert-Equal -Expected 'suspected' -Actual $errorResultRecord.last_start_attempt.confidence -Label 'UInt32 error attempt confidence'
Assert-Equal -Expected 2147946720 -Actual $errorResultRecord.last_start_attempt.result -Label 'UInt32 error attempt result'
Assert-Equal -Expected '0x800710E0' -Actual $errorResultRecord.last_start_attempt.result_hex -Label 'UInt32 error attempt hex'
Assert-Equal -Expected '2026-10-23 01:00:00' -Actual $errorResultRecord.last_start_attempt.run -Label 'UInt32 error attempt run'

$refusedNoSupervisor = New-Observation
$refusedNoSupervisor.tunnel_task.last_result = 2147946720
$refusedNoSupervisor.listener.listening = $false
$refusedNoSupervisor.listener.pid = 0
$refusedNoSupervisor.listener.process_name = ''
$refusedNoSupervisor.listener.process_started = ''
$refusedNoSupervisor.mesh_http.code = 0
$refusedNoSupervisor.mesh_http.error = 'tunnel closed'
$refusedNoSupervisorRecord = Test-AutostartEvidence -Observation $refusedNoSupervisor -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'not_running' -Actual $refusedNoSupervisorRecord.supervisor.state `
    -Label 'refused code without supervisor state'
Assert-Equal -Expected 'failed' -Actual $refusedNoSupervisorRecord.last_start_attempt.outcome `
    -Label 'refused code without supervisor outcome'
Assert-Equal -Expected 'observed' -Actual $refusedNoSupervisorRecord.last_start_attempt.confidence `
    -Label 'refused code without supervisor confidence'
Assert-Equal -Expected 2147946720 -Actual $refusedNoSupervisorRecord.last_start_attempt.result `
    -Label 'refused code without supervisor result'
Assert-Equal -Expected 'failed' -Actual $refusedNoSupervisorRecord.auto_start_state `
    -Label 'refused code without supervisor verdict'

$identityUnknown = New-Observation
$identityUnknown.tunnel_task.last_result = 2147946720
$identityUnknown.listener.parent_pid = 0
$identityUnknown.listener.parent_process_name = ''
$identityUnknown.listener.parent_command_line_observed = $false
$identityUnknown.listener.parent_runs_supervisor = $null
$identityUnknown.listener.parent_error = 'access denied'
$identityUnknownRecord = Test-AutostartEvidence -Observation $identityUnknown -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'unconfirmed' -Actual $identityUnknownRecord.supervisor.identity `
    -Label 'unread parent identity'
Assert-Equal -Expected 'unknown' -Actual $identityUnknownRecord.supervisor.state `
    -Label 'unread parent supervisor state'
Assert-Equal -Expected 'failed' -Actual $identityUnknownRecord.last_start_attempt.outcome `
    -Label 'unread parent attempt outcome'
Assert-Equal -Expected 'observed' -Actual $identityUnknownRecord.last_start_attempt.confidence `
    -Label 'unread parent attempt confidence'
Assert-Equal -Expected 2147946720 -Actual $identityUnknownRecord.last_start_attempt.result `
    -Label 'unread parent attempt result'
Assert-Check -Record $identityUnknownRecord -Name 'tunnel_task_last_result_ok' -Expected 'false' `
    -Label 'unread parent keeps the failed check'
Assert-ListContains -List $identityUnknownRecord.failed_checks -Name 'tunnel_task_last_result_ok' `
    -Label 'unread parent keeps the failed list'
Assert-Equal -Expected 'failed' -Actual $identityUnknownRecord.auto_start_state `
    -Label 'unread parent keeps the failed verdict'

$identityNoCommand = New-Observation
$identityNoCommand.tunnel_task.last_result = 2147946720
$identityNoCommand.listener.parent_command_line_observed = $false
$identityNoCommand.listener.parent_runs_supervisor = $null
$identityNoCommandRecord = Test-AutostartEvidence -Observation $identityNoCommand -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'unconfirmed' -Actual $identityNoCommandRecord.supervisor.identity `
    -Label 'parent without command line identity'
Assert-Equal -Expected 'unknown' -Actual $identityNoCommandRecord.supervisor.state `
    -Label 'parent without command line supervisor state'
Assert-Equal -Expected 'failed' -Actual $identityNoCommandRecord.last_start_attempt.outcome `
    -Label 'parent without command line outcome'
Assert-Equal -Expected 'observed' -Actual $identityNoCommandRecord.last_start_attempt.confidence `
    -Label 'parent without command line confidence'

$identityMismatch = New-Observation
$identityMismatch.tunnel_task.last_result = 2147946720
$identityMismatch.listener.parent_command_line_observed = $true
$identityMismatch.listener.parent_runs_supervisor = $false
$identityMismatchRecord = Test-AutostartEvidence -Observation $identityMismatch -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'mismatch' -Actual $identityMismatchRecord.supervisor.identity `
    -Label 'mismatched parent identity'
Assert-Equal -Expected 'unknown' -Actual $identityMismatchRecord.supervisor.state `
    -Label 'mismatched parent supervisor state'
Assert-Equal -Expected 'failed' -Actual $identityMismatchRecord.last_start_attempt.outcome `
    -Label 'mismatched parent attempt outcome'
Assert-Equal -Expected 'observed' -Actual $identityMismatchRecord.last_start_attempt.confidence `
    -Label 'mismatched parent attempt confidence'
Assert-Equal -Expected 2147946720 -Actual $identityMismatchRecord.last_start_attempt.result `
    -Label 'mismatched parent attempt result'
Assert-Equal -Expected '0x800710E0' -Actual $identityMismatchRecord.last_start_attempt.result_hex `
    -Label 'mismatched parent attempt hex'
Assert-Equal -Expected 'failed' -Actual $identityMismatchRecord.auto_start_state `
    -Label 'mismatched parent verdict'

$duplicateExit = New-Observation
$duplicateExit.tunnel_task.last_result = 2
$duplicateExitRecord = Test-AutostartEvidence -Observation $duplicateExit -Cfg $probeConfig -Now $now
Assert-Check -Record $duplicateExitRecord -Name 'tunnel_task_last_result_ok' -Expected 'false' -Label 'duplicate exit'
Assert-Equal -Expected 'duplicate_instance_exit' -Actual $duplicateExitRecord.last_start_attempt.outcome `
    -Label 'duplicate exit outcome'
Assert-Equal -Expected 'observed' -Actual $duplicateExitRecord.last_start_attempt.confidence `
    -Label 'duplicate exit confidence'
Assert-Equal -Expected 2 -Actual $duplicateExitRecord.last_start_attempt.result -Label 'duplicate exit result'
Assert-Equal -Expected 'failed' -Actual $duplicateExitRecord.auto_start_state -Label 'duplicate exit state'

$bootOnly = New-Observation
$bootOnly.tunnel_task.next_run = ''
$bootOnly.tunnel_task.triggers = @(
    [ordered]@{ kind = 'boot'; enabled = $true; repetition_interval_seconds = $null; repetition_duration_seconds = $null }
)
$bootOnlyRecord = Test-AutostartEvidence -Observation $bootOnly -Cfg $probeConfig -Now $now
Assert-Check -Record $bootOnlyRecord -Name 'tunnel_task_next_run_present' -Expected 'true' -Label 'boot only task'
Assert-Equal -Expected 'verified' -Actual $bootOnlyRecord.auto_start_state -Label 'boot only state'

$manualAgent = New-Observation
$manualAgent.mesh_agent.start_mode = 'Manual'
$manualRecord = Test-AutostartEvidence -Observation $manualAgent -Cfg $probeConfig -Now $now
Assert-Check -Record $manualRecord -Name 'mesh_agent_service_automatic' -Expected 'false' -Label 'manual agent'
Assert-Equal -Expected 'failed' -Actual $manualRecord.auto_start_state -Label 'manual agent state'

$stoppedAgent = New-Observation
$stoppedAgent.mesh_agent.status = 'Stopped'
$stoppedAgent.mesh_agent.pid = 0
$stoppedAgent.mesh_agent.process_name = ''
$stoppedAgent.mesh_agent.process_started = ''
$stoppedRecord = Test-AutostartEvidence -Observation $stoppedAgent -Cfg $probeConfig -Now $now
Assert-Check -Record $stoppedRecord -Name 'mesh_agent_running' -Expected 'false' -Label 'stopped agent'
Assert-Check -Record $stoppedRecord -Name 'mesh_agent_running_since_boot' -Expected 'unverified' -Label 'stopped agent'
Assert-Equal -Expected 'failed' -Actual $stoppedRecord.auto_start_state -Label 'stopped agent state'

$missingAgent = New-Observation
$missingAgent.mesh_agent.exists = $false
$missingAgent.mesh_agent.status = ''
$missingAgent.mesh_agent.start_mode = ''
$missingAgent.mesh_agent.process_started = ''
$missingAgentRecord = Test-AutostartEvidence -Observation $missingAgent -Cfg $probeConfig -Now $now
Assert-Check -Record $missingAgentRecord -Name 'mesh_agent_service_automatic' -Expected 'false' -Label 'missing agent'
Assert-Check -Record $missingAgentRecord -Name 'mesh_agent_running' -Expected 'false' -Label 'missing agent'

$missingListener = New-Observation
$missingListener.listener.listening = $false
$missingListener.listener.pid = 0
$missingListener.listener.process_name = ''
$missingListener.listener.process_started = ''
$missingListenerRecord = Test-AutostartEvidence -Observation $missingListener -Cfg $probeConfig -Now $now
Assert-Check -Record $missingListenerRecord -Name 'tunnel_listener_present' -Expected 'false' -Label 'missing listener'
Assert-Check -Record $missingListenerRecord -Name 'tunnel_listener_started_after_boot' -Expected 'unverified' -Label 'missing listener'
Assert-Check -Record $missingListenerRecord -Name 'tunnel_listener_process_matches' -Expected 'unverified' -Label 'missing listener'

$wrongProcess = New-Observation
$wrongProcess.listener.process_name = 'python'
$wrongProcessRecord = Test-AutostartEvidence -Observation $wrongProcess -Cfg $probeConfig -Now $now
Assert-Check -Record $wrongProcessRecord -Name 'tunnel_listener_process_matches' -Expected 'false' -Label 'wrong listener process'
Assert-Equal -Expected 'failed' -Actual $wrongProcessRecord.auto_start_state -Label 'wrong process state'
Assert-Equal -Expected 'not_running' -Actual $wrongProcessRecord.supervisor.state -Label 'wrong process supervisor state'

$ownerUnknown = New-Observation
$ownerUnknown.listener.process_name = ''
$ownerUnknownRecord = Test-AutostartEvidence -Observation $ownerUnknown -Cfg $probeConfig -Now $now
Assert-Check -Record $ownerUnknownRecord -Name 'tunnel_listener_process_matches' -Expected 'unverified' -Label 'unverified listener owner'
Assert-Equal -Expected 'unknown' -Actual $ownerUnknownRecord.supervisor.state -Label 'unverified listener owner supervisor state'
Assert-Equal -Expected 'confirmed' -Actual $ownerUnknownRecord.supervisor.identity -Label 'unverified listener owner identity'

$beforeBoot = New-Observation
$beforeBoot.listener.process_started = '2026-10-23 00:20:00'
$beforeBootRecord = Test-AutostartEvidence -Observation $beforeBoot -Cfg $probeConfig -Now $now
Assert-Check -Record $beforeBootRecord -Name 'tunnel_listener_started_after_boot' -Expected 'false' -Label 'listener before boot'

$httpDown = New-Observation
$httpDown.mesh_http.code = 500
$httpDown.mesh_http.error = 'server error'
$httpDownRecord = Test-AutostartEvidence -Observation $httpDown -Cfg $probeConfig -Now $now
Assert-Check -Record $httpDownRecord -Name 'mesh_http_200' -Expected 'false' -Label 'http 500'
Assert-Equal -Expected 'failed' -Actual $httpDownRecord.auto_start_state -Label 'http 500 state'
Assert-Equal -Expected 'running_disconnected' -Actual $httpDownRecord.supervisor.state -Label 'http 500 supervisor state'

# --- unverified handling --------------------------------------------------

Write-Output '-- unverified handling'
$noBoot = New-Observation
$noBoot.boot_time = ''
$noBoot.boot_error = 'access denied'
$noBootRecord = Test-AutostartEvidence -Observation $noBoot -Cfg $probeConfig -Now $now
Assert-Check -Record $noBootRecord -Name 'boot_time_observed' -Expected 'false' -Label 'boot missing'
Assert-Check -Record $noBootRecord -Name 'mesh_agent_running_since_boot' -Expected 'unverified' -Label 'boot missing'
Assert-Check -Record $noBootRecord -Name 'tunnel_task_ran_after_boot' -Expected 'unverified' -Label 'boot missing'
Assert-Check -Record $noBootRecord -Name 'tunnel_listener_started_after_boot' -Expected 'unverified' -Label 'boot missing'
Assert-Equal -Expected 'failed' -Actual $noBootRecord.auto_start_state -Label 'boot missing state'
Assert-Equal -Expected 3 -Actual @($noBootRecord.unverified_checks).Count -Label 'boot missing unverified count'

$queryFail = New-Observation
$queryFail.mesh_agent.queried = $false
$queryFail.mesh_agent.error = 'service query blocked'
$queryFail.tunnel_task.queried = $false
$queryFail.tunnel_task.error = 'task query blocked'
$queryFailRecord = Test-AutostartEvidence -Observation $queryFail -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'False' -Actual ([string]$queryFailRecord.auto_start_verified) -Label 'query failure not verified'
Assert-Equal -Expected 'unverified' -Actual $queryFailRecord.auto_start_state -Label 'query failure state'
Assert-Equal -Expected 0 -Actual @($queryFailRecord.failed_checks).Count -Label 'query failure failed count'
Assert-Equal -Expected 10 -Actual @($queryFailRecord.unverified_checks).Count -Label 'query failure unverified count'
Assert-Check -Record $queryFailRecord -Name 'mesh_agent_running' -Expected 'unverified' -Label 'query failure'
Assert-Check -Record $queryFailRecord -Name 'tunnel_task_exists' -Expected 'unverified' -Label 'query failure'
Assert-Equal -Expected 'running_connected' -Actual $queryFailRecord.supervisor.state -Label 'query failure supervisor state'
Assert-Equal -Expected 'unknown' -Actual $queryFailRecord.last_start_attempt.outcome -Label 'query failure attempt outcome'

$infoFail = New-Observation
$infoFail.tunnel_task.info_error = 'Get-ScheduledTaskInfo failed'
$infoFail.tunnel_task.last_run = ''
$infoFail.tunnel_task.next_run = ''
$infoFail.tunnel_task.last_result = $null
$infoFailRecord = Test-AutostartEvidence -Observation $infoFail -Cfg $probeConfig -Now $now
Assert-Check -Record $infoFailRecord -Name 'tunnel_task_next_run_present' -Expected 'unverified' -Label 'info failure'
Assert-Check -Record $infoFailRecord -Name 'tunnel_task_ran_after_boot' -Expected 'unverified' -Label 'info failure'
Assert-Check -Record $infoFailRecord -Name 'tunnel_task_last_result_ok' -Expected 'unverified' -Label 'info failure'
Assert-Equal -Expected 'unverified' -Actual $infoFailRecord.auto_start_state -Label 'info failure state'
Assert-Equal -Expected 'running_connected' -Actual $infoFailRecord.supervisor.state -Label 'info failure supervisor state'
Assert-Equal -Expected 'unknown' -Actual $infoFailRecord.last_start_attempt.outcome -Label 'info failure attempt outcome'

# --- state transition -----------------------------------------------------

Write-Output '-- state transition'
$first = Test-AutostartEvidence -Observation (New-Observation) -Cfg $probeConfig -Now $now
$second = Test-AutostartEvidence -Observation $expired -Cfg $probeConfig -Now $now.AddMinutes(5)
$recovered = New-Observation
$recovered.observed_at = '2026-10-23 01:40:00'
$recovered.tunnel_task.next_run = '2026-10-23 01:45:00'
$third = Test-AutostartEvidence -Observation $recovered -Cfg $probeConfig -Now $now.AddMinutes(10)
Assert-Equal -Expected 'verified' -Actual $first.auto_start_state -Label 'transition step 1'
Assert-Equal -Expected 'failed' -Actual $second.auto_start_state -Label 'transition step 2'
Assert-Equal -Expected 'verified' -Actual $third.auto_start_state -Label 'transition step 3'
Assert-Equal -Expected 'False' -Actual ([string]$second.auto_start_verified) -Label 'transition step 2 verified flag'

# --- CLI contract ---------------------------------------------------------

Write-Output '-- CLI contract'
$verifiedFixture = Join-Path $work 'observation-verified.json'
$expiredFixture = Join-Path $work 'observation-expired.json'
$outFile = Join-Path $work 'record.json'
$cliObservation = New-Observation
$cliObservation.observed_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$cliObservation.tunnel_task.next_run = (Get-Date).AddMinutes(10).ToString('yyyy-MM-dd HH:mm:ss')
Write-JsonFile -Path $verifiedFixture -Object $cliObservation
Write-JsonFile -Path $expiredFixture -Object $expired

$cliOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ProbePath `
    -Config $probeConfigPath -ObservationFile $verifiedFixture -Json -OutFile $outFile 2>&1
$cliExit = $LASTEXITCODE
Assert-Equal -Expected 0 -Actual $cliExit -Label 'cli verified exit'
$cliLine = @($cliOut | Where-Object { ([string]$_).Trim().StartsWith('{') }) | Select-Object -Last 1
$cliRecord = $null
if ($cliLine) { try { $cliRecord = $cliLine | ConvertFrom-Json } catch { $cliRecord = $null } }
Assert-True -Value ($null -ne $cliRecord) -Label 'cli verified json'
if ($cliRecord) {
    Assert-Equal -Expected 'True' -Actual ([string]$cliRecord.auto_start_verified) -Label 'cli verified flag'
    Assert-Equal -Expected 'verified' -Actual $cliRecord.auto_start_state -Label 'cli verified state'
    Assert-Equal -Expected 15 -Actual @($cliRecord.checks).Count -Label 'cli check count'
    Assert-Equal -Expected 'running_connected' -Actual $cliRecord.supervisor.state -Label 'cli supervisor state survives json'
    Assert-Equal -Expected 'confirmed' -Actual $cliRecord.supervisor.identity -Label 'cli supervisor identity survives json'
    Assert-Equal -Expected 30500 -Actual $cliRecord.supervisor.child_pid -Label 'cli supervisor child pid survives json'
    Assert-Equal -Expected 29000 -Actual $cliRecord.supervisor.parent_pid -Label 'cli supervisor parent pid survives json'
    Assert-True -Value (@($cliRecord.observation.listener.PSObject.Properties.Name) -notcontains 'parent_command_line') `
        -Label 'cli record carries no raw parent command line'
    Assert-Equal -Expected 'succeeded' -Actual $cliRecord.last_start_attempt.outcome -Label 'cli attempt outcome survives json'
    Assert-Equal -Expected 'observed' -Actual $cliRecord.last_start_attempt.confidence -Label 'cli attempt confidence survives json'
}
Assert-True -Value (Test-Path -LiteralPath $outFile) -Label 'cli out file written'
$savedRecord = if (Test-Path -LiteralPath $outFile) { Get-Content -LiteralPath $outFile -Raw | ConvertFrom-Json } else { $null }
Assert-True -Value ($savedRecord -and $savedRecord.auto_start_verified -eq $true) -Label 'out file verified'

$cliFailOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ProbePath `
    -Config $probeConfigPath -ObservationFile $expiredFixture -Json 2>&1
$cliFailExit = $LASTEXITCODE
Assert-Equal -Expected 0 -Actual $cliFailExit -Label 'cli expired exit'
$cliFailLine = @($cliFailOut | Where-Object { ([string]$_).Trim().StartsWith('{') }) | Select-Object -Last 1
$cliFailRecord = $null
if ($cliFailLine) { try { $cliFailRecord = $cliFailLine | ConvertFrom-Json } catch { $cliFailRecord = $null } }
Assert-True -Value ($cliFailRecord -and $cliFailRecord.auto_start_verified -eq $false) -Label 'cli expired flag'

$previousEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$cliBadOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ProbePath `
    -Config $badConfigPath -ObservationFile $verifiedFixture -Json 2>&1
$cliBadExit = $LASTEXITCODE
$ErrorActionPreference = $previousEap
Assert-Equal -Expected 1 -Actual $cliBadExit -Label 'cli bad config exit'
Assert-True -Value ((@($cliBadOut) -join ' ') -match 'tunnel_task') -Label 'cli bad config names the key'

# --- summary --------------------------------------------------------------

$summary = 'AUTOSTART SELFTEST PASS={0} FAIL={1} ARTIFACTS={2}' -f $script:Passes, $script:Failures, $work
Write-Output $summary
if ($script:Failures -gt 0) { exit 1 }
if (-not $KeepArtifacts) {
    try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue } catch { }
}
exit 0
