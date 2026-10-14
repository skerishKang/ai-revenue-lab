# Claw Connect — no-Node, no-terminal Windows installer (#4139 S1 item 9).
#
#   .\install.ps1             install (per user, no administrator right)
#   .\install.ps1 -Autostart  also register "run at Windows logon"
#   .\install.ps1 -Uninstall  remove the shortcut, autostart value and files
#
# Scope: a Start Menu shortcut plus an opt-in HKCU Run value. Nothing is
# written to the machine-wide hive, no service is created, no port is opened,
# no administrator right is requested, and no existing Resident/Broker file
# is touched.

[CmdletBinding()]
param(
    [switch]$Autostart,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$ProductName = 'Padiem Claw Connect'
$RunValueName = 'PadiemClawConnect'
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Padiem'
$ShortcutPath = Join-Path $StartMenu 'Padiem Claw Connect.lnk'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Padiem\ClawConnect'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$SourceRoot = $PSScriptRoot

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

# The command a logon autostart must run. A -c bootstrap pins the install root
# so the Run key (which has no working directory) still resolves the module.
$Bootstrap = "import sys,runpy;sys.path.insert(0,r'$InstallRoot');" +
             "sys.argv=['claw-connect','start'];runpy.run_module('claw_connect',run_name='__main__')"
$AutostartCommand = "`"$PythonExePath`" -c `"$Bootstrap`""

if ($Uninstall) {
    if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath -Force }
    if (Get-ItemProperty -Path $RunKey -Name $RunValueName -ErrorAction SilentlyContinue) {
        Remove-ItemProperty -Path $RunKey -Name $RunValueName -Force
    }
    if (Test-Path $InstallRoot) { Remove-Item $InstallRoot -Recurse -Force }
    Write-Output '{"ok":true,"action":"uninstall"}'
    exit 0
}

# Install: copy the bundled Python package, then create the per-user shortcut.
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
Copy-Item -Path (Join-Path $SourceRoot 'claw_connect') -Destination $InstallRoot `
    -Recurse -Force

New-Item -ItemType Directory -Path $StartMenu -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $PythonExePath
$shortcut.Arguments = '-m claw_connect start'
$shortcut.WorkingDirectory = $InstallRoot
$shortcut.Description = $ProductName
$shortcut.Save()

$result = [ordered]@{
    ok = $true
    action = 'install'
    shortcut = $ShortcutPath
    install_root = $InstallRoot
    autostart = $false
}

if ($Autostart) {
    New-Item -Path $RunKey -Force | Out-Null
    Set-ItemProperty -Path $RunKey -Name $RunValueName -Value $AutostartCommand -Type String
    $result.autostart = $true
}

Write-Output ($result | ConvertTo-Json -Compress)

