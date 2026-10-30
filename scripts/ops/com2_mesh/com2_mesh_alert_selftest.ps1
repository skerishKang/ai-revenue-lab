$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'com2-mesh-alert.ps1') -FunctionsOnly
$now = [datetime]'2026-10-30 12:00:00'
function Assert-Health($status, [bool]$expected, [string]$label) {
    $actual = Test-RemoteRecoveryHealth -Status $status -Now $now
    if ($actual -ne $expected) { throw "$label expected $expected got $actual" }
}
$ok = [pscustomobject]@{ ts='2026-10-30 11:59:59'; class='healthy'; remote_ok=$true; remote_http='200' }
Assert-Health $ok $true 'remote healthy'
Assert-Health $null $false 'missing'
Assert-Health ([pscustomobject]@{ts='2026-10-30 11:40:00'; class='healthy'; remote_ok=$true; remote_http='200'}) $false 'stale'
Assert-Health ([pscustomobject]@{ts='2026-10-30 11:59:59'; class='remote_probe_failed'; remote_ok=$false; remote_http='000'}) $false 'probe failure'
Assert-Health ([pscustomobject]@{ts='2026-10-30 11:59:59'; class='com2_mesh_down'; remote_ok=$true; remote_http='503'}) $false 'HTTP 503'
Assert-Health ([pscustomobject]@{ts='2026-10-30 12:05:00'; class='healthy'; remote_ok=$true; remote_http='200'}) $false 'future'
Write-Output 'ALERT SELFTEST PASS=6 FAIL=0'
