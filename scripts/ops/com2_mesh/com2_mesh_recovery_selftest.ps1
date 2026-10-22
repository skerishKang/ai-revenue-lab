<#
.SYNOPSIS
  Fixture-driven selftest for com2_mesh_recovery.ps1.

.DESCRIPTION
  Runs the recovery engine in Simulate mode against local fixtures and asserts
  the selected class, the selected action, the log/status contract and the
  "Simulate never executes an action" rule. It also checks configuration
  validation, lock handling, state persistence and the Windows argument-quoting
  helper. No network probe and no recovery action is executed.

.PARAMETER EnginePath
  Path to com2_mesh_recovery.ps1.

.PARAMETER KeepArtifacts
  Keep the temporary fixture/log directory for inspection.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_recovery_selftest.ps1
#>
[CmdletBinding()]
param(
    [string]$EnginePath = '',
    [switch]$KeepArtifacts
)

if (-not $EnginePath) {
    $EnginePath = Join-Path $PSScriptRoot 'com2_mesh_recovery.ps1'
}

$ErrorActionPreference = 'Stop'
$script:Passes = 0
$script:Failures = 0

function Assert-Equal {
    param($Expected, $Actual, [string]$Label)
    if ([string]$Expected -eq [string]$Actual) {
        $script:Passes++
        return
    }
    $script:Failures++
    Write-Output ("  FAIL {0}: expected [{1}] got [{2}]" -f $Label, $Expected, $Actual)
}

function Assert-True {
    param($Value, [string]$Label)
    if ([bool]$Value) {
        $script:Passes++
        return
    }
    $script:Failures++
    Write-Output ("  FAIL {0}: expected true" -f $Label)
}

function Assert-Contains {
    param([string]$Text, [string]$Token, [string]$Label)
    if ($Text -and $Text.Contains($Token)) {
        $script:Passes++
        return
    }
    $script:Failures++
    Write-Output ("  FAIL {0}: missing token [{1}]" -f $Label, $Token)
}

function Write-JsonFile {
    param([string]$Path, $Object)
    $json = $Object | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function New-TestConfig {
    param([string]$Directory)
    return [ordered]@{
        com2_host = '192.0.2.10'
        com2_ssh_port = 22
        com2_ssh_user = 'selftest'
        com2_ssh_key = (Join-Path $Directory 'id_selftest')
        com2_probe_script = 'C:\probe.cmd'
        tunnel_local_host = '127.0.0.1'
        tunnel_local_port = 14443
        tunnel_task = 'PADIEM-Selftest-NoSuchTask'
        mesh_url = 'https://127.0.0.1:14443/'
        health_log = (Join-Path $Directory 'health.log')
        recovery_log = (Join-Path $Directory 'recovery.jsonl')
        lock_file = (Join-Path $Directory 'recovery.lock')
        state_file = (Join-Path $Directory 'state.json')
        status_file = (Join-Path $Directory 'status.json')
        ssh_timeout_seconds = 2
        tunnel_restart_wait_seconds = 1
        verify_timeout_seconds = 1
        tcp_timeout_ms = 200
        recovery_lock_seconds = 600
    }
}

function Invoke-EngineSimulate {
    param([string]$Engine, [string]$ConfigPath, [string]$FixturePath)
    $childArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $Engine,
        '-Config', $ConfigPath,
        '-Mode', 'Simulate',
        '-Fixture', $FixturePath
    )
    $res = Invoke-BoundedProcess -FilePath 'powershell.exe' -Arguments $childArgs -TimeoutSeconds 60
    $record = $null
    if ($res.stdout) {
        $lines = $res.stdout -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') }
        if ($lines) {
            try { $record = ($lines | Select-Object -Last 1) | ConvertFrom-Json } catch { $record = $null }
        }
    }
    return @{ exit = $res.exit; stdout = $res.stdout; stderr = $res.stderr; record = $record }
}

function Test-Case {
    param(
        [string]$Name,
        [hashtable]$Fixture,
        [hashtable]$Expected,
        [string]$Engine,
        [string]$ConfigPath,
        [string]$Directory,
        [int]$LockPid = 0,
        [int]$LockAgeSeconds = 0,
        [bool]$ExpectLockRemoved = $true,
        [hashtable]$SeedState = $null
    )
    $before = $script:Failures
    $fixturePath = Join-Path $Directory ("fixture-{0}.json" -f $Name)
    Write-JsonFile -Path $fixturePath -Object $Fixture

    $lockPath = Join-Path $Directory 'recovery.lock'
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    if ($LockPid -gt 0) {
        $lock = [ordered]@{
            pid = $LockPid
            started = (Get-Date).AddSeconds(-1 * $LockAgeSeconds).ToString('o')
            trigger = 'selftest'
        }
        Write-JsonFile -Path $lockPath -Object $lock
    }

    # The engine keeps its state between runs. A test that needs a specific
    # prior state (for example an action that is still pending) seeds it here.
    if ($SeedState) {
        Write-JsonFile -Path (Join-Path $Directory 'state.json') -Object $SeedState
    }

    $res = Invoke-EngineSimulate -Engine $Engine -ConfigPath $ConfigPath -FixturePath $fixturePath
    Assert-Equal -Expected 0 -Actual $res.exit -Label "$Name exit"
    if (-not $res.record) {
        Assert-True -Value $false -Label "$Name produced a JSON record (stderr: $($res.stderr))"
        return
    }
    $rec = $res.record
    foreach ($key in $Expected.Keys) {
        Assert-Equal -Expected $Expected[$key] -Actual $rec.$key -Label ("{0} {1}" -f $Name, $key)
    }
    Assert-Equal -Expected $false -Actual $rec.executed -Label "$Name executed is false in Simulate"
    if ($rec.action -eq $rec.planned_action -and $rec.planned_action -ne 'none' -and
        $rec.planned_action -ne 'record_only') {
        Assert-True -Value ([string]$rec.detail).Contains('planned:') -Label "$Name detail is a plan"
    }
    foreach ($field in @('schema', 'ts', 'mode', 'trigger', 'executed', 'class', 'com2_ssh',
            'tunnel_tcp', 'mesh_http', 'remote_ok', 'remote_http', 'remote_keeper', 'remote_unit',
            'first_fault', 'attempt', 'planned_action', 'action', 'recovery_ok', 'recovery_at',
            'elapsed_sec', 'fault_age_sec', 'code', 'error', 'detail',
            'recovery_state', 'class_started_at', 'class_age_sec', 'engine_elapsed_sec',
            'action_started_at', 'action_finished_at', 'verify_window_sec',
            'http200_observed_at', 'http200_first_observed_sec', 'http200_observed_basis',
            'pending_since', 'pending_action', 'pending_deadline', 'pending_invalidation',
            'max_pending_seconds', 'remote_http_reason')) {
        Assert-True -Value ($rec.PSObject.Properties[$field] -ne $null) -Label "$Name record field $field"
    }
    $statusPath = Join-Path $Directory 'status.json'
    Assert-True -Value (Test-Path -LiteralPath $statusPath) -Label "$Name status file written"
    $healthPath = Join-Path $Directory 'health.log'
    $healthTail = if (Test-Path -LiteralPath $healthPath) { Get-Content -LiteralPath $healthPath -Tail 1 } else { '' }
    foreach ($token in @('com2_ssh=', 'tunnel_tcp=', 'mesh_http=', 'first_fault=', 'attempt=',
            'action=', 'recovery_at=', 'elapsed_sec=', 'fault_age_sec=', 'code=', 'error=',
            'class_started_at=', 'class_age_sec=', 'recovery_state=', 'http200_observed_at=',
            'pending_since=', 'pending_deadline=', 'remote_http_reason=')) {
        Assert-Contains -Text $healthTail -Token $token -Label "$Name health log $token"
    }
    if ($ExpectLockRemoved) {
        Assert-True -Value (-not (Test-Path -LiteralPath $lockPath)) -Label "$Name lock removed"
    } else {
        Assert-True -Value (Test-Path -LiteralPath $lockPath) -Label "$Name foreign lock left in place"
    }
    if ($script:Failures -eq $before) {
        Write-Output ("PASS {0} (class={1} planned={2} action={3})" -f $Name, $rec.class, $rec.planned_action, $rec.action)
    }
}

# --- setup ----------------------------------------------------------------

if (-not (Test-Path -LiteralPath $EnginePath)) {
    Write-Output ("FAIL engine not found: {0}" -f $EnginePath)
    exit 1
}

$work = Join-Path $env:TEMP ("com2-mesh-selftest-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null

# The engine's own helpers are reused for quoting and the bounded child run.
. $EnginePath -FunctionsOnly

# Dot-sourcing binds the engine's own [string]$Config parameter in this scope,
# so the selftest config must not reuse that variable name.
$testConfig = New-TestConfig -Directory $work
$configPath = Join-Path $work 'config.json'
Write-JsonFile -Path $configPath -Object $testConfig

# --- quoting helper -------------------------------------------------------

Write-Output '-- ConvertTo-ArgumentString'
Assert-Equal -Expected 'plain' -Actual (ConvertTo-ArgumentString -Arguments @('plain')) -Label 'plain'
Assert-Equal -Expected '"a b"' -Actual (ConvertTo-ArgumentString -Arguments @('a b')) -Label 'space'
Assert-Equal -Expected '"c\"d"' -Actual (ConvertTo-ArgumentString -Arguments @('c"d')) -Label 'quote'
Assert-Equal -Expected 'e\' -Actual (ConvertTo-ArgumentString -Arguments @('e\')) -Label 'unquoted trailing backslash'
Assert-Equal -Expected '"a b\\"' -Actual (ConvertTo-ArgumentString -Arguments @('a b\')) -Label 'quoted trailing backslash'
Assert-Equal -Expected '""' -Actual (ConvertTo-ArgumentString -Arguments @('')) -Label 'empty'
Assert-Equal -Expected 'a "b c"' -Actual (ConvertTo-ArgumentString -Arguments @('a', 'b c')) -Label 'two args'

# --- config ---------------------------------------------------------------

Write-Output '-- config'
$loaded = Get-Config -Path $configPath
Assert-True -Value ([string]$loaded.com2_keeper_start_command).Contains('pgrep') -Label 'keeper start uses pgrep'
Assert-True -Value ([string]$loaded.com2_keeper_start_command).Contains('nohup') -Label 'keeper start is detached'
Assert-True -Value ([string]$loaded.com2_keeper_start_command).Contains('sleep infinity') -Label 'keeper start runs the keeper'

$badConfig = New-TestConfig -Directory $work
$badConfig.Remove('tunnel_task')
$badConfigPath = Join-Path $work 'config-missing-key.json'
Write-JsonFile -Path $badConfigPath -Object $badConfig
$badRes = Invoke-BoundedProcess -FilePath 'powershell.exe' -Arguments @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $EnginePath,
    '-Config', $badConfigPath, '-Mode', 'Simulate',
    '-Fixture', (Join-Path $work 'fixture-healthy.json')
) -TimeoutSeconds 30
Assert-Equal -Expected 1 -Actual $badRes.exit -Label 'missing config key exits 1'

# --- branches -------------------------------------------------------------

Write-Output '-- failure branches'
Test-Case -Name 'healthy' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '200'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
} -Expected @{
    class = 'healthy'; planned_action = 'none'; action = 'none'
    recovery_ok = 'n/a'; code = 'HTTP_200'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'tunnel_broken' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
} -Expected @{
    class = 'tunnel_broken'; planned_action = 'restart_tunnel'; action = 'restart_tunnel'
    recovery_ok = 'planned'; code = 'PLANNED_RESTART_TUNNEL'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'tunnel_listener_down' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $false; mesh_http = '000'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
} -Expected @{
    class = 'tunnel_listener_down'; planned_action = 'restart_tunnel'; action = 'restart_tunnel'
    recovery_ok = 'planned'; code = 'PLANNED_RESTART_TUNNEL'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'com2_mesh_down_keeper_missing' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '000'; remote_keeper = 'MISSING'; remote_unit = 'active'
} -Expected @{
    class = 'com2_mesh_down'; planned_action = 'start_keeper'; action = 'start_keeper'
    recovery_ok = 'planned'; code = 'PLANNED_START_KEEPER'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'com2_mesh_down_unit_inactive' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '000'; remote_keeper = 'OK'; remote_unit = 'failed'
} -Expected @{
    class = 'com2_mesh_down'; planned_action = 'restart_mesh_service'; action = 'restart_mesh_service'
    recovery_ok = 'planned'; code = 'PLANNED_RESTART_MESH_SERVICE'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'com2_mesh_down_no_action' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '000'; remote_keeper = 'OK'; remote_unit = 'active'
} -Expected @{
    class = 'com2_mesh_down'; planned_action = 'record_only'; action = 'record_only'
    recovery_ok = 'no'; code = 'NO_ACTION_AVAILABLE'
    remote_http_reason = 'remote_http_no_response'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'com2_ssh_unreachable' -Fixture @{
    com2_ssh = $false; tunnel_tcp = $true; mesh_http = '000'
} -Expected @{
    class = 'com2_ssh_unreachable'; planned_action = 'record_only'; action = 'record_only'
    recovery_ok = 'no'; code = 'COM2_SSH_UNREACHABLE'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'remote_probe_failed' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'; remote_ok = $false
} -Expected @{
    class = 'remote_probe_failed'; planned_action = 'record_only'; action = 'record_only'
    recovery_ok = 'no'; code = 'REMOTE_PROBE_FAILED'
    remote_http_reason = 'remote_probe_failed'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'lock_collision' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
} -Expected @{
    class = 'tunnel_broken'; planned_action = 'restart_tunnel'; action = 'skipped_locked'
    recovery_ok = 'no'; code = 'RECOVERY_LOCKED'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work -LockPid $PID -ExpectLockRemoved $false

Test-Case -Name 'stale_lock_taken_over' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
} -Expected @{
    class = 'tunnel_broken'; planned_action = 'restart_tunnel'; action = 'restart_tunnel'
    recovery_ok = 'planned'; code = 'PLANNED_RESTART_TUNNEL'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work -LockPid 999999 -LockAgeSeconds 3600

# --- recovery verdict clocks ----------------------------------------------

function New-Stamp {
    param([int]$OffsetSeconds)
    return (Get-Date).AddSeconds($OffsetSeconds).ToString('yyyy-MM-dd HH:mm:ss')
}

Write-Output '-- pending is not success'
$pendingFixture = @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
}
$healthyFixture2 = @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '200'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
}

Test-Case -Name 'pending_active_suppresses_action' -Fixture $pendingFixture -SeedState @{
    first_fault = (New-Stamp -600); last_class = 'tunnel_broken'
    last_ts = (New-Stamp -60); last_code = 'RECOVERY_PENDING_HTTP_000'
    class_started_at = (New-Stamp -600)
    pending_since = (New-Stamp -60); pending_action = 'restart_tunnel'
    pending_deadline = (New-Stamp 600)
} -Expected @{
    class = 'tunnel_broken'; planned_action = 'none'; action = 'none'
    recovery_ok = 'pending'; recovery_state = 'pending'
    code = 'RECOVERY_PENDING_AWAITING_VERIFY'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'pending_expired_turns_failed' -Fixture $pendingFixture -SeedState @{
    first_fault = (New-Stamp -1200); last_class = 'tunnel_broken'
    last_ts = (New-Stamp -900); last_code = 'RECOVERY_PENDING_HTTP_000'
    class_started_at = (New-Stamp -1200)
    pending_since = (New-Stamp -900); pending_action = 'restart_tunnel'
    pending_deadline = (New-Stamp -60)
} -Expected @{
    class = 'tunnel_broken'; planned_action = 'none'; action = 'none'
    recovery_ok = 'no'; recovery_state = 'failed'
    code = 'RECOVERY_FAILED_PENDING_EXPIRED'; pending_invalidation = 'pending_expired'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'pending_resolved_on_later_check' -Fixture $healthyFixture2 -SeedState @{
    first_fault = (New-Stamp -600); last_class = 'tunnel_broken'
    last_ts = (New-Stamp -300); last_code = 'RECOVERY_PENDING_HTTP_000'
    class_started_at = (New-Stamp -600)
    pending_since = (New-Stamp -300); pending_action = 'restart_tunnel'
    pending_deadline = (New-Stamp 600)
} -Expected @{
    class = 'healthy'; recovery_ok = 'yes'; recovery_state = 'recovered'
    code = 'RECOVERED_HTTP200_OBSERVED_AFTER_PENDING'
    http200_observed_basis = 'observed_at_this_check'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'pending_closed_when_class_not_actionable' -Fixture @{
    com2_ssh = $false; tunnel_tcp = $true; mesh_http = '000'
} -SeedState @{
    first_fault = (New-Stamp -600); last_class = 'tunnel_broken'
    last_ts = (New-Stamp -60); last_code = 'RECOVERY_PENDING_HTTP_000'
    class_started_at = (New-Stamp -600)
    pending_since = (New-Stamp -60); pending_action = 'restart_tunnel'
    pending_deadline = (New-Stamp 600)
} -Expected @{
    class = 'com2_ssh_unreachable'; action = 'record_only'; recovery_ok = 'no'
    recovery_state = 'none'; code = 'COM2_SSH_UNREACHABLE'
    pending_since = ''; pending_deadline = ''; pending_invalidation = 'class_changed'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Test-Case -Name 'pending_closed_same_class_not_actionable' -Fixture @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '000'; remote_keeper = 'OK'; remote_unit = 'active'
} -SeedState @{
    first_fault = (New-Stamp -600); last_class = 'com2_mesh_down'
    last_ts = (New-Stamp -60); last_code = 'RECOVERY_PENDING_HTTP_000'
    class_started_at = (New-Stamp -600)
    pending_since = (New-Stamp -60); pending_action = 'restart_mesh_service'
    pending_deadline = (New-Stamp 600)
} -Expected @{
    class = 'com2_mesh_down'; action = 'record_only'; recovery_ok = 'no'
    pending_since = ''; pending_invalidation = 'class_not_actionable'
} -Engine $EnginePath -ConfigPath $configPath -Directory $work

Write-Output '-- pending is not carried past a non-actionable class'
$statePath2 = Join-Path $work 'state.json'
Write-JsonFile -Path $statePath2 -Object @{
    first_fault = (New-Stamp -600); last_class = 'tunnel_broken'
    last_ts = (New-Stamp -60); last_code = 'RECOVERY_PENDING_HTTP_000'
    class_started_at = (New-Stamp -600)
    pending_since = (New-Stamp -60); pending_action = 'restart_tunnel'
    pending_deadline = (New-Stamp 600)
}
$notActionableFixture = Join-Path $work 'fixture-not-actionable.json'
Write-JsonFile -Path $notActionableFixture -Object @{ com2_ssh = $false; tunnel_tcp = $true; mesh_http = '000' }
$notActionableRun = Invoke-EngineSimulate -Engine $EnginePath -ConfigPath $configPath -FixturePath $notActionableFixture
Assert-True -Value ($notActionableRun.record -ne $null) -Label 'not-actionable record present'
$clearedState = Get-Content -LiteralPath $statePath2 -Raw | ConvertFrom-Json
Assert-Equal -Expected '' -Actual $clearedState.pending_since -Label 'pending cleared in state'
Assert-Equal -Expected '' -Actual $clearedState.pending_deadline -Label 'pending deadline cleared in state'
Assert-True -Value ([string]$clearedState.class_started_at -ne '') -Label 'class clock kept for the new class'

Write-Output '-- episode clock vs class clock'
$classFixture = Join-Path $work 'fixture-class-change.json'
Write-JsonFile -Path $classFixture -Object $pendingFixture
Write-JsonFile -Path $statePath2 -Object @{
    first_fault = (New-Stamp -3600); last_class = 'remote_probe_failed'
    last_ts = (New-Stamp -300); last_code = 'REMOTE_PROBE_FAILED'
    class_started_at = (New-Stamp -3600)
    pending_since = ''; pending_action = ''; pending_deadline = ''
}
$classRun = Invoke-EngineSimulate -Engine $EnginePath -ConfigPath $configPath -FixturePath $classFixture
Assert-True -Value ($classRun.record -ne $null) -Label 'class change record present'
if ($classRun.record) {
    $classRun.record | Out-Null
    Assert-Equal -Expected $classRun.record.ts -Actual $classRun.record.class_started_at -Label 'class clock resets on class change'
    Assert-True -Value ([double]$classRun.record.fault_age_sec -gt 3000) -Label 'episode clock keeps the whole outage age'
    Assert-True -Value ([double]$classRun.record.class_age_sec -lt 5) -Label 'class clock restarts at the class boundary'
    Assert-True -Value ([double]$classRun.record.class_age_sec -lt [double]$classRun.record.fault_age_sec) -Label 'class age is distinct from episode age'
}

Write-Output '-- observed 200 is never back-dated'
Write-JsonFile -Path $statePath2 -Object @{
    first_fault = (New-Stamp -900); last_class = 'tunnel_broken'
    last_ts = (New-Stamp -300); last_code = 'RECOVERY_PENDING_HTTP_000'
    class_started_at = (New-Stamp -900)
    pending_since = (New-Stamp -300); pending_action = 'restart_tunnel'
    pending_deadline = (New-Stamp 600)
}
$observedFixture = Join-Path $work 'fixture-observed.json'
Write-JsonFile -Path $observedFixture -Object $healthyFixture2
$observedRun = Invoke-EngineSimulate -Engine $EnginePath -ConfigPath $configPath -FixturePath $observedFixture
Assert-True -Value ($observedRun.record -ne $null) -Label 'observed 200 record present'
if ($observedRun.record) {
    Assert-Equal -Expected $observedRun.record.ts -Actual $observedRun.record.http200_observed_at -Label 'observed 200 uses the check time'
    Assert-Equal -Expected $observedRun.record.ts -Actual $observedRun.record.recovery_at -Label 'recovery_at is the observation time'
    Assert-True -Value ([double]$observedRun.record.http200_first_observed_sec -gt 250) -Label 'first observation distance is reported'
}

# --- first-fault persistence ---------------------------------------------

Write-Output '-- first fault persistence'
$statePath = Join-Path $work 'state.json'
$lockPath = Join-Path $work 'recovery.lock'
Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
$faultFixture = Join-Path $work 'fixture-persist-fault.json'
$healthyFixture = Join-Path $work 'fixture-persist-healthy.json'
Write-JsonFile -Path $faultFixture -Object @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '000'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
}
Write-JsonFile -Path $healthyFixture -Object @{
    com2_ssh = $true; tunnel_tcp = $true; mesh_http = '200'
    remote_ok = $true; remote_http = '200'; remote_keeper = 'OK'; remote_unit = 'active'
}
$first = Invoke-EngineSimulate -Engine $EnginePath -ConfigPath $configPath -FixturePath $faultFixture
Start-Sleep -Milliseconds 1100
$second = Invoke-EngineSimulate -Engine $EnginePath -ConfigPath $configPath -FixturePath $faultFixture
Assert-True -Value ($first.record -ne $null -and $second.record -ne $null) -Label 'persist records present'
if ($first.record -and $second.record) {
    Assert-True -Value ([string]$first.record.first_fault -ne '') -Label 'first fault recorded'
    Assert-Equal -Expected $first.record.first_fault -Actual $second.record.first_fault -Label 'first fault preserved'
    Assert-True -Value ([double]$second.record.fault_age_sec -gt 0) -Label 'fault age grows'
}
$third = Invoke-EngineSimulate -Engine $EnginePath -ConfigPath $configPath -FixturePath $healthyFixture
Assert-True -Value ($third.record -ne $null) -Label 'healthy record present'
if ($third.record) {
    Assert-Equal -Expected 'SELF_RECOVERED_HTTP_200' -Actual $third.record.code -Label 'self recovery code'
    Assert-True -Value ([string]$third.record.recovery_at -ne '') -Label 'self recovery timestamp'
    $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Assert-Equal -Expected '' -Actual $saved.first_fault -Label 'first fault cleared after recovery'
}

# --- summary --------------------------------------------------------------

$summary = 'SELFTEST PASS={0} FAIL={1} ARTIFACTS={2}' -f $script:Passes, $script:Failures, $work
Write-Output $summary
if ($script:Failures -gt 0) {
    exit 1
}
if (-not $KeepArtifacts) {
    try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue } catch { }
}
exit 0
