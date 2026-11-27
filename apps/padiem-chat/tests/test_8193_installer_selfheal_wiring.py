"""#8895: installers use Windows SCM recovery, not a scheduled watcher.

The removal command remains embedded solely to clean up legacy installs.
No test touches the local Windows service or task scheduler.
"""
from __future__ import annotations

import base64
import gzip
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from _support.reinstall_selfheal_sidebar_source import (
    build_script, install_wrapper, one_click_test_source,
)

ROOT = Path(__file__).resolve().parents[3]
SELF_HEAL = runpy.run_path(
    str(ROOT / "apps/korean-ai-code-agent/src/kagent/pc_self_heal_task.py"))


def test_powershell_installer_uses_scm_recovery_without_registering_watcher():
    source = install_wrapper()
    assert "Register-PadiemSelfHealWatcher" not in source
    assert "Get-PadiemSelfHealPython" not in source
    assert "PadiemPcSelfHeal" not in source
    assert "function Set-PadiemAgentServiceRecovery {" in source
    assert "& $sc failure $PadiemAgentServiceName" in source
    assert "'restart/5000/restart/5000/restart/5000'" in source
    assert "Set-PadiemAgentServiceRecovery" in source
    assert source.index("Install-PadiemAgentService -SourceExe") < source.index(
        "Invoke-PadiemUserHelperInstall -Url")


def test_connect_exe_installer_uses_scm_and_keeps_old_task_removal():
    source = (ROOT / "scripts/pc_pairing/connect-exe/PadiemPcConnect.cs").read_text(
        encoding="utf-8")
    assert "RegisterSelfHealWatcher();" not in source
    assert "static string RegisterSelfHealWatcher()" not in source
    assert "static string SelfHealPythonExecutable()" not in source
    assert "if (!SetAgentServiceRecovery())" in source
    assert "failure " in source and "restart/5000/restart/5000/restart/5000" in source
    assert source.index("RunQuiet(durable, \"-start\")") < source.index(
        "if (!SetAgentServiceRecovery())")
    assert 'SelfHealWatcherResource("PadiemSelfHealWatcherUnregister")' in source
    uninstall = source.split("static int Uninstall()", 1)[1].split(
        "static void DeleteUninstallRegistration()", 1)[0]
    assert "UnregisterSelfHealWatcher();" in uninstall
    assert 'SelfHealWatcherResource("PadiemSelfHealWatcher")' not in source


def test_exe_build_embeds_only_legacy_unregister_payload():
    build = build_script()
    assert "/resource:self-heal-watcher.ps1,PadiemSelfHealWatcher" not in build
    assert "/resource:self-heal-watcher-unregister.ps1,PadiemSelfHealWatcherUnregister" in build
    assert "'render_watcher_command'](unregister=True)" in build
    # The uninstaller's fixed source is still pinned into the build seed.
    assert "(Get-FileHashHex $SelfHealSource)" in build
    assert "src/kagent/pc_self_heal_task.py" in one_click_test_source()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows EXE reflection")
def test_shipped_exe_contains_removal_resource_but_not_registration(tmp_path):
    from app.pc_pairing_connect_exe_asset import connect_exe_bytes

    target = tmp_path / "connect.exe"
    target.write_bytes(connect_exe_bytes())
    script = tmp_path / "inspect.ps1"
    script.write_text(r"""
param([string]$Target)
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($Target)
$names = @($assembly.GetManifestResourceNames())
if ($names -contains 'PadiemSelfHealWatcher') { throw 'register_resource_present' }
if ($names -notcontains 'PadiemSelfHealWatcherUnregister') { throw 'unregister_missing' }
$stream = $assembly.GetManifestResourceStream('PadiemSelfHealWatcherUnregister')
$reader = [IO.StreamReader]::new($stream)
try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
Write-Output ('RESOURCE=' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text)))
""", encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
         str(script), str(target)],
        capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    value = next(x.split("=", 1)[1] for x in result.stdout.splitlines()
                 if x.startswith("RESOURCE="))
    restored = base64.b64decode(value).decode("utf-8")
    payload = restored.split("FromBase64String('", 1)[1].split("')", 1)[0]
    assert gzip.decompress(base64.b64decode(payload)).decode() == SELF_HEAL["watcher_script"]()
    assert restored.endswith("-Unregister")
