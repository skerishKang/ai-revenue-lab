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
# #7564: who may touch the helper's folder. The ProgramData folder lets every
# local account create files inside a child folder, so nothing here is left to
# inheritance: the folder, the program, the secret and the status each carry
# their own security descriptor. SYSTEM and the Administrators group have full
# control, the console user who runs the helper may read (and run), and no
# other account is named. Accounts are written as SIDs, never as display names
# a localized Windows spells differently. (No percent sign anywhere in this
# block: the server-rendered lane fills its template with one.)
$PadiemHelperSystemSid = "S-1-5-18"
$PadiemHelperAdministratorsSid = "S-1-5-32-544"
$PadiemHelperOwnerSid = $PadiemHelperAdministratorsSid

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

function Get-PadiemAccountSid {
  param([string] $Account)
  # The SID Windows resolves the account to. A name that does not resolve is
  # not an account this installer may grant anything to.
  try {
    $resolved = (New-Object System.Security.Principal.NTAccount($Account)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    if ($resolved -match '^S-1-[0-9]+(-[0-9]+)+$') { return $resolved }
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

function Get-PadiemHelperTrustedOwnerSids {
  # Whose folder this installer will work in: SYSTEM, the Administrators
  # group, and the administrator account running this very install - with
  # account control off, Windows records that account, not the group, as the
  # owner of what an administrator creates. A folder any other account made
  # first is never adopted.
  $trusted = @($PadiemHelperSystemSid, $PadiemHelperAdministratorsSid)
  try {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
      $trusted += $identity.User.Value
    }
  } catch { }
  return $trusted
}

function Get-PadiemHelperSddl {
  param([string] $Kind, [string] $UserSid)
  # One descriptor per kind of object. "P" cuts inheritance. The folder's
  # entries carry OICI, so a file created inside starts from the same three
  # accounts. 0x1200a9 is read and execute (folder, program); 0x120089 is
  # read (secret, status). Without a user only SYSTEM and Administrators stay.
  $pattern = '^S-1-[0-9]+(-[0-9]+)+$'
  if ($PadiemHelperOwnerSid -notmatch $pattern) { throw "padiem_helper_owner_sid" }
  if ($UserSid -and ($UserSid -notmatch $pattern)) { throw "padiem_helper_user_sid" }
  $inherit = if ($Kind -eq "folder") { "OICI" } else { "" }
  $rights = if ($Kind -eq "data") { "0x120089" } else { "0x1200a9" }
  $sddl = "O:" + $PadiemHelperOwnerSid + "D:PAI(A;" + $inherit + ";FA;;;" + $PadiemHelperSystemSid + ")(A;" + $inherit + ";FA;;;" + $PadiemHelperAdministratorsSid + ")"
  if ($UserSid) { $sddl += "(A;" + $inherit + ";" + $rights + ";;;" + $UserSid + ")" }
  return $sddl
}

function New-PadiemHelperSecurity {
  param([string] $Kind, [string] $UserSid)
  # The descriptor as the object the file APIs take. Only the owner and the
  # access list are set, so applying it never asks for the audit privilege.
  $security = if ($Kind -eq "folder") { New-Object System.Security.AccessControl.DirectorySecurity } else { New-Object System.Security.AccessControl.FileSecurity }
  $sections = [System.Security.AccessControl.AccessControlSections]::Owner -bor [System.Security.AccessControl.AccessControlSections]::Access
  $security.SetSecurityDescriptorSddlForm((Get-PadiemHelperSddl -Kind $Kind -UserSid $UserSid), $sections)
  return $security
}

function Get-PadiemHelperSecurityFacts {
  param($Security)
  # Owner, whether inheritance is cut, and every entry: what it takes to say
  # two descriptors grant the same things to the same accounts.
  $sid = [System.Security.Principal.SecurityIdentifier]
  $rules = @($Security.GetAccessRules($true, $true, $sid) | ForEach-Object {
    "{0}/{1}/{2}/{3}/{4}/{5}" -f $_.IdentityReference.Value, [int] $_.AccessControlType, [int] $_.FileSystemRights, [int] $_.InheritanceFlags, [int] $_.PropagationFlags, [int] $_.IsInherited
  } | Sort-Object)
  return "{0};{1};{2}" -f $Security.GetOwner($sid).Value, [int] $Security.AreAccessRulesProtected, ($rules -join ",")
}

function Test-PadiemHelperSecurity {
  param([string] $Path, [string] $Kind, [string] $UserSid)
  # Reads back what the disk holds. That the call which set a descriptor did
  # not fail is not the fact; the descriptor that is there now is. A link is
  # never the object this installer made.
  try {
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return $false }
    if ($item.PSIsContainer -ne ($Kind -eq "folder")) { return $false }
    $actual = if ($Kind -eq "folder") { [System.IO.Directory]::GetAccessControl($Path) } else { [System.IO.File]::GetAccessControl($Path) }
    $expected = New-PadiemHelperSecurity -Kind $Kind -UserSid $UserSid
    return ((Get-PadiemHelperSecurityFacts $actual) -eq (Get-PadiemHelperSecurityFacts $expected))
  } catch {
    return $false
  }
}

function Test-PadiemHelperFolderAdoptable {
  param([string] $Path)
  # "" when the folder that is already there may be worked in, otherwise why
  # not. It is adopted only from an owner this installer trusts, and never
  # when it is a link that leads somewhere else.
  $item = Get-Item -LiteralPath $Path -Force
  if (-not $item.PSIsContainer) { return "state_dir_not_a_folder" }
  if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return "state_dir_is_a_link" }
  $owner = $null
  try {
    $owner = [System.IO.Directory]::GetAccessControl($Path).GetOwner([System.Security.Principal.SecurityIdentifier]).Value
  } catch { $owner = $null }
  if (-not $owner -or (@(Get-PadiemHelperTrustedOwnerSids) -notcontains $owner)) { return "state_dir_owner_untrusted" }
  return ""
}

function Protect-PadiemHelperStateDir {
  param([string] $Path, [string] $UserSid)
  # "" when the folder is this installer's own and locked, otherwise the reason
  # it will not be used. A folder that is not there is created already carrying
  # its descriptor - there is no moment it exists with the inherited one. A
  # folder that is there is checked before it is touched, and what the disk
  # holds afterwards is read back either way.
  $security = New-PadiemHelperSecurity -Kind "folder" -UserSid $UserSid
  if (Test-Path -LiteralPath $Path) {
    $refusal = Test-PadiemHelperFolderAdoptable -Path $Path
    if ($refusal) { return $refusal }
    try { [System.IO.Directory]::SetAccessControl($Path, $security) } catch { return "state_dir_acl_failed" }
  } else {
    try { [void] [System.IO.Directory]::CreateDirectory($Path, $security) } catch { return "state_dir_create_failed" }
  }
  if (-not (Test-PadiemHelperSecurity -Path $Path -Kind "folder" -UserSid $UserSid)) { return "state_dir_acl_unverified" }
  return ""
}

function New-PadiemHelperLockedFile {
  param([string] $Path, [string] $Kind, [string] $UserSid)
  # A write stream on a file that is created already carrying its descriptor.
  # CreateNew refuses a name that exists, so a file somebody left there is
  # never written through.
  $security = New-PadiemHelperSecurity -Kind $Kind -UserSid $UserSid
  return New-Object System.IO.FileStream($Path, [System.IO.FileMode]::CreateNew, [System.Security.AccessControl.FileSystemRights]::Write, [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::None, $security)
}

function Move-PadiemHelperFileIntoPlace {
  param([string] $Source, [string] $Target)
  # A rename inside the locked folder keeps the descriptor the new file was
  # created with. The old file is removed first, not replaced in place:
  # replacing would hand the new bytes to whatever owner and entries the old
  # file had. A file that was just in use can stay held for a moment after its
  # process ends; three short waits is the whole retry.
  for ($attempt = 0; ; $attempt++) {
    try {
      if (Test-Path -LiteralPath $Target) {
        [System.IO.File]::SetAttributes($Target, [System.IO.FileAttributes]::Normal)
        [System.IO.File]::Delete($Target)
      }
      [System.IO.File]::Move($Source, $Target)
      return
    } catch {
      if ($attempt -ge 3) { throw }
      Start-Sleep -Milliseconds 500
    }
  }
}

function Copy-PadiemHelperProgram {
  param([string] $Source, [string] $Target, [string] $Sha256, [string] $UserSid)
  # The program is copied into a new file that already carries its descriptor,
  # hashed where it now lies, and only then given its name. True when the
  # bytes that were placed are the reviewed ones.
  $pending = $Target + "." + [guid]::NewGuid().ToString("N") + ".new"
  try {
    $writer = New-PadiemHelperLockedFile -Path $pending -Kind "program" -UserSid $UserSid
    try {
      $reader = [System.IO.File]::OpenRead($Source)
      try { $reader.CopyTo($writer) } finally { $reader.Dispose() }
    } finally { $writer.Dispose() }
    if ((Get-PadiemSha256 -Path $pending) -ne $Sha256) { return $false }
    Move-PadiemHelperFileIntoPlace -Source $pending -Target $Target
    return $true
  } finally {
    if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending -Force -ErrorAction SilentlyContinue }
  }
}

function New-PadiemHelperSecret {
  param([string] $Path, [string] $UserSid)
  # 32 random bytes, written as 64 lowercase hex characters - the shape the
  # Connector's own provisioning lane already writes. Every install makes a new
  # one: a file that is already there is never read back or kept, because
  # whoever wrote it knows what is in it. The new file carries its descriptor
  # from the moment it exists and gets its name only once it is complete. The
  # value stays in this process and on this file; it is never written to the
  # console or the status.
  $bytes = New-Object byte[] 32
  $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $random.GetBytes($bytes) } finally { $random.Dispose() }
  $hex = -join ($bytes | ForEach-Object { $_.ToString("x2") })
  $payload = (New-Object System.Text.UTF8Encoding($false)).GetBytes($hex + "`n")
  $pending = $Path + "." + [guid]::NewGuid().ToString("N") + ".new"
  try {
    $stream = New-PadiemHelperLockedFile -Path $pending -Kind "data" -UserSid $UserSid
    try { $stream.Write($payload, 0, $payload.Length) } finally { $stream.Dispose() }
    Move-PadiemHelperFileIntoPlace -Source $pending -Target $Path
  } finally {
    if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending -Force -ErrorAction SilentlyContinue }
  }
}

function Stop-PadiemUserHelper {
  param([string] $HelperExe)
  # A helper that is still running keeps the old secret in memory and its
  # program file open, so a re-install ends it first: the task instance, then
  # any process still running this exact file. True when none is left and the
  # task record no longer says "running" - a start that Windows still counts
  # as a second instance would be ignored.
  try {
    Stop-ScheduledTask -TaskName $PadiemUserHelperTaskName -TaskPath $PadiemUserHelperTaskFolder -ErrorAction SilentlyContinue
  } catch { }
  $name = [System.IO.Path]::GetFileNameWithoutExtension($HelperExe)
  for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $running = @()
    foreach ($process in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
      $image = $null
      try { $image = $process.MainModule.FileName } catch { $image = $null }
      if ($image -and [string]::Equals($image, $HelperExe, [System.StringComparison]::OrdinalIgnoreCase)) { $running += $process }
    }
    if ($running.Count -eq 0) {
      $task = $null
      try {
        $task = Get-ScheduledTask -TaskName $PadiemUserHelperTaskName -TaskPath $PadiemUserHelperTaskFolder -ErrorAction SilentlyContinue
      } catch { $task = $null }
      if (-not $task -or ([string] $task.State -ne "Running")) { return $true }
    }
    foreach ($process in $running) { try { $process.Kill() } catch { } }
    Start-Sleep -Milliseconds 250
  }
  return $false
}

function Move-PadiemHelperForeignContent {
  param([string] $StateDir)
  # Once the folder is locked, only plain files owned by SYSTEM or an
  # administrator stay in it. Anything else - a file another account put there
  # while the folder was open to it, a subfolder, a link - is moved, by one
  # rename each and never by a walk through its contents, into a sibling
  # folder only SYSTEM and administrators can open. True when nothing of the
  # kind is left.
  $trusted = @(Get-PadiemHelperTrustedOwnerSids)
  $foreign = @()
  foreach ($child in @(Get-ChildItem -LiteralPath $StateDir -Force)) {
    $owner = $null
    if (-not $child.PSIsContainer -and (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0)) {
      try {
        $owner = [System.IO.File]::GetAccessControl($child.FullName).GetOwner([System.Security.Principal.SecurityIdentifier]).Value
      } catch { $owner = $null }
    }
    if (-not $owner -or ($trusted -notcontains $owner)) { $foreign += $child }
  }
  if ($foreign.Count -eq 0) { return $true }
  $stamp = [DateTime]::UtcNow.ToString("yyyyMMddHHmmss", [System.Globalization.CultureInfo]::InvariantCulture)
  $quarantine = $StateDir.TrimEnd('\') + ".quarantine-" + $stamp + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
  [void] [System.IO.Directory]::CreateDirectory($quarantine, (New-PadiemHelperSecurity -Kind "folder" -UserSid $null))
  if (-not (Test-PadiemHelperSecurity -Path $quarantine -Kind "folder" -UserSid $null)) { return $false }
  $moved = 0
  foreach ($child in $foreign) {
    try {
      $destination = Join-Path $quarantine $child.Name
      if ($child.PSIsContainer) {
        [System.IO.Directory]::Move($child.FullName, $destination)
      } else {
        [System.IO.File]::Move($child.FullName, $destination)
      }
      $moved++
    } catch { }
  }
  Write-Host ("도우미 설치 폴더에 있던, 관리자나 SYSTEM 소유가 아닌 항목 " + $moved + "개를 " + $quarantine + " 폴더로 옮겼습니다.")
  return ($moved -eq $foreign.Count)
}

function Get-PadiemHelperInstallFault {
  param([string] $UserSid)
  # Reads the finished install back before the helper is allowed to start from
  # it. "" when the folder, the program and the secret each carry exactly
  # their own descriptor.
  if (-not (Test-PadiemHelperSecurity -Path $PadiemUserHelperStateDir -Kind "folder" -UserSid $UserSid)) { return "state_dir_acl_unverified" }
  if (-not (Test-PadiemHelperSecurity -Path $PadiemUserHelperExe -Kind "program" -UserSid $UserSid)) { return "program_acl_unverified" }
  if (-not (Test-PadiemHelperSecurity -Path $PadiemUserHelperSecret -Kind "data" -UserSid $UserSid)) { return "secret_acl_failed" }
  return ""
}

function Write-PadiemHelperStatus {
  param([hashtable] $Status, [string] $UserSid)
  # Local evidence only. The secret is never a member of this hashtable. The
  # status is written only into a folder this installer would adopt, as a new
  # file that already carries its descriptor and is then renamed into place -
  # never through a file that was already lying there, and with the writer
  # instead of the cmdlets the wrapper bans for pairing data.
  if (-not $PadiemUserHelperStatus) { return }
  $pending = $null
  try {
    if (-not (Test-Path -LiteralPath $PadiemUserHelperStateDir)) { return }
    if (Test-PadiemHelperFolderAdoptable -Path $PadiemUserHelperStateDir) { return }
    $json = $Status | ConvertTo-Json -Compress
    $payload = (New-Object System.Text.UTF8Encoding($false)).GetBytes($json + "`n")
    $pending = $PadiemUserHelperStatus + "." + [guid]::NewGuid().ToString("N") + ".new"
    $stream = New-PadiemHelperLockedFile -Path $pending -Kind "data" -UserSid $UserSid
    try { $stream.Write($payload, 0, $payload.Length) } finally { $stream.Dispose() }
    Move-PadiemHelperFileIntoPlace -Source $pending -Target $PadiemUserHelperStatus
  } catch {
  } finally {
    if ($pending -and (Test-Path -LiteralPath $pending)) { Remove-Item -LiteralPath $pending -Force -ErrorAction SilentlyContinue }
  }
}

function Write-PadiemHelperFailure {
  param([hashtable] $Status, [string] $UserSid)
  # An install that stops says why: on the console, and - when the folder is
  # one this installer may write in - in helper-status.json. The reason is a
  # fixed code; no pairing value is ever part of it.
  Write-PadiemHelperStatus -Status $Status -UserSid $UserSid
  $reason = [string] $Status["reason"]
  if ($reason -eq "state_dir_owner_untrusted") {
    Write-Host ("도우미 설치 폴더 " + $PadiemUserHelperStateDir + " 의 소유자가 관리자나 SYSTEM이 아니어서, 그 폴더를 쓰지 않고 도우미 설치를 멈췄습니다. 관리자가 폴더를 확인해 지운 뒤 다시 설치해 주세요.")
  }
  Write-Host ("사용자 세션 도우미 설치를 멈춘 이유: " + $reason)
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
  # Lock the folder, download, verify, end a running helper, clear what does
  # not belong, place, new secret, read the install back, logon task, status:
  # the same order in both PowerShell lanes and the double-click program.
  # Every failure returns false after saying its reason; nothing here throws
  # into the caller.
  param([string] $Url, [string] $Sha256, [string] $DeviceId)
  $status = @{ status = "not_installed"; task = $PadiemUserHelperTaskName; device_id = $DeviceId }
  if (-not $Url -or -not $Sha256) { return $false }
  if (-not $PadiemUserHelperStateDir) {
    $status.reason = "state_dir_missing"
    Write-PadiemHelperFailure -Status $status -UserSid $null
    return $false
  }
  $temp = $null
  $userSid = $null
  $stopped = $false
  $verified = $false
  try {
    $consoleUser = Get-PadiemConsoleUser
    if ($consoleUser) { $userSid = Get-PadiemAccountSid -Account $consoleUser }
    if (-not $userSid) {
      $status.reason = if ($consoleUser) { "console_user_unresolved" } else { "no_console_user" }
      Write-PadiemHelperFailure -Status $status -UserSid $null
      return $false
    }
    # Nothing is downloaded, stopped or written until the folder is this
    # installer's own: a folder another account made first is refused here,
    # before anything on this PC has changed.
    $refusal = Protect-PadiemHelperStateDir -Path $PadiemUserHelperStateDir -UserSid $userSid
    if ($refusal) {
      $status.reason = $refusal
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    $temp = Join-Path $env:TEMP ("padiem-user-helper-" + [guid]::NewGuid().ToString("N") + ".exe")
    Invoke-WebRequest -Uri $Url -OutFile $temp -UseBasicParsing -TimeoutSec 180
    $expected = $Sha256.ToLowerInvariant()
    $actual = Get-PadiemSha256 -Path $temp
    if ($actual -ne $expected) {
      $status.reason = "sha256_mismatch"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    if (-not (Stop-PadiemUserHelper -HelperExe $PadiemUserHelperExe)) {
      $status.reason = "helper_still_running"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    $stopped = $true
    if (-not (Move-PadiemHelperForeignContent -StateDir $PadiemUserHelperStateDir)) {
      $status.reason = "state_dir_foreign_content"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    if (-not (Copy-PadiemHelperProgram -Source $temp -Target $PadiemUserHelperExe -Sha256 $expected -UserSid $userSid)) {
      $status.reason = "sha256_mismatch"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    New-PadiemHelperSecret -Path $PadiemUserHelperSecret -UserSid $userSid
    $fault = Get-PadiemHelperInstallFault -UserSid $userSid
    if ($fault) {
      $status.reason = $fault
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    $verified = $true
    if (-not (Register-PadiemUserHelperTask -HelperExe $PadiemUserHelperExe -SecretPath $PadiemUserHelperSecret -DeviceId $DeviceId -ConsoleUser $consoleUser)) {
      $status.reason = "task_registration_failed"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    $status.status = "installed"
    $status.sha256 = $expected
    $status.user = $consoleUser
    Write-PadiemHelperStatus -Status $status -UserSid $userSid
    return $true
  } catch {
    $status.status = "not_installed"
    $status.reason = "provision_failed"
    $status.error = $_.Exception.GetType().Name
    Write-PadiemHelperFailure -Status $status -UserSid $userSid
    return $false
  } finally {
    if ($temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
    if ($stopped -and -not $verified) {
      # The old helper was ended and the new install did not pass its
      # read-back. Without a secret the helper refuses to start, so a folder
      # that was not verified is never served from.
      Remove-Item -LiteralPath $PadiemUserHelperSecret -Force -ErrorAction SilentlyContinue
    }
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
