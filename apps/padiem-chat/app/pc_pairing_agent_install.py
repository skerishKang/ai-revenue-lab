"""The one agent-install sequence every PowerShell install lane shares (#5573).

The double-click program (``scripts/pc_pairing/connect-exe/PadiemPcConnect.cs``)
runs a measured sequence, and both PowerShell lanes must run the same one. On
the tagged Windows agent of 2026-10-28 ``-fullinstall`` exited 0 and registered
nothing while ``-install`` registered the service from the folder it ran from -
so the copy into the product's own folder under Program Files is the lane's
job, never the agent switch's, and the service is registered from that durable
folder, started from it, and then read back for its status.

The constants and the PowerShell block below are the single place both lanes
read that sequence from: the server-rendered install script embeds
:func:`render_agent_install_block` when its template is built, the wrapper
script ``scripts/pc_pairing/install-padiem-pc.ps1`` embeds the same block
verbatim, and the tests refuse a copy that drifts - the same refuse-on-drift
contract the .exe build pins with its seed.

#7108 PR-2 adds the second half of the one-click install: the user-session
helper. It is optional in exactly one sense - a MeshCentral agent that came up
is the install's success criterion, and a helper that cannot be provisioned
must never undo it. The block below still refuses to call an unverified binary:
the helper EXE is downloaded from the deployment's own versioned URL, its
SHA-256 is checked before it is placed, and only then does it get a secret and a
per-user logon task.
"""
from __future__ import annotations

#: The one service the agent registers under. A re-run updates this one
#: service; a lane that registers a second service is wrong.
AGENT_SERVICE_NAME = "Mesh Agent"
#: Where Windows records that service. The ImagePath value under this key is
#: what an update stops the old agent through, whatever folder it came from.
AGENT_SERVICE_REGISTRY_KEY = "SYSTEM\\CurrentControlSet\\Services\\Mesh Agent"
AGENT_FILE_NAME = "MeshAgent.exe"
#: The durable folder under the real Program Files - not Temp, and not the
#: old "%ProgramFiles(x86)%\\Mesh Services" default: ``-install`` leaves the
#: executing folder in the service record, so a temp folder would become a
#: service that cannot start once that folder is cleaned up.
AGENT_DURABLE_FOLDER = "PADIEM"
#: Measured, not assumed (PadiemPcConnect.cs records the run): this agent
#: build's ``-fullinstall`` exited 0 and registered nothing.
AGENT_INSTALL_SWITCH = "-install"

#: The helper's fixed task identity. One task, under this product's own folder,
#: started at the console user's logon with the Limited run level.
USER_HELPER_TASK_NAME = "PadiemUserSessionHelper"
USER_HELPER_TASK_FOLDER = "\\Padiem\\"
USER_HELPER_FILE_NAME = "padiem-user-helper.exe"
#: ProgramData, not Program Files: the secret and the helper's status live
#: beside the executable, and the task runs as the ordinary console user.
USER_HELPER_STATE_FOLDER = "Padiem"
USER_HELPER_SECRET_NAME = "helper.secret"
USER_HELPER_STATUS_NAME = "helper-status.json"


_AGENT_INSTALL_BLOCK = r"""# ---- the agent install sequence the double-click program runs ----
# Measured on the tagged Windows agent of 2026-10-28 (PadiemPcConnect.cs):
# -fullinstall exited 0 and registered nothing, while -install registered the
# service from the folder it ran from. So the copy into the product's own
# folder under Program Files is this script's job, and -install runs from
# there - never -fullinstall, never out of a temp folder.
$PadiemAgentServiceName = "Mesh Agent"
# The durable folder lives under the real Program Files. A validation-only
# run on a host without it (CI Linux, pwsh) must reach its own refusal, not
# die here: the install walk below only runs on a Windows PC that has it.
$PadiemAgentDurableDir = if ($env:ProgramFiles) { Join-Path $env:ProgramFiles "PADIEM" } else { $null }
$PadiemAgentDurableExe = if ($PadiemAgentDurableDir) { Join-Path $PadiemAgentDurableDir "MeshAgent.exe" } else { $null }

function Install-PadiemAgentService {
  # Stops an existing service through the binary its own record names, copies
  # the downloaded agent into the durable folder, registers the same single
  # service from there with -install, starts it, and answers whether the
  # service is registered afterwards. Never registers a second service: the
  # name is the one constant above, so a re-run updates in place.
  param([string] $SourceExe, [string] $AgentName)
  $record = "HKLM:\SYSTEM\CurrentControlSet\Services\" + $PadiemAgentServiceName
  $item = Get-ItemProperty -Path $record -Name ImagePath -ErrorAction SilentlyContinue
  $registered = $null
  if ($item) { $registered = ([string] $item.ImagePath).Trim() }
  if ($registered) {
    if ($registered.StartsWith('"')) {
      $closing = $registered.IndexOf('"', 1)
      $registered = if ($closing -gt 1) { $registered.Substring(1, $closing - 1) } else { $null }
    } else {
      $space = $registered.IndexOf(' ')
      $registered = if ($space -ge 0) { $registered.Substring(0, $space) } else { $registered }
    }
  }
  if ($registered -and (Test-Path -LiteralPath $registered)) {
    # The stop is asked of the agent binary itself, the way the double-click
    # program does it; a refusal here is not a failure - the copy below
    # retries over a file a still-running agent holds.
    try {
      Start-Process -FilePath $registered -ArgumentList "-stop" -Wait -WindowStyle Hidden | Out-Null
    } catch { }
  }
  New-Item -ItemType Directory -Path $PadiemAgentDurableDir -Force | Out-Null
  $copied = $false
  for ($attempt = 0; $attempt -lt 3; $attempt++) {
    try {
      Copy-Item -LiteralPath $SourceExe -Destination $PadiemAgentDurableExe -Force
      $copied = $true
      break
    } catch {
      Start-Sleep -Seconds 1
    }
  }
  if (-not $copied) { return $false }
  try {
    $installed = Start-Process -FilePath $PadiemAgentDurableExe -ArgumentList @("-install", ('--agentName="' + $AgentName + '"')) -Wait -PassThru -WindowStyle Hidden
  } catch {
    return $false
  }
  if (-not $installed -or $installed.ExitCode -ne 0) { return $false }
  # -install registers; it does not launch. The start is what makes a fresh PC
  # answer the server's first call instead of waiting for the next restart.
  try {
    Start-Process -FilePath $PadiemAgentDurableExe -ArgumentList "-start" -Wait -WindowStyle Hidden | Out-Null
  } catch { }
  $service = Get-Service -Name $PadiemAgentServiceName -ErrorAction SilentlyContinue
  return ($null -ne $service)
}
"""


_USER_HELPER_INSTALL_BLOCK = r"""# ---- the user-session helper the one-click install also provisions ----
# The helper is a per-user process, not a service: it listens on this PC's
# named pipe and runs one request per process (see claw_connect.user_helper_service).
# It is optional. The MeshCentral agent above is the connection; a helper that
# cannot be provisioned here is recorded in helper-status.json and never undoes
# the agent install or asks for a second elevation.
$PadiemUserHelperTaskName = "PadiemUserSessionHelper"
$PadiemUserHelperTaskFolder = "\Padiem\"
$PadiemUserHelperFileName = "padiem-user-helper.exe"
$PadiemUserHelperStateDir = if ($env:ProgramData) { Join-Path $env:ProgramData "Padiem" } else { $null }
$PadiemUserHelperExe = if ($PadiemUserHelperStateDir) { Join-Path $PadiemUserHelperStateDir $PadiemUserHelperFileName } else { $null }
$PadiemUserHelperSecret = if ($PadiemUserHelperStateDir) { Join-Path $PadiemUserHelperStateDir "helper.secret" } else { $null }
$PadiemUserHelperStatus = if ($PadiemUserHelperStateDir) { Join-Path $PadiemUserHelperStateDir "helper-status.json" } else { $null }

function Get-PadiemConsoleUser {
  # The account actually signed in at the console - not the elevated
  # administrator token this installer runs under. Registering the installer's
  # own identity would put the helper in the wrong session (or in no session at
  # all), which is the one thing the logon task must not do.
  try {
    $computer = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
    $name = [string] $computer.UserName
    if ($name -and $name -match '^[^\\/\s]+\\[^\\/\s]+$') { return $name }
  } catch { }
  return $null
}

function Get-PadiemHelperDeviceId {
  param([string] $Tag)
  # The pairing tag is the identifier the server and this PC already share, so
  # it is the helper's device id by default. A tag that is not a safe raw id
  # gets a fresh 32-hex id; PR-3 reads whichever value this task carries out
  # of its own argument and derives the same pipe name from it.
  if ($Tag -and $Tag -match '^[A-Za-z0-9_.$:@+\-]{1,256}$') { return $Tag }
  return [guid]::NewGuid().ToString("N")
}

function Get-PadiemSha256 {
  param([string] $Path)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
      return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally { $stream.Dispose() }
  } finally { $sha.Dispose() }
}

function New-PadiemHelperSecret {
  param([string] $Path)
  # 32 random bytes, written as 64 lowercase hex characters - the shape the
  # Connector's own provisioning lane already writes. The value stays in this
  # process and on this file; it is never written to the console or the status.
  $bytes = New-Object byte[] 32
  $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $random.GetBytes($bytes) } finally { $random.Dispose() }
  $hex = -join ($bytes | ForEach-Object { $_.ToString("x2") })
  $encoding = New-Object System.Text.UTF8Encoding($false)
  $writer = New-Object System.IO.StreamWriter($Path, $false, $encoding)
  try { $writer.Write($hex + "`n") } finally { $writer.Dispose() }
}

function Set-PadiemHelperSecretAcl {
  param([string] $Path, [string] $ConsoleUser)
  # SYSTEM reads the secret; the console user reads and writes it. Inheritance
  # is removed so the elevated installer account is not an implicit reader.
  $null = & icacls $Path /inheritance:r /grant:r "SYSTEM:(R)" ($ConsoleUser + ":(M)") 2>&1
  return ($LASTEXITCODE -eq 0)
}

function Write-PadiemHelperStatus {
  param([hashtable] $Status)
  # Local evidence only. The secret is never a member of this hashtable, and
  # the writer is used instead of the cmdlets the wrapper bans for pairing data.
  if (-not $PadiemUserHelperStatus) { return }
  try {
    New-Item -ItemType Directory -Path $PadiemUserHelperStateDir -Force | Out-Null
    $json = $Status | ConvertTo-Json -Compress
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $writer = New-Object System.IO.StreamWriter($PadiemUserHelperStatus, $false, $encoding)
    try { $writer.Write($json + "`n") } finally { $writer.Dispose() }
  } catch { }
}

function Register-PadiemUserHelperTask {
  param([string] $HelperExe, [string] $SecretPath, [string] $DeviceId, [string] $ConsoleUser)
  # ONLOGON, Interactive, Limited: the helper starts in the console user's own
  # session and never runs elevated. Registering for that user from this
  # already-elevated process does not ask Windows for another approval.
  $arguments = '--device-id "' + $DeviceId + '" --secret-file "' + $SecretPath + '"'
  $action = New-ScheduledTaskAction -Execute $HelperExe -Argument $arguments -WorkingDirectory $PadiemUserHelperStateDir
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $ConsoleUser
  $principal = New-ScheduledTaskPrincipal -UserId $ConsoleUser -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $PadiemUserHelperTaskName -TaskPath $PadiemUserHelperTaskFolder -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "PADIEM user-session helper (#7108). One request per process." -Force | Out-Null
  Start-ScheduledTask -TaskName $PadiemUserHelperTaskName -TaskPath $PadiemUserHelperTaskFolder
  return $true
}

function Install-PadiemUserHelper {
  # Download, verify, place, secret, ACL, logon task, status: the same order in
  # both PowerShell lanes and the double-click program. Every failure returns
  # false after writing its reason; nothing here throws into the caller.
  param([string] $Url, [string] $Sha256, [string] $DeviceId)
  $status = @{ status = "not_installed"; task = $PadiemUserHelperTaskName; device_id = $DeviceId }
  if (-not $Url -or -not $Sha256) { return $false }
  if (-not $PadiemUserHelperStateDir) {
    $status.reason = "state_dir_missing"
    Write-PadiemHelperStatus $status
    return $false
  }
  $temp = $null
  try {
    $consoleUser = Get-PadiemConsoleUser
    if (-not $consoleUser) {
      $status.reason = "no_console_user"
      Write-PadiemHelperStatus $status
      return $false
    }
    $temp = Join-Path $env:TEMP ("padiem-user-helper-" + [guid]::NewGuid().ToString("N") + ".exe")
    Invoke-WebRequest -Uri $Url -OutFile $temp -UseBasicParsing -TimeoutSec 180
    $actual = Get-PadiemSha256 -Path $temp
    if ($actual -ne $Sha256.ToLowerInvariant()) {
      $status.reason = "sha256_mismatch"
      Write-PadiemHelperStatus $status
      return $false
    }
    New-Item -ItemType Directory -Path $PadiemUserHelperStateDir -Force | Out-Null
    Copy-Item -LiteralPath $temp -Destination $PadiemUserHelperExe -Force
    if (-not (Test-Path -LiteralPath $PadiemUserHelperSecret) -or (Get-Item -LiteralPath $PadiemUserHelperSecret).Length -eq 0) {
      New-PadiemHelperSecret -Path $PadiemUserHelperSecret
    }
    if (-not (Set-PadiemHelperSecretAcl -Path $PadiemUserHelperSecret -ConsoleUser $consoleUser)) {
      $status.reason = "secret_acl_failed"
      Write-PadiemHelperStatus $status
      return $false
    }
    if (-not (Register-PadiemUserHelperTask -HelperExe $PadiemUserHelperExe -SecretPath $PadiemUserHelperSecret -DeviceId $DeviceId -ConsoleUser $consoleUser)) {
      $status.reason = "task_registration_failed"
      Write-PadiemHelperStatus $status
      return $false
    }
    $status.status = "installed"
    $status.sha256 = $Sha256.ToLowerInvariant()
    $status.user = $consoleUser
    Write-PadiemHelperStatus $status
    return $true
  } catch {
    $status.status = "not_installed"
    $status.reason = "provision_failed"
    $status.error = $_.Exception.GetType().Name
    Write-PadiemHelperStatus $status
    return $false
  } finally {
    if ($temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
  }
}
"""


def render_agent_install_block() -> str:
    """The self-contained PowerShell block both .ps1 lanes embed verbatim.

    The inputs are the two values every lane already has - the downloaded
    installer path and the agent name the server pairs on. The block stops an
    existing service through the binary its own record names, copies the agent
    into the durable folder, registers the one service from there with
    ``-install``, starts it, and answers whether the service is registered
    afterwards. Nothing here reads or writes a pairing secret.
    """
    return _AGENT_INSTALL_BLOCK


def render_user_helper_install_block() -> str:
    """The optional user-helper block both .ps1 lanes embed verbatim.

    It is one definition so the server-rendered lane and the wrapper cannot
    drift: the same download, SHA-256 check, ProgramData placement, 32-byte
    secret, SYSTEM + console-user ACL, ONLOGON/Limited task and local status
    file. Every failure is reported through helper-status.json and returns
    false; the agent connection is never unwound.
    """
    return _USER_HELPER_INSTALL_BLOCK
