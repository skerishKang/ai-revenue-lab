# PADIEM Connector — no-Node, no-terminal Windows installer (#4139 S1 item 9, S2).
#
#   .\install.ps1             install (per user, no administrator right)
#   .\install.ps1 -Autostart  request guarded logon registration (needs durable credential)
#   .\install.ps1 -AgentSrc <path>
#                             pin the existing PADIEM Agent (legacy kagent) source
#   .\install.ps1 -ResidentSrc <path> legacy spelling of -AgentSrc
#                             pin the kagent Resident source root that this PC
#                             supervises (the one existing local runner)
#   .\install.ps1 -Uninstall  remove the shortcut, autostart value and files
#
# Scope: a Start Menu shortcut plus the guarded autostart CLI. Nothing is
# written to the machine-wide hive, no service is created, no port is opened,
# no administrator right is requested, and no existing Resident/Broker file
# is touched.

[CmdletBinding()]
param(
    [switch]$Autostart,
    [switch]$Uninstall,
    [string]$ResidentSrc,
    [string]$AgentSrc
)

$ErrorActionPreference = 'Stop'
$ProductName = 'PADIEM Connector'
$RunValueName = 'PadiemClawConnect'
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Padiem'
$ShortcutPath = Join-Path $StartMenu 'PADIEM Connector.lnk'
$LegacyShortcutPath = Join-Path $StartMenu 'Padiem Claw Connect.lnk'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Padiem\ClawConnect'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$SourceRoot = $PSScriptRoot

function Remove-OwnedLegacyShortcut {
    # Migrate only a provably owned shortcut; preserve any unrelated link.
    if (-not (Test-Path $LegacyShortcutPath)) { return }
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($LegacyShortcutPath)
    if (($link.WorkingDirectory -eq $InstallRoot) -and
        ($link.Arguments -eq '-m claw_connect start')) {
        Remove-Item -Path $LegacyShortcutPath -Force
    }
}

function Find-Python {
    if ($env:PADIEM_PYTHON) { return @($env:PADIEM_PYTHON) }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { return @('py', '-3') }
    foreach ($name in @('python3', 'python')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return @($cmd.Source) }
    }
    return $null
}

$PythonExe = Find-Python
if (-not $PythonExe) {
    throw 'Python 3.11+ 를 찾지 못했습니다. Python 설치 후 다시 시도하세요.'
}
$PythonExePath = if ($PythonExe.Count -gt 1) {
    (Get-Command $PythonExe[0]).Source
} else {
    $PythonExe[0]
}

if ($Uninstall) {
    # Uninstall must also respect the registry ownership check. The old
    # Remove-ItemProperty blindly deleted a foreign command sharing this name.
    if (Test-Path (Join-Path $InstallRoot 'claw_connect')) {
        Push-Location $InstallRoot
        try {
            # Old installations never shipped the new Python package.
            $UninstallModule = if (Test-Path (Join-Path $InstallRoot 'padiem_connector')) {
                'padiem_connector'
            } else {
                'claw_connect'
            }
            $UnregisterReceipt = & $PythonExePath -m $UninstallModule autostart off
            if ($LASTEXITCODE -ne 0) {
                throw 'Autostart could not be safely disabled; installation preserved.'
            }
        } finally {
            Pop-Location
        }
    } elseif (Get-ItemProperty -Path $RunKey -Name $RunValueName -ErrorAction SilentlyContinue) {
        throw 'Cannot prove the Run entry is owned without the installed Connector.'
    }
    if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath -Force }
    Remove-OwnedLegacyShortcut
    if (Test-Path $InstallRoot) { Remove-Item $InstallRoot -Recurse -Force }
    Write-Output '{"ok":true,"action":"uninstall"}'
    exit 0
}

# Validate any explicit Agent source BEFORE modifying the current user's
# install, shortcut or autostart choice. Never guess a development checkout.
if ($ResidentSrc -and $AgentSrc) {
    throw 'Use -AgentSrc or legacy -ResidentSrc, not both.'
}
$SelectedAgentSrc = if ($AgentSrc) { $AgentSrc } else { $ResidentSrc }
$ValidatedAgentSrc = $null
if ($SelectedAgentSrc) {
    $ValidatedAgentSrc = (Resolve-Path -LiteralPath $SelectedAgentSrc -ErrorAction Stop).ProviderPath
    foreach ($required in @(
        'kagent\__init__.py',
        'kagent\local_agent_resident_process.py',
        'kagent\local_agent_secure_transport.py',
        'kagent\local_agent_pairing.py'
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $ValidatedAgentSrc $required) -PathType Leaf)) {
            throw "PADIEM Agent is not present at the supplied source root ($required)."
        }
    }
}

# Install: copy the bundled Python package, then create the per-user shortcut.
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
Copy-Item -Path (Join-Path $SourceRoot 'claw_connect') -Destination $InstallRoot `
    -Recurse -Force
Copy-Item -Path (Join-Path $SourceRoot 'padiem_connector') -Destination $InstallRoot `
    -Recurse -Force

# S2: pin the one existing kagent Resident this PC supervises. The Connector
# launches `kagent.local_agent_resident_process` — never a placeholder command.
# The path is supplied by the deployment and recorded once, per user. The
# Connector resolves it from <state_dir>/resident.json, and its default state
# directory is this install root.
if ($ValidatedAgentSrc) {
    $residentConfig = Join-Path $InstallRoot 'resident.json'
    $AgentConfigJson = @{ src_root = $ValidatedAgentSrc } | ConvertTo-Json -Compress
    # Windows PowerShell 5.1 Set-Content -Encoding utf8 writes a BOM.
    [System.IO.File]::WriteAllText(
        $residentConfig, $AgentConfigJson,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

New-Item -ItemType Directory -Path $StartMenu -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $PythonExePath
$shortcut.Arguments = '-m padiem_connector start'
$shortcut.WorkingDirectory = $InstallRoot
$shortcut.Description = $ProductName
$shortcut.Save()
Remove-OwnedLegacyShortcut

$result = [ordered]@{
    ok = $true
    action = 'install'
    shortcut = $ShortcutPath
    install_root = $InstallRoot
    autostart = $false
    agent_ready = $false
    agent_status = 'not_checked'
}

# A diagnostic is read-only and truthful. Do not declare the agent usable
# merely because a shortcut and Python package were copied successfully.
Push-Location $InstallRoot
try {
    $DoctorText = & $PythonExePath -m padiem_connector doctor
    $DoctorResult = $DoctorText | ConvertFrom-Json
    $result.agent_ready = ($DoctorResult.agent_ready -eq $true)
    $result.agent_status = $DoctorResult.agent_status
} finally {
    Pop-Location
}

if ($Autostart) {
    # No direct registry writes. Shared CLI checks a durable, valid canonical
    # credential AND the owner's explicit opt-out before touching HKCU Run.
    Push-Location $InstallRoot
    try {
        $AutostartReceipt = & $PythonExePath -m padiem_connector autostart on
        if ($LASTEXITCODE -ne 0) {
            throw 'Autostart refused: a durable canonical credential is required.'
        }
        $AutostartResult = $AutostartReceipt | ConvertFrom-Json
        if ($AutostartResult.ok -ne $true -or $AutostartResult.enabled -ne $true) {
            throw 'Autostart refused: no confirmed per-user registration.'
        }
        $result.autostart = $true
    } finally {
        Pop-Location
    }
}

Write-Output ($result | ConvertTo-Json -Compress)

