<#
.SYNOPSIS
  Connect this Windows PC to one PADIEM account (#5573 PR-4b).

.DESCRIPTION
  One path, one prompt: type the pairing code the browser showed you, and this
  script asks PADIEM for the installer link and the tag that belongs to that
  code, then installs the agent the way the double-click program does - the
  downloaded agent is copied into %ProgramFiles%\PADIEM, the one "Mesh Agent"
  service is registered from there with -install (a re-run updates it in
  place; a second service is never registered), it is started, and the
  service's own status is read back. The server recognises the tag in the
  agent's name and finishes the pairing - this PC never has to name itself,
  and no account password is ever asked for or stored here.

  It then provisions the optional user-session helper: the deployment's
  versioned helper EXE is downloaded, its SHA-256 checked, and it is placed in
  %ProgramData%\Padiem with a 32-byte secret, a per-user ONLOGON/Limited task
  and a local helper-status.json. A helper that cannot be provisioned never
  undoes the agent connection above.

  Nothing about the pairing is written to disk: the code, the tag and the link
  live in this process only. Re-running the script on an already-installed PC
  skips the download and re-submits the pairing for the code you type now.

.PARAMETER ChatOrigin
  The https origin of your PADIEM Chat, e.g. https://chat.padiem.net

.PARAMETER Code
  Never use this. It exists only so the automated check can exercise the
  validation path; a real run is always prompted, because a command-line value
  lands in shell history.

.EXAMPLE
  Set-ExecutionPolicy -Scope Process Bypass
  .\install-padiem-pc.ps1 -ChatOrigin https://chat.padiem.net
#>
[CmdletBinding()]
param(
  [string] $ChatOrigin = "",
  [string] $Code = "",
  [string] $AgentInstallDir = "${env:ProgramFiles(x86)}\Mesh Services",
  [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$HandoffPath = "/api/pc/pairings/handoff"
$ClaimPath = "/api/pc/pairings/claim"
$Copy = @{
  Prompt          = "PADIEM에서 표시한 12자리 연결 코드를 입력하세요 (화면에 표시되지 않습니다): "
  BadCode         = "연결 코드 형식이 올바르지 않습니다. 코드를 다시 확인하거나 새 코드를 발급하세요."
  BadOrigin       = "Chat 주소는 https로 시작해야 합니다."
  NotReady        = "서버가 아직 PC 연결 준비 중입니다. 잠시 후 다시 실행하세요."
  CodeRejected    = "이 코드는 사용할 수 없습니다(만료되었거나 이미 쓰였습니다). 새 코드로 다시 시도하세요."
  AlreadyInstalled = "이 PC에는 에이전트가 이미 설치되어 있습니다. 코드만 다시 제출합니다."
  Installed       = "에이전트 설치를 시작했습니다. 이름에 연결 표식이 붙고 서버가 이 PC를 확인하면 연결이 완료됩니다."
  Waiting         = "서버 확인 대기 중 — PADIEM의 '내 PC 연결'에서 자동으로 '연결됨'으로 바뀝니다."
  LinkPending     = "이 PC에 에이전트가 아직 없고 서버가 아직 설치 링크를 내려주지 않았습니다. 설치 링크가 준비되면 이 프로그램을 다시 실행하세요. 연결 코드는 10분 안에 만료되니 새 코드로 다시 시도하세요."
  AgentReady      = "에이전트가 이미 설치되어 있습니다. 서버 확인을 기다립니다."
  DryRunNote      = "(점검 실행: 설치 프로그램은 실행하지 않았습니다)"
  InstallFailed   = "에이전트 설치를 마치지 못했습니다. 잠시 후 다시 시도해 주세요."
  ElevationNeeded = "관리자 권한 승인 창이 나타나면 [예]를 눌러 주세요. 설치에는 관리자 권한이 필요합니다."
  ElevationRefused = "설치 권한이 거부되었습니다. 이 스크립트를 관리자 권한으로 다시 실행해 주세요."
  ElevationFailed = "PC 연결 설치 프로그램을 실행하지 못했습니다. 잠시 후 다시 시도해 주세요."
  HelperInstalled = "사용자 세션 도우미를 설치했습니다."
  HelperUnavailable = "사용자 세션 도우미는 설치하지 못했습니다. PC 연결은 계속 진행됩니다."
}

# ---- the agent install sequence the double-click program runs ----
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

# ---- the user-session helper the one-click install also provisions ----
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

function Format-PadiemCode {
  param([string] $Value)
  # Codes are issued from an unambiguous alphabet; accept the code whether the
  # human typed it lower-case, upper-case or with a stray space.
  if ($null -eq $Value) { return $null }
  $trimmed = ($Value -replace '\s', '').ToUpperInvariant()
  if ($trimmed -notmatch '^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{12}$') { return $null }
  return $trimmed
}

function Get-PadiemOrigin {
  param([string] $Value)
  # A plain https origin with a host and nothing else: no credentials, no path,
  # no port tricks. The installer is fetched from this origin, so an http hop or
  # a caller-supplied path is refused the same way the server-side validator
  # refuses it - as no configuration at all.
  if ($null -eq $Value) { return $null }
  $origin = $Value.Trim().TrimEnd('/')
  if ($origin -match '@') { return $null }
  if ($origin -notmatch '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$') { return $null }
  return $origin
}

function Test-PadiemAgentInstalled {
  param([string] $Directory)
  if ([string]::IsNullOrWhiteSpace($Directory)) { return $false }
  if (-not (Test-Path -LiteralPath $Directory -PathType Container)) { return $false }
  return (@(Get-ChildItem -LiteralPath $Directory -Filter '*.exe' -ErrorAction SilentlyContinue).Count -gt 0)
}

function Invoke-PadiemHandoff {
  param([string] $Origin, [string] $PairingCode)
  $body = @{ code = $PairingCode } | ConvertTo-Json -Compress
  try {
    return Invoke-RestMethod -Method Post -Uri ($Origin + $HandoffPath) `
      -ContentType 'application/json' -Body $body -TimeoutSec 30
  } catch {
    return $null
  }
}

function Get-PadiemDriveRoots {
  # A linked PC works over its whole local drives by default (#5573, Owner
  # decision), so the PC names the fixed drives it actually has. Network drives
  # carry a DisplayRoot and stay out. A failed query reports nothing at all: the
  # server then says the drive lookup failed instead of guessing a scope.
  try {
    return @(Get-PSDrive -PSProvider FileSystem -ErrorAction Stop |
      Where-Object { $null -eq $_.DisplayRoot } |
      ForEach-Object { $_.Name.ToUpperInvariant() + ':' } | Sort-Object -Unique)
  } catch {
    return @()
  }
}

function Invoke-PadiemClaim {
  param([string] $Origin, [string] $PairingCode, [string] $MeshNodeId, [string[]] $Drives)
  $body = @{ code = $PairingCode; mesh_node_id = $MeshNodeId; drives = @($Drives) } |
    ConvertTo-Json -Compress
  try {
    return Invoke-RestMethod -Method Post -Uri ($Origin + $ClaimPath) `
      -ContentType 'application/json' -Body $body -TimeoutSec 30
  } catch {
    return $null
  }
}

function Invoke-PadiemUserHelperInstall {
  param([string] $Url, [string] $Sha256, [string] $Tag)
  # Optional and best-effort: an unconfigured deployment says nothing, and a
  # configured one says which of the two happened without changing the exit code.
  # Defined with the other functions, before the $installed branch that can call it.
  if (-not $Url -or -not $Sha256) { return }
  try {
    $deviceId = Get-PadiemHelperDeviceId -Tag $Tag
    if (Install-PadiemUserHelper -Url $Url -Sha256 $Sha256 -DeviceId $deviceId) {
      Write-Host $Copy.HelperInstalled
    } else {
      Write-Host $Copy.HelperUnavailable
    }
  } catch {
    Write-Host $Copy.HelperUnavailable
  }
}

function Read-PadiemCode {
  # Read-Host -AsSecureString keeps the typed proof off the console and off the
  # command line; it is converted here and never leaves this scope.
  $secure = Read-Host -Prompt $Copy.Prompt -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Save-PadiemInstaller {
  param([string] $Url)
  # The installer itself is downloaded to a temp path and removed after the
  # attempt, so the pairing information never persists in a file. The service
  # sequence that follows runs the durable copy, never this one.
  $target = Join-Path $env:TEMP ("padiem-agent-" + [guid]::NewGuid().ToString('N') + ".exe")
  Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing -TimeoutSec 120
  return $target
}

function Test-PadiemAdministrator {
  $identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
  return $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-PadiemElevation {
  # The copy into Program Files and the service work below need the
  # administrator token, and one approval covers the whole sequence - the same
  # single prompt the double-click program asks for before it connects. The
  # origin (and a caller-supplied check code) travel into the elevated console;
  # a typed code never does, because a command line is not where it belongs.
  if (Test-PadiemAdministrator) { return }
  Write-Host $Copy.ElevationNeeded
  $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $PSCommandPath + '"'))
  if ($ChatOrigin) { $arguments += @("-ChatOrigin", $ChatOrigin) }
  if ($Code) { $arguments += @("-Code", $Code) }
  try {
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs
  } catch [System.ComponentModel.Win32Exception] {
    Write-Error $Copy.ElevationRefused
    exit 5
  } catch {
    Write-Error $Copy.ElevationFailed
    exit 6
  }
  exit 0
}

$origin = Get-PadiemOrigin -Value $ChatOrigin
if (-not $origin) { Write-Error $Copy.BadOrigin; exit 2 }

# A command-line code is the automated check's input, and a badly shaped one is
# refused before anything asks for elevation: a broken check run never prompts.
if (-not [string]::IsNullOrWhiteSpace($Code) -and -not (Format-PadiemCode -Value $Code)) {
  Write-Error $Copy.BadCode
  exit 2
}

if (-not $DryRun) { Assert-PadiemElevation }

$rawCode = if ([string]::IsNullOrWhiteSpace($Code)) { Read-PadiemCode } else { $Code }
$pairingCode = Format-PadiemCode -Value $rawCode
if (-not $pairingCode) { Write-Error $Copy.BadCode; exit 2 }

$handoff = Invoke-PadiemHandoff -Origin $origin -PairingCode $pairingCode
if (-not $handoff -or -not $handoff.handoff) { Write-Error $Copy.NotReady; exit 3 }
$agentUrl = [string] $handoff.handoff.agent_url
$tag = [string] $handoff.handoff.install_tag
$helperUrl = [string] $handoff.handoff.user_helper_url
$helperSha = [string] $handoff.handoff.user_helper_sha256
$installed = Test-PadiemAgentInstalled -Directory $AgentInstallDir

if (-not $agentUrl -and -not $installed) {
  # The code is still good and the tag was issued; only the download target is
  # not configured yet. Saying so is the whole answer - an already installed PC
  # continues below without ever needing a link.
  Write-Host $Copy.LinkPending
  exit 0
}

if ($installed) {
  Write-Host $Copy.AlreadyInstalled
  # The agent already exists, so the pairing is re-submitted by name: this is
  # the R3 path for a PC that is added to another account, or re-paired after a
  # revoke. The server needs the node identity it can address, which the
  # observation lane (#5573 PR-4a) already carries; the claim endpoint stays the
  # direct route when a caller knows the node id.
  if ($env:PADIEM_MESH_NODE_ID) {
    $claim = Invoke-PadiemClaim -Origin $origin -PairingCode $pairingCode -MeshNodeId $env:PADIEM_MESH_NODE_ID -Drives (Get-PadiemDriveRoots)
    if (-not $claim) { Write-Error $Copy.CodeRejected; exit 4 }
  }
  Invoke-PadiemUserHelperInstall -Url $helperUrl -Sha256 $helperSha -Tag $tag
  if ($agentUrl) { Write-Host ("{0} (표식 {1})" -f $Copy.Waiting, $tag) } else { Write-Host $Copy.AgentReady }
  exit 0
}

function Format-PadiemAgentName {
  param([string] $Tag, [string[]] $Drives)
  # The name the agent reports to the server is what completes the pairing: the
  # tag inside it decides the account, and the drive letters after it are the
  # same self-report a claiming PC posts. Anything that is not one bare letter
  # is dropped rather than guessed at.
  $letters = @($Drives |
    ForEach-Object { (($_ -replace ':', '')).ToUpperInvariant() } |
    Where-Object { $_ -match '^[A-Z]$' } | Sort-Object -Unique)
  # The trailing word is the name Windows gave this machine. The server reads
  # the tag to decide the account, the letters to grant whole drives, and that
  # name to call the PC by until its owner renames it. Dns.GetHostName() is
  # the whole DNS name; $env:COMPUTERNAME is the 15-character NetBIOS form and
  # would store a truncated name as the link's first label.
  $machine = try { [System.Net.Dns]::GetHostName() } catch { $env:COMPUTERNAME }
  if (-not $machine) { $machine = $env:COMPUTERNAME }
  if ($letters.Count -eq 0) {
    if (-not $machine) { return $Tag }
    return $Tag + ' ' + $machine
  }
  if (-not $machine) { return $Tag + ' [' + ($letters -join ' ') + ']' }
  return $Tag + ' [' + ($letters -join ' ') + '] ' + $machine
}

if ($DryRun) {
  $agentName = Format-PadiemAgentName -Tag $tag -Drives (Get-PadiemDriveRoots)
  Write-Host ("{0} -> {1}" -f $Copy.Installed, $agentUrl)
  Write-Host ("설치 위치 " + $PadiemAgentDurableExe)
  Write-Host ("실행 명령 MeshAgent.exe -install --agentName=`"" + $agentName + "`"")
  Write-Host $Copy.DryRunNote
  exit 0
}

$agentName = Format-PadiemAgentName -Tag $tag -Drives (Get-PadiemDriveRoots)
$installer = Save-PadiemInstaller -Url $agentUrl
try {
  if (-not (Install-PadiemAgentService -SourceExe $installer -AgentName $agentName)) {
    Write-Error $Copy.InstallFailed
    exit 6
  }
  $service = Get-Service -Name $PadiemAgentServiceName -ErrorAction SilentlyContinue
  if ($service) {
    Write-Host ("에이전트 서비스 상태: " + $service.Status + " - " + $PadiemAgentDurableExe)
  }
} finally {
  Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
}
Invoke-PadiemUserHelperInstall -Url $helperUrl -Sha256 $helperSha -Tag $tag
Write-Host $Copy.Installed
Write-Host ("{0} (표식 {1})" -f $Copy.Waiting, $tag)
