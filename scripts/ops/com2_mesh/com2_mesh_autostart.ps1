<#
.SYNOPSIS
  Read-only observation probe for COM1 Mesh auto-start evidence.

.DESCRIPTION
  Replaces a hardcoded auto_start_verified with values that were observed after
  the current boot:

  - the MeshAgent service state and start mode, and the service process start;
  - the tunnel scheduled task: enabled state, triggers, repetition duration,
    NextRunTime, LastRunTime and LastTaskResult;
  - the loopback forward listener process and its start time;
  - the MeshCentral HTTP code through the listener.

  Every check is tri-state: true (observed and satisfied), false (observed and
  not satisfied) and null (not observed). auto_start_verified is true only when
  every check is true.

  The probe never starts, stops or reconfigures a process, service or task. It
  performs read-only queries and one bounded HTTP GET, plus a local TCP connect
  through the listener.

.PARAMETER Config
  Recovery config JSON. Required keys: tunnel_task, tunnel_local_host,
  tunnel_local_port, mesh_url. Optional keys: mesh_agent_service,
  tunnel_process_name, autostart_boot_tolerance_seconds,
  autostart_http_timeout_seconds.

.PARAMETER ObservationFile
  Evaluate a recorded observation instead of querying the host. Used by the
  selftest and for mocked fault injection.

.PARAMETER OutFile
  Optional path for the JSON record.

.PARAMETER Json
  Write the record as one compressed JSON line.

.PARAMETER FunctionsOnly
  Define the functions and return. Used by the selftest.
#>
[CmdletBinding()]
param(
    [string]$Config = '',
    [string]$ObservationFile = '',
    [string]$OutFile = '',
    [switch]$Json,
    [switch]$FunctionsOnly
)

$ErrorActionPreference = 'Stop'

# --- settings -------------------------------------------------------------

function Set-AutostartDefault {
    param($Cfg, [string]$Name, $Value)
    if (-not $Cfg.PSObject.Properties[$Name]) {
        $Cfg | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Get-AutostartConfig {
    param([string]$Path)
    if (-not $Path) { throw 'config path is required' }
    if (-not (Test-Path -LiteralPath $Path)) { throw "config not found: $Path" }
    $cfg = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($name in @('tunnel_task', 'tunnel_local_host', 'tunnel_local_port', 'mesh_url')) {
        if (-not $cfg.PSObject.Properties[$name]) { throw "config key missing: $name" }
        if ([string]::IsNullOrWhiteSpace([string]$cfg.$name)) { throw "config key is empty: $name" }
    }
    Set-AutostartDefault -Cfg $cfg -Name 'mesh_agent_service' -Value 'Mesh Agent'
    Set-AutostartDefault -Cfg $cfg -Name 'tunnel_process_name' -Value 'ssh.exe'
    Set-AutostartDefault -Cfg $cfg -Name 'autostart_boot_tolerance_seconds' -Value 120
    Set-AutostartDefault -Cfg $cfg -Name 'autostart_http_timeout_seconds' -Value 8
    return $cfg
}

# --- time helpers ---------------------------------------------------------

function ConvertTo-ObsTimeString {
    param($Value)
    if ($null -eq $Value) { return '' }
    if ($Value -is [datetime]) {
        if ($Value.Year -lt 2000 -or $Value.Year -gt 2100) { return '' }
        return $Value.ToString('yyyy-MM-dd HH:mm:ss')
    }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return '' }
    $dt = [datetime]::MinValue
    if ([datetime]::TryParse($text, [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::None, [ref]$dt) -or
        [datetime]::TryParse($text, [ref]$dt)) {
        if ($dt.Year -lt 2000 -or $dt.Year -gt 2100) { return '' }
        return $dt.ToString('yyyy-MM-dd HH:mm:ss')
    }
    return ''
}

function ConvertFrom-ObsTime {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    $dt = [datetime]::MinValue
    if ([datetime]::TryParse($Value, [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::None, [ref]$dt) -or
        [datetime]::TryParse($Value, [ref]$dt)) {
        return $dt
    }
    return $null
}

function ConvertFrom-IsoDurationSeconds {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    if ($Value -eq 'PT0S') { return 0 }
    if ($Value -match '^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$') {
        $days = 0; $hours = 0; $minutes = 0; $seconds = 0.0
        if ($Matches[1]) { $days = [int]$Matches[1] }
        if ($Matches[2]) { $hours = [int]$Matches[2] }
        if ($Matches[3]) { $minutes = [int]$Matches[3] }
        if ($Matches[4]) { $seconds = [double]$Matches[4] }
        return [double]($days * 86400 + $hours * 3600 + $minutes * 60 + $seconds)
    }
    return $null
}

# --- observations ---------------------------------------------------------

function Get-BootObservation {
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        return @{ boot_time = (ConvertTo-ObsTimeString $os.LastBootUpTime); error = '' }
    } catch {
        return @{ boot_time = ''; error = $_.Exception.Message }
    }
}

function Get-MeshAgentObservation {
    param([string]$ServiceName)
    $obs = [ordered]@{
        queried = $true; exists = $false; name = $ServiceName
        status = ''; start_mode = ''; pid = 0; process_name = ''; process_started = ''
        error = ''
    }
    try {
        $safe = $ServiceName.Replace("'", "''")
        $svc = Get-CimInstance -ClassName Win32_Service -Filter ("Name='{0}'" -f $safe) -ErrorAction Stop |
            Select-Object -First 1
        if (-not $svc) { return $obs }
        $obs.exists = $true
        $obs.status = [string]$svc.State
        $obs.start_mode = [string]$svc.StartMode
        $obs.pid = [int]$svc.ProcessId
        if ($obs.pid -gt 0) {
            $proc = Get-Process -Id $obs.pid -ErrorAction Stop
            $obs.process_name = [string]$proc.ProcessName
            $obs.process_started = ConvertTo-ObsTimeString $proc.StartTime
        }
        return $obs
    } catch {
        $obs.queried = $false
        $obs.error = $_.Exception.Message
        return $obs
    }
}

function ConvertTo-TaskStateName {
    param($Value)
    $number = -1
    if ([int]::TryParse([string]$Value, [ref]$number)) {
        switch ($number) {
            0 { return 'Unknown' }
            1 { return 'Disabled' }
            2 { return 'Queued' }
            3 { return 'Ready' }
            4 { return 'Running' }
            default { return ('State{0}' -f $number) }
        }
    }
    return [string]$Value
}

function Get-TunnelTaskObservation {
    param([string]$TaskName)
    $obs = [ordered]@{
        queried = $true; exists = $false; name = $TaskName
        enabled = $false; state = ''; last_run = ''; last_result = $null
        next_run = ''; triggers = @(); info_error = ''; error = ''
    }
    try {
        $safe = $TaskName.Replace("'", "''")
        $task = Get-CimInstance -Namespace 'Root/Microsoft/Windows/TaskScheduler' `
            -ClassName MSFT_ScheduledTask -Filter ("TaskName='{0}'" -f $safe) -ErrorAction Stop |
            Select-Object -First 1
        if (-not $task) { return $obs }
        $obs.exists = $true
        $obs.enabled = [bool]$task.Settings.Enabled
        $obs.state = ConvertTo-TaskStateName $task.State

        $triggers = New-Object System.Collections.Generic.List[object]
        foreach ($t in @($task.Triggers)) {
            $class = [string]$t.CimClass.CimClassName
            $kind = 'other'
            if ($class -eq 'MSFT_TaskBootTrigger') { $kind = 'boot' }
            elseif ($class -eq 'MSFT_TaskTimeTrigger') { $kind = 'time' }
            elseif ($class -eq 'MSFT_TaskLogonTrigger') { $kind = 'logon' }
            elseif ($class -eq 'MSFT_TaskDailyTrigger') { $kind = 'daily' }
            $triggers.Add([ordered]@{
                kind = $kind
                enabled = [bool]$t.Enabled
                repetition_interval_seconds = ConvertFrom-IsoDurationSeconds ([string]$t.Repetition.Interval)
                repetition_duration_seconds = ConvertFrom-IsoDurationSeconds ([string]$t.Repetition.Duration)
            })
        }
        $obs.triggers = $triggers.ToArray()

        try {
            $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
            $obs.last_run = ConvertTo-ObsTimeString $info.LastRunTime
            if ($null -ne $info.LastTaskResult) { $obs.last_result = [int]$info.LastTaskResult }
            $obs.next_run = ConvertTo-ObsTimeString $info.NextRunTime
        } catch {
            $obs.info_error = $_.Exception.Message
        }
        return $obs
    } catch {
        $obs.queried = $false
        $obs.error = $_.Exception.Message
        return $obs
    }
}

function Get-ListenerObservation {
    param($Cfg)
    $obs = [ordered]@{
        queried = $true; listening = $false; local_address = ''
        pid = 0; process_name = ''; process_started = ''; error = ''
    }
    try {
        $port = [int]$Cfg.tunnel_local_port
        $connections = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop)
        $match = @($connections | Where-Object {
                [string]$_.LocalAddress -eq [string]$Cfg.tunnel_local_host
            }) | Select-Object -First 1
        if (-not $match) { $match = @($connections) | Select-Object -First 1 }
        if (-not $match) { return $obs }
        $obs.listening = $true
        $obs.local_address = [string]$match.LocalAddress
        $obs.pid = [int]$match.OwningProcess
        if ($obs.pid -gt 0) {
            $proc = Get-Process -Id $obs.pid -ErrorAction Stop
            $obs.process_name = [string]$proc.ProcessName
            $obs.process_started = ConvertTo-ObsTimeString $proc.StartTime
        }
        return $obs
    } catch {
        $obs.queried = $false
        $obs.error = $_.Exception.Message
        return $obs
    }
}

function Get-MeshHttpObservation {
    param([string]$Url, [int]$TimeoutSeconds)
    $obs = [ordered]@{ queried = $true; code = 0; error = '' }
    if ([string]::IsNullOrWhiteSpace($Url)) {
        $obs.queried = $false
        $obs.error = 'mesh_url is empty'
        return $obs
    }
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (-not (Test-Path -LiteralPath $curl)) {
        $obs.queried = $false
        $obs.error = 'curl.exe was not found'
        return $obs
    }
    $timeout = [Math]::Max(1, $TimeoutSeconds)
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # The MeshCentral endpoint uses a local self-signed certificate and the
        # Windows PowerShell 5.1 scriptblock certificate callback does not run
        # reliably on the .NET worker thread, so the bounded curl probe is used.
        $output = & $curl -s -k -o NUL -w '%{http_code}' --max-time $timeout $Url 2>&1
        $exitCode = $LASTEXITCODE
        $codeText = @($output | ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ -match '^\d{3}$' }) | Select-Object -Last 1
        if ($codeText) { $obs.code = [int]$codeText }
        if ($exitCode -ne 0) {
            $message = @($output | ForEach-Object { ([string]$_).Trim() } |
                Where-Object { $_ -and $_ -notmatch '^\d{3}$' }) -join ' '
            $obs.error = ('curl exit {0}' -f $exitCode)
            if ($message) { $obs.error += ': ' + $message }
        }
    } catch {
        $obs.queried = $false
        $obs.error = $_.Exception.Message
    } finally {
        $ErrorActionPreference = $previousEap
    }
    return $obs
}

function Get-AutostartObservation {
    param($Cfg)
    $boot = Get-BootObservation
    return [ordered]@{
        schema = 'com2_mesh_autostart_observation/v1'
        observed_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        boot_time = $boot.boot_time
        boot_error = $boot.error
        mesh_agent = Get-MeshAgentObservation -ServiceName ([string]$Cfg.mesh_agent_service)
        tunnel_task = Get-TunnelTaskObservation -TaskName ([string]$Cfg.tunnel_task)
        listener = Get-ListenerObservation -Cfg $Cfg
        mesh_http = Get-MeshHttpObservation -Url ([string]$Cfg.mesh_url) -TimeoutSeconds ([int]$Cfg.autostart_http_timeout_seconds)
    }
}

# --- evaluation -----------------------------------------------------------

function New-AutostartCheck {
    param([string]$Name, $Ok, [string]$Detail, $Observed, $Expected)
    return [ordered]@{
        name = $Name
        ok = $Ok
        detail = $Detail
        observed = $Observed
        expected = $Expected
    }
}

function Test-AutostartEvidence {
    param($Observation, $Cfg, [datetime]$Now)
    if (-not $Now) { $Now = Get-Date }
    $tolerance = [double]$Cfg.autostart_boot_tolerance_seconds
    if ($tolerance -lt 0) { $tolerance = 0 }

    $checks = New-Object System.Collections.Generic.List[object]
    $boot = ConvertFrom-ObsTime ([string]$Observation.boot_time)
    $bootDetail = if ($boot) { 'LastBootUpTime was read' } else { 'last boot time was not observed' }
    if (-not $boot -and $Observation.boot_error) {
        $bootDetail = 'last boot time was not observed: ' + [string]$Observation.boot_error
    }
    $checks.Add((New-AutostartCheck 'boot_time_observed' ([bool]$boot) $bootDetail `
        ([string]$Observation.boot_time) 'a boot timestamp'))

    # MeshAgent service
    $agent = $Observation.mesh_agent
    $agentQueried = ($agent -and $agent.queried -eq $true)
    $agentNames = @('mesh_agent_service_automatic', 'mesh_agent_running', 'mesh_agent_running_since_boot')
    if (-not $agentQueried) {
        $reason = 'the MeshAgent service was not queried'
        if ($agent -and $agent.error) { $reason += ': ' + [string]$agent.error }
        foreach ($name in $agentNames) {
            $checks.Add((New-AutostartCheck $name $null $reason '' 'observed service state'))
        }
    } elseif ($agent.exists -ne $true) {
        foreach ($name in $agentNames) {
            $checks.Add((New-AutostartCheck $name $false 'the configured MeshAgent service was not found' '' 'the service exists'))
        }
    } else {
        $startMode = ([string]$agent.start_mode).Trim().ToLowerInvariant()
        $automaticOk = ($startMode -eq 'auto' -or $startMode -eq 'automatic' -or $startMode -eq 'automaticdelayedstart')
        $checks.Add((New-AutostartCheck 'mesh_agent_service_automatic' $automaticOk `
            ('start_mode=' + [string]$agent.start_mode) ([string]$agent.start_mode) 'Auto'))
        $running = ([string]$agent.status -eq 'Running')
        $checks.Add((New-AutostartCheck 'mesh_agent_running' $running `
            ('status=' + [string]$agent.status) ([string]$agent.status) 'Running'))

        $agentStarted = ConvertFrom-ObsTime ([string]$agent.process_started)
        $sinceBootOk = $null
        $sinceBootDetail = ''
        if (-not $boot) {
            $sinceBootDetail = 'not verified: last boot time was not observed'
        } elseif (-not $agentStarted) {
            $sinceBootDetail = 'not verified: the service process start time was not observed'
        } else {
            $sinceBootOk = ($agentStarted -ge $boot.AddSeconds(-1 * $tolerance))
            $sinceBootDetail = ('process started {0}; boot {1}' -f
                $agentStarted.ToString('yyyy-MM-dd HH:mm:ss'), $boot.ToString('yyyy-MM-dd HH:mm:ss'))
        }
        $checks.Add((New-AutostartCheck 'mesh_agent_running_since_boot' $sinceBootOk $sinceBootDetail `
            ([string]$agent.process_started) 'a process start at or after boot'))
    }

    # Tunnel task
    $task = $Observation.tunnel_task
    $taskQueried = ($task -and $task.queried -eq $true)
    $taskNames = @('tunnel_task_exists', 'tunnel_task_enabled', 'tunnel_task_autostart_trigger',
        'tunnel_task_repetition_unbounded', 'tunnel_task_next_run_present',
        'tunnel_task_ran_after_boot', 'tunnel_task_last_result_ok')
    if (-not $taskQueried) {
        $reason = 'the tunnel task was not queried'
        if ($task -and $task.error) { $reason += ': ' + [string]$task.error }
        foreach ($name in $taskNames) {
            $checks.Add((New-AutostartCheck $name $null $reason '' 'observed task state'))
        }
    } else {
        $taskExists = ($task.exists -eq $true)
        $checks.Add((New-AutostartCheck 'tunnel_task_exists' $taskExists `
            ('task=' + [string]$task.name) ([string]$task.name) 'the task exists'))
        if (-not $taskExists) {
            foreach ($name in $taskNames[1..($taskNames.Count - 1)]) {
                $checks.Add((New-AutostartCheck $name $false 'the configured tunnel task was not found' '' 'the task exists'))
            }
        } else {
            $enabled = ($task.enabled -eq $true -and [string]$task.state -ne 'Disabled')
            $checks.Add((New-AutostartCheck 'tunnel_task_enabled' $enabled `
                ('enabled={0}; state={1}' -f $task.enabled, $task.state) ([string]$task.state) 'enabled and not Disabled'))

            $triggers = @($task.triggers)
            $autoTriggers = @($triggers | Where-Object {
                    ($_.kind -eq 'boot' -or $_.kind -eq 'time' -or $_.kind -eq 'logon' -or $_.kind -eq 'daily') -and
                    $_.enabled -ne $false
                })
            $triggerKinds = @($triggers | ForEach-Object { [string]$_.kind }) -join ','
            $checks.Add((New-AutostartCheck 'tunnel_task_autostart_trigger' ($autoTriggers.Count -gt 0) `
                ('triggers=' + $triggerKinds) $triggerKinds 'a boot, logon, daily or time trigger'))

            $timeReps = @($triggers | Where-Object {
                    $_.kind -eq 'time' -and $null -ne $_.repetition_interval_seconds
                })
            $finite = @($timeReps | Where-Object {
                    $null -ne $_.repetition_duration_seconds -and [double]$_.repetition_duration_seconds -gt 0
                })
            if ($finite.Count -gt 0) {
                $durations = @($finite | ForEach-Object { [string]$_.repetition_duration_seconds }) -join ','
                $checks.Add((New-AutostartCheck 'tunnel_task_repetition_unbounded' $false `
                    ('finite repetition duration(s): ' + $durations + 's') $durations 'no finite Duration (empty or PT0S)'))
            } else {
                $checks.Add((New-AutostartCheck 'tunnel_task_repetition_unbounded' $true `
                    'no finite repetition duration' '' 'no finite Duration (empty or PT0S)'))
            }

            $infoError = [string]$task.info_error
            $next = ConvertFrom-ObsTime ([string]$task.next_run)
            if ($infoError) {
                $checks.Add((New-AutostartCheck 'tunnel_task_next_run_present' $null `
                    ('not verified: task run info was not read: ' + $infoError) '' 'a future NextRunTime'))
            } elseif ($timeReps.Count -eq 0) {
                $checks.Add((New-AutostartCheck 'tunnel_task_next_run_present' $true `
                    'no time-trigger repetition, so NextRunTime is not required' '' 'a future NextRunTime when a repetition exists'))
            } elseif (-not $next) {
                $checks.Add((New-AutostartCheck 'tunnel_task_next_run_present' $false `
                    'NextRunTime is empty, which is what an expired repetition looks like' '' 'a future NextRunTime'))
            } elseif ($next -lt $Now.AddSeconds(-1 * $tolerance)) {
                $checks.Add((New-AutostartCheck 'tunnel_task_next_run_present' $false `
                    ('NextRunTime is in the past: ' + $next.ToString('yyyy-MM-dd HH:mm:ss')) '' 'a future NextRunTime'))
            } else {
                $checks.Add((New-AutostartCheck 'tunnel_task_next_run_present' $true `
                    ('NextRunTime=' + $next.ToString('yyyy-MM-dd HH:mm:ss')) ([string]$task.next_run) 'a future NextRunTime'))
            }

            $last = ConvertFrom-ObsTime ([string]$task.last_run)
            $ranOk = $null
            $ranDetail = ''
            if ($infoError) {
                $ranDetail = 'not verified: task run info was not read'
            } elseif (-not $boot) {
                $ranDetail = 'not verified: last boot time was not observed'
            } elseif (-not $last) {
                $ranOk = $false
                $ranDetail = 'LastRunTime is empty, so the task did not run after boot'
            } else {
                $ranOk = ($last -ge $boot.AddSeconds(-1 * $tolerance))
                $ranDetail = ('last run {0}; boot {1}' -f
                    $last.ToString('yyyy-MM-dd HH:mm:ss'), $boot.ToString('yyyy-MM-dd HH:mm:ss'))
            }
            $checks.Add((New-AutostartCheck 'tunnel_task_ran_after_boot' $ranOk $ranDetail `
                ([string]$task.last_run) 'a run at or after boot'))

            $resultOk = $null
            $resultDetail = ''
            if ($infoError) {
                $resultDetail = 'not verified: task run info was not read'
            } elseif ($null -eq $task.last_result) {
                $resultDetail = 'not verified: LastTaskResult was not observed'
            } else {
                $code = [int]$task.last_result
                $resultOk = ($code -eq 0 -or $code -eq 267009)
                $resultDetail = 'LastTaskResult=' + $code
                if ($code -eq 267009) { $resultDetail += ' (running)' }
                elseif ($code -eq 267011) { $resultDetail += ' (has not run yet)' }
                elseif ($code -eq 267010) { $resultDetail += ' (disabled)' }
            }
            $checks.Add((New-AutostartCheck 'tunnel_task_last_result_ok' $resultOk $resultDetail `
                $task.last_result '0 or 267009 while running'))
        }
    }

    # Forward listener
    $listener = $Observation.listener
    $listenerQueried = ($listener -and $listener.queried -eq $true)
    if (-not $listenerQueried) {
        $reason = 'the forward listener was not queried'
        if ($listener -and $listener.error) { $reason += ': ' + [string]$listener.error }
        foreach ($name in @('tunnel_listener_present', 'tunnel_listener_started_after_boot', 'tunnel_listener_process_matches')) {
            $checks.Add((New-AutostartCheck $name $null $reason '' 'observed listener state'))
        }
    } elseif ($listener.listening -ne $true) {
        $checks.Add((New-AutostartCheck 'tunnel_listener_present' $false 'no listener on the configured loopback port' '' 'a listener'))
        $checks.Add((New-AutostartCheck 'tunnel_listener_started_after_boot' $null 'not verified: there is no listener process' '' 'a process start at or after boot'))
        $checks.Add((New-AutostartCheck 'tunnel_listener_process_matches' $null 'not verified: there is no listener process' '' 'the configured process name'))
    } else {
        $checks.Add((New-AutostartCheck 'tunnel_listener_present' $true `
            ('listening on {0}; pid={1}' -f $listener.local_address, $listener.pid) ([string]$listener.local_address) 'a listener'))

        $listenerStarted = ConvertFrom-ObsTime ([string]$listener.process_started)
        $listenerBootOk = $null
        $listenerBootDetail = ''
        if (-not $boot) {
            $listenerBootDetail = 'not verified: last boot time was not observed'
        } elseif (-not $listenerStarted) {
            $listenerBootDetail = 'not verified: the listener process start time was not observed'
        } else {
            $listenerBootOk = ($listenerStarted -ge $boot.AddSeconds(-1 * $tolerance))
            $listenerBootDetail = ('process started {0}; boot {1}' -f
                $listenerStarted.ToString('yyyy-MM-dd HH:mm:ss'), $boot.ToString('yyyy-MM-dd HH:mm:ss'))
        }
        $checks.Add((New-AutostartCheck 'tunnel_listener_started_after_boot' $listenerBootOk $listenerBootDetail `
            ([string]$listener.process_started) 'a process start at or after boot'))

        $expectedName = [System.IO.Path]::GetFileNameWithoutExtension([string]$Cfg.tunnel_process_name)
        $actualName = [System.IO.Path]::GetFileNameWithoutExtension([string]$listener.process_name)
        if (-not $actualName) {
            $checks.Add((New-AutostartCheck 'tunnel_listener_process_matches' $null `
                'not verified: the listener process name was not observed' '' $expectedName))
        } else {
            $matchOk = ($expectedName -ne '' -and ($expectedName -ieq $actualName))
            $checks.Add((New-AutostartCheck 'tunnel_listener_process_matches' $matchOk `
                ('process=' + $actualName) $actualName $expectedName))
        }
    }

    # MeshCentral HTTP through the listener
    $http = $Observation.mesh_http
    if (-not $http -or $http.queried -ne $true) {
        $reason = 'the MeshCentral HTTP probe did not run'
        if ($http -and $http.error) { $reason += ': ' + [string]$http.error }
        $checks.Add((New-AutostartCheck 'mesh_http_200' $null $reason '' 'HTTP 200'))
    } else {
        $code = 0
        if ($null -ne $http.code) { $code = [int]$http.code }
        $httpDetail = 'HTTP ' + $code
        if ($http.error) { $httpDetail += ': ' + [string]$http.error }
        $checks.Add((New-AutostartCheck 'mesh_http_200' ($code -eq 200) $httpDetail $code 'HTTP 200'))
    }

    $failed = @($checks | Where-Object { $_.ok -eq $false } | ForEach-Object { [string]$_.name })
    $unverified = @($checks | Where-Object { $null -eq $_.ok } | ForEach-Object { [string]$_.name })
    $state = 'verified'
    if ($failed.Count -gt 0) { $state = 'failed' }
    elseif ($unverified.Count -gt 0) { $state = 'unverified' }

    return [ordered]@{
        schema = 'com2_mesh_autostart/v1'
        ts = $Now.ToString('yyyy-MM-dd HH:mm:ss')
        source = 'observed'
        auto_start_verified = ($state -eq 'verified')
        auto_start_state = $state
        boot_time = [string]$Observation.boot_time
        checked_at = [string]$Observation.observed_at
        checks = $checks.ToArray()
        failed_checks = $failed
        unverified_checks = $unverified
        observation = $Observation
    }
}

# --- main -----------------------------------------------------------------

if ($FunctionsOnly) { return }

try {
    $cfg = Get-AutostartConfig -Path $Config
    if ($ObservationFile) {
        if (-not (Test-Path -LiteralPath $ObservationFile)) { throw "observation file not found: $ObservationFile" }
        $observation = Get-Content -LiteralPath $ObservationFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } else {
        $observation = Get-AutostartObservation -Cfg $cfg
    }
    $record = Test-AutostartEvidence -Observation $observation -Cfg $cfg -Now (Get-Date)
    $jsonText = $record | ConvertTo-Json -Depth 10 -Compress
    if ($OutFile) {
        [System.IO.File]::WriteAllText($OutFile, $jsonText,
            (New-Object System.Text.UTF8Encoding($false)))
    }
    if ($Json) {
        Write-Output $jsonText
    } else {
        Write-Output ('auto_start_verified={0} state={1}' -f $record.auto_start_verified, $record.auto_start_state)
        foreach ($check in $record.checks) {
            $label = 'UNVERIFIED'
            if ($check.ok -eq $true) { $label = 'PASS' }
            elseif ($check.ok -eq $false) { $label = 'FAIL' }
            Write-Output ('{0} {1}: {2}' -f $label, $check.name, $check.detail)
        }
    }
    exit 0
} catch {
    [Console]::Error.WriteLine(('autostart probe failed: {0}' -f $_.Exception.Message))
    exit 1
}
