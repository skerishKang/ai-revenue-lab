# PADIEM user-session helper — single-file Windows builder (#7108 PR-1).
#
# Produces a no-Python `padiem-user-helper.exe` from the existing helper
# modules. The artifact is onefile and windowed; the entrypoint adds
# CREATE_NO_WINDOW to child powershell/cmd processes.
#   powershell -ExecutionPolicy Bypass -File build-windows-helper.ps1
#
# This script only builds. Code signing is the same handoff as the connector
# setup: report whether a signer certificate is present; otherwise the SHA-256
# in the receipt is the verifiable identity until the signing step lands.
[CmdletBinding()]
param(
    [string]$Python = (Get-Command python -ErrorAction SilentlyContinue).Source,
    [string]$OutRoot = ""
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$BuildStarted = Get-Date

$VersionLine = Select-String -LiteralPath (Join-Path $Here "claw_connect\__init__.py") -Pattern '^CONNECT_VERSION = "([^"]+)"' | Select-Object -First 1
if (-not $VersionLine) { throw "CONNECT_VERSION not found in claw_connect\__init__.py" }
$ConnectVersion = $VersionLine.Matches[0].Groups[1].Value

if (-not $Python) { throw "Python 3.11+ is required to create the build venv." }
if (-not $OutRoot) {
    $OutRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("padiem-user-helper-" + $ConnectVersion)
}
$OutRoot = [System.IO.Path]::GetFullPath($OutRoot)
New-Item -ItemType Directory -Path $OutRoot -Force | Out-Null
$BuildLog = Join-Path $OutRoot "build.log"
$VenvDir = Join-Path ([System.IO.Path]::GetTempPath()) "padiem-helper-buildvenv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$PyInstaller = Join-Path $VenvDir "Scripts\pyinstaller.exe"

function Invoke-LoggedNative {
    # PyInstaller writes INFO lines to stderr. Windows PowerShell 5.1 turns a
    # redirected native stderr record into NativeCommandError under the script's
    # Stop preference, so native calls run with Continue and are judged by exit
    # code instead. Cmdlet errors still obey Stop.
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$What
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments *>> $LogPath
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($exitCode -ne 0) { throw "$What failed (exit $exitCode); see $LogPath" }
}

Write-Host "Building padiem-user-helper $ConnectVersion"
Write-Host "  output: $OutRoot"
Write-Host "  log:    $BuildLog"

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Invoke-LoggedNative -FilePath $Python -Arguments @("-m", "venv", $VenvDir) -LogPath $BuildLog -What "build venv creation"
}
Invoke-LoggedNative -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pyinstaller") -LogPath $BuildLog -What "PyInstaller install"

$DistDir = Join-Path $OutRoot "dist"
$WorkDir = Join-Path $OutRoot "work"
$PyInstallerStarted = Get-Date
Invoke-LoggedNative -FilePath $PyInstaller -Arguments @("--noconfirm", "--clean", "--distpath", $DistDir, "--workpath", $WorkDir, (Join-Path $Here "padiem-user-helper.spec")) -LogPath $BuildLog -What "PyInstaller build"

$Exe = Join-Path $DistDir "padiem-user-helper.exe"
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "PyInstaller did not produce $Exe" }
$File = Get-Item -LiteralPath $Exe
$Hash = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash
$Signed = $null -ne (Get-AuthenticodeSignature -FilePath $Exe).SignerCertificate
$BuildSeconds = [math]::Round(((Get-Date) - $BuildStarted).TotalSeconds, 1)
$PyInstallerSeconds = [math]::Round(((Get-Date) - $PyInstallerStarted).TotalSeconds, 1)

Write-Host ("Built {0} bytes in {1}s (PyInstaller {2}s), signed={3}" -f $File.Length, $BuildSeconds, $PyInstallerSeconds, $Signed)
Write-Output (@{
    ok = $true
    exe = $File.FullName
    bytes = $File.Length
    sha256 = $Hash
    signed = $Signed
    version = $ConnectVersion
    build_seconds = $BuildSeconds
    pyinstaller_seconds = $PyInstallerSeconds
    source_sha = (git -C $Here rev-parse HEAD)
    log = $BuildLog
} | ConvertTo-Json -Compress)
