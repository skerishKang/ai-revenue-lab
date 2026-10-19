"""Official name changes while all existing device/runtime authorities remain one."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

def test_official_and_legacy_python_commands_share_product_and_device(tmp_path):
    env = dict(os.environ, CLAW_CONNECT_STATE_DIR=str(tmp_path / "state"))
    def run(module: str, *args: str):
        return subprocess.run(
            [sys.executable, "-m", module, *args], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=25, check=False,
        )
    old = run("claw_connect", "--version")
    new = run("padiem_connector", "--version")
    assert old.returncode == new.returncode == 0
    assert old.stdout == new.stdout
    assert "PADIEM Connector" in new.stdout
    old_status = run("claw_connect", "status")
    new_status = run("padiem_connector", "status")
    assert old_status.returncode == new_status.returncode == 0
    a,b=json.loads(old_status.stdout),json.loads(new_status.stdout)
    assert a["product"] == b["product"] == "PADIEM Connector"
    assert a["enrollment"]["device_id"] == b["enrollment"]["device_id"]

def test_installer_migrates_only_its_owned_legacy_shortcut():
    source=(ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "PADIEM Connector.lnk" in source
    assert "Padiem Claw Connect.lnk" in source
    assert "Remove-OwnedLegacyShortcut" in source
    assert "$link.WorkingDirectory -eq $InstallRoot" in source
    assert "$link.Arguments -eq '-m claw_connect start'" in source
    assert "Copy-Item -Path (Join-Path $SourceRoot 'padiem_connector')" in source
    assert "& $PythonExePath -m padiem_connector autostart on" in source
    assert "& $PythonExePath -m $UninstallModule autostart off" in source
    assert "'claw_connect'" in source and "'padiem_connector'" in source

def test_windows_identity_stays_identical_across_public_brand_alias():
    from claw_connect import AUTOSTART_RUN_VALUE_NAME, SINGLE_INSTANCE_MUTEX
    from claw_connect.runtime import QUIT_EVENT_NAME
    assert AUTOSTART_RUN_VALUE_NAME == "PadiemClawConnect"
    assert SINGLE_INSTANCE_MUTEX == "PadiemClawConnect.SingleInstance.v1"
    assert QUIT_EVENT_NAME == "PadiemClawConnect.QuitEvent.v1"

def test_padiem_agent_alias_names_one_existing_legacy_resident():
    alias=(REPO / "apps/korean-ai-code-agent/src/padiem_agent/resident.py").read_text(encoding="utf-8")
    assert "from kagent.local_agent_resident_process import main" in alias
    assert "class Resident" not in alias
    assert "def main(" not in alias
    from claw_connect.resident_supervisor import RESIDENT_ENTRY_MODULE
    assert RESIDENT_ENTRY_MODULE == "kagent.local_agent_resident_process"
