<#
.SYNOPSIS
  Single-instance supervisor for the COM1 -> COM2 loopback SSH forward.

.DESCRIPTION
  Owns exactly one forward child process for its whole lifetime.

  - An exclusive lock file (FileShare.None) refuses a second supervisor. The
    lock is an OS handle, so a dead supervisor releases it automatically.
  - The child is assigned to a Windows job object with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, so it cannot outlive the supervisor
    even when the task is ended with a hard terminate. A job object that
    cannot be created or assigned is fatal: the supervisor never reports
    forwarding for an unowned child.
  - A failed child is retried with a capped backoff. A child that ran for at
    least tunnel_stable_seconds resets the attempt budget. After
    tunnel_max_attempts failures the supervisor exits; the scheduled task's
    five-minute trigger starts a fresh episode, and the task's IgnoreNew
    policy prevents a second instance while one is alive.
  - No COM2 service is restarted here. The existing recovery engine owns all
    service actions; this supervisor only owns its own child process.

.PARAMETER Config
  JSON file. Required keys:
    com2_host, com2_ssh_port, com2_ssh_user, com2_ssh_key,
    tunnel_local_host, tunnel_local_port,
    tunnel_lock_file, tunnel_state_file, tunnel_log.
  Optional keys:
    tunnel_ssh_path, tunnel_ssh_log, tunnel_stable_seconds,
    tunnel_backoff_schedule_seconds, tunnel_max_attempts,
    tunnel_ready_wait_seconds, tunnel_require_listener,
    tunnel_child_path, tunnel_child_arguments.
  tunnel_child_path and tunnel_child_arguments are a transport override. When
  unset, the supervisor runs ssh.exe with the configured key and forward.

.PARAMETER FunctionsOnly
  Define the functions and return. Used by the selftest.
#>
[CmdletBinding()]
param(
    [string]$Config = '',
    [switch]$FunctionsOnly
)

$ErrorActionPreference = 'Stop'

# --- settings -------------------------------------------------------------

function Set-SupDefault {
    param($Cfg, [string]$Name, $Value)
    if (-not $Cfg.PSObject.Properties[$Name]) {
        $Cfg | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Get-SupervisorConfig {
    param([string]$Path)
    if (-not $Path) { throw 'config path is required' }
    if (-not (Test-Path -LiteralPath $Path)) { throw "config not found: $Path" }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $cfg = $raw | ConvertFrom-Json

    foreach ($name in @('com2_host', 'com2_ssh_port', 'com2_ssh_user', 'com2_ssh_key',
            'tunnel_local_host', 'tunnel_local_port',
            'tunnel_lock_file', 'tunnel_state_file', 'tunnel_log')) {
        if (-not $cfg.PSObject.Properties[$name]) { throw "config key missing: $name" }
        if ([string]::IsNullOrWhiteSpace([string]$cfg.$name)) { throw "config key is empty: $name" }
    }

    Set-SupDefault -Cfg $cfg -Name 'tunnel_ssh_path' -Value (
        Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe')
    Set-SupDefault -Cfg $cfg -Name 'tunnel_ssh_log' -Value ''
    Set-SupDefault -Cfg $cfg -Name 'tunnel_stable_seconds' -Value 120
    Set-SupDefault -Cfg $cfg -Name 'tunnel_backoff_schedule_seconds' -Value @(5, 15, 30, 60)
    Set-SupDefault -Cfg $cfg -Name 'tunnel_max_attempts' -Value 5
    Set-SupDefault -Cfg $cfg -Name 'tunnel_ready_wait_seconds' -Value 15
    Set-SupDefault -Cfg $cfg -Name 'tunnel_require_listener' -Value $true
    Set-SupDefault -Cfg $cfg -Name 'tunnel_child_path' -Value ''
    Set-SupDefault -Cfg $cfg -Name 'tunnel_child_arguments' -Value @()
    return $cfg
}

# --- telemetry ------------------------------------------------------------

function Write-SupLog {
    param($Cfg, [string]$Message)
    try {
        $line = ('{0} {1}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Message)
        Add-Content -LiteralPath $Cfg.tunnel_log -Value $line -Encoding UTF8 -ErrorAction Stop
    } catch { }
}

function Write-SupState {
    param($Cfg, $State)
    $State.ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    try {
        [System.IO.File]::WriteAllText($Cfg.tunnel_state_file,
            ($State | ConvertTo-Json -Depth 6),
            (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

# --- process helpers ------------------------------------------------------

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

function New-SingleInstanceLock {
    param($Cfg)
    $stream = $null
    try {
        $stream = [System.IO.FileStream]::new(
            [string]$Cfg.tunnel_lock_file,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None)
        $payload = [ordered]@{
            schema = 'com2_mesh_tunnel_supervisor_lock/v1'
            pid = $PID
            started = (Get-Date).ToString('o')
        }
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
        $stream.SetLength(0)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        return @{ ok = $true; already_running = $false; stream = $stream; error = '' }
    } catch {
        if ($stream) { try { $stream.Dispose() } catch { } }
        $msg = $_.Exception.Message
        $base = $_.Exception.GetBaseException()
        $hresult = 0
        try { $hresult = [int]$base.HResult } catch { }
        # ERROR_SHARING_VIOLATION; the message text is localized, so the code
        # is the locale-independent signal.
        $busy = ($hresult -eq -2147024864) -or
            ($msg -match 'being used by another process|sharing violation|0x80070020')
        return @{ ok = $false; already_running = $busy; stream = $null; error = $msg }
    }
}

# The child must not survive a hard terminate of this supervisor. The job
# object is created once and every child is assigned before it can be useful.
function New-ChildJob {
    if (-not ('Com2MeshTunnelJob' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class Com2MeshTunnelJob
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr attrs, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimit
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimit
    {
        public BasicLimit BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    public static IntPtr Create()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) { return IntPtr.Zero; }
        ExtendedLimit info = new ExtendedLimit();
        info.BasicLimitInformation.LimitFlags = 0x2000;
        int length = Marshal.SizeOf(typeof(ExtendedLimit));
        IntPtr ptr = Marshal.AllocHGlobal(length);
        try
        {
            Marshal.StructureToPtr(info, ptr, false);
            if (!SetInformationJobObject(job, 9, ptr, (uint)length))
            {
                CloseHandle(job);
                return IntPtr.Zero;
            }
        }
        finally
        {
            Marshal.FreeHGlobal(ptr);
        }
        return job;
    }

    public static bool Assign(IntPtr job, IntPtr process)
    {
        return AssignProcessToJobObject(job, process);
    }

    public static void Close(IntPtr job)
    {
        if (job != IntPtr.Zero) { CloseHandle(job); }
    }
}
'@
    }
    try { return [Com2MeshTunnelJob]::Create() } catch { return [IntPtr]::Zero }
}

function Get-ChildInvocation {
    param($Cfg)
    if (-not [string]::IsNullOrWhiteSpace([string]$Cfg.tunnel_child_path)) {
        return @{
            path = [string]$Cfg.tunnel_child_path
            args = @($Cfg.tunnel_child_arguments | ForEach-Object { [string]$_ })
        }
    }
    $args = @(
        '-N', '-T',
        '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        '-i', [string]$Cfg.com2_ssh_key,
        '-p', [string]$Cfg.com2_ssh_port,
        '-L', ('{0}:{1}:{0}:{1}' -f $Cfg.tunnel_local_host, $Cfg.tunnel_local_port)
    )
    if (-not [string]::IsNullOrWhiteSpace([string]$Cfg.tunnel_ssh_log)) {
        $args += @('-E', [string]$Cfg.tunnel_ssh_log)
    }
    $args += ('{0}@{1}' -f $Cfg.com2_ssh_user, $Cfg.com2_host)
    return @{ path = [string]$Cfg.tunnel_ssh_path; args = $args }
}

function Start-ForwardChild {
    param($Cfg)
    $inv = Get-ChildInvocation -Cfg $Cfg
    if (-not (Test-Path -LiteralPath $inv.path)) {
        return @{ ok = $false; process = $null; error = ('child not found: {0}' -f $inv.path) }
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $inv.path
    if ($psi.PSObject.Properties['ArgumentList']) {
        foreach ($a in $inv.args) { [void]$psi.ArgumentList.Add($a) }
    } else {
        $psi.Arguments = ConvertTo-ArgumentString -Arguments $inv.args
    }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = 'Hidden'
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    try {
        if (-not $proc.Start()) {
            return @{ ok = $false; process = $null; error = 'child process did not start' }
        }
    } catch {
        try { $proc.Dispose() } catch { }
        return @{ ok = $false; process = $null; error = $_.Exception.Message }
    }
    return @{ ok = $true; process = $proc; error = '' }
}

function Stop-ForwardChild {
    param($Process)
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            try { $Process.Kill($true) } catch { try { $Process.Kill() } catch { } }
        }
    } catch { }
    try { [void]$Process.WaitForExit(5000) } catch { }
    try { $Process.Dispose() } catch { }
}

function Start-OwnedChild {
    param($Cfg, [IntPtr]$Job)
    if ($Job -eq [IntPtr]::Zero) {
        return @{ ok = $false; process = $null; error = 'job_object_unavailable' }
    }
    $child = Start-ForwardChild -Cfg $Cfg
    if (-not $child.ok) { return $child }
    $assigned = $false
    try { $assigned = [Com2MeshTunnelJob]::Assign($Job, $child.process.Handle) } catch { $assigned = $false }
    if (-not $assigned) {
        Stop-ForwardChild -Process $child.process
        return @{ ok = $false; process = $null; error = 'job_object_assign_failed' }
    }
    return $child
}

function Get-ListenerOwnerPid {
    param([string]$TargetHost, [int]$Port)
    try {
        $connections = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop)
        $match = @($connections | Where-Object { [string]$_.LocalAddress -eq $TargetHost }) |
            Select-Object -First 1
        if (-not $match) { $match = $connections | Select-Object -First 1 }
        if ($match) { return [int]$match.OwningProcess }
    } catch { }
    return (Get-NetstatListenerOwnerPid -Port $Port)
}

# Fallback when the connection cmdlet is unavailable. It still returns a real
# owner PID, so readiness keeps comparing the owner with the supervisor's child
# instead of accepting any process that answers on the port.
function Get-NetstatListenerOwnerPid {
    param([int]$Port)
    try {
        $lines = & netstat.exe -ano -p tcp 2>$null
        foreach ($line in $lines) {
            if ([string]$line -match ('^\s*TCP\s+\S+:' + $Port + '\s+\S+\s+LISTENING\s+(\d+)\s*$')) {
                return [int]$Matches[1]
            }
        }
    } catch { }
    return 0
}

# The forward is ready only when the child owns the port. A stale or foreign
# listener on the same port must not satisfy readiness, otherwise the
# supervisor would report forwarding while its own child is exiting.
function Wait-ForwardListener {
    param($Cfg, $Process, [int]$TimeoutSeconds)
    if ($Cfg.tunnel_require_listener -ne $true) { return $true }
    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    while ((Get-Date) -lt $deadline) {
        $ownerPid = Get-ListenerOwnerPid -TargetHost ([string]$Cfg.tunnel_local_host) -Port ([int]$Cfg.tunnel_local_port)
        if ($ownerPid -gt 0 -and $Process -and $ownerPid -eq $Process.Id) { return $true }
        try {
            if ($Process -and $Process.HasExited) { return $false }
        } catch {
            return $false
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Get-SupBackoffSeconds {
    param($Cfg, [int]$AttemptCount)
    $values = New-Object System.Collections.Generic.List[int]
    foreach ($v in @($Cfg.tunnel_backoff_schedule_seconds)) {
        $n = 0
        if ([int]::TryParse([string]$v, [ref]$n) -and $n -ge 0) { [void]$values.Add($n) }
    }
    if ($values.Count -eq 0) { [void]$values.Add(5) }
    $index = [Math]::Min([Math]::Max($AttemptCount - 1, 0), $values.Count - 1)
    return [int]$values[$index]
}

# --- main -----------------------------------------------------------------

if ($FunctionsOnly) { return }

$cfg = $null
$lock = $null
$job = [IntPtr]::Zero
$proc = $null
$finalExit = 0
$state = [ordered]@{
    schema = 'com2_mesh_tunnel_supervisor/v1'
    ts = ''
    state = 'starting'
    pid = $PID
    started_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    child_pid = $null
    attempt = 0
    max_attempts = 0
    stable_runs = 0
    forwarding_since = ''
    next_attempt_at = ''
    last_exit_code = $null
    last_run_seconds = $null
    last_error = ''
}

try {
    $cfg = Get-SupervisorConfig -Path $Config
    $state.max_attempts = [int]$cfg.tunnel_max_attempts
    $lock = New-SingleInstanceLock -Cfg $cfg
    if (-not $lock.ok) {
        Write-SupLog -Cfg $cfg -Message ('duplicate_refused pid={0} reason={1}' -f $PID, $lock.error)
        if ($lock.already_running) { $finalExit = 2 } else { $finalExit = 1 }
    } else {
        $job = New-ChildJob
        Write-SupLog -Cfg $cfg -Message ('supervisor_start pid={0} job_object={1}' -f $PID, ($job -ne [IntPtr]::Zero))
        $attempt = 0
        $stableRuns = 0
        if ($job -eq [IntPtr]::Zero) {
            $state.state = 'error'
            $state.last_error = 'job_object_unavailable'
            Write-SupState -Cfg $cfg -State $state
            Write-SupLog -Cfg $cfg -Message 'job_object_unavailable'
            $finalExit = 1
        } else {
        while ($true) {
            $child = Start-OwnedChild -Cfg $cfg -Job $job
            if (-not $child.ok) {
                if ($child.error -eq 'job_object_assign_failed') {
                    $state.state = 'error'
                    $state.last_error = 'job_object_assign_failed'
                    Write-SupState -Cfg $cfg -State $state
                    Write-SupLog -Cfg $cfg -Message 'job_object_assign_failed'
                    $finalExit = 1
                    break
                }
                $attempt++
                $state.attempt = $attempt
                $state.last_error = [string]$child.error
                $state.state = 'backoff'
                $max = [int]$cfg.tunnel_max_attempts
                if ($max -gt 0 -and $attempt -ge $max) {
                    $state.state = 'exhausted'
                    $state.next_attempt_at = ''
                    Write-SupState -Cfg $cfg -State $state
                    Write-SupLog -Cfg $cfg -Message ('retry_exhausted attempts={0} error={1}' -f $attempt, $child.error)
                    $finalExit = 3
                    break
                }
                $delay = Get-SupBackoffSeconds -Cfg $cfg -AttemptCount $attempt
                $state.next_attempt_at = (Get-Date).AddSeconds($delay).ToString('yyyy-MM-dd HH:mm:ss')
                Write-SupState -Cfg $cfg -State $state
                Write-SupLog -Cfg $cfg -Message ('child_start_failed attempt={0} backoff={1}s error={2}' -f $attempt, $delay, $child.error)
                Start-Sleep -Seconds $delay
                continue
            }

            $proc = $child.process
            $state.child_pid = $proc.Id
            $state.state = 'starting'
            Write-SupState -Cfg $cfg -State $state
            Write-SupLog -Cfg $cfg -Message ('child_started pid={0} attempt={1}' -f $proc.Id, $attempt)

            $childStarted = Get-Date
            $ready = Wait-ForwardListener -Cfg $cfg -Process $proc -TimeoutSeconds ([int]$cfg.tunnel_ready_wait_seconds)
            if (-not $ready) {
                $state.last_error = 'forward listener did not come up'
                Stop-ForwardChild -Process $proc
                $proc = $null
                $attempt++
                $state.child_pid = $null
                $state.attempt = $attempt
                $state.state = 'backoff'
                $max = [int]$cfg.tunnel_max_attempts
                if ($max -gt 0 -and $attempt -ge $max) {
                    $state.state = 'exhausted'
                    $state.next_attempt_at = ''
                    Write-SupState -Cfg $cfg -State $state
                    Write-SupLog -Cfg $cfg -Message ('retry_exhausted attempts={0} error=forward_listener_down' -f $attempt)
                    $finalExit = 3
                    break
                }
                $delay = Get-SupBackoffSeconds -Cfg $cfg -AttemptCount $attempt
                $state.next_attempt_at = (Get-Date).AddSeconds($delay).ToString('yyyy-MM-dd HH:mm:ss')
                Write-SupState -Cfg $cfg -State $state
                Write-SupLog -Cfg $cfg -Message ('forward_listener_down attempt={0} backoff={1}s' -f $attempt, $delay)
                Start-Sleep -Seconds $delay
                continue
            }

            $state.state = 'forwarding'
            $state.forwarding_since = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
            $state.last_error = ''
            Write-SupState -Cfg $cfg -State $state
            Write-SupLog -Cfg $cfg -Message ('forwarding child_pid={0}' -f $proc.Id)

            try { $proc.WaitForExit() } catch { }
            $runSeconds = [Math]::Round(((Get-Date) - $childStarted).TotalSeconds, 1)
            $exitCode = $null
            try { $exitCode = $proc.ExitCode } catch { }
            $state.child_pid = $null
            $state.forwarding_since = ''
            $state.last_exit_code = $exitCode
            $state.last_run_seconds = $runSeconds
            Stop-ForwardChild -Process $proc
            $proc = $null

            if ($runSeconds -ge [int]$cfg.tunnel_stable_seconds) {
                $attempt = 0
                $stableRuns++
                $state.stable_runs = $stableRuns
            }
            $attempt++
            $state.attempt = $attempt
            $max = [int]$cfg.tunnel_max_attempts
            if ($max -gt 0 -and $attempt -ge $max) {
                $state.state = 'exhausted'
                $state.next_attempt_at = ''
                Write-SupState -Cfg $cfg -State $state
                Write-SupLog -Cfg $cfg -Message ('retry_exhausted attempts={0} last_exit={1} run_seconds={2}' -f
                    $attempt, $exitCode, $runSeconds)
                $finalExit = 3
                break
            }
            $delay = Get-SupBackoffSeconds -Cfg $cfg -AttemptCount $attempt
            $state.state = 'backoff'
            $state.next_attempt_at = (Get-Date).AddSeconds($delay).ToString('yyyy-MM-dd HH:mm:ss')
            Write-SupState -Cfg $cfg -State $state
            Write-SupLog -Cfg $cfg -Message ('child_exit exit={0} run_seconds={1} attempt={2} backoff={3}s' -f
                $exitCode, $runSeconds, $attempt, $delay)
            Start-Sleep -Seconds $delay
        }
        }
    }
} catch {
    if ($cfg) {
        $state.state = 'error'
        $state.last_error = $_.Exception.Message
        Write-SupState -Cfg $cfg -State $state
        Write-SupLog -Cfg $cfg -Message ('supervisor_error {0}' -f $_.Exception.Message)
    }
    [Console]::Error.WriteLine(('tunnel supervisor failed: {0}' -f $_.Exception.Message))
    $finalExit = 1
} finally {
    Stop-ForwardChild -Process $proc
    if ($job -ne [IntPtr]::Zero) {
        try { [Com2MeshTunnelJob]::Close($job) } catch { }
    }
    if ($lock -and $lock.stream) {
        try { $lock.stream.Dispose() } catch { }
    }
    if ($cfg) {
        if ($lock -and $lock.ok) {
            try { Remove-Item -LiteralPath $cfg.tunnel_lock_file -Force -ErrorAction SilentlyContinue } catch { }
        }
        Write-SupLog -Cfg $cfg -Message ('supervisor_stop pid={0} exit={1}' -f $PID, $finalExit)
    }
}

exit $finalExit
