<#
.SYNOPSIS
  Render and verify the COM1 tunnel task XML without registering it.

.DESCRIPTION
  The template carries no account, path or key. This script replaces the
  placeholders, writes a UTF-16 task XML file and verifies the invariants that
  the old task lost:

  - the five-minute repetition has no Duration, so it does not expire;
  - StartWhenAvailable is true and MultipleInstancesPolicy is IgnoreNew;
  - the execution time limit is unlimited (PT0S);
  - the boot trigger and the S4U principal are present.

  It never calls Register-ScheduledTask, Unregister-ScheduledTask or
  schtasks. Applying the rendered file is an operator decision documented in
  the hardening plan.

.PARAMETER OutputPath
  Destination for the rendered UTF-16 XML file. When omitted the XML is
  written to stdout.

.PARAMETER StartBoundary
  Local start boundary for the time trigger, for example 2026-10-23T00:00:00.
  When omitted it defaults to local midnight of today. The repetition has no
  Duration, so the boundary is only the base of an indefinite schedule.

.PARAMETER FunctionsOnly
  Define the functions and return. Used by the selftest.
#>
[CmdletBinding()]
param(
    [string]$TemplatePath = '',
    [string]$OutputPath = '',
    [string]$TaskUser = '',
    [string]$StartBoundary = '',
    [string]$PowerShellPath = '',
    [string]$SupervisorPath = '',
    [string]$ConfigPath = '',
    [string]$WorkingDirectory = '',
    [switch]$FunctionsOnly
)

$ErrorActionPreference = 'Stop'
$TaskNamespace = 'http://schemas.microsoft.com/windows/2004/02/mit/task'

function New-TaskXmlText {
    param([string]$TemplateText, [hashtable]$Values)
    $text = $TemplateText
    foreach ($key in $Values.Keys) {
        $safe = [System.Security.SecurityElement]::Escape([string]$Values[$key])
        $text = $text.Replace(('{{' + $key + '}}'), $safe)
    }
    return $text
}

function Get-TaskXmlViolations {
    param([string]$XmlText, [hashtable]$Expected)
    $violations = New-Object System.Collections.Generic.List[string]
    if (-not $XmlText) {
        [void]$violations.Add('xml_empty')
        return @($violations)
    }
    if ($XmlText.Contains('{{')) { [void]$violations.Add('placeholder_remaining') }

    $doc = New-Object System.Xml.XmlDocument
    $doc.PreserveWhitespace = $true
    try {
        $doc.LoadXml($XmlText)
    } catch {
        [void]$violations.Add('xml_invalid')
        return @($violations)
    }
    $ns = New-Object System.Xml.XmlNamespaceManager($doc.NameTable)
    $ns.AddNamespace('t', $TaskNamespace)

    $boot = $doc.SelectSingleNode('/t:Task/t:Triggers/t:BootTrigger', $ns)
    if ($null -eq $boot) { [void]$violations.Add('boot_trigger_missing') }
    else {
        $enabled = $boot.SelectSingleNode('t:Enabled', $ns)
        if ($null -eq $enabled -or $enabled.InnerText.Trim() -ne 'true') {
            [void]$violations.Add('boot_trigger_disabled')
        }
    }

    $time = $doc.SelectSingleNode('/t:Task/t:Triggers/t:TimeTrigger', $ns)
    if ($null -eq $time) { [void]$violations.Add('time_trigger_missing') }
    else {
        $enabled = $time.SelectSingleNode('t:Enabled', $ns)
        if ($null -eq $enabled -or $enabled.InnerText.Trim() -ne 'true') {
            [void]$violations.Add('time_trigger_disabled')
        }
        if ($Expected.ContainsKey('start_boundary')) {
            $boundary = $time.SelectSingleNode('t:StartBoundary', $ns)
            if ($null -eq $boundary -or $boundary.InnerText.Trim() -ne [string]$Expected.start_boundary) {
                [void]$violations.Add('start_boundary_mismatch')
            }
        }
        $repetition = $time.SelectSingleNode('t:Repetition', $ns)
        if ($null -eq $repetition) {
            [void]$violations.Add('repetition_missing')
        } else {
            $interval = $repetition.SelectSingleNode('t:Interval', $ns)
            if ($null -eq $interval -or $interval.InnerText.Trim() -ne 'PT5M') {
                [void]$violations.Add('repetition_interval_wrong')
            }
            $duration = $repetition.SelectSingleNode('t:Duration', $ns)
            if ($null -ne $duration) { [void]$violations.Add('repetition_duration_present') }
        }
    }

    $startWhenAvailable = $doc.SelectSingleNode('/t:Task/t:Settings/t:StartWhenAvailable', $ns)
    if ($null -eq $startWhenAvailable -or $startWhenAvailable.InnerText.Trim() -ne 'true') {
        [void]$violations.Add('start_when_available_not_true')
    }
    $instances = $doc.SelectSingleNode('/t:Task/t:Settings/t:MultipleInstancesPolicy', $ns)
    if ($null -eq $instances -or $instances.InnerText.Trim() -ne 'IgnoreNew') {
        [void]$violations.Add('multiple_instances_not_ignore_new')
    }
    $limit = $doc.SelectSingleNode('/t:Task/t:Settings/t:ExecutionTimeLimit', $ns)
    if ($null -eq $limit -or $limit.InnerText.Trim() -ne 'PT0S') {
        [void]$violations.Add('execution_time_limit_not_unlimited')
    }

    $principal = $doc.SelectSingleNode('/t:Task/t:Principals/t:Principal', $ns)
    if ($null -eq $principal) {
        [void]$violations.Add('principal_missing')
    } else {
        $logon = $principal.SelectSingleNode('t:LogonType', $ns)
        if ($null -eq $logon -or $logon.InnerText.Trim() -ne 'S4U') {
            [void]$violations.Add('principal_logon_type_wrong')
        }
        $runLevel = $principal.SelectSingleNode('t:RunLevel', $ns)
        if ($null -eq $runLevel -or $runLevel.InnerText.Trim() -ne 'HighestAvailable') {
            [void]$violations.Add('principal_run_level_wrong')
        }
        $userId = $principal.SelectSingleNode('t:UserId', $ns)
        if ($Expected.ContainsKey('task_user') -and
            ($null -eq $userId -or $userId.InnerText.Trim() -ne [string]$Expected.task_user)) {
            [void]$violations.Add('principal_user_mismatch')
        }
    }

    $exec = $doc.SelectSingleNode('/t:Task/t:Actions/t:Exec', $ns)
    if ($null -eq $exec) {
        [void]$violations.Add('exec_action_missing')
    } else {
        $command = $exec.SelectSingleNode('t:Command', $ns)
        if ($Expected.ContainsKey('powershell_path') -and
            ($null -eq $command -or $command.InnerText.Trim() -ne [string]$Expected.powershell_path)) {
            [void]$violations.Add('exec_command_mismatch')
        }
        $arguments = $exec.SelectSingleNode('t:Arguments', $ns)
        $argText = if ($null -ne $arguments) { $arguments.InnerText } else { '' }
        if ($Expected.ContainsKey('supervisor_path') -and
            -not $argText.Contains([string]$Expected.supervisor_path)) {
            [void]$violations.Add('exec_arguments_missing_supervisor')
        }
        if ($Expected.ContainsKey('config_path') -and
            -not $argText.Contains([string]$Expected.config_path)) {
            [void]$violations.Add('exec_arguments_missing_config')
        }
        if ($Expected.ContainsKey('working_directory')) {
            $workDir = $exec.SelectSingleNode('t:WorkingDirectory', $ns)
            if ($null -eq $workDir -or $workDir.InnerText.Trim() -ne [string]$Expected.working_directory) {
                [void]$violations.Add('working_directory_mismatch')
            }
        }
    }

    return @($violations)
}

if ($FunctionsOnly) { return }

try {
    if (-not $TemplatePath) { $TemplatePath = Join-Path $PSScriptRoot 'com2_mesh_tunnel_task.template.xml' }
    if (-not (Test-Path -LiteralPath $TemplatePath)) { throw "template not found: $TemplatePath" }
    if (-not $TaskUser) { throw 'TaskUser is required' }
    if (-not $ConfigPath) { throw 'ConfigPath is required' }
    if (-not $PowerShellPath) {
        $PowerShellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    }
    if (-not $SupervisorPath) {
        $SupervisorPath = Join-Path $PSScriptRoot 'com2_mesh_tunnel_supervisor.ps1'
    }
    if (-not $WorkingDirectory) { $WorkingDirectory = Split-Path -Parent $ConfigPath }
    if (-not $WorkingDirectory) { throw 'WorkingDirectory is required' }
    if (-not $StartBoundary) {
        $StartBoundary = ((Get-Date).ToString('yyyy-MM-dd') + 'T00:00:00')
    }

    $templateText = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8
    $values = @{
        TASK_USER = $TaskUser
        START_BOUNDARY = $StartBoundary
        POWERSHELL_PATH = $PowerShellPath
        SUPERVISOR_PATH = $SupervisorPath
        CONFIG_PATH = $ConfigPath
        WORKING_DIRECTORY = $WorkingDirectory
    }
    $xmlText = New-TaskXmlText -TemplateText $templateText -Values $values
    $expected = @{
        task_user = $TaskUser
        start_boundary = $StartBoundary
        powershell_path = $PowerShellPath
        supervisor_path = $SupervisorPath
        config_path = $ConfigPath
        working_directory = $WorkingDirectory
    }
    $violations = Get-TaskXmlViolations -XmlText $xmlText -Expected $expected

    if ($OutputPath) {
        $encoding = New-Object System.Text.UnicodeEncoding($false, $true)
        [System.IO.File]::WriteAllText($OutputPath, $xmlText, $encoding)
    } else {
        Write-Output $xmlText
    }

    $summary = [ordered]@{
        ok = ($violations.Count -eq 0)
        output = $OutputPath
        start_boundary = $StartBoundary
        violations = @($violations)
    }
    Write-Output ($summary | ConvertTo-Json -Depth 4 -Compress)
    if ($violations.Count -gt 0) { exit 1 }
    exit 0
} catch {
    [Console]::Error.WriteLine(('task template render failed: {0}' -f $_.Exception.Message))
    exit 1
}
