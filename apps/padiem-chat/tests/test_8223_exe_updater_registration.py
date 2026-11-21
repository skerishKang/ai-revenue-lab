"""#8223: the shipped EXE registers the same updater and reports failures."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.pc_helper_update import render_helper_updater_command
from app.pc_pairing_connect_exe_asset import connect_exe_bytes

ROOT = Path(__file__).resolve().parents[3]


def test_exe_installer_uses_registration_flow_after_provisioning():
    # Pin the entry point; actual execution and status serialization are below.
    source = (ROOT / "scripts/pc_pairing/connect-exe/PadiemPcConnect.cs").read_bytes().decode()
    install = source.split("static bool InstallUserHelper(string tag)", 1)[1]
    install = install.split("static string ProvisionUserHelper(", 1)[0]
    assert install.index("ProvisionUserHelper(") < install.index("FinishUserHelperInstall(")
    assert "RegisterHelperUpdater," in install
    assert "WriteUserHelperStatus(" in install


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer and child PowerShell")
def test_shipped_exe_registration_and_status_contract(tmp_path):
    target = tmp_path / "connect.exe"
    target.write_bytes(connect_exe_bytes())
    driver = tmp_path / "registration.ps1"
    driver.write_text(r"""
param([string]$Target)
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($Target)
$type = $assembly.GetType('Padiem.Connect.PadiemPcConnect', $true)
$flags = [Reflection.BindingFlags]'NonPublic,Static'
$finish = $type.GetMethod('FinishUserHelperInstall', $flags)
$payload = $type.GetMethod('UserHelperStatusPayload', $flags)
$run = $type.GetMethod('RunHelperUpdaterRegistration', $flags)
$stream = $assembly.GetManifestResourceStream('PadiemHelperUpdater')
$reader = [IO.StreamReader]::new($stream)
try { $resource = $reader.ReadToEnd() } finally { $reader.Dispose() }
Write-Output ('RESOURCE=' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($resource)))

# Run only synthetic, local child commands, never the real scheduled updater.
$cases = @{
    '$null = 1' = ''
    "throw 'updater_running'" = 'updater_running'
    "throw 'missing_fixed_source'" = 'missing_fixed_source'
    "throw 'invalid_install_record'" = 'invalid_install_record'
    "throw 'installed_digest_mismatch'" = 'installed_digest_mismatch'
    "throw 'private path and data'" = 'task_registration_failed'
}
foreach ($case in $cases.GetEnumerator()) {
    $answer = $run.Invoke($null, [object[]]@($case.Key))
    if ($answer -cne $case.Value) { throw 'incorrect child exit mapping' }
}
if ($run.Invoke($null, [object[]]@('')) -ne 'missing_fixed_source') { throw 'empty resource accepted' }

foreach ($fixture in @(
    @{reason='';release='0.3.0-rc2';error='';expected=$true;events='status,register'},
    @{reason='';release='0.3.0-rc2';error='updater_running';expected=$true;events='status,register,status,update_warning'},
    @{reason='';release='';error='';expected=$true;events='status,status,update_warning'},
    @{reason='provision_failed';release='0.3.0-rc2';error='';expected=$false;events='status,helper_warning'}
)) {
    $events = [Collections.Generic.List[string]]::new()
    $records = [Collections.Generic.List[string]]::new()
    $register = [Func[string]] { $events.Add('register'); return $fixture.error }
    $record = [Action[string]] {
        param($errorCode)
        $events.Add('status')
        $status = if ($fixture.reason) {'not_installed'} else {'installed'}
        $json = $payload.Invoke($null, [object[]]@(
            $status, $fixture.reason, 'fixture', ('a' * 64), 'PC\fixture',
            $fixture.release, $errorCode))
        $records.Add([Text.Encoding]::UTF8.GetString($json).Trim())
    }
    $helperWarning = [Action[string]] { param($code) $events.Add('helper_warning') }
    $updateWarning = [Action[string]] {
        param($code)
        $events.Add('update_warning')
        if ($code -notin @('updater_running','version_unavailable')) { throw 'wrong warning code' }
    }
    $installed = $finish.Invoke($null, [object[]]@(
        $fixture.reason, $fixture.release, $register, $record, $helperWarning, $updateWarning))
    if ($installed -ne $fixture.expected -or ($events -join ',') -ne $fixture.events) { throw 'wrong install flow' }
    foreach ($recorded in $records) { Write-Output ('STATUS=' + $recorded) }
}
""", encoding="utf-8")
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(driver), str(target)],
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    resource = next(line.partition("=")[2] for line in lines if line.startswith("RESOURCE="))
    assert base64.b64decode(resource) == render_helper_updater_command().encode("utf-8")
    records = [json.loads(line.partition("=")[2]) for line in lines if line.startswith("STATUS=")]
    assert len(records) == 6
    assert records[0]["status"] == "installed"
    assert records[0]["version"] == "0.3.0-rc2"
    assert "update_registration_error" not in records[0]
    assert records[2]["status"] == "installed"
    assert records[2]["update_result"] == "registration_failed"
    assert records[2]["update_registration_error"] == "updater_running"
    assert records[2]["reason"] == "update_registration_failed:updater_running"
    assert records[4]["status"] == "installed"
    assert records[4]["reason"] == "update_registration_failed:version_unavailable"
    assert records[5]["status"] == "not_installed"
    assert records[5]["reason"] == "provision_failed"
