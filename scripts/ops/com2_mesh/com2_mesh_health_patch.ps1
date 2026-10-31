<#
.SYNOPSIS
  Hash-guarded patch applier for the out-of-repo COM2 Mesh health monitor.

.DESCRIPTION
  Adds the auto-start supervisor / last-start-attempt display to
  com2-mesh-health.ps1 by replacing two anchor blocks:

  - the auto-start status copy block: loads com2_mesh_health_display.ps1 from
    the same directory and calls Add-AutostartDisplayFields after the existing
    assignments, so the existing verdict fields are copied unchanged first;
  - the auto-start HTML rows: appends New-AutostartDisplayRows after the four
    existing rows.

  Both replacements are inert when the display module is not present next to
  the health script: the status copy block keeps its original assignments and
  the HTML keeps its original rows.

  Safety contract:

  - Dry run by default. -Apply writes the file only after a timestamped backup.
  - Refuses to run when the file SHA256 does not match -ExpectedSha256
    (default: the 2026-10-23 deployed base) or when an anchor is missing or
    occurs more than once.
  - Never starts, stops, restarts or schedules anything, and never touches any
    other file. Deploying com2_mesh_health_display.ps1 next to the health
    script is a separate manual step.

.PARAMETER HealthScript
  Path to com2-mesh-health.ps1.

.PARAMETER ExpectedSha256
  Required SHA256 of the file before patching.

.PARAMETER Apply
  Write the patched file. Without it the script only reports what it would do.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_health_patch.ps1 -HealthScript <path>
  powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_health_patch.ps1 -HealthScript <path> -Apply
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$HealthScript,
    [string]$ExpectedSha256 = '44914F0CBB142CA71596A0D0368B0B797C547B1389C4211FC0C2169DCFE737F5',
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $HealthScript)) {
    [Console]::Error.WriteLine(('health script not found: {0}' -f $HealthScript))
    exit 1
}

$actualHash = (Get-FileHash -LiteralPath $HealthScript -Algorithm SHA256).Hash.ToUpperInvariant()
$expectedHash = $ExpectedSha256.ToUpperInvariant()
if ($actualHash -ne $expectedHash) {
    [Console]::Error.WriteLine(('base hash mismatch: expected {0} actual {1}' -f $expectedHash, $actualHash))
    exit 1
}

$raw = [System.IO.File]::ReadAllText($HealthScript)
$usesCrLf = $raw.Contains("`r`n")
$text = $raw.Replace("`r`n", "`n")

$anchorA = @'
$status.auto_start_verified = if ($autostart) { [bool]$autostart.auto_start_verified } else { $false }
$status.auto_start_state = if ($autostart) { [string]$autostart.auto_start_state } else { "unverified" }
$status.auto_start_failed_checks = if ($autostart) { (@($autostart.failed_checks) -join ",") } else { "probe_missing" }
$status.auto_start_unverified_checks = if ($autostart) { (@($autostart.unverified_checks) -join ",") } else { "probe_missing" }
$status.auto_start_probe_ts = if ($autostart) { [string]$autostart.ts } else { "" }
'@.Replace("`r`n", "`n")

$replaceA = @'
$autostartDisplayOk = $false
$displayModule = Join-Path $base "com2_mesh_health_display.ps1"
if (Test-Path -LiteralPath $displayModule) {
    . $displayModule
    $autostartDisplayOk = $true
}
$status.auto_start_verified = if ($autostart) { [bool]$autostart.auto_start_verified } else { $false }
$status.auto_start_state = if ($autostart) { [string]$autostart.auto_start_state } else { "unverified" }
$status.auto_start_failed_checks = if ($autostart) { (@($autostart.failed_checks) -join ",") } else { "probe_missing" }
$status.auto_start_unverified_checks = if ($autostart) { (@($autostart.unverified_checks) -join ",") } else { "probe_missing" }
$status.auto_start_probe_ts = if ($autostart) { [string]$autostart.ts } else { "" }
if ($autostartDisplayOk) { Add-AutostartDisplayFields -Status $status -Autostart $autostart }
'@.Replace("`r`n", "`n")

$anchorB = @'
<tr><td>Auto-start verified</td><td class='$autoStartClass'>$($status.auto_start_verified) / $($status.auto_start_state)</td></tr>
<tr><td>Auto-start failed checks</td><td class='$autoStartFailedClass'>$($status.auto_start_failed_checks)</td></tr>
<tr><td>Auto-start unverified checks</td><td class='$autoStartUnverifiedClass'>$($status.auto_start_unverified_checks)</td></tr>
<tr><td>Auto-start probe time</td><td>$($status.auto_start_probe_ts)</td></tr>
'@.Replace("`r`n", "`n")

$replaceB = $anchorB + "`n" + '$(if ($autostartDisplayOk) { New-AutostartDisplayRows -Status $status })'

function Test-SingleOccurrence {
    param([string]$Haystack, [string]$Needle, [string]$Label)
    $first = $Haystack.IndexOf($Needle, [System.StringComparison]::Ordinal)
    if ($first -lt 0) { throw ('anchor not found: {0}' -f $Label) }
    $second = $Haystack.IndexOf($Needle, $first + 1, [System.StringComparison]::Ordinal)
    if ($second -ge 0) { throw ('anchor is ambiguous: {0}' -f $Label) }
    return $first
}

try {
    $posA = Test-SingleOccurrence -Haystack $text -Needle $anchorA -Label 'autostart status copy block'
    $posB = Test-SingleOccurrence -Haystack $text -Needle $anchorB -Label 'autostart html rows'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}

$patched = $text.Replace($anchorA, $replaceA).Replace($anchorB, $replaceB)
$lineA = ($text.Substring(0, $posA) -split "`n").Count
$lineB = ($text.Substring(0, $posB) -split "`n").Count
$addedA = ($replaceA -split "`n").Count - ($anchorA -split "`n").Count
$addedB = ($replaceB -split "`n").Count - ($anchorB -split "`n").Count

Write-Output ('base sha256: {0}' -f $actualHash)
Write-Output ('anchor A at line {0}: +{1} lines (display module load and field copy)' -f $lineA, $addedA)
Write-Output ('anchor B at line {0}: +{1} lines (html rows)' -f $lineB, $addedB)
Write-Output 'reminder: com2_mesh_health_display.ps1 must sit next to the health script; without it the patched script behaves exactly as before'

if (-not $Apply) {
    Write-Output 'dry run: no file was changed'
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = $HealthScript + '.bak-' + $stamp
Copy-Item -LiteralPath $HealthScript -Destination $backupPath
$outText = if ($usesCrLf) { $patched.Replace("`n", "`r`n") } else { $patched }
[System.IO.File]::WriteAllText($HealthScript, $outText, (New-Object System.Text.UTF8Encoding($false)))
$newHash = (Get-FileHash -LiteralPath $HealthScript -Algorithm SHA256).Hash.ToUpperInvariant()
Write-Output ('applied. backup: {0}' -f $backupPath)
Write-Output ('new sha256: {0}' -f $newHash)
exit 0
