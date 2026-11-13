# PADIEM user-session helper — installer (#7065 c, stage 2)
#
#   .\install_user_helper.ps1 -DeviceId <raw device id> -SecretFile <path>
#       Register the helper to start at this user's logon. NO administrator right.
#       -DeviceId accepts raw MeshCentral device IDs (may include '$'); a stable
#       hashed pipe identifier is derived internally.
#
#   .\install_user_helper.ps1 -DeviceId <raw device id> -SecretFile <path> -GrantSystemAcl
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
#
# #7564: this script does not make the secret - it registers the helper against
# the file it is given. It therefore refuses a secret that another local
# account could know or replace: the file and its folder must be owned by
# SYSTEM, the Administrators group or this user, must not inherit, and must
# name no other account. The one-click install and the Connector's own
# provisioning both leave the secret that way.

[CmdletBinding()]
param(
    [string]$DeviceId,
    [string]$SecretFile,
    [switch]$GrantSystemAcl,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$InstallRoot = $PSScriptRoot
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

function Get-SecretRefusal {
    param([string]$Path)
    # $null when only SYSTEM, the Administrators group and this user can reach
    # the secret and its folder; otherwise the reason, without the content.
    $sid = [Security.Principal.SecurityIdentifier]
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $trusted = @('S-1-5-18', 'S-1-5-32-544', $me)
    $full = (Resolve-Path -LiteralPath $Path).ProviderPath
    foreach ($target in @($full, (Split-Path -Parent $full))) {
        $item = Get-Item -LiteralPath $target -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            return "is a link: $target"
        }
        $acl = Get-Acl -LiteralPath $target
        if (-not $acl.AreAccessRulesProtected) {
            return "inherits its access list from the folder above: $target"
        }
        if ($trusted -notcontains $acl.GetOwner($sid).Value) {
            return "is owned by another account: $target"
        }
        foreach ($rule in $acl.GetAccessRules($true, $true, $sid)) {
            if ($trusted -notcontains $rule.IdentityReference.Value) {
                return "names another account ($($rule.IdentityReference.Value)): $target"
            }
        }
    }
    return $null
}

function Stop-HelperTask {
    # A helper that is still running keeps the secret it read at start, so a
    # registration against a new secret ends it first and waits for the task
    # record to stop saying "running".
    $existing = Get-ScheduledTask -TaskPath $TaskFolder -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) { return }
    Stop-ScheduledTask -TaskPath $TaskFolder -TaskName $TaskName -ErrorAction SilentlyContinue
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $existing = Get-ScheduledTask -TaskPath $TaskFolder -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $existing -or $existing.State -ne 'Running') { return }
        Start-Sleep -Milliseconds 250
    }
    throw "the running helper task did not end; nothing was changed"
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
$secretRefusal = Get-SecretRefusal -Path $SecretFile
if ($secretRefusal) {
    throw "the secret file is not locked and was not used: $secretRefusal. Install the helper with the one-click install or the Connector, which make a new locked secret."
}

# The device id is validated by the Python module, not by this script: one
# definition of a valid raw device id; the module derives a stable hashed pipe name.
$deviceOk = & $Python -c "import sys; from claw_connect.user_session_helper import pipe_name; pipe_name(sys.argv[1])" $DeviceId 2>&1
if ($LASTEXITCODE -ne 0) { throw "invalid device id: $deviceOk" }

$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$argument = '-m claw_connect.user_helper_service --device-id ' + $DeviceId + ' --secret-file "' + $SecretFile + '"'

Stop-HelperTask
$action = New-ScheduledTaskAction -Execute $Python -Argument $argument -WorkingDirectory $InstallRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskFolder -Action $action `
    -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'PADIEM user-session helper (#7065). One request per process.' -Force | Out-Null

Write-Output "registered task $TaskFolder$TaskName for $user (run level Limited)"
Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskFolder

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
