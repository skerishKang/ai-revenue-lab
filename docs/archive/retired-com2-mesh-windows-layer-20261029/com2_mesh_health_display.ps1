<#
.SYNOPSIS
  Health display fields for the COM2 Mesh auto-start probe record.

.DESCRIPTION
  Dot-sourced by the out-of-repo health monitor (com2-mesh-health.ps1) through
  the patch applied by com2_mesh_health_patch.ps1. It copies the supervisor and
  last-start-attempt fields of a com2_mesh_autostart.ps1 record into flat health
  status fields and renders the matching HTML rows.

  Display contract:

  - The check verdicts are never touched. auto_start_state, auto_start_verified,
    failed_checks and unverified_checks keep exactly what the probe recorded, so
    an existing failure stays visible next to the new fields.
  - A normal running supervisor is shown only when the probe recorded
    identity=confirmed together with a running_* state. The probe confirms that
    only when the listener exists, is owned by the configured process, and that
    process is a child of a process whose command line names the supervisor
    script. This module never re-derives or upgrades a state.
  - A refusal code is shown with the outcome and confidence the probe recorded.
    suspected_refused_while_running / suspected is an inference from the result
    code plus a confirmed running supervisor; Task Scheduler events are not
    read by the probe, and the original result code and run time are preserved.
  - A record without the new fields (an older deployed probe) is shown as
    not_reported, never as a normal running state.

  The module performs no host queries and no writes other than the status
  fields it is given.
#>

function Get-AutostartDisplayClass {
    param([string]$State, [string]$Identity)
    if ($State -eq 'running_connected' -and $Identity -eq 'confirmed') { return 'ok' }
    if ($State -eq 'not_running') { return 'bad' }
    if ($State -like 'running_*' -and $Identity -ne 'confirmed') { return 'bad' }
    return ''
}

function Add-AutostartDisplayFields {
    param($Status, $Autostart)
    $Status.auto_start_supervisor_state = ''
    $Status.auto_start_supervisor_identity = ''
    $Status.auto_start_supervisor_child = ''
    $Status.auto_start_last_attempt_run = ''
    $Status.auto_start_last_attempt_result = ''
    $Status.auto_start_last_attempt_result_hex = ''
    $Status.auto_start_last_attempt_outcome = ''
    $Status.auto_start_last_attempt_confidence = ''
    $Status.auto_start_last_attempt_detail = ''

    if (-not $Autostart) {
        $Status.auto_start_supervisor_state = 'probe_not_run'
        $Status.auto_start_supervisor_identity = 'probe_not_run'
        $Status.auto_start_last_attempt_outcome = 'probe_not_run'
        $Status.auto_start_last_attempt_confidence = 'unknown'
        return
    }

    $supervisor = $Autostart.supervisor
    if ($supervisor) {
        $Status.auto_start_supervisor_state = [string]$supervisor.state
        $Status.auto_start_supervisor_identity = [string]$supervisor.identity
        $Status.auto_start_supervisor_child = ('child_pid={0}; child={1}; parent_pid={2}' -f
            [string]$supervisor.child_pid, [string]$supervisor.child_process, [string]$supervisor.parent_pid)
    } else {
        $Status.auto_start_supervisor_state = 'not_reported'
        $Status.auto_start_supervisor_identity = 'not_reported'
        $Status.auto_start_supervisor_child = 'not_reported'
    }

    $attempt = $Autostart.last_start_attempt
    if ($attempt) {
        $Status.auto_start_last_attempt_run = [string]$attempt.run
        $Status.auto_start_last_attempt_result = [string]$attempt.result
        $Status.auto_start_last_attempt_result_hex = [string]$attempt.result_hex
        $Status.auto_start_last_attempt_outcome = [string]$attempt.outcome
        $Status.auto_start_last_attempt_confidence = [string]$attempt.confidence
        $Status.auto_start_last_attempt_detail = [string]$attempt.detail
    } else {
        $Status.auto_start_last_attempt_outcome = 'not_reported'
        $Status.auto_start_last_attempt_confidence = 'unknown'
        $Status.auto_start_last_attempt_detail = 'the probe record has no last_start_attempt field'
    }
}

function New-AutostartDisplayRows {
    param($Status)
    $supervisorClass = Get-AutostartDisplayClass `
        -State ([string]$Status.auto_start_supervisor_state) `
        -Identity ([string]$Status.auto_start_supervisor_identity)
    $outcome = [string]$Status.auto_start_last_attempt_outcome
    $attemptClass = ''
    if ($outcome -eq 'succeeded') { $attemptClass = 'ok' }
    elseif ($outcome -eq 'failed' -or $outcome -eq 'duplicate_instance_exit') { $attemptClass = 'bad' }
    $rows = New-Object System.Collections.Generic.List[string]
    $rows.Add(("<tr><td>Supervisor / identity</td><td class='{0}'>{1} / {2}</td></tr>" -f
            $supervisorClass, $Status.auto_start_supervisor_state, $Status.auto_start_supervisor_identity))
    $rows.Add(("<tr><td>Supervisor child / listener owner</td><td>{0}</td></tr>" -f
            $Status.auto_start_supervisor_child))
    $rows.Add(("<tr><td>Last start attempt (time / result)</td><td>{0} / {1} {2}</td></tr>" -f
            $Status.auto_start_last_attempt_run, $Status.auto_start_last_attempt_result,
            $Status.auto_start_last_attempt_result_hex))
    $rows.Add(("<tr><td>Last start attempt (outcome / confidence)</td><td class='{0}'>{1} / {2}</td></tr>" -f
            $attemptClass, $outcome, $Status.auto_start_last_attempt_confidence))
    $rows.Add(("<tr><td>Last start attempt detail</td><td>{0}</td></tr>" -f
            $Status.auto_start_last_attempt_detail))
    return ($rows -join "`n")
}
