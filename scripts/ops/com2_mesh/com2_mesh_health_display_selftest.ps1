<#
.SYNOPSIS
  Fixture-driven selftest for com2_mesh_health_display.ps1 and
  com2_mesh_health_patch.ps1.

.DESCRIPTION
  Evaluates recorded probe output only. It never queries the host, never
  starts or stops a process, and never touches the deployed health script.

  It verifies:

  - the display class contract: a normal running supervisor is shown as ok
    only together with identity=confirmed, and an inconsistent record never
    renders as ok;
  - Add-AutostartDisplayFields copies the supervisor and last-attempt fields
    without touching the verdict fields, maps an old-schema record to
    not_reported and a missing record to probe_not_run;
  - end to end from com2_mesh_autostart.ps1: a refusal-code record with a
    confirmed supervisor keeps auto_start_state=failed and the failed check
    visible while the new fields show suspected_refused_while_running with
    the original result code and run time preserved;
  - com2_mesh_health_patch.ps1: dry run leaves the file unchanged, a hash
    mismatch or a missing anchor is refused, and an applied patch produces a
    parsing script whose status and HTML keep the existing failure rows and
    add the new display rows. Without the display module next to the script
    the patched file behaves exactly as before.

.PARAMETER DisplayPath
  Path to com2_mesh_health_display.ps1.

.PARAMETER PatchPath
  Path to com2_mesh_health_patch.ps1.

.PARAMETER ProbePath
  Path to com2_mesh_autostart.ps1.

.PARAMETER KeepArtifacts
  Keep the temporary directory for inspection.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_health_display_selftest.ps1
#>
[CmdletBinding()]
param(
    [string]$DisplayPath = '',
    [string]$PatchPath = '',
    [string]$ProbePath = '',
    [switch]$KeepArtifacts
)

if (-not $DisplayPath) { $DisplayPath = Join-Path $PSScriptRoot 'com2_mesh_health_display.ps1' }
if (-not $PatchPath) { $PatchPath = Join-Path $PSScriptRoot 'com2_mesh_health_patch.ps1' }
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

function Write-TextFile {
    param([string]$Path, [string]$Text)
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

# Native stderr under a Stop preference becomes a terminating error in
# Windows PowerShell 5.1, so every child run goes through this helper.
function Invoke-ChildScript {
    param([string[]]$Arguments)
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass @Arguments 2>&1
        return [pscustomobject]@{ Exit = $LASTEXITCODE; Output = @($output | ForEach-Object { [string]$_ }) }
    } finally {
        $ErrorActionPreference = $previousEap
    }
}

# --- setup ----------------------------------------------------------------

foreach ($p in @($DisplayPath, $PatchPath, $ProbePath)) {
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Output ("FAIL required file not found: {0}" -f $p)
        exit 1
    }
}

. $DisplayPath
. $ProbePath -FunctionsOnly

$work = Join-Path $env:TEMP ("com2-health-display-selftest-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null

# --- display class contract -----------------------------------------------

Write-Output '-- display class contract'
Assert-Equal -Expected 'ok' -Actual (Get-AutostartDisplayClass -State 'running_connected' -Identity 'confirmed') -Label 'running connected and confirmed is ok'
Assert-Equal -Expected 'bad' -Actual (Get-AutostartDisplayClass -State 'running_connected' -Identity 'unconfirmed') -Label 'running without confirmed identity is bad'
Assert-Equal -Expected 'bad' -Actual (Get-AutostartDisplayClass -State 'running_connected' -Identity 'mismatch') -Label 'running with mismatched identity is bad'
Assert-Equal -Expected '' -Actual (Get-AutostartDisplayClass -State 'running_disconnected' -Identity 'confirmed') -Label 'running disconnected is neutral'
Assert-Equal -Expected 'bad' -Actual (Get-AutostartDisplayClass -State 'not_running' -Identity 'confirmed') -Label 'not running is bad'
Assert-Equal -Expected '' -Actual (Get-AutostartDisplayClass -State 'unknown' -Identity 'confirmed') -Label 'unknown is neutral'
Assert-Equal -Expected '' -Actual (Get-AutostartDisplayClass -State 'not_reported' -Identity 'not_reported') -Label 'not reported is neutral'

# --- field copy contract ----------------------------------------------------

Write-Output '-- field copy contract'
$fullRecord = [pscustomobject]@{
    auto_start_state = 'failed'
    failed_checks = @('tunnel_task_last_result_ok')
    supervisor = [pscustomobject]@{
        state = 'running_connected'; identity = 'confirmed'
        child_pid = 20796; child_process = 'ssh'; parent_pid = 43668
    }
    last_start_attempt = [pscustomobject]@{
        run = '2026-10-23 02:56:56'; result = 2147946720; result_hex = '0x800710E0'
        outcome = 'suspected_refused_while_running'; confidence = 'suspected'
        detail = 'LastTaskResult=2147946720 (0x800710E0)'
    }
}
$fullStatus = [ordered]@{
    auto_start_state = 'failed'
    auto_start_failed_checks = 'tunnel_task_last_result_ok'
}
Add-AutostartDisplayFields -Status $fullStatus -Autostart $fullRecord
Assert-Equal -Expected 'failed' -Actual $fullStatus.auto_start_state -Label 'module keeps the verdict state'
Assert-Equal -Expected 'tunnel_task_last_result_ok' -Actual $fullStatus.auto_start_failed_checks -Label 'module keeps the failed checks'
Assert-Equal -Expected 'running_connected' -Actual $fullStatus.auto_start_supervisor_state -Label 'supervisor state copied'
Assert-Equal -Expected 'confirmed' -Actual $fullStatus.auto_start_supervisor_identity -Label 'supervisor identity copied'
Assert-Equal -Expected 'child_pid=20796; child=ssh; parent_pid=43668' -Actual $fullStatus.auto_start_supervisor_child -Label 'supervisor child copied'
Assert-Equal -Expected '2026-10-23 02:56:56' -Actual $fullStatus.auto_start_last_attempt_run -Label 'attempt run preserved'
Assert-Equal -Expected '2147946720' -Actual $fullStatus.auto_start_last_attempt_result -Label 'attempt result preserved'
Assert-Equal -Expected '0x800710E0' -Actual $fullStatus.auto_start_last_attempt_result_hex -Label 'attempt hex preserved'
Assert-Equal -Expected 'suspected_refused_while_running' -Actual $fullStatus.auto_start_last_attempt_outcome -Label 'attempt outcome copied'
Assert-Equal -Expected 'suspected' -Actual $fullStatus.auto_start_last_attempt_confidence -Label 'attempt confidence copied'

$fullRows = New-AutostartDisplayRows -Status $fullStatus
Assert-True -Value ($fullRows -match "<td class='ok'>running_connected / confirmed</td>") -Label 'confirmed running row is ok'
Assert-True -Value ($fullRows -match 'suspected_refused_while_running / suspected') -Label 'suspected outcome row shows the confidence'
Assert-True -Value ($fullRows -notmatch "<td class='ok'>suspected_refused_while_running") -Label 'suspected outcome is never ok'
Assert-True -Value ($fullRows -match '2026-10-23 02:56:56 / 2147946720 0x800710E0') -Label 'attempt row preserves code and time'

$oldStatus = [ordered]@{ auto_start_state = 'failed' }
Add-AutostartDisplayFields -Status $oldStatus -Autostart ([pscustomobject]@{ auto_start_state = 'failed' })
Assert-Equal -Expected 'not_reported' -Actual $oldStatus.auto_start_supervisor_state -Label 'old schema supervisor is not_reported'
Assert-Equal -Expected 'not_reported' -Actual $oldStatus.auto_start_supervisor_identity -Label 'old schema identity is not_reported'
Assert-Equal -Expected 'not_reported' -Actual $oldStatus.auto_start_last_attempt_outcome -Label 'old schema outcome is not_reported'
Assert-Equal -Expected 'unknown' -Actual $oldStatus.auto_start_last_attempt_confidence -Label 'old schema confidence is unknown'
$oldRows = New-AutostartDisplayRows -Status $oldStatus
Assert-True -Value ($oldRows -notmatch 'running_connected') -Label 'old schema never renders as running'
Assert-True -Value ($oldRows -notmatch "<td class='ok'>") -Label 'old schema has no ok row'

$nullStatus = [ordered]@{ auto_start_state = 'unverified' }
Add-AutostartDisplayFields -Status $nullStatus -Autostart $null
Assert-Equal -Expected 'probe_not_run' -Actual $nullStatus.auto_start_supervisor_state -Label 'missing record is probe_not_run'
Assert-Equal -Expected 'probe_not_run' -Actual $nullStatus.auto_start_last_attempt_outcome -Label 'missing record outcome is probe_not_run'
Assert-Equal -Expected 'unknown' -Actual $nullStatus.auto_start_last_attempt_confidence -Label 'missing record confidence is unknown'

$failedStatus = [ordered]@{ auto_start_state = 'failed' }
$failedRecord = [pscustomobject]@{
    supervisor = [pscustomobject]@{
        state = 'unknown'; identity = 'unconfirmed'
        child_pid = 20796; child_process = 'ssh'; parent_pid = 0
    }
    last_start_attempt = [pscustomobject]@{
        run = '2026-10-23 02:56:56'; result = 2147946720; result_hex = '0x800710E0'
        outcome = 'failed'; confidence = 'observed'; detail = 'refused without a confirmed supervisor'
    }
}
Add-AutostartDisplayFields -Status $failedStatus -Autostart $failedRecord
$failedRows = New-AutostartDisplayRows -Status $failedStatus
Assert-True -Value ($failedRows -match "<td class='bad'>failed / observed</td>") -Label 'failed outcome row is bad'
Assert-True -Value ($failedRows -notmatch "<td class='ok'>") -Label 'unconfirmed identity has no ok row'

# --- probe end to end -------------------------------------------------------

Write-Output '-- probe end to end'
$cfgObject = [ordered]@{
    tunnel_task = 'PADIEM-Mesh-Tunnel'
    tunnel_local_host = '127.0.0.1'
    tunnel_local_port = 4443
    mesh_url = 'https://127.0.0.1:4443/'
}
$cfgPath = Join-Path $work 'config.json'
Write-TextFile -Path $cfgPath -Text ($cfgObject | ConvertTo-Json -Depth 5)
$cfg = Get-AutostartConfig -Path $cfgPath

$observation = [ordered]@{
    schema = 'com2_mesh_autostart_observation/v1'
    observed_at = '2026-10-23 02:56:56'
    boot_time = '2026-10-23 00:44:45'
    boot_error = ''
    mesh_agent = [ordered]@{
        queried = $true; exists = $true; name = 'Mesh Agent'
        status = 'Running'; start_mode = 'Auto'; pid = 5180
        process_name = 'MeshAgent'; process_started = '2026-10-23 00:46:34'; error = ''
    }
    tunnel_task = [ordered]@{
        queried = $true; exists = $true; name = 'PADIEM-Mesh-Tunnel'
        enabled = $true; state = 'Running'
        last_run = '2026-10-23 02:56:56'; last_result = 2147946720
        next_run = '2026-10-23 03:01:01'; info_error = ''
        triggers = @(
            [ordered]@{ kind = 'boot'; enabled = $true; repetition_interval_seconds = $null; repetition_duration_seconds = $null },
            [ordered]@{ kind = 'time'; enabled = $true; repetition_interval_seconds = 300; repetition_duration_seconds = $null }
        )
        error = ''
    }
    listener = [ordered]@{
        queried = $true; listening = $true; local_address = '127.0.0.1'
        pid = 20796; process_name = 'ssh'; process_started = '2026-10-23 02:35:56'; error = ''
        parent_pid = 43668; parent_process_name = 'powershell'
        parent_command_line = 'powershell.exe -NoProfile -File C:\Padiem\com2_mesh_tunnel_supervisor.ps1 -Config C:\Padiem\com2-mesh-config.json'
        parent_error = ''
    }
    mesh_http = [ordered]@{ queried = $true; code = 200; error = '' }
}
$probeNow = [datetime]'2026-10-23 03:00:00'
$probeRecord = Test-AutostartEvidence -Observation $observation -Cfg $cfg -Now $probeNow
Assert-Equal -Expected 'failed' -Actual $probeRecord.auto_start_state -Label 'probe keeps the refusal failure'
Assert-Equal -Expected 1 -Actual @($probeRecord.failed_checks).Count -Label 'probe has exactly one failed check'
Assert-Equal -Expected 'tunnel_task_last_result_ok' -Actual (@($probeRecord.failed_checks) -join ',') -Label 'probe failed check name'
Assert-Equal -Expected 'running_connected' -Actual $probeRecord.supervisor.state -Label 'probe supervisor state'
Assert-Equal -Expected 'confirmed' -Actual $probeRecord.supervisor.identity -Label 'probe supervisor identity'
Assert-Equal -Expected 'suspected_refused_while_running' -Actual $probeRecord.last_start_attempt.outcome -Label 'probe attempt outcome'
Assert-Equal -Expected 'suspected' -Actual $probeRecord.last_start_attempt.confidence -Label 'probe attempt confidence'
Assert-Equal -Expected 2147946720 -Actual $probeRecord.last_start_attempt.result -Label 'probe attempt result'
Assert-Equal -Expected '0x800710E0' -Actual $probeRecord.last_start_attempt.result_hex -Label 'probe attempt hex'
Assert-Equal -Expected '2026-10-23 02:56:56' -Actual $probeRecord.last_start_attempt.run -Label 'probe attempt run time'

# The health monitor consumes the probe through its JSON output.
$recordJsonPath = Join-Path $work 'record.json'
Write-TextFile -Path $recordJsonPath -Text ($probeRecord | ConvertTo-Json -Depth 10 -Compress)
$roundTripped = Get-Content -LiteralPath $recordJsonPath -Raw | ConvertFrom-Json
$e2eStatus = [ordered]@{
    auto_start_state = [string]$roundTripped.auto_start_state
    auto_start_failed_checks = (@($roundTripped.failed_checks) -join ',')
}
Add-AutostartDisplayFields -Status $e2eStatus -Autostart $roundTripped
Assert-Equal -Expected 'failed' -Actual $e2eStatus.auto_start_state -Label 'json round trip keeps the failed state'
Assert-Equal -Expected 'tunnel_task_last_result_ok' -Actual $e2eStatus.auto_start_failed_checks -Label 'json round trip keeps the failed check'
Assert-Equal -Expected 'running_connected' -Actual $e2eStatus.auto_start_supervisor_state -Label 'json round trip supervisor state'
Assert-Equal -Expected 'confirmed' -Actual $e2eStatus.auto_start_supervisor_identity -Label 'json round trip supervisor identity'
Assert-Equal -Expected 'suspected_refused_while_running' -Actual $e2eStatus.auto_start_last_attempt_outcome -Label 'json round trip attempt outcome'
Assert-Equal -Expected 'suspected' -Actual $e2eStatus.auto_start_last_attempt_confidence -Label 'json round trip attempt confidence'
Assert-Equal -Expected '2147946720' -Actual $e2eStatus.auto_start_last_attempt_result -Label 'json round trip attempt result'
Assert-Equal -Expected '0x800710E0' -Actual $e2eStatus.auto_start_last_attempt_result_hex -Label 'json round trip attempt hex'
Assert-Equal -Expected '2026-10-23 02:56:56' -Actual $e2eStatus.auto_start_last_attempt_run -Label 'json round trip attempt run time'
$e2eRows = New-AutostartDisplayRows -Status $e2eStatus
Assert-True -Value ($e2eRows -match "<td class='ok'>running_connected / confirmed</td>") -Label 'json round trip row is ok'
Assert-True -Value ($e2eRows -match 'suspected_refused_while_running / suspected') -Label 'json round trip suspected row'

# --- patch applier -----------------------------------------------------------

Write-Output '-- patch applier'
$fixtureDir = Join-Path $work 'fixture'
New-Item -ItemType Directory -Path $fixtureDir -Force | Out-Null
$fixtureScript = Join-Path $fixtureDir 'com2-mesh-health.ps1'

# The anchors must be byte-identical to the applier's anchors. If the applier
# anchors drift, the applier refuses the fixture and this selftest fails.
$anchorA = @'
$status.auto_start_verified = if ($autostart) { [bool]$autostart.auto_start_verified } else { $false }
$status.auto_start_state = if ($autostart) { [string]$autostart.auto_start_state } else { "unverified" }
$status.auto_start_failed_checks = if ($autostart) { (@($autostart.failed_checks) -join ",") } else { "probe_missing" }
$status.auto_start_unverified_checks = if ($autostart) { (@($autostart.unverified_checks) -join ",") } else { "probe_missing" }
$status.auto_start_probe_ts = if ($autostart) { [string]$autostart.ts } else { "" }
'@

$anchorB = @'
<tr><td>Auto-start verified</td><td class='$autoStartClass'>$($status.auto_start_verified) / $($status.auto_start_state)</td></tr>
<tr><td>Auto-start failed checks</td><td class='$autoStartFailedClass'>$($status.auto_start_failed_checks)</td></tr>
<tr><td>Auto-start unverified checks</td><td class='$autoStartUnverifiedClass'>$($status.auto_start_unverified_checks)</td></tr>
<tr><td>Auto-start probe time</td><td>$($status.auto_start_probe_ts)</td></tr>
'@

$fixtureTemplate = @'
$ErrorActionPreference = "SilentlyContinue"
$base = $PSScriptRoot
$statusPath = Join-Path $base "status.json"
$htmlPath = Join-Path $base "status.html"
$recordPath = Join-Path $base "record.json"

$status = [ordered]@{}
$status.timestamp = "2026-10-23 05:00:00"
$status.auto_start_verified = $false
$status.auto_start_state = "unverified"
$status.auto_start_failed_checks = ""
$status.auto_start_unverified_checks = "probe_not_run"
$status.auto_start_probe_ts = ""
$status.other_field = "kept"

$autostart = $null
if (Test-Path -LiteralPath $recordPath) {
    try { $autostart = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json } catch { $autostart = $null }
}

@@ANCHOR_A@@

$status | ConvertTo-Json -Depth 3 | Set-Content -Path $statusPath -Encoding UTF8

$autoStartClass = if ($status.auto_start_state -eq "verified") { "ok" } elseif ($status.auto_start_state -eq "failed") { "bad" } else { "" }
$autoStartFailedClass = if ([string]$status.auto_start_failed_checks) { "bad" } else { "" }
$autoStartUnverifiedClass = if ([string]$status.auto_start_unverified_checks) { "bad" } else { "" }

$html = @"
<table>
<tr><td>Other</td><td>$($status.other_field)</td></tr>
@@ANCHOR_B@@
</table>
"@
Set-Content -Path $htmlPath -Value $html -Encoding UTF8
'@

$fixtureText = $fixtureTemplate.Replace('@@ANCHOR_A@@', $anchorA).Replace('@@ANCHOR_B@@', $anchorB)
Write-TextFile -Path $fixtureScript -Text $fixtureText
Copy-Item -LiteralPath $DisplayPath -Destination (Join-Path $fixtureDir 'com2_mesh_health_display.ps1')
Copy-Item -LiteralPath $recordJsonPath -Destination (Join-Path $fixtureDir 'record.json')
$fixtureHash = (Get-FileHash -LiteralPath $fixtureScript -Algorithm SHA256).Hash

$dryRun = Invoke-ChildScript -Arguments @('-File', $PatchPath, '-HealthScript', $fixtureScript, '-ExpectedSha256', $fixtureHash)
Assert-Equal -Expected 0 -Actual $dryRun.Exit -Label 'dry run exit'
Assert-True -Value (($dryRun.Output -join ' ') -match 'dry run: no file was changed') -Label 'dry run reports no change'
Assert-Equal -Expected $fixtureHash -Actual (Get-FileHash -LiteralPath $fixtureScript -Algorithm SHA256).Hash -Label 'dry run leaves the file unchanged'

$badHashRun = Invoke-ChildScript -Arguments @('-File', $PatchPath, '-HealthScript', $fixtureScript, '-ExpectedSha256', 'DEADBEEF')
Assert-Equal -Expected 1 -Actual $badHashRun.Exit -Label 'hash mismatch refused'
Assert-True -Value (($badHashRun.Output -join ' ') -match 'base hash mismatch') -Label 'hash mismatch names the reason'
Assert-Equal -Expected $fixtureHash -Actual (Get-FileHash -LiteralPath $fixtureScript -Algorithm SHA256).Hash -Label 'hash mismatch leaves the file unchanged'

$noAnchorDir = Join-Path $work 'no-anchor'
New-Item -ItemType Directory -Path $noAnchorDir -Force | Out-Null
$noAnchorScript = Join-Path $noAnchorDir 'com2-mesh-health.ps1'
Write-TextFile -Path $noAnchorScript -Text '$status = [ordered]@{}'
$noAnchorHash = (Get-FileHash -LiteralPath $noAnchorScript -Algorithm SHA256).Hash
$noAnchorRun = Invoke-ChildScript -Arguments @('-File', $PatchPath, '-HealthScript', $noAnchorScript, '-ExpectedSha256', $noAnchorHash)
Assert-Equal -Expected 1 -Actual $noAnchorRun.Exit -Label 'missing anchor refused'
Assert-True -Value (($noAnchorRun.Output -join ' ') -match 'anchor not found') -Label 'missing anchor names the reason'

$applyRun = Invoke-ChildScript -Arguments @('-File', $PatchPath, '-HealthScript', $fixtureScript, '-ExpectedSha256', $fixtureHash, '-Apply')
Assert-Equal -Expected 0 -Actual $applyRun.Exit -Label 'apply exit'
Assert-True -Value (($applyRun.Output -join ' ') -match 'applied\. backup: ') -Label 'apply reports a backup'
$backup = @(Get-ChildItem -LiteralPath $fixtureDir -Filter 'com2-mesh-health.ps1.bak-*') | Select-Object -First 1
Assert-True -Value ($null -ne $backup) -Label 'backup file exists'
if ($backup) {
    Assert-Equal -Expected $fixtureHash -Actual (Get-FileHash -LiteralPath $backup.FullName -Algorithm SHA256).Hash -Label 'backup is the unpatched base'
}
$patchedHash = (Get-FileHash -LiteralPath $fixtureScript -Algorithm SHA256).Hash
Assert-True -Value ($patchedHash -ne $fixtureHash) -Label 'applied file changed'

$parseErrors = $null
[void][System.Management.Automation.PSParser]::Tokenize([System.IO.File]::ReadAllText($fixtureScript), [ref]$parseErrors)
Assert-Equal -Expected 0 -Actual @($parseErrors).Count -Label 'patched fixture parses'

$runOut = Invoke-ChildScript -Arguments @('-File', $fixtureScript)
Assert-Equal -Expected 0 -Actual $runOut.Exit -Label 'patched fixture runs'
$statusJsonPath = Join-Path $fixtureDir 'status.json'
$htmlOutPath = Join-Path $fixtureDir 'status.html'
Assert-True -Value (Test-Path -LiteralPath $statusJsonPath) -Label 'patched fixture wrote status json'
Assert-True -Value (Test-Path -LiteralPath $htmlOutPath) -Label 'patched fixture wrote html'
$patchedStatus = Get-Content -LiteralPath $statusJsonPath -Raw | ConvertFrom-Json
Assert-Equal -Expected 'failed' -Actual $patchedStatus.auto_start_state -Label 'patched status keeps the failed state'
Assert-Equal -Expected 'tunnel_task_last_result_ok' -Actual $patchedStatus.auto_start_failed_checks -Label 'patched status keeps the failed checks'
Assert-Equal -Expected 'kept' -Actual $patchedStatus.other_field -Label 'patched status keeps unrelated fields'
Assert-Equal -Expected 'running_connected' -Actual $patchedStatus.auto_start_supervisor_state -Label 'patched status supervisor state'
Assert-Equal -Expected 'confirmed' -Actual $patchedStatus.auto_start_supervisor_identity -Label 'patched status supervisor identity'
Assert-Equal -Expected 'suspected_refused_while_running' -Actual $patchedStatus.auto_start_last_attempt_outcome -Label 'patched status attempt outcome'
Assert-Equal -Expected 'suspected' -Actual $patchedStatus.auto_start_last_attempt_confidence -Label 'patched status attempt confidence'
Assert-Equal -Expected '2147946720' -Actual $patchedStatus.auto_start_last_attempt_result -Label 'patched status attempt result'
Assert-Equal -Expected '0x800710E0' -Actual $patchedStatus.auto_start_last_attempt_result_hex -Label 'patched status attempt hex'
Assert-Equal -Expected '2026-10-23 02:56:56' -Actual $patchedStatus.auto_start_last_attempt_run -Label 'patched status attempt run time'
$patchedHtml = Get-Content -LiteralPath $htmlOutPath -Raw
Assert-True -Value ($patchedHtml -match 'Auto-start failed checks') -Label 'patched html keeps the failed checks row'
Assert-True -Value ($patchedHtml -match "<td class='bad'>tunnel_task_last_result_ok</td>") -Label 'patched html shows the failure as bad'
Assert-True -Value ($patchedHtml -match "<td class='ok'>running_connected / confirmed</td>") -Label 'patched html shows the confirmed supervisor'
Assert-True -Value ($patchedHtml -match 'suspected_refused_while_running / suspected') -Label 'patched html shows the suspected outcome'
Assert-True -Value ($patchedHtml -match '2026-10-23 02:56:56 / 2147946720 0x800710E0') -Label 'patched html preserves code and time'

Remove-Item -LiteralPath (Join-Path $fixtureDir 'com2_mesh_health_display.ps1') -Force
Remove-Item -LiteralPath $statusJsonPath -Force
Remove-Item -LiteralPath $htmlOutPath -Force
$nullRunOut = Invoke-ChildScript -Arguments @('-File', $fixtureScript)
Assert-Equal -Expected 0 -Actual $nullRunOut.Exit -Label 'patched fixture runs without the module'
$moduleLessStatus = Get-Content -LiteralPath $statusJsonPath -Raw | ConvertFrom-Json
Assert-Equal -Expected 'failed' -Actual $moduleLessStatus.auto_start_state -Label 'module-less status keeps the failed state'
Assert-True -Value ($null -eq $moduleLessStatus.auto_start_supervisor_state) -Label 'module-less status has no supervisor field'
$moduleLessHtml = Get-Content -LiteralPath $htmlOutPath -Raw
Assert-True -Value ($moduleLessHtml -notmatch 'Supervisor / identity') -Label 'module-less html has no new rows'
Assert-True -Value ($moduleLessHtml -match 'Auto-start failed checks') -Label 'module-less html keeps the old rows'

# --- summary --------------------------------------------------------------

$summary = 'HEALTH DISPLAY SELFTEST PASS={0} FAIL={1} ARTIFACTS={2}' -f $script:Passes, $script:Failures, $work
Write-Output $summary
if ($script:Failures -gt 0) { exit 1 }
if (-not $KeepArtifacts) {
    try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue } catch { }
}
exit 0
