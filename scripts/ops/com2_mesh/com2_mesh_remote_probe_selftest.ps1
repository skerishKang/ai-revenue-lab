$ErrorActionPreference = 'Stop'
$work = Join-Path $env:TEMP ('mesh-remote-probe-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Copy-Item (Join-Path $PSScriptRoot 'com2_mesh_autostart.ps1') (Join-Path $work 'com2_mesh_autostart.ps1')
    $fake = @'
param([switch]$FunctionsOnly)
function Get-Config { param($Path) return @{ path=$Path } }
function Invoke-RemoteProbe { param($Cfg) return @{ ok=$true; http='200' } }
if ($FunctionsOnly) { return }
'@
    Set-Content (Join-Path $work 'com2_mesh_recovery.ps1') $fake -Encoding UTF8
    . (Join-Path $work 'com2_mesh_autostart.ps1') -FunctionsOnly
    $r = Get-RemoteHttpObservation -ConfigPath 'test-config'
    if (-not $r.queried -or $r.code -ne 200) { throw 'remote success failed' }
    Remove-Item (Join-Path $work 'com2_mesh_recovery.ps1')
    $r = Get-RemoteHttpObservation -ConfigPath 'test-config'
    if ($r.queried -or $r.code -ne 0) { throw 'missing recovery was not unverified' }
    Write-Output 'REMOTE PROBE SELFTEST PASS=2 FAIL=0'
} finally { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
