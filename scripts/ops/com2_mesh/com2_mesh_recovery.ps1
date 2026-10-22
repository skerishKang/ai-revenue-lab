<#
.SYNOPSIS
  COM2 MeshCentral auto-recovery engine (COM1 side).

.DESCRIPTION
  Classifies a MeshCentral fault into one failure class, applies only the action
  that belongs to that class, and verifies the result with a real HTTP 200.

  Failure classes
    healthy                 - the MeshCentral HTTP probe answered 200.
    com2_ssh_unreachable    - the COM2 host did not answer on the SSH port.
    tunnel_listener_down    - the COM1 loopback forward port is not accepting.
    tunnel_broken           - COM2 answers 200 on its own loopback, but the
                              COM1 forward does not deliver it.
    com2_mesh_down          - COM2 itself does not serve MeshCentral.
    remote_probe_failed     - COM2 is reachable but the remote probe failed.

  Recovery actions (one per class, never combined)
    restart_tunnel          - stop the detached forward transport (only when it
                              is the ssh process that owns the configured
                              loopback port), restart the forward task, wait
                              for the listener, then verify HTTP 200.
    start_keeper            - start the COM2 WSL keeper process only.
    restart_mesh_service    - restart the COM2 WSL MeshCentral unit only.
    record_only             - record the state and wait for the next check.

  Safety
    - Nothing is restarted while the MeshCentral probe answers 200.
    - The WSL distribution is never stopped, and the Windows MeshCentral
      process is never killed.
    - A single-instance lock keeps two recovery processes apart.
    - Every action is verified with a real HTTP 200 before it counts as a
      recovery.

.PARAMETER Config
  Path to the JSON configuration file. It holds the endpoints and the local
  paths; the script itself carries no address or credential.

.PARAMETER Mode
  Live runs the real probes and actions. Simulate reads the probe results from
  a fixture and never executes an action.

.PARAMETER Fixture
  Fixture file used by Simulate mode.

.PARAMETER DryRun
  Classify and plan the action, write the log, but do not execute it.

.PARAMETER FunctionsOnly
  Define the functions and return. Used by the selftest.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_recovery.ps1 -Config C:\...\com2-mesh-config.json
#>
[CmdletBinding()]
param(
    [string]$Config = '',
    [ValidateSet('Live', 'Simulate')]
    [string]$Mode = 'Live',
    [string]$Fixture = '',
    [switch]$DryRun,
    [string]$Trigger = 'scheduled',
    [switch]$FunctionsOnly
)

$ErrorActionPreference = 'Stop'
$script:LoadedConfig = $null

# --- settings -------------------------------------------------------------

function Set-ConfigDefault {
    param($Cfg, [string]$Name, $Value)
    if (-not $Cfg.PSObject.Properties[$Name]) {
        $Cfg | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Get-Config {
    param([string]$Path)
    if (-not $Path) { throw 'config path is required' }
    if (-not (Test-Path -LiteralPath $Path)) { throw "config not found: $Path" }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $cfg = $raw | ConvertFrom-Json

    foreach ($name in @('com2_host', 'com2_ssh_port', 'com2_ssh_user', 'com2_ssh_key',
            'com2_probe_script', 'tunnel_local_host', 'tunnel_local_port', 'tunnel_task',
            'health_log', 'recovery_log', 'lock_file', 'state_file', 'status_file')) {
        if (-not $cfg.PSObject.Properties[$name]) { throw "config key missing: $name" }
    }

    Set-ConfigDefault -Cfg $cfg -Name 'mesh_scheme' -Value 'https'
    if (-not $cfg.PSObject.Properties['mesh_url']) {
        $cfg | Add-Member -NotePropertyName 'mesh_url' -NotePropertyValue (
            "{0}://{1}:{2}/" -f $cfg.mesh_scheme, $cfg.tunnel_local_host, $cfg.tunnel_local_port)
    }
    Set-ConfigDefault -Cfg $cfg -Name 'recovery_lock_seconds' -Value 600
    Set-ConfigDefault -Cfg $cfg -Name 'ssh_timeout_seconds' -Value 15
    Set-ConfigDefault -Cfg $cfg -Name 'tunnel_restart_wait_seconds' -Value 20
    Set-ConfigDefault -Cfg $cfg -Name 'verify_timeout_seconds' -Value 30
    # How long a not-yet-verified action may stay PENDING before it is recorded
    # as failed. PENDING is never a success state: it only says the action ran
    # and the first HTTP 200 was not observed inside the verification window.
    Set-ConfigDefault -Cfg $cfg -Name 'max_pending_seconds' -Value 900
    Set-ConfigDefault -Cfg $cfg -Name 'tcp_timeout_ms' -Value 3000
    Set-ConfigDefault -Cfg $cfg -Name 'tunnel_process_name' -Value 'ssh.exe'
    Set-ConfigDefault -Cfg $cfg -Name 'com2_wsl_distro' -Value 'Ubuntu'
    Set-ConfigDefault -Cfg $cfg -Name 'com2_mesh_unit' -Value 'padiem-meshcentral.service'
    Set-ConfigDefault -Cfg $cfg -Name 'com2_keeper_pattern' -Value '[p]adiem-wsl-keepalive'
    Set-ConfigDefault -Cfg $cfg -Name 'com2_keeper_process_name' -Value 'padiem-wsl-keepalive'
    if (-not $cfg.PSObject.Properties['com2_keeper_start_command'] -or
        [string]::IsNullOrWhiteSpace([string]$cfg.com2_keeper_start_command)) {
        # The keeper is a Linux process. The Windows shortcut task may be
        # disabled, so the keeper is started inside the distro instead.
        $keeperCmd = (
            'wsl.exe -d {0} -u root --exec bash -lc "if ! pgrep -af ''{1}'' >/dev/null 2>&1; ' +
            'then nohup bash -c ''exec -a {2} sleep infinity'' >/dev/null 2>&1 & fi"'
        ) -f $cfg.com2_wsl_distro, $cfg.com2_keeper_pattern, $cfg.com2_keeper_process_name
        $cfg | Add-Member -NotePropertyName 'com2_keeper_start_command' -NotePropertyValue $keeperCmd -Force
    }
    return $cfg
}

# --- logging --------------------------------------------------------------

function Write-LogLine {
    param([string]$Path, [string]$Line)
    try {
        Add-Content -LiteralPath $Path -Value $Line -Encoding UTF8 -ErrorAction Stop
    } catch { }
}

function Write-HealthLine {
    param($Cfg, $Record)
    $line = @(
        "check=$($Record.ts)",
        "mode=$($Record.mode)",
        "class=$($Record.class)",
        "com2_ssh=$($Record.com2_ssh)",
        "tunnel_tcp=$($Record.tunnel_tcp)",
        "mesh_http=$($Record.mesh_http)",
        "remote_http=$($Record.remote_http)",
        "remote_keeper=$($Record.remote_keeper)",
        "remote_unit=$($Record.remote_unit)",
        "first_fault=$($Record.first_fault)",
        "attempt=$($Record.attempt)",
        "planned_action=$($Record.planned_action)",
        "action=$($Record.action)",
        "executed=$($Record.executed)",
        "recovery_ok=$($Record.recovery_ok)",
        "recovery_at=$($Record.recovery_at)",
        "elapsed_sec=$($Record.elapsed_sec)",
        "fault_age_sec=$($Record.fault_age_sec)",
        "class_started_at=$($Record.class_started_at)",
        "class_age_sec=$($Record.class_age_sec)",
        "recovery_state=$($Record.recovery_state)",
        "http200_observed_at=$($Record.http200_observed_at)",
        "pending_since=$($Record.pending_since)",
        "pending_deadline=$($Record.pending_deadline)",
        "remote_http_reason=$($Record.remote_http_reason)",
        "code=$($Record.code)",
        "error=$($Record.error)",
        "detail=$($Record.detail)"
    ) -join ' '
    Write-LogLine -Path $Cfg.health_log -Line $line
}

# --- probes ---------------------------------------------------------------

function Test-TcpPort {
    param([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 3000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        try { $client.Close() } catch { }
    }
}

function Get-MeshHttpCode {
    param([string]$Url, [int]$TimeoutSeconds = 8)
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (-not (Test-Path $curl)) { return @{ code = '000'; exit = -1 } }
    $out = & $curl -sk -o NUL -w '%{http_code}' --max-time $TimeoutSeconds $Url 2>$null
    $code = if ($out) { ($out | Select-Object -Last 1).ToString().Trim() } else { '' }
    if ($code -notmatch '^\d{3}$') { $code = '000' }
    return @{ code = $code; exit = $LASTEXITCODE }
}

# Windows PowerShell 5.1 has no ProcessStartInfo.ArgumentList, so the command
# line is built with the Windows quoting rules when the property is missing.
function ConvertTo-ArgumentString {
    param([string[]]$Arguments)
    $slash = [string][char]92
    $quote = [char]34
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($a in $Arguments) {
        if ($null -eq $a -or $a -eq '') { $parts.Add('""'); continue }
        if ($a -notmatch '[\s"]') { $parts.Add($a); continue }
        $sb = New-Object System.Text.StringBuilder
        [void]$sb.Append($quote)
        $bs = 0
        foreach ($ch in $a.ToCharArray()) {
            if ($ch -eq $quote) {
                [void]$sb.Append((($slash * ($bs * 2 + 1)) -join ''))
                [void]$sb.Append($quote)
                $bs = 0
            } elseif ($ch -eq [char]92) {
                $bs++
            } else {
                if ($bs -gt 0) {
                    [void]$sb.Append((($slash * $bs) -join ''))
                    $bs = 0
                }
                [void]$sb.Append($ch)
            }
        }
        if ($bs -gt 0) { [void]$sb.Append((($slash * ($bs * 2)) -join '')) }
        [void]$sb.Append($quote)
        $parts.Add($sb.ToString())
    }
    return ($parts -join ' ')
}

# Runs one bounded command. The SSH transport is killed when it does not
# answer in time, so a hung probe can never leave an ssh.exe behind.
function Invoke-BoundedProcess {
    param([string]$FilePath, [string[]]$Arguments, [int]$TimeoutSeconds)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    if ($psi.PSObject.Properties['ArgumentList']) {
        foreach ($a in $Arguments) { [void]$psi.ArgumentList.Add($a) }
    } else {
        $psi.Arguments = ConvertTo-ArgumentString -Arguments $Arguments
    }
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $stdout = ''
    $stderr = ''
    $exitCode = -1
    $timedOut = $false
    try {
        [void]$proc.Start()
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit([Math]::Max(1000, $TimeoutSeconds * 1000))) {
            $timedOut = $true
            try { $proc.Kill($true) } catch { try { $proc.Kill() } catch { } }
            try { [void]$proc.WaitForExit(5000) } catch { }
        }
        try { $stdout = $outTask.Result } catch { $stdout = '' }
        try { $stderr = $errTask.Result } catch { $stderr = '' }
        try { $exitCode = $proc.ExitCode } catch { $exitCode = -1 }
    } catch {
        $stderr = $_.Exception.Message
    } finally {
        try { $proc.Dispose() } catch { }
    }
    return @{ exit = $exitCode; stdout = $stdout; stderr = $stderr; timedOut = $timedOut }
}

function Get-SshPaths {
    $ssh = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
    return $ssh
}

function Invoke-RemoteProbe {
    param($Cfg)
    $ssh = Get-SshPaths
    if (-not (Test-Path $ssh)) {
        return @{ ok = $false; output = ''; error = 'ssh client not found' }
    }
    $sshArgs = @(
        '-F', 'none',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=5',
        '-o', 'ServerAliveCountMax=2',
        '-i', $Cfg.com2_ssh_key,
        ("{0}@{1}" -f $Cfg.com2_ssh_user, $Cfg.com2_host),
        $Cfg.com2_probe_script
    )
    $res = Invoke-BoundedProcess -FilePath $ssh -Arguments $sshArgs -TimeoutSeconds ([int]$Cfg.ssh_timeout_seconds)
    if ($res.timedOut) {
        return @{ ok = $false; output = ''; error = 'remote probe timeout' }
    }
    $text = ($res.stdout + "`n" + $res.stderr).Trim()
    $http = '000'
    $keeper = 'unknown'
    $unit = 'unknown'
    if ($text -match 'HTTP=(\d{3})') { $http = $Matches[1] }
    if ($text -match 'KEEPER=(OK|MISSING|UNKNOWN)') { $keeper = $Matches[1] }
    if ($text -match 'UNIT=(active|inactive|failed|unknown)') { $unit = $Matches[1] }
    if ($http -eq '000' -and $keeper -eq 'unknown' -and $unit -eq 'unknown') {
        return @{ ok = $false; output = $text; error = 'remote probe produced no verdict' }
    }
    return @{ ok = $true; output = $text; error = ''; http = $http; keeper = $keeper; unit = $unit }
}

function Get-LiveProbes {
    param($Cfg)
    $com2Ssh = Test-TcpPort -TargetHost $Cfg.com2_host -Port ([int]$Cfg.com2_ssh_port) -TimeoutMs ([int]$Cfg.tcp_timeout_ms)
    $tunnel = Test-TcpPort -TargetHost $Cfg.tunnel_local_host -Port ([int]$Cfg.tunnel_local_port) -TimeoutMs ([int]$Cfg.tcp_timeout_ms)
    $mesh = Get-MeshHttpCode -Url $Cfg.mesh_url -TimeoutSeconds 8
    $remote = @{ ok = $false; http = '000'; keeper = 'unknown'; unit = 'unknown'; error = 'not probed' }
    if ($com2Ssh) { $remote = Invoke-RemoteProbe -Cfg $Cfg }
    return @{
        com2_ssh = $com2Ssh
        tunnel_tcp = $tunnel
        mesh_http = $mesh.code
        mesh_exit = $mesh.exit
        remote_ok = $remote.ok
        remote_http = $remote.http
        remote_keeper = $remote.keeper
        remote_unit = $remote.unit
        remote_error = $remote.error
    }
}

function Get-SimulatedProbes {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { throw "fixture not found: $Path" }
    $fx = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    return @{
        com2_ssh = [bool]$fx.com2_ssh
        tunnel_tcp = [bool]$fx.tunnel_tcp
        mesh_http = if ($fx.PSObject.Properties['mesh_http']) { [string]$fx.mesh_http } else { '000' }
        mesh_exit = 0
        remote_ok = ($fx.PSObject.Properties['remote_ok']) -and [bool]$fx.remote_ok
        remote_http = if ($fx.PSObject.Properties['remote_http']) { [string]$fx.remote_http } else { '000' }
        remote_keeper = if ($fx.PSObject.Properties['remote_keeper']) { [string]$fx.remote_keeper } else { 'unknown' }
        remote_unit = if ($fx.PSObject.Properties['remote_unit']) { [string]$fx.remote_unit } else { 'unknown' }
        remote_error = ''
    }
}

# --- classification -------------------------------------------------------

function Get-FailureClass {
    param($Probes)
    if ($Probes.mesh_http -eq '200') { return 'healthy' }
    if (-not $Probes.com2_ssh) { return 'com2_ssh_unreachable' }
    if (-not $Probes.tunnel_tcp) { return 'tunnel_listener_down' }
    if (-not $Probes.remote_ok) { return 'remote_probe_failed' }
    if ($Probes.remote_http -eq '200') { return 'tunnel_broken' }
    return 'com2_mesh_down'
}

function Get-PlannedAction {
    param([string]$FailureClass, $Probes)
    switch ($FailureClass) {
        'healthy' { return 'none' }
        'tunnel_listener_down' { return 'restart_tunnel' }
        'tunnel_broken' { return 'restart_tunnel' }
        'com2_mesh_down' {
            if ($Probes.remote_keeper -eq 'MISSING') { return 'start_keeper' }
            if ($Probes.remote_unit -ne 'active') { return 'restart_mesh_service' }
            return 'record_only'
        }
        default { return 'record_only' }
    }
}

function Get-RecordOnlyDetail {
    param([string]$FailureClass, $Probes)
    switch ($FailureClass) {
        'healthy' { return 'no action: MeshCentral HTTP 200' }
        'com2_ssh_unreachable' { return 'record only: COM2 SSH TCP probe failed' }
        'remote_probe_failed' {
            $why = if ($Probes.remote_error) { $Probes.remote_error } else { 'unknown' }
            return ("record only: COM2 reachable but the remote probe failed ({0})" -f $why)
        }
        'com2_mesh_down' {
            # The probe only knows that the remote HTTP request did not return a
            # usable code. It does not prove the unit stopped or the server is
            # broken, so the recorded reason stays an HTTP observation.
            return ('no action: remote HTTP probe returned no usable code ({0}); ' +
                'keeper={1} unit={2}') -f $Probes.remote_http, $Probes.remote_keeper, $Probes.remote_unit
        }
        default { return 'record only: no automatic action belongs to this failure class' }
    }
}

# --- actions --------------------------------------------------------------

function Get-ListenerProcessId {
    param([string]$TargetHost, [int]$Port)
    $getNet = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
    if ($getNet) {
        $conn = Get-NetTCPConnection -LocalAddress $TargetHost -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
    }
    $lines = & netstat.exe -ano -p tcp 2>$null
    foreach ($line in $lines) {
        if ($line -match ("^\s*TCP\s+" + [regex]::Escape($TargetHost) + ":" + $Port + "\s+\S+\s+LISTENING\s+(\d+)\s*$")) {
            return [int]$Matches[1]
        }
    }
    return 0
}

function Stop-StaleTunnelProcess {
    param($Cfg)
    $listenerPid = Get-ListenerProcessId -TargetHost $Cfg.tunnel_local_host -Port ([int]$Cfg.tunnel_local_port)
    if (-not $listenerPid) { return @{ ok = $true; detail = 'no listener to stop' } }
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $listenerPid) -ErrorAction SilentlyContinue
    if (-not $proc) { return @{ ok = $false; detail = ('listener pid {0} is not inspectable' -f $listenerPid) } }
    if ([string]$proc.Name -ne [string]$Cfg.tunnel_process_name) {
        return @{ ok = $false; detail = ('port is held by {0} (pid {1}), not by the configured forward transport' -f $proc.Name, $listenerPid) }
    }
    $cmd = [string]$proc.CommandLine
    if ($cmd -notmatch '-L' -or $cmd -notmatch ([regex]::Escape([string]$Cfg.tunnel_local_port))) {
        return @{ ok = $false; detail = ('listener pid {0} does not match the configured forward' -f $listenerPid) }
    }
    try {
        Stop-Process -Id $listenerPid -Force -ErrorAction Stop
    } catch {
        return @{ ok = $false; detail = ('could not stop stale forward pid {0}: {1}' -f $listenerPid, $_.Exception.Message) }
    }
    $deadline = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-ListenerProcessId -TargetHost $Cfg.tunnel_local_host -Port ([int]$Cfg.tunnel_local_port))) {
            return @{ ok = $true; detail = ('stopped stale forward pid {0}' -f $listenerPid) }
        }
        Start-Sleep -Milliseconds 500
    }
    return @{ ok = $false; detail = ('stopped forward pid {0} but the port is still held' -f $listenerPid) }
}

function Restart-Tunnel {
    param($Cfg, [switch]$Execute)
    if (-not $Execute) { return @{ ok = $true; detail = 'planned: restart the COM1 SSH forward task only' } }
    $details = @()
    try { Stop-ScheduledTask -TaskName $Cfg.tunnel_task -ErrorAction SilentlyContinue } catch { }
    $stale = Stop-StaleTunnelProcess -Cfg $Cfg
    if (-not $stale.ok) { return @{ ok = $false; detail = $stale.detail } }
    $details += $stale.detail
    Start-Sleep -Seconds 2
    try {
        Start-ScheduledTask -TaskName $Cfg.tunnel_task -ErrorAction Stop
        $details += ('started task {0}' -f $Cfg.tunnel_task)
    } catch {
        return @{ ok = $false; detail = ('restart of task {0} failed: {1}' -f $Cfg.tunnel_task, $_.Exception.Message) }
    }
    $deadline = (Get-Date).AddSeconds([int]$Cfg.tunnel_restart_wait_seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort -TargetHost $Cfg.tunnel_local_host -Port ([int]$Cfg.tunnel_local_port) -TimeoutMs 1000) {
            $details += 'forward listener is up'
            return @{ ok = $true; detail = ($details -join '; ') }
        }
        Start-Sleep -Seconds 2
    }
    $details += 'forward listener did not come up in time'
    return @{ ok = $false; detail = ($details -join '; ') }
}

function Invoke-RemoteCommand {
    param($Cfg, [string]$Command, [switch]$Execute)
    if (-not $Execute) { return @{ ok = $true; detail = "planned: remote command ($Command)" } }
    $ssh = Get-SshPaths
    if (-not (Test-Path $ssh)) { return @{ ok = $false; detail = 'ssh client not found' } }
    $sshArgs = @(
        '-F', 'none',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=5',
        '-o', 'ServerAliveCountMax=2',
        '-i', $Cfg.com2_ssh_key,
        ("{0}@{1}" -f $Cfg.com2_ssh_user, $Cfg.com2_host),
        $Command
    )
    $res = Invoke-BoundedProcess -FilePath $ssh -Arguments $sshArgs -TimeoutSeconds ([int]$Cfg.ssh_timeout_seconds)
    if ($res.timedOut) { return @{ ok = $false; detail = 'remote command timeout' } }
    $text = ($res.stdout + ' ' + $res.stderr).Trim()
    return @{ ok = ($res.exit -eq 0); detail = $text; exit = $res.exit }
}

function Start-Com2Keeper {
    param($Cfg, [switch]$Execute)
    # Only the keeper process is started. The distribution is never stopped and
    # the Windows MeshCentral process is never touched.
    $res = Invoke-RemoteCommand -Cfg $Cfg -Command $Cfg.com2_keeper_start_command -Execute:$Execute
    return @{ ok = $res.ok; detail = ('keeper start: {0}' -f $res.detail) }
}

function Restart-Com2MeshService {
    param($Cfg, [switch]$Execute)
    # Only the WSL MeshCentral unit is restarted, as root inside the distro.
    $cmd = ('wsl.exe -d {0} -u root --exec bash -lc "systemctl restart {1}; systemctl is-active {1}"' -f
        $Cfg.com2_wsl_distro, $Cfg.com2_mesh_unit)
    $res = Invoke-RemoteCommand -Cfg $Cfg -Command $cmd -Execute:$Execute
    return @{ ok = $res.ok; detail = ('mesh unit restart: {0}' -f $res.detail) }
}

function Invoke-RecoveryAction {
    param([string]$Action, $Probes, $Cfg, [switch]$Execute)
    switch ($Action) {
        'restart_tunnel' { return Restart-Tunnel -Cfg $Cfg -Execute:$Execute }
        'start_keeper' { return Start-Com2Keeper -Cfg $Cfg -Execute:$Execute }
        'restart_mesh_service' { return Restart-Com2MeshService -Cfg $Cfg -Execute:$Execute }
        default { return @{ ok = $true; detail = (Get-RecordOnlyDetail -FailureClass (Get-FailureClass -Probes $Probes) -Probes $Probes) } }
    }
}

function Wait-MeshHttp200 {
    param($Cfg, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $code = '000'
    while ($true) {
        $code = (Get-MeshHttpCode -Url $Cfg.mesh_url -TimeoutSeconds 5).code
        if ($code -eq '200') { return $code }
        if ((Get-Date) -ge $deadline) { return $code }
        Start-Sleep -Seconds 5
    }
}

# --- lock and state -------------------------------------------------------

function Test-LockAvailable {
    param($Cfg)
    $lock = $Cfg.lock_file
    if (-not (Test-Path -LiteralPath $lock)) { return $true }
    try {
        $raw = Get-Content -LiteralPath $lock -Raw
        $obj = $raw | ConvertFrom-Json
        $age = ((Get-Date) - [datetime]$obj.started).TotalSeconds
        if ($age -lt [int]$Cfg.recovery_lock_seconds) {
            $lockPid = [int]$obj.pid
            $alive = $false
            try { $alive = [bool](Get-Process -Id $lockPid -ErrorAction SilentlyContinue) } catch { }
            if ($alive) { return $false }
        }
    } catch { }
    return $true
}

function New-RecoveryLock {
    param($Cfg)
    $obj = [ordered]@{
        pid = $PID
        started = (Get-Date).ToString('o')
        trigger = $Trigger
    }
    $json = $obj | ConvertTo-Json -Compress
    try {
        [System.IO.File]::WriteAllText($Cfg.lock_file, $json, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

function Remove-RecoveryLock {
    param($Cfg)
    try { Remove-Item -LiteralPath $Cfg.lock_file -Force -ErrorAction SilentlyContinue } catch { }
}

function Get-RecoveryState {
    param($Cfg)
    $state = [ordered]@{
        first_fault = ''; last_class = ''; last_ts = ''; last_code = ''
        class_started_at = ''; pending_since = ''; pending_action = ''; pending_deadline = ''
    }
    if (-not (Test-Path -LiteralPath $Cfg.state_file)) { return $state }
    try {
        $obj = Get-Content -LiteralPath $Cfg.state_file -Raw | ConvertFrom-Json
        foreach ($k in @('first_fault', 'last_class', 'last_ts', 'last_code',
                'class_started_at', 'pending_since', 'pending_action', 'pending_deadline')) {
            if ($obj.PSObject.Properties[$k]) { $state[$k] = [string]$obj.$k }
        }
    } catch { }
    return $state
}

function Save-RecoveryState {
    param($Cfg, $State)
    try {
        $json = ($State | ConvertTo-Json -Compress)
        [System.IO.File]::WriteAllText($Cfg.state_file, $json, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

function ConvertTo-FaultAgeSeconds {
    param([string]$FirstFault, [datetime]$Now)
    if (-not $FirstFault) { return '' }
    try {
        $t = [datetime]::ParseExact($FirstFault, 'yyyy-MM-dd HH:mm:ss', $null)
        return [Math]::Round(($Now - $t).TotalSeconds, 1)
    } catch {
        return ''
    }
}

function Get-RemoteHttpReason {
    # A non-200 remote HTTP probe is an HTTP observation only. It is never
    # evidence that the COM2 unit stopped or that the server is broken, so the
    # record must not claim either.
    param($Probes)
    if (-not $Probes.remote_ok) { return 'remote_probe_failed' }
    $code = [string]$Probes.remote_http
    if ($code -match '^\d{3}$' -and $code -ne '000') { return 'remote_http_code' }
    return 'remote_http_no_response'
}

# --- main -----------------------------------------------------------------

if ($FunctionsOnly) { return }

$started = Get-Date
$record = $null

try {
    $script:LoadedConfig = Get-Config -Path $Config
    $cfg = $script:LoadedConfig

    if ($Mode -eq 'Simulate') {
        if (-not $Fixture) { throw 'fixture is required in Simulate mode' }
        $probes = Get-SimulatedProbes -Path $Fixture
    } else {
        $probes = Get-LiveProbes -Cfg $cfg
    }

    $failureClass = Get-FailureClass -Probes $probes
    $plannedAction = Get-PlannedAction -FailureClass $failureClass -Probes $probes
    $state = Get-RecoveryState -Cfg $cfg
    # Two independent clocks. `first_fault` is the start of the whole fault
    # episode (a run of non-healthy checks, whatever the class).
    # `class_started_at` is the start of the *current* failure class only.
    $firstFault = [string]$state.first_fault
    $classStartedAt = [string]$state.class_started_at
    $pendingSince = [string]$state.pending_since
    $pendingAction = [string]$state.pending_action
    $pendingDeadline = [string]$state.pending_deadline
    $maxPending = [int]$cfg.max_pending_seconds
    $nowStamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')

    $attempt = ''
    $action = 'none'
    $executed = $false
    $recoveryOk = 'n/a'
    $recoveryAt = ''
    $elapsed = ''
    $faultAge = ''
    $classAge = ''
    $code = ''
    $detail = ''
    $failureReason = ''
    # Observability, never a claim of success: none|recovered|pending|failed|planned|locked
    $recoveryState = 'none'
    $actionStartedAt = ''
    $actionFinishedAt = ''
    $http200ObservedAt = ''
    $http200ObservedSec = ''
    $pendingInvalidation = ''

    $execute = ($Mode -eq 'Live') -and (-not $DryRun) -and
        ($plannedAction -eq 'restart_tunnel' -or $plannedAction -eq 'start_keeper' -or
         $plannedAction -eq 'restart_mesh_service')

    if ($failureClass -eq 'healthy') {
        $action = 'none'
        if ($firstFault) {
            # The previous check was a fault and the path answered 200 now. The
            # 200 was OBSERVED at this check; it is not proof that the path came
            # back at this check, so the recovery instant is never back-dated.
            $recoveryAt = $nowStamp
            $faultAge = ConvertTo-FaultAgeSeconds -FirstFault $firstFault -Now (Get-Date)
            $classAge = ConvertTo-FaultAgeSeconds -FirstFault $classStartedAt -Now (Get-Date)
            $elapsed = [Math]::Round(((Get-Date) - $started).TotalSeconds, 1)
            $recoveryOk = 'yes'
            $recoveryState = 'recovered'
            if ($pendingSince) {
                $http200ObservedAt = $nowStamp
                $http200ObservedSec = ConvertTo-FaultAgeSeconds -FirstFault $pendingSince -Now (Get-Date)
                $code = 'RECOVERED_HTTP200_OBSERVED_AFTER_PENDING'
                $detail = 'HTTP 200 observed at this check after a pending action; the first-observed ' +
                    'time is an upper bound on the recovery instant, not the recovery instant itself'
            } else {
                $code = 'SELF_RECOVERED_HTTP_200'
                $detail = 'the MeshCentral path answered 200 without this check taking an action'
            }
            $firstFault = ''
            $classStartedAt = ''
            $pendingSince = ''
            $pendingAction = ''
            $pendingDeadline = ''
        } else {
            $recoveryOk = 'n/a'
            $code = 'HTTP_200'
            $detail = 'no action: MeshCentral HTTP 200'
        }
    } elseif ($plannedAction -eq 'record_only') {
        $action = 'record_only'
        $recoveryOk = 'no'
        $detail = Get-RecordOnlyDetail -FailureClass $failureClass -Probes $probes
        $failureReason = $detail
        switch ($failureClass) {
            'com2_ssh_unreachable' { $code = 'COM2_SSH_UNREACHABLE' }
            'remote_probe_failed' { $code = 'REMOTE_PROBE_FAILED' }
            default { $code = 'NO_ACTION_AVAILABLE' }
        }
        if (-not $firstFault) { $firstFault = $nowStamp }
        # Same two clocks as the action branch. A class boundary resets the
        # class clock, and a pending verdict never outlives its class: this
        # branch permits no action at all, so carrying the verdict forward would
        # later suppress an unrelated action or expire into a false failure.
        $classChanged = ($state.last_class -ne $failureClass) -or (-not $classStartedAt)
        if ($classChanged) { $classStartedAt = $nowStamp }
        if ($pendingSince) {
            $pendingInvalidation = $(if ($classChanged) { 'class_changed' } else { 'class_not_actionable' })
            $pendingSince = ''
            $pendingAction = ''
            $pendingDeadline = ''
        }
        $faultAge = ConvertTo-FaultAgeSeconds -FirstFault $firstFault -Now (Get-Date)
        $classAge = ConvertTo-FaultAgeSeconds -FirstFault $classStartedAt -Now (Get-Date)
    } else {
        # Episode clock vs. class clock. A new first_fault starts a new episode;
        # a class change only resets class_started_at, so the age of the whole
        # outage and the age of the current failure class can be read apart.
        if (-not $firstFault) { $firstFault = $nowStamp }
        if ($state.last_class -ne $failureClass -or -not $classStartedAt) {
            if ($pendingSince) {
                # The pending verdict belonged to the previous class.
                $pendingInvalidation = 'class_changed'
                $pendingSince = ''
                $pendingAction = ''
                $pendingDeadline = ''
            }
            $classStartedAt = $nowStamp
        }
        $faultAge = ConvertTo-FaultAgeSeconds -FirstFault $firstFault -Now (Get-Date)
        $classAge = ConvertTo-FaultAgeSeconds -FirstFault $classStartedAt -Now (Get-Date)

        # A pending action is not a success. It only says: the action ran and no
        # HTTP 200 was observed inside the verification window. Until the window
        # closes it suppresses a second action; after it closes it is a failure.
        $pendingActive = $false
        $pendingExpired = $false
        if ($pendingSince) {
            try {
                $pendingEnd = [datetime]::ParseExact($pendingDeadline, 'yyyy-MM-dd HH:mm:ss', $null)
                if ((Get-Date) -lt $pendingEnd) { $pendingActive = $true } else { $pendingExpired = $true }
            } catch {
                $pendingExpired = $true
            }
        }

        if ($pendingActive) {
            $action = 'none'
            $plannedAction = 'none'
            $recoveryOk = 'pending'
            $recoveryState = 'pending'
            $code = 'RECOVERY_PENDING_AWAITING_VERIFY'
            $detail = ('previous action {0} is still inside its verification window (deadline {1}); ' +
                'no new action taken') -f $pendingAction, $pendingDeadline
        } elseif ($pendingExpired) {
            $action = 'none'
            $plannedAction = 'none'
            $recoveryOk = 'no'
            $recoveryState = 'failed'
            $code = 'RECOVERY_FAILED_PENDING_EXPIRED'
            $failureReason = ('action {0} stayed pending past {1} without an observed HTTP 200' -f
                $pendingAction, $pendingDeadline)
            $detail = 'pending window closed; the next check may act again'
            $pendingInvalidation = 'pending_expired'
            $pendingSince = ''
            $pendingAction = ''
            $pendingDeadline = ''
        } elseif (-not (Test-LockAvailable -Cfg $cfg)) {
            $action = 'skipped_locked'
            $recoveryOk = 'no'
            $recoveryState = 'locked'
            $code = 'RECOVERY_LOCKED'
            $detail = 'another recovery process holds the lock'
            $failureReason = $detail
        } else {
            New-RecoveryLock -Cfg $cfg
            try {
                $attempt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
                $executed = $execute
                $actionStartedAt = $attempt
                $result = Invoke-RecoveryAction -Action $plannedAction -Probes $probes -Cfg $cfg -Execute:$execute
                $action = $plannedAction
                $detail = [string]$result.detail
                if ($execute) { $actionFinishedAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') }

                if ($execute) {
                    $finalCode = Wait-MeshHttp200 -Cfg $cfg -TimeoutSeconds ([int]$cfg.verify_timeout_seconds)
                    $elapsed = [Math]::Round(((Get-Date) - $started).TotalSeconds, 1)
                    $faultAge = ConvertTo-FaultAgeSeconds -FirstFault $firstFault -Now (Get-Date)
                    $classAge = ConvertTo-FaultAgeSeconds -FirstFault $classStartedAt -Now (Get-Date)
                    if ($finalCode -eq '200') {
                        $recoveryOk = 'yes'
                        $recoveryState = 'recovered'
                        $recoveryAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
                        $http200ObservedAt = $recoveryAt
                        $http200ObservedSec = ConvertTo-FaultAgeSeconds -FirstFault $actionFinishedAt -Now (Get-Date)
                        $code = 'RECOVERED_HTTP_200'
                        $firstFault = ''
                        $classStartedAt = ''
                    } else {
                        # Not a failure verdict: the verification window was too
                        # short to observe the 200. Keep waiting, bounded.
                        $recoveryOk = 'pending'
                        $recoveryState = 'pending'
                        $code = ('RECOVERY_PENDING_HTTP_{0}' -f $finalCode)
                        $pendingSince = $actionFinishedAt
                        $pendingAction = $plannedAction
                        $pendingDeadline = ([datetime]::ParseExact($actionFinishedAt,
                            'yyyy-MM-dd HH:mm:ss', $null)).AddSeconds($maxPending).ToString('yyyy-MM-dd HH:mm:ss')
                        $failureReason = ''
                        $detail = ('{0} | no HTTP 200 observed inside {1}s; pending until {2}' -f
                            $detail, [int]$cfg.verify_timeout_seconds, $pendingDeadline)
                    }
                } else {
                    $recoveryOk = 'planned'
                    $recoveryState = 'planned'
                    $code = ('PLANNED_{0}' -f $plannedAction.ToUpperInvariant())
                    if ([string]$result.detail -notmatch '^planned:') {
                        $detail = ('planned action was not executed: {0}' -f $result.detail)
                    }
                    $elapsed = [Math]::Round(((Get-Date) - $started).TotalSeconds, 1)
                }
            } finally {
                Remove-RecoveryLock -Cfg $cfg
            }
        }
    }

    $now = Get-Date
    $record = [ordered]@{
        schema = 'com2_mesh_recovery/v1'
        ts = $now.ToString('yyyy-MM-dd HH:mm:ss')
        mode = $Mode
        trigger = $Trigger
        executed = [bool]$executed
        class = $failureClass
        com2_ssh = $(if ($probes.com2_ssh) { 'OK' } else { 'FAIL' })
        tunnel_tcp = $(if ($probes.tunnel_tcp) { 'OK' } else { 'FAIL' })
        mesh_http = $probes.mesh_http
        remote_ok = [bool]$probes.remote_ok
        remote_http = $probes.remote_http
        remote_keeper = $probes.remote_keeper
        remote_unit = $probes.remote_unit
        first_fault = $firstFault
        attempt = $attempt
        planned_action = $plannedAction
        action = $action
        recovery_ok = $recoveryOk
        recovery_at = $recoveryAt
        elapsed_sec = $elapsed
        fault_age_sec = $faultAge
        code = $code
        error = $failureReason
        detail = $detail
        # --- additive observability (consumers of the fields above are unaffected)
        recovery_state = $recoveryState
        class_started_at = $classStartedAt
        class_age_sec = $classAge
        engine_elapsed_sec = $elapsed
        action_started_at = $actionStartedAt
        action_finished_at = $actionFinishedAt
        verify_window_sec = [int]$cfg.verify_timeout_seconds
        http200_observed_at = $http200ObservedAt
        http200_first_observed_sec = $http200ObservedSec
        http200_observed_basis = $(if ($http200ObservedAt) { 'observed_at_this_check' } else { '' })
        pending_since = $pendingSince
        pending_action = $pendingAction
        pending_deadline = $pendingDeadline
        pending_invalidation = $pendingInvalidation
        max_pending_seconds = $maxPending
        remote_http_reason = Get-RemoteHttpReason -Probes $probes
    }

    $newState = [ordered]@{
        first_fault = $firstFault
        last_class = $failureClass
        last_ts = $record.ts
        last_code = $code
        class_started_at = $classStartedAt
        pending_since = $pendingSince
        pending_action = $pendingAction
        pending_deadline = $pendingDeadline
    }
    Save-RecoveryState -Cfg $cfg -State $newState

    $json = ($record | ConvertTo-Json -Depth 6 -Compress)
    Write-LogLine -Path $cfg.recovery_log -Line $json
    Write-HealthLine -Cfg $cfg -Record $record
    try {
        [System.IO.File]::WriteAllText($cfg.status_file, ($record | ConvertTo-Json -Depth 6),
            (New-Object System.Text.UTF8Encoding($false)))
    } catch { }

    Write-Output $json
    exit 0
} catch {
    $msg = ('recovery engine failed: {0}' -f $_.Exception.Message)
    if ($script:LoadedConfig) {
        try {
            $errRecord = [ordered]@{
                schema = 'com2_mesh_recovery/v1'
                ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
                mode = $Mode
                trigger = $Trigger
                executed = $false
                class = 'engine_error'
                com2_ssh = 'UNKNOWN'
                tunnel_tcp = 'UNKNOWN'
                mesh_http = '000'
                remote_ok = $false
                remote_http = '000'
                remote_keeper = 'unknown'
                remote_unit = 'unknown'
                first_fault = ''
                attempt = ''
                planned_action = 'none'
                action = 'none'
                recovery_ok = 'no'
                recovery_at = ''
                elapsed_sec = [Math]::Round(((Get-Date) - $started).TotalSeconds, 1)
                fault_age_sec = ''
                code = 'ENGINE_ERROR'
                error = $msg
                detail = $msg
            }
            Write-LogLine -Path $script:LoadedConfig.recovery_log -Line ($errRecord | ConvertTo-Json -Depth 5 -Compress)
            Write-HealthLine -Cfg $script:LoadedConfig -Record $errRecord
            try {
                [System.IO.File]::WriteAllText($script:LoadedConfig.status_file, ($errRecord | ConvertTo-Json -Depth 5),
                    (New-Object System.Text.UTF8Encoding($false)))
            } catch { }
        } catch { }
    }
    [Console]::Error.WriteLine($msg)
    exit 1
}
