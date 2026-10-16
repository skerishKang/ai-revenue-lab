# One-package PADIEM Connector installer. Per-user; no host Python.
[CmdletBinding()]
param([switch]$Uninstall, [switch]$NoTrayStart, [string]$BundleRoot = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$Root = Join-Path $env:LOCALAPPDATA 'Padiem\ClawConnect'
$App = Join-Path $Root 'app'
$Exe = Join-Path $App 'padiem-connector.exe'
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Padiem'
$ShortcutPath = Join-Path $StartMenu 'PADIEM Connector.lnk'
$ProtocolRoot = 'HKCU:\Software\Classes\padiem-connector'
$ProtocolCommand = Join-Path $ProtocolRoot 'shell\open\command'
$ProtocolExpected = '"' + $Exe + '" open-from-web "%1"'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$RunValue = 'PadiemClawConnect'

function Test-OwnedProtocol {
    if (-not (Test-Path $ProtocolRoot)) { return $false }
    $item = Get-Item $ProtocolRoot
    if ($item.GetValue('PadiemConnectorInstallRoot', $null) -ine $Root) { return $false }
    if (-not (Test-Path $ProtocolCommand)) { return $false }
    $registered = (Get-Item $ProtocolCommand).GetValue('')
    # Recognise only our legacy Python launcher at this exact owned install
    # root, so upgrading an existing Connector never hijacks a foreign URI.
    $legacyScript = Join-Path $Root 'launch_protocol.py'
    $legacyPattern = '^"[^"]*[\\/](?:py|python|pythonw|python3)\.exe" "' + [regex]::Escape($legacyScript) + '" "%1"$'
    $legacyOwned = (Test-Path -LiteralPath $legacyScript -PathType Leaf) -and
        ($registered -cmatch $legacyPattern)
    if ($registered -cne $ProtocolExpected -and -not $legacyOwned) { return $false }
    if (@($item.GetSubKeyNames() | Where-Object { $_ -cne 'shell' }).Count -ne 0) { return $false }
    if (@($item.GetValueNames() | Where-Object { $_ -cnotin @('', 'URL Protocol', 'PadiemConnectorInstallRoot') }).Count -ne 0) { return $false }
    $shell = Get-Item (Join-Path $ProtocolRoot 'shell')
    $open = Get-Item (Join-Path $ProtocolRoot 'shell\open')
    $command = Get-Item $ProtocolCommand
    return (
        @($shell.GetSubKeyNames() | Where-Object { $_ -cne 'open' }).Count -eq 0 -and
        @($open.GetSubKeyNames() | Where-Object { $_ -cne 'command' }).Count -eq 0 -and
        @($command.GetSubKeyNames()).Count -eq 0 -and
        @($shell.GetValueNames()).Count -eq 0 -and
        @($open.GetValueNames()).Count -eq 0 -and
        @($command.GetValueNames() | Where-Object { $_ -cne '' }).Count -eq 0
    )
}

if ($Uninstall) {
    if (Test-Path $Exe) {
        & $Exe stop | Out-Null
        & $Exe autostart off | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not safely disable owned Windows autostart.' }
    } elseif (Get-ItemProperty -Path $RunKey -Name $RunValue -ErrorAction SilentlyContinue) {
        throw 'Installed EXE missing: cannot prove the Run entry belongs to this product.'
    }
    if (Test-Path $ProtocolRoot) {
        if (-not (Test-OwnedProtocol)) { throw 'Foreign or modified browser protocol; refusing deletion.' }
        Remove-Item $ProtocolRoot -Recurse -Force
    }
    if (Test-Path $ShortcutPath) {
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($ShortcutPath)
        if ($shortcut.TargetPath -ieq $Exe) { Remove-Item $ShortcutPath -Force }
    }
    if (Test-Path $App) { Remove-Item $App -Recurse -Force }
    # Enrollment and DPAPI user state and explicit OFF preference are kept.
    Write-Output '{"ok":true,"action":"uninstall","user_state_preserved":true}'
    exit 0
}
$SourceExe = Join-Path $BundleRoot 'padiem-connector.exe'
$SourceAgent = Join-Path $BundleRoot '_internal\kagent\local_agent_resident_process.py'
if (-not (Test-Path $SourceExe -PathType Leaf) -or -not (Test-Path $SourceAgent -PathType Leaf)) {
    throw 'Incomplete bundled Connector or canonical Resident.'
}
if ((Test-Path $ProtocolRoot) -and -not (Test-OwnedProtocol)) {
    throw 'A different application or unknown registry data owns padiem-connector://.'
}
# The installed Python-era Connector may still own the same tray mutex even
# when this is the first EXE installation. The *bundled* command can signal
# its existing named quit event without any host Python.
if (Test-Path $Exe) {
    & $Exe stop | Out-Null
} else {
    & $SourceExe stop | Out-Null
}
New-Item -ItemType Directory -Path $Root -Force | Out-Null
$Staged = Join-Path $Root ('app.new.' + [guid]::NewGuid().ToString('N'))
$Old = Join-Path $Root 'app.previous'
Copy-Item $BundleRoot $Staged -Recurse
if (-not (Test-Path (Join-Path $Staged 'padiem-connector.exe') -PathType Leaf)) {
    Remove-Item $Staged -Recurse -Force
    throw 'Bundle staging failed.'
}
if (Test-Path $Old) { Remove-Item $Old -Recurse -Force }
if (Test-Path $App) { Move-Item -LiteralPath $App -Destination $Old }
try { Move-Item -LiteralPath $Staged -Destination $App }
catch {
    if (Test-Path $Old) { Move-Item -LiteralPath $Old -Destination $App }
    throw
}
# The existing Agent preflight reads the source pin; frozen execution uses
# the dedicated --resident-child command, not an external Python interpreter.
$Json = @{src_root=(Join-Path $App '_internal')} | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText((Join-Path $Root 'resident.json'),$Json,(New-Object System.Text.UTF8Encoding($false)))
New-Item -ItemType Directory -Path $StartMenu -Force | Out-Null
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $Exe
$shortcut.Arguments = 'start'
$shortcut.WorkingDirectory = $App
$shortcut.Description = 'PADIEM Connector'
$shortcut.Save()
New-Item -Path $ProtocolRoot -Force | Out-Null
Set-Item -Path $ProtocolRoot -Value 'URL:PADIEM Connector'
New-ItemProperty -Path $ProtocolRoot -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $ProtocolRoot -Name 'PadiemConnectorInstallRoot' -Value $Root -PropertyType String -Force | Out-Null
New-Item -Path $ProtocolCommand -Force | Out-Null
Set-Item -Path $ProtocolCommand -Value $ProtocolExpected
$Doctor = (& $Exe doctor | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0 -or $Doctor.agent_ready -ne $true) {
    throw 'The embedded canonical Resident preflight failed.'
}
# Maintenance reinstallation can preserve the user's explicit OFF and avoid
# a new PC first-offer before the originating signed-in Claw click. Ordinary
# customer installation continues to launch the existing tray as before.
if (-not $NoTrayStart) {
    $TrayProcess = Start-Process -FilePath $Exe -ArgumentList 'start' -WorkingDirectory $App -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 1200
    $TrayProcess.Refresh()
    if ($TrayProcess.HasExited) {
        throw 'Installed Connector tray did not stay running.'
    }
}
# The tray writes HKCU Run only after durable enrollment. Explicit OFF stays OFF.
Write-Output (@{ok=$true; action='install'; exe=$Exe; agent_ready=$true;
               tray_launch_requested=([bool](-not $NoTrayStart)); autostart='credential_gated';
               browser_protocol_registered=$true; connected=$false} |
              ConvertTo-Json -Compress)
