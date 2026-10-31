<#
.SYNOPSIS
  Health display fields for the COM2 Mesh auto-start probe record.

.DESCRIPTION
  Dot-sourced by the out-of-repo health monitor (com2-mesh-health.ps1) through
  the patch applied by com2_mesh_health_patch.ps1. It renders the per-check
  detail of a com2_mesh_autostart.ps1 record as one HTML row.

  Display contract:

  - The check verdicts are never touched. auto_start_state, auto_start_verified,
    failed_checks and unverified_checks keep exactly what the probe recorded, so
    an existing failure stays visible next to the detail row.
  - The detail row lists every check as name=verdict (true / false / unverified)
    in the order the probe recorded. It is a rendering of the record only; this
    module never re-derives or upgrades a verdict.
  - A record without checks (an older deployed probe) is shown as not_reported.

  The supervisor and last-start-attempt rows were removed with #5643 together
  with the record fields they rendered.

  The module performs no host queries and no writes other than the status
  fields it is given.
#>

function Add-AutostartDisplayFields {
    param($Status, $Autostart)
    $Status.auto_start_checks_detail = ''

    if (-not $Autostart) {
        $Status.auto_start_checks_detail = 'probe_not_run'
        return
    }

    $checks = @()
    if ($Autostart.PSObject.Properties['checks']) { $checks = @($Autostart.checks) }
    if ($checks.Count -eq 0) {
        $Status.auto_start_checks_detail = 'not_reported'
        return
    }
    $parts = foreach ($check in $checks) {
        $verdict = 'unverified'
        if ($check.ok -eq $true) { $verdict = 'true' }
        elseif ($check.ok -eq $false) { $verdict = 'false' }
        ('{0}={1}' -f [string]$check.name, $verdict)
    }
    $Status.auto_start_checks_detail = ($parts -join '; ')
}

function New-AutostartDisplayRows {
    param($Status)
    $rows = New-Object System.Collections.Generic.List[string]
    $rows.Add(("<tr><td>Auto-start checks (per-check verdict)</td><td>{0}</td></tr>" -f
            [string]$Status.auto_start_checks_detail))
    return ($rows -join "`n")
}
