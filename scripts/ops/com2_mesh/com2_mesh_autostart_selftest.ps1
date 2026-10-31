<#
.SYNOPSIS
  Fixture-driven selftest for com2_mesh_autostart.ps1.

.DESCRIPTION
  Runs the auto-start evidence evaluation against local observation fixtures and
  asserts the five-check mesh contract (boot time, MeshAgent service state,
  agent process start after boot, MeshCentral HTTP), the tri-state verdict
  rules and the CLI record shape. The tunnel task, listener and supervisor
  checks were removed with #5643 and are asserted to be absent. No network
  probe and no host mutation is executed.

.PARAMETER ProbePath
  Path to com2_mesh_autostart.ps1.

.PARAMETER KeepArtifacts
  Keep the temporary fixture directory for inspection.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_autostart_selftest.ps1
#>
[CmdletBinding()]
param(
    [string]$ProbePath = '',
    [switch]$KeepArtifacts
)

if (-not $ProbePath) {
    $ProbePath = Join-Path $PSScriptRoot 'com2_mesh_autostart.ps1'
}

$script:Passes = 0
$script:Failures = 0

function Assert-Equal {
    param($Expected, $Actual, [string]$Label)
    if ([string]$Expected -eq [string]$Actual) {
        $script:Passes++
        return
    }
    $script:Failures++
    Write-Output ("  FAIL {0}: expected [{1}] got [{2}]" -f $Label, $Expected, $Actual)
}

function Assert-True {
    param($Value, [string]$Label)
    if ([bool]$Value) {
        $script:Passes++
        return
    }
    $script:Failures++
    Write-Output ("  FAIL {0}: expected true" -f $Label)
}

function Write-JsonFile {
    param([string]$Path, $Object)
    [System.IO.File]::WriteAllText($Path, ($Object | ConvertTo-Json -Depth 10),
        (New-Object System.Text.UTF8Encoding($false)))
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

function Assert-ListNotContains {
    param($List, [string]$Name, [string]$Label)
    if (@($List) -notcontains $Name) { $script:Passes++; return }
    $script:Failures++
    Write-Output ("  FAIL {0}: unexpectedly present [{1}]" -f $Label, $Name)
}

# --- setup ----------------------------------------------------------------

if (-not (Test-Path -LiteralPath $ProbePath)) {
    Write-Output ("FAIL probe not found: {0}" -f $ProbePath)
    exit 1
}

$work = Join-Path $env:TEMP ("com2-autostart-selftest-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null

. $ProbePath -FunctionsOnly

# --- config ---------------------------------------------------------------

Write-Output '-- config'
$probeConfigObject = [ordered]@{
    com2_host = '192.0.2.10'
    mesh_url = 'https://192.0.2.10:4443/'
    # Legacy tunnel keys from an existing host config must be ignored, not rejected.
    tunnel_task = 'PADIEM-Mesh-Tunnel'
    tunnel_local_host = '127.0.0.1'
    tunnel_local_port = 4443
}
$probeConfigPath = Join-Path $work 'config.json'
Write-JsonFile -Path $probeConfigPath -Object $probeConfigObject
$probeConfig = Get-AutostartConfig -Path $probeConfigPath
$now = [datetime]'2026-10-23 01:30:00'

Assert-Equal -Expected 'Mesh Agent' -Actual $probeConfig.mesh_agent_service -Label 'default agent service'
Assert-Equal -Expected 120 -Actual $probeConfig.autostart_boot_tolerance_seconds -Label 'default boot tolerance'
Assert-Equal -Expected 8 -Actual $probeConfig.autostart_http_timeout_seconds -Label 'default http timeout'
Assert-Equal -Expected 'https://192.0.2.10:4443/' -Actual $probeConfig.mesh_url -Label 'explicit mesh_url is kept'

$derivedConfigObject = [ordered]@{ com2_host = '192.0.2.10' }
$derivedConfigPath = Join-Path $work 'config-derived.json'
Write-JsonFile -Path $derivedConfigPath -Object $derivedConfigObject
$derivedConfig = Get-AutostartConfig -Path $derivedConfigPath
Assert-Equal -Expected 'https://192.0.2.10:4443/' -Actual $derivedConfig.mesh_url `
    -Label 'mesh_url is derived from com2_host and the default port'

$badConfigObject = [ordered]@{
    tunnel_task = 'PADIEM-Mesh-Tunnel'
    tunnel_local_host = '127.0.0.1'
    tunnel_local_port = 4443
    mesh_url = 'https://127.0.0.1:4443/'
}
$badConfigPath = Join-Path $work 'config-bad.json'
Write-JsonFile -Path $badConfigPath -Object $badConfigObject
$badConfigRejected = $false
try { [void](Get-AutostartConfig -Path $badConfigPath) } catch { $badConfigRejected = $true }
Assert-True -Value $badConfigRejected -Label 'missing com2_host rejected'

# --- verified baseline ----------------------------------------------------

Write-Output '-- verified baseline'
$baseRecord = Test-AutostartEvidence -Observation (New-Observation) -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'com2_mesh_autostart/v1' -Actual $baseRecord.schema -Label 'record schema'
Assert-Equal -Expected 'observed' -Actual $baseRecord.source -Label 'record source'
Assert-Equal -Expected 'True' -Actual ([string]$baseRecord.auto_start_verified) -Label 'baseline verified'
Assert-Equal -Expected 'verified' -Actual $baseRecord.auto_start_state -Label 'baseline state'
Assert-Equal -Expected 0 -Actual @($baseRecord.failed_checks).Count -Label 'baseline failed count'
Assert-Equal -Expected 0 -Actual @($baseRecord.unverified_checks).Count -Label 'baseline unverified count'
Assert-Equal -Expected 5 -Actual @($baseRecord.checks).Count -Label 'check count'
Assert-True -Value ($null -eq $baseRecord.supervisor) -Label 'supervisor block removed'
Assert-True -Value ($null -eq $baseRecord.last_start_attempt) -Label 'last_start_attempt block removed'
foreach ($name in @('boot_time_observed', 'mesh_agent_service_automatic', 'mesh_agent_running',
        'mesh_agent_running_since_boot', 'mesh_http_200')) {
    Assert-Check -Record $baseRecord -Name $name -Expected 'true' -Label 'baseline'
}
foreach ($name in @('tunnel_task_exists', 'tunnel_task_enabled', 'tunnel_task_last_result_ok',
        'tunnel_listener_present', 'tunnel_listener_process_matches')) {
    $gone = Get-Check -Record $baseRecord -Name $name
    Assert-True -Value ($null -eq $gone) -Label "tunnel check retired: $name"
}

# --- fault injection ------------------------------------------------------

Write-Output '-- fault injection'
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
Assert-Equal -Expected 'failed' -Actual $missingAgentRecord.auto_start_state -Label 'missing agent state'

$beforeBoot = New-Observation
$beforeBoot.mesh_agent.process_started = '2026-10-23 00:20:00'
$beforeBootRecord = Test-AutostartEvidence -Observation $beforeBoot -Cfg $probeConfig -Now $now
Assert-Check -Record $beforeBootRecord -Name 'mesh_agent_running_since_boot' -Expected 'false' -Label 'agent before boot'
Assert-Equal -Expected 'failed' -Actual $beforeBootRecord.auto_start_state -Label 'agent before boot state'

$httpDown = New-Observation
$httpDown.mesh_http.code = 500
$httpDown.mesh_http.error = 'server error'
$httpDownRecord = Test-AutostartEvidence -Observation $httpDown -Cfg $probeConfig -Now $now
Assert-Check -Record $httpDownRecord -Name 'mesh_http_200' -Expected 'false' -Label 'http 500'
Assert-Equal -Expected 'failed' -Actual $httpDownRecord.auto_start_state -Label 'http 500 state'
Assert-ListContains -List $httpDownRecord.failed_checks -Name 'mesh_http_200' -Label 'http 500 failed list'

# --- unverified handling --------------------------------------------------

Write-Output '-- unverified handling'
$noBoot = New-Observation
$noBoot.boot_time = ''
$noBoot.boot_error = 'access denied'
$noBootRecord = Test-AutostartEvidence -Observation $noBoot -Cfg $probeConfig -Now $now
Assert-Check -Record $noBootRecord -Name 'boot_time_observed' -Expected 'false' -Label 'boot missing'
Assert-Check -Record $noBootRecord -Name 'mesh_agent_running_since_boot' -Expected 'unverified' -Label 'boot missing'
Assert-Equal -Expected 'failed' -Actual $noBootRecord.auto_start_state -Label 'boot missing state'
Assert-Equal -Expected 1 -Actual @($noBootRecord.unverified_checks).Count -Label 'boot missing unverified count'

$queryFail = New-Observation
$queryFail.mesh_agent.queried = $false
$queryFail.mesh_agent.error = 'service query blocked'
$queryFailRecord = Test-AutostartEvidence -Observation $queryFail -Cfg $probeConfig -Now $now
Assert-Equal -Expected 'False' -Actual ([string]$queryFailRecord.auto_start_verified) -Label 'query failure not verified'
Assert-Equal -Expected 'unverified' -Actual $queryFailRecord.auto_start_state -Label 'query failure state'
Assert-Equal -Expected 0 -Actual @($queryFailRecord.failed_checks).Count -Label 'query failure failed count'
Assert-Equal -Expected 3 -Actual @($queryFailRecord.unverified_checks).Count -Label 'query failure unverified count'
Assert-Check -Record $queryFailRecord -Name 'mesh_agent_running' -Expected 'unverified' -Label 'query failure'

$httpUnqueried = New-Observation
$httpUnqueried.mesh_http.queried = $false
$httpUnqueried.mesh_http.error = 'curl.exe was not found'
$httpUnqueriedRecord = Test-AutostartEvidence -Observation $httpUnqueried -Cfg $probeConfig -Now $now
Assert-Check -Record $httpUnqueriedRecord -Name 'mesh_http_200' -Expected 'unverified' -Label 'http not queried'
Assert-Equal -Expected 'unverified' -Actual $httpUnqueriedRecord.auto_start_state -Label 'http not queried state'
Assert-ListContains -List $httpUnqueriedRecord.unverified_checks -Name 'mesh_http_200' -Label 'http unverified list'

# --- state transition -----------------------------------------------------

Write-Output '-- state transition'
$httpDownFixture = New-Observation
$httpDownFixture.mesh_http.code = 500
$first = Test-AutostartEvidence -Observation (New-Observation) -Cfg $probeConfig -Now $now
$second = Test-AutostartEvidence -Observation $httpDownFixture -Cfg $probeConfig -Now $now.AddMinutes(5)
$third = Test-AutostartEvidence -Observation (New-Observation) -Cfg $probeConfig -Now $now.AddMinutes(10)
Assert-Equal -Expected 'verified' -Actual $first.auto_start_state -Label 'transition step 1'
Assert-Equal -Expected 'failed' -Actual $second.auto_start_state -Label 'transition step 2'
Assert-Equal -Expected 'verified' -Actual $third.auto_start_state -Label 'transition step 3'
Assert-Equal -Expected 'False' -Actual ([string]$second.auto_start_verified) -Label 'transition step 2 verified flag'

# --- CLI contract ---------------------------------------------------------

Write-Output '-- CLI contract'
$verifiedFixture = Join-Path $work 'observation-verified.json'
$outFile = Join-Path $work 'record.json'
$cliObservation = New-Observation
$cliObservation.observed_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
Write-JsonFile -Path $verifiedFixture -Object $cliObservation

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
    Assert-Equal -Expected 5 -Actual @($cliRecord.checks).Count -Label 'cli check count'
    Assert-True -Value ($null -eq $cliRecord.supervisor) -Label 'cli record has no supervisor block'
    Assert-True -Value ($null -eq $cliRecord.last_start_attempt) -Label 'cli record has no last_start_attempt block'
    Assert-Equal -Expected 200 -Actual $cliRecord.observation.mesh_http.code -Label 'cli observation survives json'
}
Assert-True -Value (Test-Path -LiteralPath $outFile) -Label 'cli out file written'
$savedRecord = if (Test-Path -LiteralPath $outFile) { Get-Content -LiteralPath $outFile -Raw | ConvertFrom-Json } else { $null }
Assert-True -Value ($savedRecord -and $savedRecord.auto_start_verified -eq $true) -Label 'out file verified'

$httpDownFixture2 = New-Observation
$httpDownFixture2.mesh_http.code = 500
$httpDownFixture2.observed_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$failedFixture = Join-Path $work 'observation-failed.json'
Write-JsonFile -Path $failedFixture -Object $httpDownFixture2
$cliFailOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ProbePath `
    -Config $probeConfigPath -ObservationFile $failedFixture -Json 2>&1
$cliFailExit = $LASTEXITCODE
Assert-Equal -Expected 0 -Actual $cliFailExit -Label 'cli failed exit'
$cliFailLine = @($cliFailOut | Where-Object { ([string]$_).Trim().StartsWith('{') }) | Select-Object -Last 1
$cliFailRecord = $null
if ($cliFailLine) { try { $cliFailRecord = $cliFailLine | ConvertFrom-Json } catch { $cliFailRecord = $null } }
Assert-True -Value ($cliFailRecord -and $cliFailRecord.auto_start_verified -eq $false) -Label 'cli failed flag'

$previousEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$cliBadOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ProbePath `
    -Config $badConfigPath -ObservationFile $verifiedFixture -Json 2>&1
$cliBadExit = $LASTEXITCODE
$ErrorActionPreference = $previousEap
Assert-Equal -Expected 1 -Actual $cliBadExit -Label 'cli bad config exit'
Assert-True -Value ((@($cliBadOut) -join ' ') -match 'com2_host') -Label 'cli bad config names the key'

# --- summary --------------------------------------------------------------

$summary = 'AUTOSTART SELFTEST PASS={0} FAIL={1} ARTIFACTS={2}' -f $script:Passes, $script:Failures, $work
Write-Output $summary
if ($script:Failures -gt 0) { exit 1 }
if (-not $KeepArtifacts) {
    try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue } catch { }
}
exit 0
