<#
.SYNOPSIS
  Checks (and optionally sets) the Windows Update active-hours window (#4953).
.DESCRIPTION
  Default expectation: active 00:00–18:00, so an automatic restart can only be
  planned for 18:00–24:00 — away from the nightly SQLite backups (04:10–05:10)
  and the offsite upload (05:10). Read-only unless -Apply is given.
#>
[CmdletBinding()]
param(
  [int]$StartHour = 0,
  [int]$EndHour = 18,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$path = "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
$current = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue
$start = $null
$end = $null
if ($null -ne $current) {
  $start = $current.ActiveHoursStart
  $end = $current.ActiveHoursEnd
}

$state = if ($null -eq $start -or $null -eq $end) { "MISSING" }
         elseif ($start -eq $StartHour -and $end -eq $EndHour) { "OK" }
         else { "MISMATCH" }
Write-Output ("ACTIVE_HOURS=" + $state + " START=" + $start + " END=" + $end + " EXPECTED=" + $StartHour + "-" + $EndHour)

if ($state -eq "OK") { exit 0 }
if (-not $Apply) {
  Write-Output "ACTIVE_HOURS_ACTION=SET_REQUIRED (run again with -Apply, then reboot window applies)"
  exit 1
}
if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
New-ItemProperty -Path $path -Name ActiveHoursStart -PropertyType DWord -Value $StartHour -Force | Out-Null
New-ItemProperty -Path $path -Name ActiveHoursEnd -PropertyType DWord -Value $EndHour -Force | Out-Null
$verify = Get-ItemProperty -Path $path
if ($verify.ActiveHoursStart -eq $StartHour -and $verify.ActiveHoursEnd -eq $EndHour) {
  Write-Output "ACTIVE_HOURS=PASS"
  exit 0
}
Write-Output "ACTIVE_HOURS=FAIL reason=write_not_visible"
exit 3
