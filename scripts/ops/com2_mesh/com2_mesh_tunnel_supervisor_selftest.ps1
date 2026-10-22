<#
.SYNOPSIS
  Process-level selftest for com2_mesh_tunnel_supervisor.ps1 and the task XML.

.DESCRIPTION
  Uses a local mock child process; no SSH connection, no real transport and no
  scheduled task is created. It verifies:

  - an exclusive lock refuses a second supervisor without touching the live
    state, and the job object kills the child when the supervisor is hard
    terminated;
  - failed children are retried with a capped backoff and a bounded budget;
  - a run at least tunnel_stable_seconds long resets the attempt budget;
  - a missing forward listener is treated as a failure and leaves no child;
  - the rendered task XML has a non-expiring five-minute repetition,
    StartWhenAvailable, IgnoreNew and an unlimited execution time, and the
    verifier rejects a mutated expired XML.

.PARAMETER SupervisorPath
  Path to com2_mesh_tunnel_supervisor.ps1.

.PARAMETER TemplateScriptPath
  Path to com2_mesh_task_template.ps1.

.PARAMETER KeepArtifacts
  Keep the temporary directory for inspection.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_tunnel_supervisor_selftest.ps1
#>
[CmdletBinding()]
param(
    [string]$SupervisorPath = '',
    [string]$TemplateScriptPath = '',
    [switch]$KeepArtifacts
)

if (-not $SupervisorPath) { $SupervisorPath = Join-Path $PSScriptRoot 'com2_mesh_tunnel_supervisor.ps1' }
if (-not $TemplateScriptPath) { $TemplateScriptPath = Join-Path $PSScriptRoot 'com2_mesh_task_template.ps1' }

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

function Assert-Contains {
    param([string]$Text, [string]$Token, [string]$Label)
    if ($Text -and $Text.Contains($Token)) { $script:Passes++; return }
    $script:Failures++
    Write-Output ("  FAIL {0}: missing token [{1}]" -f $Label, $Token)
}

function Write-JsonFile {
    param([string]$Path, $Object)
    $json = $Object | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-FreeTcpPort {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Parse('127.0.0.1'), 0)
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

function New-MockChild {
    param([string]$Path)
    $text = @'
param(
    [switch]$Listen,
    [string]$ListenHost = '127.0.0.1',
    [int]$ListenPort = 0,
    [string]$CounterFile = '',
    [double]$SleepSeconds = 0,
    [int]$ExitCode = 0
)
if ($CounterFile) {
    if (Test-Path -LiteralPath $CounterFile) { exit $ExitCode }
    Set-Content -LiteralPath $CounterFile -Value 'first'
}
if ($Listen) {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Parse($ListenHost), $ListenPort)
    $listener.Start()
    try {
        $deadline = (Get-Date).AddSeconds(300)
        while ((Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    } finally {
        $listener.Stop()
    }
    exit $ExitCode
}
if ($SleepSeconds -gt 0) { Start-Sleep -Milliseconds ([int]($SleepSeconds * 1000)) }
exit $ExitCode
'@
    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

function New-SupConfig {
    param(
        [string]$Directory,
        [int]$Port,
        [string]$MockChild,
        [string[]]$ChildArguments,
        [hashtable]$Overrides = @{}
    )
    $cfg = [ordered]@{
        com2_host = '192.0.2.10'
        com2_ssh_port = 22
        com2_ssh_user = 'selftest'
        com2_ssh_key = (Join-Path $Directory 'id_selftest')
        tunnel_local_host = '127.0.0.1'
        tunnel_local_port = $Port
        tunnel_lock_file = (Join-Path $Directory 'tunnel.lock')
        tunnel_state_file = (Join-Path $Directory 'tunnel-state.json')
        tunnel_log = (Join-Path $Directory 'tunnel.log')
        tunnel_stable_seconds = 30
        tunnel_backoff_schedule_seconds = @(0)
        tunnel_max_attempts = 2
        tunnel_ready_wait_seconds = 3
        tunnel_require_listener = $false
        tunnel_child_path = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
        tunnel_child_arguments = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $MockChild) + @($ChildArguments)
    }
    foreach ($k in $Overrides.Keys) { $cfg[$k] = $Overrides[$k] }
    return $cfg
}

function Start-SupProcess {
    param([string]$ScriptPath, [string]$ConfigPath)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = ConvertTo-ArgumentString -Arguments @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath, '-Config', $ConfigPath)
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = 'Hidden'
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    if (-not $proc.Start()) { throw 'supervisor process did not start' }
    return $proc
}

function Wait-SupState {
    param([string]$Path, [string]$State, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $Path) {
            try {
                $obj = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
                if (-not $State -or [string]$obj.state -eq $State) { return $obj }
            } catch { }
        }
        Start-Sleep -Milliseconds 150
    }
    return $null
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json) } catch { return $null }
}

function Stop-SupProcess {
    param($Process)
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) { $Process.Kill() }
    } catch { }
    try { [void]$Process.WaitForExit(5000) } catch { }
    try { $Process.Dispose() } catch { }
}

function Get-MockChildProcesses {
    param([string]$MockPath)
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains($MockPath) })
    } catch {
        return @()
    }
}

# --- setup ----------------------------------------------------------------

if (-not (Test-Path -LiteralPath $SupervisorPath)) {
    Write-Output ("FAIL supervisor not found: {0}" -f $SupervisorPath)
    exit 1
}
if (-not (Test-Path -LiteralPath $TemplateScriptPath)) {
    Write-Output ("FAIL task template script not found: {0}" -f $TemplateScriptPath)
    exit 1
}

$work = Join-Path $env:TEMP ("com2-tunnel-selftest-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null
$mockChild = Join-Path $work 'mock-child.ps1'
New-MockChild -Path $mockChild

. $SupervisorPath -FunctionsOnly

Write-Output '-- argument quoting and config'
Assert-Equal -Expected '"a b"' -Actual (ConvertTo-ArgumentString -Arguments @('a b')) -Label 'quote space'
Assert-Equal -Expected '"c\"d"' -Actual (ConvertTo-ArgumentString -Arguments @('c"d')) -Label 'quote quote'
Assert-Equal -Expected '"a b\\"' -Actual (ConvertTo-ArgumentString -Arguments @('a b\')) -Label 'quote trailing slash'
$baseConfigDir = Join-Path $work 'config'
New-Item -ItemType Directory -Path $baseConfigDir -Force | Out-Null
$baseConfig = New-SupConfig -Directory $baseConfigDir -Port 4443 -MockChild $mockChild -ChildArguments @()
foreach ($optional in @('tunnel_ssh_path', 'tunnel_ssh_log', 'tunnel_stable_seconds',
        'tunnel_backoff_schedule_seconds', 'tunnel_max_attempts', 'tunnel_ready_wait_seconds',
        'tunnel_require_listener', 'tunnel_child_path', 'tunnel_child_arguments')) {
    $baseConfig.Remove($optional)
}
$baseConfigPath = Join-Path $baseConfigDir 'config.json'
Write-JsonFile -Path $baseConfigPath -Object $baseConfig
$loadedSup = Get-SupervisorConfig -Path $baseConfigPath
Assert-Equal -Expected 5 -Actual $loadedSup.tunnel_max_attempts -Label 'config max attempts default'
Assert-Equal -Expected 120 -Actual $loadedSup.tunnel_stable_seconds -Label 'config stable default'
Assert-Equal -Expected 15 -Actual $loadedSup.tunnel_ready_wait_seconds -Label 'config ready wait default'
Assert-Equal -Expected 'True' -Actual $loadedSup.tunnel_require_listener -Label 'config require listener default'
Assert-Equal -Expected 5 -Actual (Get-SupBackoffSeconds -Cfg $loadedSup -AttemptCount 1) -Label 'backoff first'
Assert-Equal -Expected 60 -Actual (Get-SupBackoffSeconds -Cfg $loadedSup -AttemptCount 9) -Label 'backoff capped'

$badConfig = New-SupConfig -Directory $baseConfigDir -Port 4443 -MockChild $mockChild -ChildArguments @()
$badConfig.Remove('tunnel_lock_file')
$badConfigPath = Join-Path $work 'config-bad.json'
Write-JsonFile -Path $badConfigPath -Object $badConfig
$badReported = $false
try { [void](Get-SupervisorConfig -Path $badConfigPath) } catch { $badReported = $true }
Assert-True -Value $badReported -Label 'missing config key rejected'

# --- single instance and child lifetime -----------------------------------

Write-Output '-- single instance and child lifetime'
$singleDir = Join-Path $work 'single'
New-Item -ItemType Directory -Path $singleDir -Force | Out-Null
$singlePort = Get-FreeTcpPort
$singleCfg = New-SupConfig -Directory $singleDir -Port $singlePort -MockChild $mockChild -ChildArguments @(
    '-Listen', '-ListenHost', '127.0.0.1', '-ListenPort', [string]$singlePort) -Overrides @{
    tunnel_require_listener = $true
    tunnel_ready_wait_seconds = 10
    tunnel_max_attempts = 2
}
$singleCfgPath = Join-Path $singleDir 'config.json'
Write-JsonFile -Path $singleCfgPath -Object $singleCfg
$singleStatePath = Join-Path $singleDir 'tunnel-state.json'
$singleLogPath = Join-Path $singleDir 'tunnel.log'

$first = Start-SupProcess -ScriptPath $SupervisorPath -ConfigPath $singleCfgPath
$firstState = Wait-SupState -Path $singleStatePath -State 'forwarding' -TimeoutSeconds 25
Assert-True -Value ($null -ne $firstState) -Label 'first supervisor reaches forwarding'
$firstChildPid = 0
if ($firstState) { $firstChildPid = [int]$firstState.child_pid }
Assert-True -Value ($firstChildPid -gt 0) -Label 'first supervisor owns a child'
Assert-True -Value ($null -ne (Get-Process -Id $firstChildPid -ErrorAction SilentlyContinue)) -Label 'child is alive while forwarding'

$second = Start-SupProcess -ScriptPath $SupervisorPath -ConfigPath $singleCfgPath
$secondExited = $second.WaitForExit(15000)
Assert-True -Value $secondExited -Label 'second supervisor exits'
if ($secondExited) { Assert-Equal -Expected 2 -Actual $second.ExitCode -Label 'second supervisor refuses duplicate' }
Stop-SupProcess -Process $second
$liveState = Read-JsonFile -Path $singleStatePath
Assert-Equal -Expected 'forwarding' -Actual $liveState.state -Label 'duplicate does not overwrite live state'
$singleLog = if (Test-Path -LiteralPath $singleLogPath) { Get-Content -LiteralPath $singleLogPath -Raw } else { '' }
Assert-Contains -Text $singleLog -Token 'duplicate_refused' -Label 'duplicate is logged'

Stop-SupProcess -Process $first
Start-Sleep -Milliseconds 1500
$orphan = Get-Process -Id $firstChildPid -ErrorAction SilentlyContinue
Assert-True -Value ($null -eq $orphan) -Label 'job object kills child on hard stop'

# --- bounded retry --------------------------------------------------------

Write-Output '-- bounded retry'
$retryDir = Join-Path $work 'retry'
New-Item -ItemType Directory -Path $retryDir -Force | Out-Null
$retryCfg = New-SupConfig -Directory $retryDir -Port (Get-FreeTcpPort) -MockChild $mockChild -ChildArguments @(
    '-ExitCode', '7') -Overrides @{
    tunnel_require_listener = $false
    tunnel_stable_seconds = 30
    tunnel_backoff_schedule_seconds = @(0, 0, 0)
    tunnel_max_attempts = 2
}
$retryCfgPath = Join-Path $retryDir 'config.json'
Write-JsonFile -Path $retryCfgPath -Object $retryCfg
$retryStatePath = Join-Path $retryDir 'tunnel-state.json'
$retryLogPath = Join-Path $retryDir 'tunnel.log'
$retryProc = Start-SupProcess -ScriptPath $SupervisorPath -ConfigPath $retryCfgPath
$retryExited = $retryProc.WaitForExit(25000)
Assert-True -Value $retryExited -Label 'retry supervisor exits after budget'
if ($retryExited) { Assert-Equal -Expected 3 -Actual $retryProc.ExitCode -Label 'retry supervisor exit code' }
Stop-SupProcess -Process $retryProc
$retryState = Read-JsonFile -Path $retryStatePath
Assert-Equal -Expected 'exhausted' -Actual $retryState.state -Label 'retry state exhausted'
Assert-Equal -Expected 2 -Actual $retryState.attempt -Label 'retry attempt count bounded'
Assert-Equal -Expected 7 -Actual $retryState.last_exit_code -Label 'retry last exit code'
$retryLog = if (Test-Path -LiteralPath $retryLogPath) { Get-Content -LiteralPath $retryLogPath -Raw } else { '' }
Assert-Contains -Text $retryLog -Token 'child_exit' -Label 'retry logs child exit'
Assert-Contains -Text $retryLog -Token 'retry_exhausted' -Label 'retry logs exhaustion'
Assert-True -Value (@(Get-MockChildProcesses -MockPath $mockChild).Count -eq 0) -Label 'retry leaves no child'

# --- stable run resets the budget ----------------------------------------

Write-Output '-- stable run reset'
$stableDir = Join-Path $work 'stable'
New-Item -ItemType Directory -Path $stableDir -Force | Out-Null
$counterFile = Join-Path $stableDir 'runs.counter'
$stableCfg = New-SupConfig -Directory $stableDir -Port (Get-FreeTcpPort) -MockChild $mockChild -ChildArguments @(
    '-CounterFile', $counterFile, '-SleepSeconds', '1.5', '-ExitCode', '8') -Overrides @{
    tunnel_require_listener = $false
    tunnel_stable_seconds = 1
    tunnel_backoff_schedule_seconds = @(0, 0, 0)
    tunnel_max_attempts = 2
}
$stableCfgPath = Join-Path $stableDir 'config.json'
Write-JsonFile -Path $stableCfgPath -Object $stableCfg
$stableStatePath = Join-Path $stableDir 'tunnel-state.json'
$stableProc = Start-SupProcess -ScriptPath $SupervisorPath -ConfigPath $stableCfgPath
$stableExited = $stableProc.WaitForExit(30000)
Assert-True -Value $stableExited -Label 'stable supervisor exits after budget'
if ($stableExited) { Assert-Equal -Expected 3 -Actual $stableProc.ExitCode -Label 'stable supervisor exit code' }
Stop-SupProcess -Process $stableProc
$stableState = Read-JsonFile -Path $stableStatePath
Assert-Equal -Expected 'exhausted' -Actual $stableState.state -Label 'stable state exhausted'
Assert-Equal -Expected 1 -Actual $stableState.stable_runs -Label 'stable run counted'
Assert-Equal -Expected 2 -Actual $stableState.attempt -Label 'stable run reset the attempt budget'
Assert-True -Value ([double]$stableState.last_run_seconds -lt 0.5) -Label 'last run is the short failure'

# --- listener readiness failure ------------------------------------------

Write-Output '-- listener readiness'
$readyDir = Join-Path $work 'ready'
New-Item -ItemType Directory -Path $readyDir -Force | Out-Null
$readyCfg = New-SupConfig -Directory $readyDir -Port (Get-FreeTcpPort) -MockChild $mockChild -ChildArguments @(
    '-SleepSeconds', '30') -Overrides @{
    tunnel_require_listener = $true
    tunnel_ready_wait_seconds = 1
    tunnel_stable_seconds = 30
    tunnel_max_attempts = 1
}
$readyCfgPath = Join-Path $readyDir 'config.json'
Write-JsonFile -Path $readyCfgPath -Object $readyCfg
$readyStatePath = Join-Path $readyDir 'tunnel-state.json'
$readyProc = Start-SupProcess -ScriptPath $SupervisorPath -ConfigPath $readyCfgPath
$readyExited = $readyProc.WaitForExit(25000)
Assert-True -Value $readyExited -Label 'readiness supervisor exits'
if ($readyExited) { Assert-Equal -Expected 3 -Actual $readyProc.ExitCode -Label 'readiness supervisor exit code' }
Stop-SupProcess -Process $readyProc
$readyState = Read-JsonFile -Path $readyStatePath
Assert-Equal -Expected 'exhausted' -Actual $readyState.state -Label 'readiness state exhausted'
Assert-Contains -Text ([string]$readyState.last_error) -Token 'forward listener' -Label 'readiness error recorded'
Assert-True -Value (@(Get-MockChildProcesses -MockPath $mockChild).Count -eq 0) -Label 'readiness leaves no child'

# --- foreign listener is not accepted -------------------------------------

Write-Output '-- foreign listener is not accepted'
$foreignPort = Get-FreeTcpPort
$foreignListener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Parse('127.0.0.1'), $foreignPort)
$foreignListener.Start()
try {
    $foreignDir = Join-Path $work 'foreign'
    New-Item -ItemType Directory -Path $foreignDir -Force | Out-Null
    $foreignCfg = New-SupConfig -Directory $foreignDir -Port $foreignPort -MockChild $mockChild -ChildArguments @(
        '-SleepSeconds', '30') -Overrides @{
        tunnel_require_listener = $true
        tunnel_ready_wait_seconds = 1
        tunnel_stable_seconds = 30
        tunnel_max_attempts = 1
    }
    $foreignCfgPath = Join-Path $foreignDir 'config.json'
    Write-JsonFile -Path $foreignCfgPath -Object $foreignCfg
    $foreignStatePath = Join-Path $foreignDir 'tunnel-state.json'
    $foreignProc = Start-SupProcess -ScriptPath $SupervisorPath -ConfigPath $foreignCfgPath
    $foreignExited = $foreignProc.WaitForExit(25000)
    Assert-True -Value $foreignExited -Label 'foreign listener supervisor exits'
    if ($foreignExited) { Assert-Equal -Expected 3 -Actual $foreignProc.ExitCode -Label 'foreign listener supervisor exit code' }
    Stop-SupProcess -Process $foreignProc
    $foreignState = Read-JsonFile -Path $foreignStatePath
    Assert-Equal -Expected 'exhausted' -Actual $foreignState.state -Label 'foreign listener state exhausted'
    Assert-Contains -Text ([string]$foreignState.last_error) -Token 'forward listener' -Label 'foreign listener is not ready'
    Assert-True -Value (@(Get-MockChildProcesses -MockPath $mockChild).Count -eq 0) -Label 'foreign listener leaves no child'
} finally {
    try { $foreignListener.Stop() } catch { }
}

# --- task XML -------------------------------------------------------------

Write-Output '-- task XML'
$taskOut = Join-Path $work 'tunnel-task.xml'
$renderUser = 'SELFTEST\User'
$renderBoundary = '2026-10-23T00:00:00'
$renderShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$renderSupervisor = 'C:\Ops\com2_mesh_tunnel_supervisor.ps1'
$renderConfig = 'C:\Ops\com2-mesh-config.json'
$renderWorkDir = 'C:\Ops'
$renderOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $TemplateScriptPath `
    -OutputPath $taskOut -TaskUser $renderUser -StartBoundary $renderBoundary `
    -PowerShellPath $renderShell -SupervisorPath $renderSupervisor `
    -ConfigPath $renderConfig -WorkingDirectory $renderWorkDir 2>&1
$renderExit = $LASTEXITCODE
Assert-Equal -Expected 0 -Actual $renderExit -Label 'task render exit'
Assert-True -Value (Test-Path -LiteralPath $taskOut) -Label 'task xml written'
$taskText = if (Test-Path -LiteralPath $taskOut) { Get-Content -LiteralPath $taskOut -Raw } else { '' }
Assert-True -Value ($taskText -notmatch '\{\{') -Label 'no placeholder remains'
$taskBytes = [System.IO.File]::ReadAllBytes($taskOut)
Assert-Equal -Expected 255 -Actual $taskBytes[0] -Label 'task xml utf16 bom high'
Assert-Equal -Expected 254 -Actual $taskBytes[1] -Label 'task xml utf16 bom low'

. $TemplateScriptPath -FunctionsOnly
$expectedTask = @{
    task_user = $renderUser
    start_boundary = $renderBoundary
    powershell_path = $renderShell
    supervisor_path = $renderSupervisor
    config_path = $renderConfig
    working_directory = $renderWorkDir
}
$taskViolations = Get-TaskXmlViolations -XmlText $taskText -Expected $expectedTask
Assert-Equal -Expected 0 -Actual @($taskViolations).Count -Label 'rendered task has no violations'
Assert-True -Value (-not $taskText.Contains('<Duration>')) -Label 'rendered repetition has no duration'
Assert-True -Value ($taskText.Contains('<StartWhenAvailable>true</StartWhenAvailable>')) -Label 'start when available'
Assert-True -Value ($taskText.Contains('<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>')) -Label 'ignore new'

$expiredText = $taskText.Replace('<Repetition>', '<Repetition><Duration>P1D</Duration>')
$expiredViolations = Get-TaskXmlViolations -XmlText $expiredText -Expected $expectedTask
Assert-True -Value (@($expiredViolations) -contains 'repetition_duration_present') -Label 'expired repetition is rejected'

$noStartWhenAvailable = $taskText.Replace(
    '<StartWhenAvailable>true</StartWhenAvailable>',
    '<StartWhenAvailable>false</StartWhenAvailable>')
$swaViolations = Get-TaskXmlViolations -XmlText $noStartWhenAvailable -Expected $expectedTask
Assert-True -Value (@($swaViolations) -contains 'start_when_available_not_true') -Label 'start when available is checked'

$wrongUser = Get-TaskXmlViolations -XmlText $taskText -Expected @{ task_user = 'OTHER\User' }
Assert-True -Value (@($wrongUser) -contains 'principal_user_mismatch') -Label 'principal user is checked'

# --- summary --------------------------------------------------------------

$summary = 'SUPERVISOR SELFTEST PASS={0} FAIL={1} ARTIFACTS={2}' -f $script:Passes, $script:Failures, $work
Write-Output $summary
if ($script:Failures -gt 0) { exit 1 }
if (-not $KeepArtifacts) {
    try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue } catch { }
}
exit 0
