# Setup payload entry, launched by an IExpress self-extracting EXE.
# One bundled Connector installation, no host Python, no second login.
$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:TEMP ('PadiemConnectorSetup.' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Expand-Archive -LiteralPath (Join-Path $PSScriptRoot 'connector-payload.zip') -DestinationPath $dir -Force
    & (Join-Path $PSScriptRoot 'install-standalone.ps1') -BundleRoot $dir
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw 'PADIEM Connector setup failed.' }
} finally {
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }
}
