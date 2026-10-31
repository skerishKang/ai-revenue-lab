param([switch]$FunctionsOnly)
$ErrorActionPreference = "SilentlyContinue"

function Test-RemoteRecoveryHealth {
    param($Status, [datetime]$Now = (Get-Date))
    if (-not $Status) { return $false }
    $ts = [datetime]::MinValue
    if (-not [datetime]::TryParse([string]$Status.ts, [ref]$ts)) { return $false }
    $age = ($Now - $ts).TotalSeconds
    if ($age -lt -60 -or $age -gt 900) { return $false }
    return ($Status.class -eq 'healthy' -and $Status.remote_ok -eq $true -and [string]$Status.remote_http -eq '200')
}
if ($FunctionsOnly) { return }

$configPath = Join-Path $PSScriptRoot "com2-mesh-config.json"
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$statusPath = [string]$config.status_file
$statePath = (Join-Path $PSScriptRoot "com2-mesh-alert-state.json")
$logPath = (Join-Path $PSScriptRoot "com2-mesh-alert.log")
$pendingPath = (Join-Path $PSScriptRoot "com2-mesh-alert-pending.txt")
$msgPath = (Join-Path $PSScriptRoot "com2-mesh-alert-message.txt")
$notifier = (Join-Path $PSScriptRoot "com2-mesh-notifier.cmd")

$status = $null
if ($statusPath -and (Test-Path -LiteralPath $statusPath)) {
    try { $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json } catch {}
}
$now = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$healthy = Test-RemoteRecoveryHealth -Status $status

$prev = $null
if (Test-Path $statePath) { try { $prev = Get-Content $statePath -Raw | ConvertFrom-Json } catch {} }
$lastHealth = if ($prev) { $prev.last_health } else { $null }
$lastAlertType = if ($prev) { $prev.last_alert_type } else { "" }
$lastAlertTime = if ($prev) { $prev.last_alert_time } else { "" }
$lastNormalTime = if ($prev) { $prev.last_normal_time } else { "" }

$failed = @()
if (-not $healthy) { $failed += 'COM2 remote recovery health unavailable or unhealthy' }
$failedStr = if ($failed.Count -gt 0) { $failed -join ", " } else { "" }

$shouldAlert = $false
$alertType = ""
if ($healthy) {
    if ($lastHealth -eq $false) { $alertType = "RECOVERY"; $shouldAlert = $true }
    $lastNormalTime = $now
} else {
    if ($lastHealth -ne $false) { $alertType = "FAULT"; $shouldAlert = $true }
    else {
        $cooldownOk = $true
        if ($lastAlertType -eq "FAULT" -and $lastAlertTime) {
            try {
                $last = [DateTime]::Parse($lastAlertTime)
                if (((Get-Date) - $last).TotalMinutes -lt 30) { $cooldownOk = $false }
            } catch { $cooldownOk = $true }
        }
        if ($cooldownOk) { $alertType = "FAULT"; $shouldAlert = $true }
    }
}

if ($shouldAlert) {
    $msg = "Target: COM2 Mesh (K_LIPVOICE)" + "`n" + "Type: " + $alertType + "`n" + "Check time: " + $now + "`n" + "Failed checks: " + $failedStr + "`n" + "Last normal: " + $lastNormalTime + "`n" + "Status screen: $statusPath"
    $msg | Set-Content -Path $msgPath -Encoding UTF8
    $delivered = $false
    if (Test-Path $notifier) {
        try {
            $p = Start-Process -FilePath $notifier -ArgumentList "`"$msgPath`"" -Wait -PassThru -WindowStyle Hidden
            if ($p.ExitCode -eq 0) { $delivered = $true }
        } catch { $delivered = $false }
    }
# Local toast notification (always available)
try {
    $toastMsg = $msg -replace "`n", " | "
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $env:USERPROFILE "toast-notification.ps1") -Title "COM2 Mesh Alert" -Message $toastMsg | Out-Null
} catch {}
    if (-not $delivered) {
        $msg | Set-Content -Path $pendingPath -Encoding UTF8
    } else {
        if (Test-Path $pendingPath) { Remove-Item $pendingPath -Force }
    }
    "$now $alertType delivered=$delivered :: $msg" | Add-Content -Path $logPath -Encoding UTF8
    $lastAlertType = $alertType
    $lastAlertTime = $now
}

$state = [ordered]@{
    last_health = $healthy
    last_check = $now
    last_alert_type = $lastAlertType
    last_alert_time = $lastAlertTime
    last_normal_time = $lastNormalTime
    last_failed = $failedStr
}
$state | ConvertTo-Json -Depth 3 | Set-Content -Path $statePath -Encoding UTF8
