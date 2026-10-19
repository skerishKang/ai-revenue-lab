# COM1-only task runner, current interactive Windows user + DPAPI secret.
$ErrorActionPreference = 'Stop'
$backup = Join-Path $PSScriptRoot 'grafana_com1_backup.py'
if (!(Test-Path -LiteralPath $backup)) { exit 4 }
$python = (Get-Command python -ErrorAction Stop).Source
& $python $backup
exit $LASTEXITCODE
