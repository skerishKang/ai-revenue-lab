# PADIEM customer Windows onefile setup. No host Python on customer PC.
[CmdletBinding()]
param([string]$BundleRoot, [string]$OutputExe)
$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
if (-not $BundleRoot) {
    $BundleRoot = Join-Path (Split-Path (Split-Path $Here)) 'padiem-connector-standalone-0.1.0\dist\padiem-connector'
}
if (-not $OutputExe) {
    $OutputExe = Join-Path (Split-Path $Here) 'PADIEM-Connector-Setup-0.1.0.exe'
}
if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot 'padiem-connector.exe') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $BundleRoot '_internal\kagent\local_agent_resident_process.py') -PathType Leaf)) {
    throw 'Build canonical Connector/Resident bundle first.'
}
$PyInstaller = Join-Path ([IO.Path]::GetTempPath()) 'padiem-standalone-buildvenv\Scripts\pyinstaller.exe'
if (-not (Test-Path -LiteralPath $PyInstaller -PathType Leaf)) {
    throw 'Missing packaging venv; run build-windows-standalone.ps1 first.'
}
$OutputExe = [IO.Path]::GetFullPath($OutputExe)
$OutputDir = Split-Path $OutputExe
$Name = [IO.Path]::GetFileNameWithoutExtension($OutputExe)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$Stage = Join-Path ([IO.Path]::GetTempPath()) ('padiem-setup-build-' + [guid]::NewGuid().ToString('N'))
New-Item $Stage -ItemType Directory -Force | Out-Null
try {
    $Zip = Join-Path $Stage 'connector-payload.zip'
    Compress-Archive -Path (Join-Path $BundleRoot '*') -DestinationPath $Zip -CompressionLevel Optimal
    $DataZip = "$Zip;."
    $DataInstaller = "$(Join-Path $Here 'install-standalone.ps1');."
    $Work = Join-Path $Stage 'work'
    & $PyInstaller --noconfirm --clean --onefile --console --name $Name --add-data $DataZip --add-data $DataInstaller --distpath $OutputDir --workpath $Work --specpath $Stage (Join-Path $Here 'packaged_setup.py')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputExe -PathType Leaf)) {
        throw 'PyInstaller did not produce the single-file setup EXE.'
    }
    $File = Get-Item -LiteralPath $OutputExe
    Write-Output (@{
        ok=$true; setup_exe=$File.FullName; bytes=$File.Length
        sha256=(Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash
        signed=($null -ne (Get-AuthenticodeSignature -FilePath $File.FullName).SignerCertificate)
    } | ConvertTo-Json -Compress)
} finally {
    if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue }
}
