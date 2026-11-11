<#
.SYNOPSIS
  Checks (and optionally sets) the COM2 nightly restart window (#4953, 대표 결정 2026-11-08).
.DESCRIPTION
  Windows applies the restart only OUTSIDE the active-hours window. The platform
  caps that window at 18 hours, so the narrowest restart window is 6 hours; a
  one-hour pin is not a supported setting.

  Expected: active 10:00 -> 04:00 (18h), i.e. an automatic update restart can
  only be planned for 04:00-10:00. Windows Update acts at the first opportunity
  after 04:00, so in practice the restart lands at the start of the window.
  The systemd backup timers (chat 04:20, offsite 05:10) are Persistent=true and
  catch up after the restart; see the 비공개 운영 기록(거버넌스 폴더, 같은 상대 경로), COM2_RESTART_AND_BACKUP_ONE_PAGE_20261108.md.

  A signed-in console session alone would also hold a restart: the reviewed
  policy NoAutoRebootWithLoggedOnUsers must be 0 for the nightly window to take
  effect. Read-only unless -Apply is given.
#>
[CmdletBinding()]
param(
  [int]$StartHour = 10,
  [int]$EndHour = 4,
  [int]$NoAutoRebootWithLoggedOnUsers = 0,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$uxPath = "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
$auPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
$current = Get-ItemProperty -Path $uxPath -ErrorAction SilentlyContinue
$au = Get-ItemProperty -Path $auPath -ErrorAction SilentlyContinue
$start = $null
$end = $null
$loggedOnReboot = $null
if ($null -ne $current) {
  $start = $current.ActiveHoursStart
  $end = $current.ActiveHoursEnd
}
if ($null -ne $au) {
  $loggedOnReboot = $au.NoAutoRebootWithLoggedOnUsers
}

$state = if ($null -eq $start -or $null -eq $end) { "MISSING" }
         elseif ($start -eq $StartHour -and $end -eq $EndHour) { "OK" }
         else { "MISMATCH" }
$policyState = if ($null -eq $loggedOnReboot) { "MISSING" }
               elseif ($loggedOnReboot -eq $NoAutoRebootWithLoggedOnUsers) { "OK" }
               else { "MISMATCH" }
Write-Output ("ACTIVE_HOURS=" + $state + " START=" + $start + " END=" + $end + " EXPECTED=" + $StartHour + "-" + $EndHour)
Write-Output ("NO_AUTO_REBOOT_LOGGED_ON=" + $policyState + " VALUE=" + $loggedOnReboot + " EXPECTED=" + $NoAutoRebootWithLoggedOnUsers)

if ($state -eq "OK" -and $policyState -eq "OK") {
  Write-Output "RESTART_WINDOW=PASS"
  exit 0
}
if (-not $Apply) {
  Write-Output "RESTART_WINDOW_ACTION=SET_REQUIRED (run again with -Apply, then the window applies)"
  exit 1
}
if (-not (Test-Path $uxPath)) { New-Item -Path $uxPath -Force | Out-Null }
New-ItemProperty -Path $uxPath -Name ActiveHoursStart -PropertyType DWord -Value $StartHour -Force | Out-Null
New-ItemProperty -Path $uxPath -Name ActiveHoursEnd -PropertyType DWord -Value $EndHour -Force | Out-Null
if (-not (Test-Path $auPath)) { New-Item -Path $auPath -Force | Out-Null }
New-ItemProperty -Path $auPath -Name NoAutoRebootWithLoggedOnUsers -PropertyType DWord -Value $NoAutoRebootWithLoggedOnUsers -Force | Out-Null
$verify = Get-ItemProperty -Path $uxPath
$verifyAu = Get-ItemProperty -Path $auPath
if ($verify.ActiveHoursStart -eq $StartHour -and $verify.ActiveHoursEnd -eq $EndHour -and
    $verifyAu.NoAutoRebootWithLoggedOnUsers -eq $NoAutoRebootWithLoggedOnUsers) {
  Write-Output "RESTART_WINDOW=PASS"
  exit 0
}
Write-Output "RESTART_WINDOW=FAIL reason=write_not_visible"
exit 3
