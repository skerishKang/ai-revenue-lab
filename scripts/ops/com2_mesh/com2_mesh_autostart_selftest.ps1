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
Assert-Equal -Expected 120 -Actual $probeConfig.autostart_boot_tolerance_seconds -Label 'default boot tolerance'
Assert-Equal -Expected 8 -Actual $probeConfig.autostart_http_timeout_seconds -Label 'default http timeout'

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

$runningTask = New-Observation
$runningTask.tunnel_task.last_result = 267009
$runningRecord = Test-AutostartEvidence -Observation $runningTask -Cfg $probeConfig -Now $now
Assert-Check -Record $runningRecord -Name 'tunnel_task_last_result_ok' -Expected 'true' -Label 'running task result'
Assert-Equal -Expected 'verified' -Actual $runningRecord.auto_start_state -Label 'running task state'

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
