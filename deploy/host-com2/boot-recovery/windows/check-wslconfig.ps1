<#
.SYNOPSIS
  Checks the .wslconfig idle timeout and the distro's systemd setting (#4953).
.DESCRIPTION
  WSL2 shuts a distro VM down after an idle period; on a 24-hour server that
  means "all services stop until someone asks for a shell". This script reports:
    * vmIdleTimeout in %USERPROFILE%\.wslconfig and in the SYSTEM profile
      (the boot task runs WSL as SYSTEM), recommending a multi-day value;
    * [boot] systemd=true in /etc/wsl.conf inside the distro.
  Read-only by default. -Apply only CREATES a missing user .wslconfig with the
  recommended block; it never rewrites an existing file.
#>
[CmdletBinding()]
param(
  [string]$Distro = "Ubuntu",
  [long]$MinimumIdleMs = 2592000000,   # 30 days
  [switch]$Apply
)

$ErrorActionPreference = "Continue"
$recommend = "[wsl2]`nvmIdleTimeout=$([long]::MaxValue)"
$paths = @(
  (Join-Path $env:USERPROFILE ".wslconfig"),
  (Join-Path $env:SystemRoot "System32\config\systemprofile\.wslconfig")
)
$exit = 0
foreach ($path in $paths) {
  if (-not (Test-Path $path)) {
    Write-Output ("WSL_CONFIG=MISSING path=" + $path)
    $exit = 1
    continue
  }
  $lines = Get-Content -Path $path -ErrorAction SilentlyContinue
  $section = ""
  $value = $null
  foreach ($line in $lines) {
    if ($line -match '^\s*\[(.+)\]\s*$') { $section = $Matches[1].Trim().ToLower() }
    elseif ($section -eq "wsl2" -and $line -match '^\s*vmIdleTimeout\s*=\s*(-?\d+)') { $value = [long]$Matches[1] }
  }
  if ($null -eq $value) {
    Write-Output ("WSL_CONFIG=VM_IDLE_TIMEOUT_MISSING path=" + $path)
    Write-Output ("WSL_CONFIG_RECOMMEND=" + ($recommend -replace "`n", " "))
    $exit = 1
  }
  elseif ($value -ge 0 -and $value -lt $MinimumIdleMs) {
    Write-Output ("WSL_CONFIG=VM_IDLE_TIMEOUT_SHORT path=" + $path + " value=" + $value)
    $exit = 1
  }
  else {
    Write-Output ("WSL_CONFIG=VM_IDLE_TIMEOUT_OK path=" + $path + " value=" + $value)
  }
}

$wslConf = $null
try { $wslConf = (& wsl.exe -d $Distro -u root --exec /bin/sh -c "cat /etc/wsl.conf 2>/dev/null") -join "`n" } catch { }
if ($wslConf -match '(?m)^\s*boot\s*$[\s\S]*?systemd\s*=\s*true') {
  Write-Output "WSL_SYSTEMD=OK distro=$Distro"
}
else {
  Write-Output "WSL_SYSTEMD=MISSING_OR_UNREADABLE distro=$Distro (expected [boot] systemd=true in /etc/wsl.conf)"
  $exit = 1
}

if ($exit -ne 0 -and $Apply) {
  $userConfig = $paths[0]
  if (-not (Test-Path $userConfig)) {
    Set-Content -Path $userConfig -Value $recommend -Encoding ascii
    Write-Output ("WSL_CONFIG=CREATED path=" + $userConfig)
    Write-Output "WSL_CONFIG_NEXT=wsl --shutdown (in an approved window) then start WSL again"
  }
  else {
    Write-Output "WSL_CONFIG_ACTION=EDIT_REQUIRED (existing file left untouched)"
  }
}
exit $exit
