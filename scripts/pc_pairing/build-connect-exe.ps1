<#
.SYNOPSIS
  Build the double-click PC connect program and publish its reviewed bytes.

.DESCRIPTION
  Compiles scripts/pc_pairing/connect-exe with the .NET Framework compiler that
  ships with Windows - no SDK, no package download, nothing else to install on the
  machine that produces the artifact. There is no code signature and none is
  planned: the product's own name is carried in the file's version resource instead,
  and the unsigned warning is documented rather than avoided.

  Two things make this more than a call to csc:

  * Reproducibility. The Framework compiler writes a random module id and a
    compile-time stamp into every assembly, so two builds of one source differ for
    reasons no reviewer can see. The byte work lives in
    scripts/pc_pairing/connect-exe/win32_reproducible.py, which also writes the
    version resource. This script builds twice into separate folders and refuses to
    publish unless the two results hash identically. Same source, same bytes - or no
    artifact at all.
  * The reviewed artifact travels as a Python module. Chat serves these exact bytes
    to the browser, and the digest is pinned in the same file that carries them, so
    what a PC downloads cannot drift from what was reviewed here. The build prints
    the digest and writes it into the module and the docs line.

  The built program is then asked about itself with --check, which installs nothing,
  so a broken artifact cannot reach a person's Downloads folder.

.EXAMPLE
  Set-ExecutionPolicy -Scope Process Bypass
  .\build-connect-exe.ps1
#>
[CmdletBinding()]
param(
  [string] $OutputExe = "",
  [string] $AssetModule = "",
  [string] $DocsMemo = "",
  [switch] $SkipReproducibleCheck
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$Source = Join-Path $PSScriptRoot "connect-exe\PadiemPcConnect.cs"
$Manifest = Join-Path $PSScriptRoot "connect-exe\app.manifest"
$Bytes = Join-Path $PSScriptRoot "connect-exe\win32_reproducible.py"
$ExeName = "padiem-pc-connect.exe"
$Compiler = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not $OutputExe) { $OutputExe = Join-Path $PSScriptRoot "connect-exe\dist\$ExeName" }
if (-not $AssetModule) { $AssetModule = Join-Path $Root "apps\padiem-chat\app\pc_pairing_connect_exe_asset.py" }
if (-not $DocsMemo) { $DocsMemo = Join-Path $Root "docs\operations\PC_CONNECT_EXE_20261028.md" }

foreach ($required in @($Source, $Manifest, $Bytes, $Compiler)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "build input missing: $required" }
}
$Python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Python) { throw "python is required to normalize the compiled bytes" }
# Parsed before it is embedded: a manifest Windows cannot read turns into a
# side-by-side error on the person's PC, which says nothing about the comma that
# caused it.
try { [void][Xml](Get-Content -LiteralPath $Manifest -Raw) }
catch { throw "connect_exe_manifest_not_well_formed" }

function Get-FileHashHex {
  param([string] $Path)
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    # Hashed with line feeds only: a checkout that materialized CRLF is the same
    # source, and the seed must not move because of a machine's core.autocrlf.
    $text = [IO.File]::ReadAllText($Path).Replace("`r`n", "`n")
    $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))
    return $hash.Replace("-", "").ToLowerInvariant()
  } finally { $sha.Dispose() }
}

function Get-CombinedSeed {
  # One seed over the code, the manifest and the byte work: all three decide the
  # artifact. It replaces the module id the compiler would otherwise pick at random,
  # so a source change moves the digest and a rebuild of unchanged source does not.
  $joined = (Get-FileHashHex $Source) + (Get-FileHashHex $Manifest) + (Get-FileHashHex $Bytes)
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($joined)))
    return $hash.Replace("-", "").ToLowerInvariant()
  } finally { $sha.Dispose() }
}

function Invoke-Compile {
  param([string] $Directory, [string] $Seed)
  # Compiled into its own folder under the final file name: the compiler writes that
  # name into the assembly, so a build under another name is a different file.
  New-Item -ItemType Directory -Force -Path $Directory | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Directory -Force
  # The manifest travels into the file byte for byte, so it is staged with the line
  # endings the seed was computed over: otherwise a machine that checked the source
  # out with CRLF would build a different artifact from the same reviewed source.
  [IO.File]::WriteAllText((Join-Path $Directory "app.manifest"),
    [IO.File]::ReadAllText($Manifest).Replace("`r`n", "`n"),
    (New-Object Text.UTF8Encoding($false)))
  $arguments = @(
    "/nologo", "/noconfig", "/target:exe", "/optimize+", "/platform:anycpu", "/debug-",
    "/codepage:65001", "/reference:System.dll", "/win32manifest:app.manifest",
    "/out:$ExeName", "PadiemPcConnect.cs"
  )
  # Every path this function touches is absolute: the two builds run in one process,
  # and a working directory left behind by the first would be the second one's
  # input folder.
  $compiled = Join-Path $Directory $ExeName
  $normalized = Join-Path $Directory "normalized-$ExeName"
  $worked = Start-Process -FilePath $Compiler -ArgumentList $arguments -WorkingDirectory $Directory `
    -NoNewWindow -Wait -PassThru
  if ($worked.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $compiled)) {
    throw "connect_exe_compile_failed_$($worked.ExitCode)"
  }
  $byte_arguments = @(
    "`"$Bytes`"", "--in", "`"$compiled`"", "--out", "`"$normalized`"", "--seed", "`"$Seed`""
  )
  $bytes = Start-Process -FilePath $Python.Source -ArgumentList $byte_arguments `
    -WorkingDirectory $Directory -NoNewWindow -Wait -PassThru
  if ($bytes.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $normalized)) {
    throw "connect_exe_normalize_failed"
  }
  return $normalized
}

function Get-FileDigestHex {
  param([string] $Path)
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    $hash = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path)))
    return $hash.Replace("-", "").ToLowerInvariant()
  } finally { $sha.Dispose() }
}

$Seed = Get-CombinedSeed
$builds = @()
$rounds = 2
if ($SkipReproducibleCheck) { $rounds = 1 }
for ($round = 1; $round -le $rounds; $round++) {
  $directory = Join-Path $env:TEMP ("padiem-connect-build-" + [guid]::NewGuid().ToString("N"))
  $builds += ,(Invoke-Compile $directory $Seed)
}

$digests = @($builds | ForEach-Object { Get-FileDigestHex $_ })
$digest = $digests[0]
$reproducible = 1
if (-not $SkipReproducibleCheck) {
  foreach ($other in $digests) { if ($other -ne $digest) { $reproducible = 0 } }
  if ($reproducible -ne 1) {
    Write-Output "CONNECT_EXE_REPRODUCIBLE=0"
    Write-Output "CONNECT_EXE_BUILDS=$($digests -join ',')"
    throw "connect_exe_not_reproducible"
  }
  # The second build's bytes are compared and then thrown away; nothing but the
  # verified artifact leaves this script.
  Remove-Item -LiteralPath ([IO.Path]::GetDirectoryName($builds[1])) -Recurse -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($OutputExe)) | Out-Null
Copy-Item -LiteralPath $builds[0] -Destination $OutputExe -Force
Remove-Item -LiteralPath ([IO.Path]::GetDirectoryName($builds[0])) -Recurse -Force -ErrorAction SilentlyContinue
$artifactBytes = (Get-Item -LiteralPath $OutputExe).Length

# --check on the file that was just produced: the artifact is runnable and reports
# its own shape before anything ships it.
$probe = @(& $OutputExe --check 2>&1)
$probeExit = [int]$LASTEXITCODE
if ($probeExit -ne 0 -or -not (($probe -join " ") -match "CONNECT_EXE_CHECK=")) {
  throw "connect_exe_self_check_failed_$probeExit"
}

# ---- publish the reviewed bytes as a Python module -------------------------
$base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($OutputExe))
$lines = @()
for ($cursor = 0; $cursor -lt $base64.Length; $cursor += 76) {
  $take = [Math]::Min(76, $base64.Length - $cursor)
  $lines += $base64.Substring($cursor, $take)
}
$payload = $lines -join "`n"

$module = @"
"""#5573 follow-up: the double-click PC connect program, as reviewed bytes.

Generated by scripts/pc_pairing/build-connect-exe.ps1 from
scripts/pc_pairing/connect-exe/PadiemPcConnect.cs, its app.manifest and
win32_reproducible.py. Do not edit by hand: rebuilding from that source reproduces
these bytes exactly, and the digest below is what that build verified.

Why the program travels inside a Python module instead of as a file on a disk the
server reads: Chat runs as a Worker, where the only bytes guaranteed to be served
are the bytes that ship with the code. Keeping the artifact and its digest in one
reviewed file is also what makes drift impossible to miss - a reader sees both.

Nothing here is secret: the program carries no credential, no account and no
signature. The per-account pairing tag is appended by the route at download time,
never built in.
"""
from __future__ import annotations

import base64
import hashlib

PC_PAIRING_CONNECT_EXE_FILENAME = "$ExeName"
PC_PAIRING_CONNECT_EXE_SHA256 = "$digest"
PC_PAIRING_CONNECT_EXE_BYTES = $artifactBytes
PC_PAIRING_CONNECT_EXE_BUILD = "scripts/pc_pairing/build-connect-exe.ps1"
PC_PAIRING_CONNECT_EXE_SEED = "$Seed"

_PAYLOAD = """
$payload
"""


def connect_exe_bytes() -> bytes:
    """The exact bytes the build verified, or a refusal when they are not there.

    Checked on every read rather than once at import: a truncated checkout or a
    hand-edited payload must not reach a PC, because what a person downloads from
    this route is the program they will run as administrator.
    """
    data = base64.b64decode(_PAYLOAD)
    if len(data) != PC_PAIRING_CONNECT_EXE_BYTES:
        raise ValueError("pc_connect_exe_size")
    if hashlib.sha256(data).hexdigest() != PC_PAIRING_CONNECT_EXE_SHA256:
        raise ValueError("pc_connect_exe_digest")
    if data[:2] != b"MZ":
        raise ValueError("pc_connect_exe_not_executable")
    return data
"@
[IO.File]::WriteAllText($AssetModule, $module.Replace("`r`n", "`n"),
  (New-Object Text.UTF8Encoding($false)))

Write-Output "CONNECT_EXE=$OutputExe"
Write-Output "CONNECT_EXE_BYTES=$artifactBytes"
Write-Output "CONNECT_EXE_SHA256=$digest"
Write-Output "CONNECT_EXE_REPRODUCIBLE=$reproducible"
Write-Output "CONNECT_EXE_SEED=$Seed"
Write-Output "CONNECT_EXE_ASSET_MODULE=$AssetModule"
Write-Output "CONNECT_EXE_CHECK=$($probe -join ';')"

if (Test-Path -LiteralPath $DocsMemo) {
  # The install guide has to carry the same number the build just proved, so the
  # build refreshes the line it owns instead of leaving a second copy to rot.
  $text = [IO.File]::ReadAllText($DocsMemo)
  $updated = $text -replace '(?m)^CONNECT_EXE_SHA256=.*$', "CONNECT_EXE_SHA256=$digest"
  if ($updated -ne $text) {
    [IO.File]::WriteAllText($DocsMemo, $updated, (New-Object Text.UTF8Encoding($false)))
    Write-Output "CONNECT_EXE_DOCS_UPDATED=$DocsMemo"
  }
}
