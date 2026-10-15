# PADIEM Connector — standalone Windows bundle builder (#4139 item 4).
#
# Produces a no-Prerequisites bundle directory: the Connector CLI plus the
# pinned kagent tree as data, runnable without system Python/Node/Git.
#   powershell -ExecutionPolicy Bypass -File build-windows-standalone.ps1
#
# Output: <repo>/../padiem-connector-standalone-<version>/
#   padiem-connector/padiem-connector.exe + _internal/ (runtime + kagent/)
# Pin PADIEM_AGENT_SRC at install time to <install>\_internal (it contains
# kagent/__init__.py and the other canonical Resident modules).
#
# This script only builds. Homepage publishing (download path, signatures)
# is a separate reviewed handoff; the bundle is unsigned.
[CmdletBinding()]
param(
    [string]$Python = (Get-Command python -ErrorAction SilentlyContinue).Source,
    [string]$OutRoot = (Join-Path (Split-Path $PSScriptRoot) ".." "padiem-connector-standalone-0.1.0"),
    [string]$WssPin = "websockets==17.2"
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$AgentSrc = Join-Path $Here "..\korean-ai-code-agent\src" -Resolve
$CoreSrc = Join-Path $Here "..\..\packages\padiem-ai-core" -Resolve
$VenvDir = Join-Path ([System.IO.Path]::GetTempPath()) "padiem-standalone-buildvenv"

if (-not $Python) { throw "Python 3.11+ is required to create the build venv." }
& $Python -m venv $VenvDir
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
& $VenvPython -m pip install --disable-pip-version-check pyinstaller $WssPin cryptography $CoreSrc
if ($LASTEXITCODE -ne 0) { throw "build venv dependency install failed." }

$DistDir = Join-Path $OutRoot "dist"
$WorkDir = Join-Path $OutRoot "work"
& (Join-Path $VenvDir "Scripts\pyinstaller.exe") `
    --noconfirm --clean --onedir --console --name padiem-connector `
    --paths (Join-Path $Here ".") `
    --paths $AgentSrc `
    --paths $CoreSrc `
    --collect-submodules claw_connect `
    --collect-submodules padiem_connector `
    --hidden-import kagent.local_agent_resident_process `
    --hidden-import padiem_ai_core.agent_approval `
    --add-data "$CoreSrc\padiem_ai_core;padiem_ai_core" `
    --add-data "$AgentSrc\kagent;kagent" `
    --distpath $DistDir --workpath $WorkDir `
    (Join-Path $Here "padiem_connector\__main__.py")
if ($LASTEXITCODE -ne 0) { throw "pyinstaller build failed." }

$Exe = Join-Path $DistDir "padiem-connector\padiem-connector.exe"
$Hash = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash
$Total = (Get-ChildItem -Recurse -LiteralPath (Join-Path $DistDir "padiem-connector") | Measure-Object Length -Sum).Sum
$Version = (& $Exe --version 2>$null | Select-Object -First 1)
Write-Output (@{
    ok = $true
    exe = $Exe
    sha256 = $Hash
    total_bytes = $Total
    version = "$Version"
    source_sha = (git -C $Here rev-parse HEAD)
} | ConvertTo-Json -Compress)
