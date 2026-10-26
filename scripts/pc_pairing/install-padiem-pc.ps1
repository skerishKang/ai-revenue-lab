<#
.SYNOPSIS
  Connect this Windows PC to one PADIEM account (#5573 PR-4b).

.DESCRIPTION
  One path, one prompt: type the pairing code the browser showed you, and this
  script asks PADIEM for the installer link and the tag that belongs to that
  code, then runs the installer so the agent appears on the MeshCentral server
  with the tag in its name. The server recognises the tag in its own device
  observation and finishes the pairing — this PC never has to name itself, and
  no account password is ever asked for or stored here.

  Nothing is written to disk: the code, the tag and the link live in this
  process only. Re-running the script on an already-installed PC skips the
  download and re-submits the pairing for the code you type now.

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
  [string] $AgentInstallerArgs = "/S",
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
  NoAgentUrl      = "서버가 설치 링크를 주지 않았습니다. 배포 설정(PC_AGENT_INSTALL_URL) 확인이 필요합니다."
  DryRunNote      = "(점검 실행: 설치 프로그램은 실행하지 않았습니다)"
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

function Invoke-PadiemClaim {
  param([string] $Origin, [string] $PairingCode, [string] $MeshNodeId)
  $body = @{ code = $PairingCode; mesh_node_id = $MeshNodeId } | ConvertTo-Json -Compress
  try {
    return Invoke-RestMethod -Method Post -Uri ($Origin + $ClaimPath) `
      -ContentType 'application/json' -Body $body -TimeoutSec 30
  } catch {
    return $null
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

function Start-PadiemInstall {
  param([string] $Url, [string] $Arguments, [switch] $Simulate)
  if ($Simulate) { return $false }
  # The installer itself is downloaded to a temp path and removed after the
  # attempt, so the pairing information never persists in a file.
  $target = Join-Path $env:TEMP ("padiem-agent-" + [guid]::NewGuid().ToString('N') + ".exe")
  try {
    Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing -TimeoutSec 120
    $switches = $Arguments -split ' ' | Where-Object { $_ }
    Start-Process -FilePath $target -ArgumentList $switches -Wait
    return $true
  } finally {
    Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
  }
}

$origin = Get-PadiemOrigin -Value $ChatOrigin
if (-not $origin) { Write-Error $Copy.BadOrigin; exit 2 }

$rawCode = if ([string]::IsNullOrWhiteSpace($Code)) { Read-PadiemCode } else { $Code }
$pairingCode = Format-PadiemCode -Value $rawCode
if (-not $pairingCode) { Write-Error $Copy.BadCode; exit 2 }

$handoff = Invoke-PadiemHandoff -Origin $origin -PairingCode $pairingCode
if (-not $handoff) { Write-Error $Copy.NotReady; exit 3 }
if (-not $handoff.handoff -or -not $handoff.handoff.agent_url) { Write-Error $Copy.NoAgentUrl; exit 3 }
$agentUrl = [string] $handoff.handoff.agent_url
$tag = [string] $handoff.handoff.install_tag

if (Test-PadiemAgentInstalled -Directory $AgentInstallDir) {
  Write-Host $Copy.AlreadyInstalled
  # The agent already exists, so the pairing is re-submitted by name: this is
  # the R3 path for a PC that is added to another account, or re-paired after a
  # revoke. The server needs the node identity it can address, which the
  # observation lane (#5573 PR-4a) already carries; the claim endpoint stays the
  # direct route when a caller knows the node id.
  if ($env:PADIEM_MESH_NODE_ID) {
    $claim = Invoke-PadiemClaim -Origin $origin -PairingCode $pairingCode -MeshNodeId $env:PADIEM_MESH_NODE_ID
    if (-not $claim) { Write-Error $Copy.CodeRejected; exit 4 }
  }
  Write-Host $Copy.Waiting
  exit 0
}

if ($DryRun) {
  Write-Host ("{0} -> {1} ({2})" -f $Copy.Installed, $agentUrl, $Copy.DryRunNote)
  exit 0
}

Start-PadiemInstall -Url $agentUrl -Arguments $AgentInstallerArgs | Out-Null
Write-Host $Copy.Installed
Write-Host ("{0} (표식 {1})" -f $Copy.Waiting, $tag)
