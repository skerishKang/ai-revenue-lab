<#
.SYNOPSIS
  Launcher contract tests for the COM1 SSH forward (VBS -> CMD -> SSH).

.DESCRIPTION
  Runs the real background-tunnel.vbs / padiem-tunnel-wrapper.cmd /
  padiem-tunnel.cmd files against a stub stand-in for ssh and asserts:

    * the ssh exit code reaches the wrapper caller and the tunnel log;
    * a concurrent start is refused instead of creating a second forward;
    * the single-instance lock is released after the forward ends;
    * the VBS waits for the wrapper (bWaitOnReturn = True), which is what makes
      the Task Scheduler instance lifetime equal the ssh lifetime.

  No ssh connection is opened and no scheduled task, service or process outside
  this temporary directory is started or stopped.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tests/test_tunnel_launcher.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$script:Passes = 0
$script:Failures = 0

function Assert-Equal {
    param($Expected, $Actual, [string]$Label)
    if ([string]$Expected -eq [string]$Actual) { $script:Passes++; return }
    $script:Failures++
    Write-Output ("  FAIL {0}: expected [{1}] got [{2}]" -f $Label, $Expected, $Actual)
}

function Assert-True {
    param($Value, [string]$Label)
    if ([bool]$Value) { $script:Passes++; return }
    $script:Failures++
    Write-Output ("  FAIL {0}: expected true" -f $Label)
}

$sourceDir = Split-Path -Parent $PSScriptRoot
$work = Join-Path $env:TEMP ("com2-mesh-launcher-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null

$wrapperName = 'padiem-tunnel-wrapper.cmd'
$workerName = 'padiem-tunnel.cmd'
$vbsName = 'background-tunnel.vbs'
foreach ($f in @($wrapperName, $workerName, $vbsName)) {
    Copy-Item -LiteralPath (Join-Path $sourceDir $f) -Destination (Join-Path $work $f) -Force
}
Set-Content -LiteralPath (Join-Path $work 'padiem-tunnel-target.txt') -Value 'comp2' -Encoding ASCII

$marker = Join-Path $work 'stub-runs.txt'
$stub = Join-Path $work 'stub-ssh.cmd'
@(
    '@echo off',
    ('echo run >> "' + $marker + '"'),
    'ping -n 3 127.0.0.1 >nul',
    'exit /b 7'
) | Set-Content -LiteralPath $stub -Encoding ASCII

$logPath = Join-Path $work 'tunnel.log'
$wrapper = Join-Path $work $wrapperName
$lockDir = Join-Path $work 'padiem-tunnel.lock.d'

$env:PADIEM_SSH_EXE = $stub
$env:PADIEM_TUNNEL_LOG = $logPath

# --- static contract ------------------------------------------------------

Write-Output '-- launcher contract'
$vbsText = Get-Content -LiteralPath (Join-Path $work $vbsName) -Raw
$wrapperText = Get-Content -LiteralPath $wrapper -Raw
$workerText = Get-Content -LiteralPath (Join-Path $work $workerName) -Raw

Assert-True -Value ($vbsText -match ',\s*0,\s*True') -Label 'vbs waits for the wrapper'
Assert-True -Value (-not ($vbsText -match ',\s*0,\s*False')) -Label 'vbs no longer detaches'
Assert-True -Value ($vbsText -match 'GetParentFolderName') -Label 'vbs resolves its own directory'
Assert-True -Value ($wrapperText -match 'call\s+"%BASE%padiem-tunnel\.cmd"') -Label 'wrapper calls the worker'
Assert-True -Value ($wrapperText -match 'set\s+"RC=%ERRORLEVEL%"') -Label 'wrapper captures the worker exit code'
Assert-True -Value ($wrapperText -match 'endlocal\s*&\s*exit\s*/b\s*%RC%') -Label 'wrapper returns the worker exit code'
Assert-True -Value (-not ($wrapperText -match 'C:\\Users\\limone')) -Label 'wrapper has no machine-specific path'
Assert-True -Value ($workerText -match 'goto comp2') -Label 'worker branches with labels, not a block'
Assert-True -Value ($workerText -match 'call\s+"%SSH%"') -Label 'worker uses call so a stand-in returns control'
Assert-True -Value (-not ($workerText -match 'if\s+/i\s+"%TARGET%"=="comp2"\s*\(')) -Label 'worker has no parenthesised exit-code block'

# --- exit code propagation ------------------------------------------------

Write-Output '-- exit code propagation'
& $wrapper | Out-Null
$rc = $LASTEXITCODE
Assert-Equal -Expected 7 -Actual $rc -Label 'wrapper returns the ssh exit code'
Assert-True -Value (-not (Test-Path -LiteralPath $lockDir)) -Label 'lock released after a normal exit'
$logText = if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Raw } else { '' }
Assert-True -Value ($logText -match 'TUNNEL START') -Label 'start logged'
Assert-True -Value ($logText -match 'TUNNEL EXIT=7') -Label 'exit code logged'

# --- concurrent start -----------------------------------------------------

Write-Output '-- concurrent start'
Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
$first = Start-Process -FilePath $env:ComSpec -ArgumentList '/c', ('"' + $wrapper + '"') -PassThru -WindowStyle Hidden
Start-Sleep -Milliseconds 500
& $wrapper | Out-Null
$second = $LASTEXITCODE
$first.WaitForExit()
Assert-Equal -Expected 7 -Actual $first.ExitCode -Label 'first start keeps its own exit code'
Assert-Equal -Expected 3 -Actual $second -Label 'second start is refused'
$runs = if (Test-Path -LiteralPath $marker) { @(Get-Content -LiteralPath $marker).Count } else { 0 }
Assert-Equal -Expected 1 -Actual $runs -Label 'only one forward was launched'
$logText2 = Get-Content -LiteralPath $logPath -Raw
Assert-True -Value ($logText2 -match 'TUNNEL SKIP rc=already-running') -Label 'refusal is logged'

# --- release after completion --------------------------------------------

Write-Output '-- release after completion'
Assert-True -Value (-not (Test-Path -LiteralPath $lockDir)) -Label 'lock freed when the forward ends'
& $wrapper | Out-Null
Assert-Equal -Expected 7 -Actual $LASTEXITCODE -Label 'a later start works again'
$runs2 = if (Test-Path -LiteralPath $marker) { @(Get-Content -LiteralPath $marker).Count } else { 0 }
Assert-Equal -Expected 2 -Actual $runs2 -Label 'the later start launched the forward again'

# --- summary --------------------------------------------------------------

$summary = 'LAUNCHER SELFTEST PASS={0} FAIL={1} ARTIFACTS={2}' -f $script:Passes, $script:Failures, $work
Write-Output $summary
Remove-Item Env:\PADIEM_SSH_EXE -ErrorAction SilentlyContinue
Remove-Item Env:\PADIEM_TUNNEL_LOG -ErrorAction SilentlyContinue
if ($script:Failures -gt 0) { exit 1 }
Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
exit 0
