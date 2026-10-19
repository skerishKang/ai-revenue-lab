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
$sourceRunner = Join-Path $PSScriptRoot 'run_grafana_com1_backup.ps1'
if (!(Test-Path -LiteralPath $sourceRunner)) { throw 'BACKUP_RUNNER_NOT_FOUND' }
# Install into a stable COM1 user directory. Deleting a Git worktree cannot
# silently break an operating backup schedule.
$installedDir = Join-Path $env:LOCALAPPDATA 'PADIEM\GrafanaLogs\bin'
New-Item -ItemType Directory -Force -Path $installedDir | Out-Null
Copy-Item -LiteralPath $script -Destination (Join-Path $installedDir 'grafana_com1_backup.py') -Force
Copy-Item -LiteralPath $sourceRunner -Destination (Join-Path $installedDir 'run_grafana_com1_backup.ps1') -Force
# A no-spaces powershell.exe launcher avoids quoting native executable paths.
$runner = Join-Path $installedDir 'run_grafana_com1_backup.ps1'
$taskCommand = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' + $runner
# Every 15 minutes without finite duration, current Windows interactive user.
& schtasks.exe /Create /TN $taskName /TR $taskCommand /SC MINUTE /MO 15 /IT /F *> $null
if ($LASTEXITCODE -ne 0) {
    throw ('COM1_BACKUP_SCHEDULE_REGISTER_FAILED_' + $LASTEXITCODE)
}
Write-Output ('COM1_BACKUP_SCHEDULED task='+$taskName+' interval=15m mode=interactive-user')