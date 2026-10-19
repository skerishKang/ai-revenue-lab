"""Real HKCU SCRATCH-key regression for the PADIEM browser protocol.

Never reads or modifies the installed padiem-connector scheme.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import subprocess

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "install.ps1"


def test_browser_protocol_ownership_against_isolated_hkcu_key():
    if os.name != "nt" or not shutil.which("powershell"):
        pytest.skip("Windows PowerShell HKCU scratch test")
    # Parse the real installer with the Windows PowerShell AST, then exercise
    # its actual ownership functions against a private, randomly named key.
    source = str(INSTALLER).replace("'", "''")
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '__SOURCE__', [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw 'Installer PowerShell syntax invalid' }
$wanted = @('Get-ProtocolCommand', 'Test-ProtocolKeyShape', 'Test-OwnedBrowserProtocol')
$functions = $ast.FindAll({
    param($node)
    ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) -and
    ($node.Name -in $wanted)
}, $true)
if ($functions.Count -ne 3) { throw 'Missing registry ownership functions' }
foreach ($fn in $functions) { . ([scriptblock]::Create($fn.Extent.Text)) }
$BrowserProtocolKey = 'HKCU:\Software\PadiemConnectorScratch_' + [guid]::NewGuid().ToString('N')
$BrowserProtocolCommandKey = Join-Path $BrowserProtocolKey 'shell\open\command'
$ProtocolOwnershipValue = 'PadiemConnectorInstallRoot'
$ExpectedProtocolCommand = '"C:\safe\pythonw.exe" "C:\safe\launch_protocol.py" "%1"'
$InstallRoot = 'C:\safe\ClawConnect'
function Assert-Ownership {
    param([bool]$Expected, [string]$Case)
    $Actual = Test-OwnedBrowserProtocol
    if ($Actual -ne $Expected) { throw "Ownership failure: $Case" }
}
try {
    New-Item -Path $BrowserProtocolCommandKey -Force | Out-Null
    Set-Item -Path $BrowserProtocolKey -Value 'URL:PADIEM Connector'
    New-ItemProperty -Path $BrowserProtocolKey -Name 'URL Protocol' -Value '' -PropertyType String | Out-Null
    Set-Item -Path $BrowserProtocolCommandKey -Value $ExpectedProtocolCommand
    Assert-Ownership $true 'legacy exact owned footprint'
    New-ItemProperty -Path $BrowserProtocolKey -Name $ProtocolOwnershipValue -Value $InstallRoot -PropertyType String | Out-Null
    Assert-Ownership $true 'marked exact owned footprint'
    New-ItemProperty -Path $BrowserProtocolCommandKey -Name 'ForeignData' -Value 'keep' -PropertyType String | Out-Null
    Assert-Ownership $false 'foreign command property'
    Remove-ItemProperty -Path $BrowserProtocolCommandKey -Name 'ForeignData'
    New-Item -Path (Join-Path $BrowserProtocolKey 'ForeignTool') | Out-Null
    Assert-Ownership $false 'foreign sibling key'
    Remove-Item -Path (Join-Path $BrowserProtocolKey 'ForeignTool') -Recurse
    Set-ItemProperty -Path $BrowserProtocolKey -Name $ProtocolOwnershipValue -Value 'C:\other'
    Assert-Ownership $false 'foreign ownership marker'
    Set-ItemProperty -Path $BrowserProtocolKey -Name $ProtocolOwnershipValue -Value $InstallRoot
    Set-Item -Path $BrowserProtocolCommandKey -Value '"C:\other\app.exe" "%1"'
    Assert-Ownership $false 'different executable'
    Set-Item -Path $BrowserProtocolCommandKey -Value $ExpectedProtocolCommand
    Assert-Ownership $true 'ownership restored'
    Write-Output 'SCRATCH_REGISTRY_OWNERSHIP=PASS'
} finally {
    if (Test-Path -LiteralPath $BrowserProtocolKey) {
        Remove-Item -LiteralPath $BrowserProtocolKey -Recurse -Force
    }
}
""".replace("__SOURCE__", source)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=40, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "SCRATCH_REGISTRY_OWNERSHIP=PASS" in result.stdout
