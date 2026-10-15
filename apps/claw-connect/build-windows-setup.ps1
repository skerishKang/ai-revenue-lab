# Windows stock IExpress SFX packager (no installer toolkit, no host Python).
# Run this after build-windows-standalone.ps1. The result is a single EXE
# containing a zipped, pinned one-directory Python/Resident runtime.
[CmdletBinding()]
param(
    [string]$BundleRoot,
    [string]$OutputExe
)
$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
if (-not $BundleRoot) {
    $BundleRoot = Join-Path (Split-Path (Split-Path $Here)) 'padiem-connector-standalone-0.1.0\dist\padiem-connector'
}
if (-not $OutputExe) {
    $OutputExe = Join-Path (Split-Path $Here) 'PADIEM-Connector-Setup-0.1.0.exe'
}
if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot 'padiem-connector.exe') -PathType Leaf)) {
    throw 'Build the standalone Connector before setup packaging.'
}
if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot '_internal\kagent\local_agent_resident_process.py') -PathType Leaf)) {
    throw 'The canonical Resident is missing from the bundle.'
}
$IExpress = Join-Path $env:WINDIR 'System32\iexpress.exe'
if (-not (Test-Path -LiteralPath $IExpress -PathType Leaf)) {
    throw 'Microsoft Windows IExpress packager is unavailable.'
}
$OutputExe = [System.IO.Path]::GetFullPath($OutputExe)
$Stage = Join-Path $env:TEMP ('PadiemConnectorSfx.' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $Here 'setup-standalone-launch.ps1') -Destination $Stage
    Copy-Item -LiteralPath (Join-Path $Here 'install-standalone.ps1') -Destination $Stage
    Compress-Archive -Path (Join-Path $BundleRoot '*') -DestinationPath (Join-Path $Stage 'connector-payload.zip') -CompressionLevel Optimal
    $SedTemplate = @'
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=__TARGET__
FriendlyName=PADIEM Connector
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -File setup-standalone-launch.ps1
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="setup-standalone-launch.ps1"
FILE1="install-standalone.ps1"
FILE2="connector-payload.zip"
[SourceFiles]
SourceFiles0=__STAGE__
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
'@
    $SedFile = Join-Path $Stage 'padiem-setup.sed'
    $SedText = $SedTemplate.Replace('__TARGET__', $OutputExe).Replace('__STAGE__', ($Stage + '\'))
    [System.IO.File]::WriteAllText($SedFile, $SedText, [System.Text.Encoding]::Default)
    & $IExpress /N /Q /M $SedFile
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputExe -PathType Leaf)) {
        throw 'IExpress did not produce a Windows customer setup EXE.'
    }
    $File = Get-Item -LiteralPath $OutputExe
    Write-Output (@{
        ok=$true
        setup_exe=$File.FullName
        bytes=$File.Length
        sha256=(Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash
        signed=($null -ne (Get-AuthenticodeSignature -FilePath $File.FullName).SignerCertificate)
    } | ConvertTo-Json -Compress)
} finally {
    if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue }
}
