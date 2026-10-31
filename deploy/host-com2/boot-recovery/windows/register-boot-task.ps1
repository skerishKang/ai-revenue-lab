<#
.SYNOPSIS
  Registers the COM2 boot task that starts WSL and runs the boot self-check
  without a user logon (#4953). DRY-RUN unless -Apply is given.
.DESCRIPTION
  AtStartup trigger, SYSTEM/service-account principal. The task only starts WSL
  and the self-check; it never starts, stops or restarts a PADIEM service — the
  distro's systemd units are enabled and handle themselves.
.PARAMETER Distro
  WSL distribution name shown by `wsl.exe -l -v`.
.PARAMETER Script
  Absolute path inside the distro (installed by the WSL-side install.sh).
#>
[CmdletBinding()]
param(
  [string]$TaskName = "PadiemBootRecovery",
  [string]$Distro = "Ubuntu",
  [string]$WslUser = "root",
  [string]$Script = "/opt/padiem/boot-recovery/boot-recovery.sh",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$wsl = Join-Path $env:SystemRoot "System32\wsl.exe"
if (-not (Test-Path $wsl)) {
  Write-Output "BOOT_TASK=FAIL reason=wsl_missing"
  exit 2
}

$arguments = "-d `"$Distro`" -u $WslUser --exec /bin/bash -lc `"$Script`""
$action = New-ScheduledTaskAction -Execute $wsl -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 2) `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

if (-not $Apply) {
  Write-Output "BOOT_TASK=DRY_RUN"
  Write-Output ("ACTION=" + $wsl + " " + $arguments)
  Write-Output "TRIGGER=AtStartup"
  Write-Output "PRINCIPAL=SYSTEM RUN_LEVEL=Highest NO_USER_LOGON=true"
  Write-Output "RESTART=3x2m START_IF_ON_BATTERIES=true"
  exit 0
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq "Running") {
  Write-Output "BOOT_TASK=FAIL reason=task_running"
  exit 3
}
Register-ScheduledTask -TaskName $TaskName `
  -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
  -Description "PADIEM COM2 boot recovery: start WSL and run the boot self-check without a user logon (#4953)" `
  -Force | Out-Null
$task = Get-ScheduledTask -TaskName $TaskName
Write-Output ("BOOT_TASK=PASS NAME=" + $task.TaskName + " STATE=" + $task.State)
Write-Output "NEXT=reboot in an approved window, then journalctl -u padiem-boot-recovery.service -n 40"
