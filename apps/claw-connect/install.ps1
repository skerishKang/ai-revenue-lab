# PADIEM Connector — no-Node, no-terminal Windows installer (#4139 S1 item 9, S2).
#
#   .\install.ps1             install (per user, no administrator right)
#   .\install.ps1 -Autostart  request guarded logon registration (needs durable credential)
#   .\install.ps1 -AgentSrc <path>
#                             pin the existing PADIEM Agent (legacy kagent) source
#   .\install.ps1 -ResidentSrc <path> legacy spelling of -AgentSrc
#                             pin the kagent Resident source root that this PC
#                             supervises (the one existing local runner)
#   .\install.ps1 -OperatorWssAcceptance -AgentSrc <path>
#                             prepare isolated pinned websockets 17.2 (does NOT enable WSS)
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
    [string]$AgentSrc,
    [switch]$OperatorWssAcceptance
)

$ErrorActionPreference = 'Stop'
$ProductName = 'PADIEM Connector'
$RunValueName = 'PadiemClawConnect'
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Padiem'
$ShortcutPath = Join-Path $StartMenu 'PADIEM Connector.lnk'
$LegacyShortcutPath = Join-Path $StartMenu 'Padiem Claw Connect.lnk'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Padiem\ClawConnect'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$BrowserProtocolKey = 'HKCU:\Software\Classes\padiem-connector'
$BrowserProtocolCommandKey = Join-Path $BrowserProtocolKey 'shell\open\command'
$ProtocolOwnershipValue = 'PadiemConnectorInstallRoot'
$BrowserLaunchScript = Join-Path $InstallRoot 'launch_protocol.py'
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

# Exact per-user protocol; browser URI is never an authentication claim.
$ProtocolPython = $PythonExePath
if ([System.IO.Path]::GetFileName($PythonExePath) -ieq 'python.exe') {
    $PossiblePythonw = Join-Path (Split-Path $PythonExePath) 'pythonw.exe'
    if (Test-Path -LiteralPath $PossiblePythonw -PathType Leaf) {
        $ProtocolPython = $PossiblePythonw
    }
}
$ExpectedProtocolCommand = '"' + $ProtocolPython + '" "' + $BrowserLaunchScript + '" "%1"'
function Get-ProtocolCommand {
    if (-not (Test-Path -LiteralPath $BrowserProtocolCommandKey)) { return $null }
    return (Get-Item -LiteralPath $BrowserProtocolCommandKey).GetValue('')
}

function Test-ProtocolKeyShape {
    param([string]$Key, [string[]]$AllowedValues, [string[]]$AllowedChildren)
    if (-not (Test-Path -LiteralPath $Key)) { return $false }
    $entry = Get-Item -LiteralPath $Key
    foreach ($name in $entry.GetValueNames()) {
        if ($name -cnotin $AllowedValues) { return $false }
    }
    foreach ($name in $entry.GetSubKeyNames()) {
        if ($name -cnotin $AllowedChildren) { return $false }
    }
    return $true
}

function Test-OwnedBrowserProtocol {
    # A matching command alone is insufficient: a different program may own
    # additional values/subkeys that uninstall must never recursively delete.
    if ((Get-ProtocolCommand) -cne $ExpectedProtocolCommand) { return $false }
    if (-not (Test-Path -LiteralPath $BrowserProtocolKey)) { return $false }
    $root = Get-Item -LiteralPath $BrowserProtocolKey
    if ($root.GetValue('') -cne 'URL:PADIEM Connector' -or
        $root.GetValue('URL Protocol', $null) -cne '') { return $false }
    $registeredRoot = $root.GetValue($ProtocolOwnershipValue, $null)
    if ($null -ne $registeredRoot -and $registeredRoot -ine $InstallRoot) { return $false }
    if (-not (Test-ProtocolKeyShape $BrowserProtocolKey @('', 'URL Protocol', $ProtocolOwnershipValue) @('shell'))) { return $false }
    $shellKey = Join-Path $BrowserProtocolKey 'shell'
    $openKey = Join-Path $shellKey 'open'
    if (-not (Test-ProtocolKeyShape $shellKey @() @('open'))) { return $false }
    if (-not (Test-ProtocolKeyShape $openKey @() @('command'))) { return $false }
    if (-not (Test-ProtocolKeyShape $BrowserProtocolCommandKey @('') @())) { return $false }
    return $true
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
    # Preserve foreign additions rather than deleting someone else's values
    # under our URL scheme, even if the original default command still matches.
    $BrowserProtocolPreserved = $false
    if (Test-Path -LiteralPath $BrowserProtocolKey) {
        if (Test-OwnedBrowserProtocol) {
            # No recursive subtree deletion: fail rather than consume an
            # unexpected sibling that appeared after the ownership check.
            Remove-Item -LiteralPath $BrowserProtocolCommandKey -Force
            Remove-Item -LiteralPath (Join-Path $BrowserProtocolKey 'shell\open') -Force
            Remove-Item -LiteralPath (Join-Path $BrowserProtocolKey 'shell') -Force
            Remove-Item -LiteralPath $BrowserProtocolKey -Force
        } else {
            $BrowserProtocolPreserved = $true
        }
    }
    if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath -Force }
    Remove-OwnedLegacyShortcut
    if (Test-Path $InstallRoot) { Remove-Item $InstallRoot -Recurse -Force }
    Write-Output (@{ ok = $true; action = 'uninstall'; browser_protocol_preserved = $BrowserProtocolPreserved } | ConvertTo-Json -Compress)
    exit 0
}

if (Test-Path -LiteralPath $BrowserProtocolKey) {
    if (-not (Test-OwnedBrowserProtocol)) {
        throw 'A different application or unknown registry entries already own the browser launch scheme.'
    }
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
if ($OperatorWssAcceptance -and -not $ValidatedAgentSrc) {
    throw 'Operator WSS acceptance requires explicit -AgentSrc for the existing canonical Agent.'
}
if ($OperatorWssAcceptance -and -not (Test-Path -LiteralPath (Join-Path $SourceRoot 'requirements-wss-review.txt') -PathType Leaf)) {
    throw 'The reviewed WSS dependency pin is unavailable.'
}

# Install: copy the bundled Python package, then create the per-user shortcut.
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
Copy-Item -Path (Join-Path $SourceRoot 'claw_connect') -Destination $InstallRoot `
    -Recurse -Force
Copy-Item -Path (Join-Path $SourceRoot 'padiem_connector') -Destination $InstallRoot -Recurse -Force
Copy-Item -Path (Join-Path $SourceRoot 'launch_protocol.py') -Destination $InstallRoot -Force

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

# Optional, isolated dependency setup for the exact operator acceptance mode.
# Never install/upgrade the shared Python interpreter or enable WSS globally.
# A normal user installation follows the original path and stays default-OFF.
$ReviewWssPrepared = $false
if ($OperatorWssAcceptance) {
    $ReviewVenv = Join-Path $InstallRoot '.venv-wss-review'
    $ReviewPython = Join-Path $ReviewVenv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $ReviewPython -PathType Leaf)) {
        & $PythonExePath -m venv $ReviewVenv
        if ($LASTEXITCODE -ne 0) { throw 'Isolated WSS Python environment failed to create.' }
    }
    & $ReviewPython -m pip install --disable-pip-version-check --no-input `
        -r (Join-Path $SourceRoot 'requirements-wss-review.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Isolated WSS client dependency install failed.' }
    & $ReviewPython -c 'from websockets.asyncio.client import connect; import websockets; assert websockets.__version__ == "17.2"'
    if ($LASTEXITCODE -ne 0) { throw 'Pinned WSS version does not match the reviewed interface.' }
    $PythonExePath = $ReviewPython
    $ReviewWssPrepared = $true
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

# ShellExecute only, not an inbound listener. Unknown URL payloads are denied
# by the package before any user-state or network initialization.
New-Item -Path $BrowserProtocolKey -Force | Out-Null
Set-Item -Path $BrowserProtocolKey -Value 'URL:PADIEM Connector' | Out-Null
New-ItemProperty -Path $BrowserProtocolKey -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $BrowserProtocolKey -Name $ProtocolOwnershipValue -Value $InstallRoot -PropertyType String -Force | Out-Null
New-Item -Path $BrowserProtocolCommandKey -Force | Out-Null
Set-Item -Path $BrowserProtocolCommandKey -Value $ExpectedProtocolCommand | Out-Null

$result = [ordered]@{
    ok = $true
    action = 'install'
    shortcut = $ShortcutPath
    install_root = $InstallRoot
    autostart = $false
    agent_ready = $false
    agent_status = 'not_checked'
    review_wss_dependencies_prepared = $ReviewWssPrepared
    review_wss_server_activated = $false
    tray_launch_requested = $false
    browser_launch_registered = $true
    connected = $false
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

# Start the tray immediately after installation. An unregistered tray stays
# visibly UNREGISTERED and must not start the Agent without a valid device.
# Subsequent logon autostart remains canonical-credential gated in runtime.
$LaunchPython = $PythonExePath
if ([System.IO.Path]::GetFileName($PythonExePath) -ieq 'python.exe') {
    $CandidatePythonw = Join-Path (Split-Path $PythonExePath) 'pythonw.exe'
    if (Test-Path -LiteralPath $CandidatePythonw -PathType Leaf) {
        $LaunchPython = $CandidatePythonw
    }
}
try {
    Start-Process -FilePath $LaunchPython -ArgumentList '-m padiem_connector start' -WorkingDirectory $InstallRoot -WindowStyle Hidden | Out-Null
    $result.tray_launch_requested = $true
} catch {
    throw 'Connector installed, but tray startup failed.'
}

Write-Output ($result | ConvertTo-Json -Compress)

