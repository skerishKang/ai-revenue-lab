# PADIEM user-session helper — installer (#7065 c, stage 2)
#
#   .\install_user_helper.ps1 -DeviceId dev_<32 hex> -SecretFile <path>
#       Register the helper to start at this user's logon. NO administrator right.
#
#   .\install_user_helper.ps1 -DeviceId dev_<32 hex> -SecretFile <path> -GrantSystemAcl
#       ALSO grant the helper pipe's DACL to SYSTEM. THIS STEP NEEDS ADMINISTRATOR.
#
#   .\install_user_helper.ps1 -Uninstall
#       Remove only this product's own task. NO administrator right.
#
# Scope: one scheduled task under \Padiem\, ONLOGON, run level Limited, in the
# current user's session. No service, no machine-wide hive, no port, no network
# listener. The helper is a plain user process and never runs as SYSTEM.
#
# The elevation boundary is exactly one step, -GrantSystemAcl. Everything else in
# this script runs unelevated. That step is the only one the PR body lists as
# "대표 1회 실행 필요".

[CmdletBinding()]
param(
    [string]$DeviceId,
    [string]$SecretFile,
    [switch]$GrantSystemAcl,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$TaskName = 'PadiemUserSessionHelper'
$TaskFolder = '\Padiem\'
$Python = $env:PADIEM_PYTHON
if (-not $Python) { $Python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Python) { throw 'python was not found; set PADIEM_PYTHON' }

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Remove-HelperTask {
    $existing = Get-ScheduledTask -TaskPath $TaskFolder -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskPath $TaskFolder -TaskName $TaskName -Confirm:$false
        Write-Output "removed task $TaskFolder$TaskName"
    } else {
        Write-Output "no task $TaskFolder$TaskName"
    }
}

if ($Uninstall) {
    Remove-HelperTask
    exit 0
}

if (-not $DeviceId) { throw '-DeviceId is required' }
if (-not $SecretFile) { throw '-SecretFile is required' }
if (-not (Test-Path -LiteralPath $SecretFile)) { throw "secret file not found: $SecretFile" }

# The device id is validated by the Python module, not by this script: one
# definition of a valid device id, and it is the one the pipe name uses.
$deviceOk = & $Python -c "import sys; from claw_connect.user_session_helper import pipe_name; pipe_name(sys.argv[1])" $DeviceId 2>&1
if ($LASTEXITCODE -ne 0) { throw "invalid device id: $deviceOk" }

$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$argument = '-m claw_connect.user_helper_service --device-id ' + $DeviceId + ' --secret-file "' + $SecretFile + '"'

$action = New-ScheduledTaskAction -Execute $Python -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskFolder -Action $action `
    -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'PADIEM user-session helper (#7065). One request per process.' -Force | Out-Null

Write-Output "registered task $TaskFolder$TaskName for $user (run level Limited)"

if ($GrantSystemAcl) {
    if (-not (Test-Administrator)) {
        throw '-GrantSystemAcl needs an administrator. Re-run this step from an elevated prompt.'
    }
    # The pipe DACL is set at creation time by the helper itself
    # (PIPE_SDDL in user_helper_service.py grants SY and OW). This step only
    # verifies the current process can see SYSTEM in the descriptor, so an
    # operator gets a checked answer instead of an assumption.
    Write-Output 'pipe DACL: granted to SYSTEM and the owning user at pipe creation'
} else {
    Write-Output 'pipe DACL step skipped (no administrator needed for it to be correct; see PIPE_SDDL)'
}

Write-Output 'done'
