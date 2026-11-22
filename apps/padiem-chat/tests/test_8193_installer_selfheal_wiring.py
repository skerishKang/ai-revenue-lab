"""#8193: both installers register/remove the SYSTEM self-heal task from one payload."""
from __future__ import annotations

import base64
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SELF_HEAL = runpy.run_path(
    str(ROOT / "apps/korean-ai-code-agent/src/kagent/pc_self_heal_task.py"))


def test_installer_wrapper_embeds_the_reviewed_payload():
    wrapper = (ROOT / "scripts/pc_pairing/install-padiem-pc.ps1").read_text(encoding="utf-8-sig")
    block = wrapper.split("function Register-PadiemSelfHealWatcher {", 1)[1].split("\n}", 1)[0]
    payload = block.split("FromBase64String('", 1)[1].split("')", 1)[0]
    assert gzip_decompress(payload) == SELF_HEAL["watcher_script"]()
    assert "param([string]$PythonExecutable)" in block
    assert "Register-PadiemSelfHealWatcher -PythonExecutable" in wrapper


def gzip_decompress(payload: str) -> str:
    import gzip
    return gzip.decompress(base64.b64decode(payload)).decode("utf-8")


def test_installer_registration_follows_the_agent_and_precedes_the_helper():
    wrapper = (ROOT / "scripts/pc_pairing/install-padiem-pc.ps1").read_text(encoding="utf-8-sig")
    agent = wrapper.index("Install-PadiemAgentService -SourceExe")
    register = wrapper.index("Register-PadiemSelfHealWatcher -PythonExecutable")
    helper = wrapper.index("Invoke-PadiemUserHelperInstall -Url")
    assert agent < register < helper
    # #8225 removed the one-host exclusion; no machine-name gate is reintroduced.
    assert "Test-ExcludedComputer" not in wrapper
    block = wrapper.split("function Register-PadiemSelfHealWatcher {", 1)[1].split("\n}", 1)[0]
    assert "COMPUTERNAME" not in block.upper()


def test_connect_exe_wires_registration_and_removal():
    source = (ROOT / "scripts/pc_pairing/connect-exe/PadiemPcConnect.cs").read_bytes().decode()
    assert 'SelfHealWatcherResource("PadiemSelfHealWatcher")' in source
    assert 'SelfHealWatcherResource("PadiemSelfHealWatcherUnregister")' in source
    install = source.split("string selfHealError = RegisterSelfHealWatcher();", 1)[1]
    assert "bool helperConfigured" in install
    uninstall = source.split("static int Uninstall()", 1)[1].split("static void DeleteUninstallRegistration()", 1)[0]
    assert "UnregisterSelfHealWatcher();" in uninstall


def test_build_embeds_both_resources_and_seeds_their_source():
    build = (ROOT / "scripts/pc_pairing/build-connect-exe.ps1").read_text(encoding="utf-8-sig")
    assert "/resource:self-heal-watcher.ps1,PadiemSelfHealWatcher" in build
    assert "/resource:self-heal-watcher-unregister.ps1,PadiemSelfHealWatcherUnregister" in build
    assert "(Get-FileHashHex $SelfHealSource)" in build
    test_source = (ROOT / "apps/padiem-chat/tests/test_5573_pc_one_click_install.py").read_text()
    assert "src/kagent/pc_self_heal_task.py" in test_source


@pytest.mark.skipif(sys.platform != "win32", reason="Windows assembly reflection and child PowerShell")
def test_shipped_exe_embeds_the_same_payloads(tmp_path):
    from app.pc_pairing_connect_exe_asset import connect_exe_bytes

    target = tmp_path / "connect.exe"
    target.write_bytes(connect_exe_bytes())
    driver = tmp_path / "resources.ps1"
    driver.write_text(r"""
param([string]$Target)
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($Target)
$type = $assembly.GetType('Padiem.Connect.PadiemPcConnect', $true)
$flags = [Reflection.BindingFlags]'NonPublic,Static'
$run = $type.GetMethod('RunSelfHealWatcherCommand', $flags)
foreach ($name in @('PadiemSelfHealWatcher','PadiemSelfHealWatcherUnregister')) {
    $stream = $assembly.GetManifestResourceStream($name)
    if ($null -eq $stream) { throw ('missing_resource:' + $name) }
    $reader = [IO.StreamReader]::new($stream)
    try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
    Write-Output ('RESOURCE=' + $name + '=' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text)))
}
# Synthetic child commands only: no scheduled task API is reached.
$cases = @{
    'exit 0' = ''
    "throw 'boom'" = 'task_registration_failed'
    '' = 'missing_fixed_source'
}
foreach ($case in $cases.GetEnumerator()) {
    $answer = $run.Invoke($null, [object[]]@($case.Key, 'C:\fake\python.exe'))
    if ($answer -cne $case.Value) { throw 'incorrect child exit mapping' }
}
""", encoding="utf-8")
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(driver), str(target)],
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    found = {}
    for line in done.stdout.splitlines():
        if line.startswith("RESOURCE="):
            _, name, value = line.split("=", 2)
            found[name] = base64.b64decode(value).decode("utf-8")
    import gzip
    import re

    for name, unregister in (("PadiemSelfHealWatcher", False),
                             ("PadiemSelfHealWatcherUnregister", True)):
        text = found[name]
        payload = re.search(r"FromBase64String\('([^']+)'\)", text)[1]
        assert gzip.decompress(base64.b64decode(payload)).decode() == SELF_HEAL["watcher_script"]()
        assert text.endswith(
            "-Unregister" if unregister else "-PythonExecutable $PythonExecutable")
