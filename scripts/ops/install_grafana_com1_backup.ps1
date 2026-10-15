# COM1 Windows Task Scheduler for independent Grafana Loki -> local SQLite backup.
# Prerequisite: separate logs:read token stored using DPAPI for CURRENT Windows user.
# Run interactively on COM1 after creating read-only Grafana Access Policy.
[CmdletBinding()]
param([switch]$InitializeSecret,[switch]$Remove)
$ErrorActionPreference = 'Stop'
$taskName = 'PADIEM-Grafana-Logs-COM1-Backup'
$secretDir = Join-Path $env:LOCALAPPDATA 'PADIEM\secrets'
$secretPath = Join-Path $secretDir 'grafana-loki-read.dpapi'
if ($InitializeSecret) {
    New-Item -ItemType Directory -Force -Path $secretDir | Out-Null
    # Console handles the token; it never appears in a command argument or transcript.
    $token = Read-Host -AsSecureString 'Grafana logs:read token (not displayed)'
    $token | ConvertFrom-SecureString | Set-Content -LiteralPath $secretPath -NoNewline
    Write-Output 'COM1_READ_SECRET_STORED_DPAPI'
}
if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output 'COM1_BACKUP_SCHEDULE_REMOVED'
    exit 0
}
if (!(Test-Path -LiteralPath $secretPath)) {
    Write-Output 'NOT_ACTIVATED: create a distinct logs:read token and initialize local DPAPI secret first'
    exit 2
}
$script = Join-Path $PSScriptRoot 'grafana_com1_backup.py'
if (!(Test-Path -LiteralPath $script)) { throw 'ARCHIVE_SCRIPT_NOT_FOUND' }
$python = (Get-Command python -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $python -Argument ('"'+$script+'"') -WorkingDirectory $PSScriptRoot
# Repeat every 15 min, refreshed daily. No Windows service/extra cloud compute.
$trigger = New-ScheduledTaskTrigger -Daily -At 00:00
$trigger.Repetition.Interval = 'PT15M'
$trigger.Repetition.Duration = 'P1D'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Output ('COM1_BACKUP_SCHEDULED task='+$taskName+' interval=15m')