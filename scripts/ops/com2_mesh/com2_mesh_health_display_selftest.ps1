<#
.SYNOPSIS
  Fixture-driven selftest for com2_mesh_health_display.ps1 and
  com2_mesh_health_patch.ps1.

.DESCRIPTION
  Evaluates recorded probe output only. It never queries the host, never
  starts or stops a process, and never touches the deployed health script.

  It verifies:

  - Add-AutostartDisplayFields renders the per-check verdict detail of a
    com2_mesh_autostart.ps1 record without touching the verdict fields, maps
    an old-schema record to not_reported and a missing record to probe_not_run;
  - end to end from com2_mesh_autostart.ps1: a failed auto-start record keeps
    auto_start_state=failed and the failed check visible while the detail row
    lists every check verdict in the recorded order;
  - com2_mesh_health_patch.ps1: dry run leaves the file unchanged, a hash
    mismatch or a missing anchor is refused, and an applied patch produces a
    parsing script whose status and HTML keep the existing failure rows and
    add the new display row. Without the display module next to the script
    the patched file behaves exactly as before.

  The supervisor and last-start-attempt display was removed with #5643 together
  with the record fields it rendered; the selftest asserts its absence.

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

# --- field copy contract ----------------------------------------------------

Write-Output '-- field copy contract'
$fullRecord = [pscustomobject]@{
    auto_start_state = 'failed'
    failed_checks = @('mesh_agent_running_since_boot')
    checks = @(
        [pscustomobject]@{ name = 'boot_time_observed'; ok = $true }
        [pscustomobject]@{ name = 'mesh_agent_service_automatic'; ok = $true }
        [pscustomobject]@{ name = 'mesh_agent_running'; ok = $true }
        [pscustomobject]@{ name = 'mesh_agent_running_since_boot'; ok = $false }
        [pscustomobject]@{ name = 'mesh_http_200'; ok = $true }
    )
}
$fullStatus = [ordered]@{
    auto_start_state = 'failed'
    auto_start_failed_checks = 'mesh_agent_running_since_boot'
}
Add-AutostartDisplayFields -Status $fullStatus -Autostart $fullRecord
Assert-Equal -Expected 'failed' -Actual $fullStatus.auto_start_state -Label 'module keeps the verdict state'
Assert-Equal -Expected 'mesh_agent_running_since_boot' -Actual $fullStatus.auto_start_failed_checks -Label 'module keeps the failed checks'
Assert-Equal -Expected ('boot_time_observed=true; mesh_agent_service_automatic=true; mesh_agent_running=true; ' +
    'mesh_agent_running_since_boot=false; mesh_http_200=true') -Actual $fullStatus.auto_start_checks_detail `
    -Label 'per-check detail is rendered in the recorded order'

$fullRows = New-AutostartDisplayRows -Status $fullStatus
Assert-True -Value ($fullRows -match 'Auto-start checks \(per-check verdict\)') -Label 'detail row is present'
Assert-True -Value ($fullRows -match 'mesh_agent_running_since_boot=false') -Label 'failed check appears in the detail row'
Assert-True -Value ($fullRows -notmatch 'Supervisor / identity') -Label 'supervisor row is retired'
Assert-True -Value ($fullRows -notmatch 'Last start attempt') -Label 'attempt row is retired'

$oldStatus = [ordered]@{ auto_start_state = 'failed' }
Add-AutostartDisplayFields -Status $oldStatus -Autostart ([pscustomobject]@{ auto_start_state = 'failed' })
Assert-Equal -Expected 'not_reported' -Actual $oldStatus.auto_start_checks_detail -Label 'old schema detail is not_reported'
$oldRows = New-AutostartDisplayRows -Status $oldStatus
Assert-True -Value ($oldRows -match 'not_reported') -Label 'old schema renders as not_reported'
Assert-True -Value ($oldRows -notmatch "<td class='ok'>") -Label 'old schema has no ok row'

$nullStatus = [ordered]@{ auto_start_state = 'unverified' }
Add-AutostartDisplayFields -Status $nullStatus -Autostart $null
Assert-Equal -Expected 'probe_not_run' -Actual $nullStatus.auto_start_checks_detail -Label 'missing record is probe_not_run'

# --- probe end to end -------------------------------------------------------

Write-Output '-- probe end to end'
$cfgObject = [ordered]@{
    com2_host = '192.0.2.10'
    mesh_url = 'https://192.0.2.10:4443/'
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
        process_name = 'MeshAgent'; process_started = '2026-10-23 00:20:00'; error = ''
    }
    mesh_http = [ordered]@{ queried = $true; code = 200; error = '' }
}
$probeNow = [datetime]'2026-10-23 03:00:00'
$probeRecord = Test-AutostartEvidence -Observation $observation -Cfg $cfg -Now $probeNow
Assert-Equal -Expected 'failed' -Actual $probeRecord.auto_start_state -Label 'probe keeps the failed verdict'
Assert-Equal -Expected 1 -Actual @($probeRecord.failed_checks).Count -Label 'probe has exactly one failed check'
Assert-Equal -Expected 'mesh_agent_running_since_boot' -Actual (@($probeRecord.failed_checks) -join ',') -Label 'probe failed check name'
Assert-True -Value ($null -eq $probeRecord.supervisor) -Label 'probe record has no supervisor block'
Assert-True -Value ($null -eq $probeRecord.last_start_attempt) -Label 'probe record has no last_start_attempt block'

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
Assert-Equal -Expected 'mesh_agent_running_since_boot' -Actual $e2eStatus.auto_start_failed_checks -Label 'json round trip keeps the failed check'
Assert-True -Value ($e2eStatus.auto_start_checks_detail -match 'mesh_agent_running_since_boot=false') `
    -Label 'json round trip keeps the failed check in the detail row'
Assert-True -Value ($e2eStatus.auto_start_checks_detail -match 'mesh_http_200=true') `
    -Label 'json round trip keeps the passing checks in the detail row'
$e2eRows = New-AutostartDisplayRows -Status $e2eStatus
Assert-True -Value ($e2eRows -match 'mesh_agent_running_since_boot=false') -Label 'json round trip detail row shows the failure'

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
Assert-Equal -Expected 'mesh_agent_running_since_boot' -Actual $patchedStatus.auto_start_failed_checks -Label 'patched status keeps the failed checks'
Assert-Equal -Expected 'kept' -Actual $patchedStatus.other_field -Label 'patched status keeps unrelated fields'
Assert-True -Value ([string]$patchedStatus.auto_start_checks_detail -match 'mesh_agent_running_since_boot=false') `
    -Label 'patched status carries the per-check detail'
$patchedHtml = Get-Content -LiteralPath $htmlOutPath -Raw
Assert-True -Value ($patchedHtml -match 'Auto-start failed checks') -Label 'patched html keeps the failed checks row'
Assert-True -Value ($patchedHtml -match "<td class='bad'>mesh_agent_running_since_boot</td>") -Label 'patched html shows the failure as bad'
Assert-True -Value ($patchedHtml -match 'mesh_agent_running_since_boot=false') -Label 'patched html shows the per-check detail row'

Remove-Item -LiteralPath (Join-Path $fixtureDir 'com2_mesh_health_display.ps1') -Force
Remove-Item -LiteralPath $statusJsonPath -Force
Remove-Item -LiteralPath $htmlOutPath -Force
$nullRunOut = Invoke-ChildScript -Arguments @('-File', $fixtureScript)
Assert-Equal -Expected 0 -Actual $nullRunOut.Exit -Label 'patched fixture runs without the module'
$moduleLessStatus = Get-Content -LiteralPath $statusJsonPath -Raw | ConvertFrom-Json
Assert-Equal -Expected 'failed' -Actual $moduleLessStatus.auto_start_state -Label 'module-less status keeps the failed state'
Assert-True -Value ($null -eq $moduleLessStatus.auto_start_checks_detail) -Label 'module-less status has no detail field'
$moduleLessHtml = Get-Content -LiteralPath $htmlOutPath -Raw
Assert-True -Value ($moduleLessHtml -notmatch 'per-check verdict') -Label 'module-less html has no new row'
Assert-True -Value ($moduleLessHtml -match 'Auto-start failed checks') -Label 'module-less html keeps the old rows'

# --- summary --------------------------------------------------------------

$summary = 'HEALTH DISPLAY SELFTEST PASS={0} FAIL={1} ARTIFACTS={2}' -f $script:Passes, $script:Failures, $work
Write-Output $summary
if ($script:Failures -gt 0) { exit 1 }
if (-not $KeepArtifacts) {
    try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue } catch { }
}
exit 0
