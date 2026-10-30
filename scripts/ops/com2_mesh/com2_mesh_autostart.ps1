<#
.SYNOPSIS
  Read-only observation probe for COM1 Mesh auto-start evidence.

.DESCRIPTION
  Replaces a hardcoded auto_start_verified with values that were observed after
  the current boot:

  - the MeshAgent service state and start mode, and the service process start;
  - the MeshCentral HTTP code on the direct COM2 path.

  Every check is tri-state: true (observed and satisfied), false (observed and
  not satisfied) and null (not observed). auto_start_verified is true only when
  every check is true.

  The tunnel task, the loopback listener and the supervisor-identity checks were
  removed with #5643: the agent reaches COM2 through its own ingress, so there
  is no COM1 forward task, listener or supervisor left to observe.

  The probe never starts, stops or reconfigures a process, service or task. It
  performs read-only queries and one bounded HTTP GET.

.PARAMETER Config
  Recovery config JSON. Required keys: com2_host. Optional keys: mesh_url
  (derived from com2_host and com2_mesh_port when absent), mesh_agent_service,
  com2_mesh_port, autostart_boot_tolerance_seconds, autostart_http_timeout_seconds.
  Legacy tunnel keys in an existing config are ignored.

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
    foreach ($name in @('com2_host')) {
        if (-not $cfg.PSObject.Properties[$name]) { throw "config key missing: $name" }
        if ([string]::IsNullOrWhiteSpace([string]$cfg.$name)) { throw "config key is empty: $name" }
    }
    Set-AutostartDefault -Cfg $cfg -Name 'mesh_agent_service' -Value 'Mesh Agent'
    Set-AutostartDefault -Cfg $cfg -Name 'mesh_scheme' -Value 'https'
    Set-AutostartDefault -Cfg $cfg -Name 'com2_mesh_port' -Value 4443
    if (-not $cfg.PSObject.Properties['mesh_url']) {
        $cfg | Add-Member -NotePropertyName 'mesh_url' -NotePropertyValue (
            "{0}://{1}:{2}/" -f $cfg.mesh_scheme, $cfg.com2_host, $cfg.com2_mesh_port)
    }
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

function Get-RemoteHttpObservation {
    param([string]$ConfigPath)
    $obs = [ordered]@{ queried = $false; code = 0; error = '' }
    try {
        $recovery = Join-Path $PSScriptRoot 'com2_mesh_recovery.ps1'
        if (-not (Test-Path -LiteralPath $recovery)) { throw 'recovery engine not found' }
        . $recovery -FunctionsOnly
        $recoveryCfg = Get-Config -Path $ConfigPath
        $result = Invoke-RemoteProbe -Cfg $recoveryCfg
        if (-not $result.ok) { throw 'COM2 remote probe unavailable' }
        if ([string]$result.http -notmatch '^\d{3}$' -or [string]$result.http -eq '000') {
            throw 'COM2 remote HTTP response unavailable'
        }
        $obs.queried = $true
        $obs.code = [int]$result.http
    } catch {
        $obs.error = $_.Exception.Message
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
        mesh_http = Get-RemoteHttpObservation -ConfigPath $Config
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
