"""Safe PADIEM Agent source diagnostics and install compatibility.

No real tray, Broker, Agent, registry or Windows installer is run in tests.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from claw_connect.agent_preflight import agent_preflight
from claw_connect.resident_path import resident_src_root

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def _fake_agent_source(root: Path) -> None:
    pkg = root / "kagent"
    pkg.mkdir(parents=True)
    for file in (
        "__init__.py", "local_agent_resident_process.py",
        "local_agent_secure_transport.py", "local_agent_pairing.py",
    ):
        (pkg / file).write_text("# safe stub only\n", encoding="utf-8")


def test_valid_pinned_source_is_read_only_and_reports_source_only(tmp_path, monkeypatch):
    root = tmp_path / "agent_src"
    _fake_agent_source(root)
    monkeypatch.setenv("PADIEM_AGENT_SRC", str(root))
    monkeypatch.delenv("CLAW_RESIDENT_SRC", raising=False)
    state = tmp_path / "not-created"
    result = agent_preflight(state_dir=state)
    assert result["product"] == "PADIEM Agent"
    assert result["agent_ready"] is True
    assert result["agent_status"] == "ok"
    assert result["source_kind"] == "configured"
    assert result["agent_started"] is False
    assert result["production_gateway_enabled"] is False
    assert result["device_enrollment_changed"] is False
    assert not state.exists()
    assert resident_src_root(state_dir=state) == str(root)


def test_legacy_agent_source_environment_is_supported(tmp_path, monkeypatch):
    root = tmp_path / "agent_src"
    _fake_agent_source(root)
    monkeypatch.delenv("PADIEM_AGENT_SRC", raising=False)
    monkeypatch.setenv("CLAW_RESIDENT_SRC", str(root))
    assert agent_preflight(state_dir=tmp_path / "not-created")["agent_ready"]


def test_explicit_missing_module_never_falls_back_to_another_source(tmp_path, monkeypatch):
    root = tmp_path / "agent_src"
    _fake_agent_source(root)
    (root / "kagent" / "local_agent_pairing.py").unlink()
    monkeypatch.setenv("PADIEM_AGENT_SRC", str(root))
    monkeypatch.delenv("CLAW_RESIDENT_SRC", raising=False)
    info = agent_preflight(state_dir=tmp_path / "missing")
    assert info["agent_ready"] is False
    assert info["agent_status"] == "agent_source_invalid"
    assert info["source_kind"] == "configured"
    assert not (tmp_path / "missing").exists()


def test_conflicting_agent_source_aliases_fail_closed(tmp_path, monkeypatch):
    a, b = tmp_path / "agent_a", tmp_path / "agent_b"
    _fake_agent_source(a)
    _fake_agent_source(b)
    monkeypatch.setenv("PADIEM_AGENT_SRC", str(a))
    monkeypatch.setenv("CLAW_RESIDENT_SRC", str(b))
    with pytest.raises(ValueError, match="disagree"):
        resident_src_root(state_dir=tmp_path / "state")
    info = agent_preflight(state_dir=tmp_path / "state")
    assert info["agent_ready"] is False
    assert info["agent_status"] == "agent_source_conflict"


def test_legacy_resident_json_remains_supported(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _fake_agent_source(source)
    monkeypatch.delenv("PADIEM_AGENT_SRC", raising=False)
    monkeypatch.delenv("CLAW_RESIDENT_SRC", raising=False)
    config = tmp_path / "state"
    config.mkdir()
    (config / "resident.json").write_text(
        json.dumps({"src_root": str(source)}), encoding="utf-8"
    )
    assert resident_src_root(state_dir=config) == str(source)
    assert agent_preflight(state_dir=config)["agent_ready"]


def test_official_cli_doctor_never_mints_an_identity_or_runs_agent(tmp_path):
    scratch = tmp_path / "no-state"
    env = dict(os.environ, CLAW_CONNECT_STATE_DIR=str(scratch))
    env.pop("PADIEM_AGENT_SRC", None)
    env.pop("CLAW_RESIDENT_SRC", None)
    env["PADIEM_AGENT_SRC"] = str(tmp_path / "not-an-agent")
    call = subprocess.run(
        [sys.executable, "-m", "padiem_connector", "doctor"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=20,
    )
    assert call.returncode == 1, call.stderr
    parsed = json.loads(call.stdout)
    assert parsed["product"] == "PADIEM Agent"
    assert parsed["agent_status"] == "agent_source_invalid"
    assert parsed["device_enrollment_changed"] is False
    assert parsed["agent_started"] is False
    assert not scratch.exists()


def test_actual_repo_agent_source_is_recognised_but_never_launched(tmp_path, monkeypatch):
    source = REPO / "apps" / "korean-ai-code-agent" / "src"
    monkeypatch.setenv("PADIEM_AGENT_SRC", str(source))
    monkeypatch.delenv("CLAW_RESIDENT_SRC", raising=False)
    info = agent_preflight(state_dir=tmp_path / "untouched")
    assert info["agent_ready"] is True
    assert info["agent_started"] is False
    assert not (tmp_path / "untouched").exists()


def test_installer_guards_agent_source_and_old_version_uninstall():
    script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "[string]$AgentSrc" in script
    assert "Use -AgentSrc or legacy -ResidentSrc, not both" in script
    assert "$ValidatedAgentSrc = (Resolve-Path -LiteralPath $SelectedAgentSrc" in script
    assert "kagent\\local_agent_secure_transport.py" in script
    assert "if (Test-Path (Join-Path $InstallRoot 'padiem_connector'))" in script
    assert "'claw_connect'" in script
    assert "padiem_connector doctor" in script
    # The validation happens before creating the user's real install folder.
    assert script.index("if ($SelectedAgentSrc)") < script.index(
        "New-Item -ItemType Directory -Path $InstallRoot"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell parser")
def test_installer_powershell_syntax_without_running_or_modifying_pc():
    env = dict(os.environ, PADIEM_INSTALLER_SOURCE=str(ROOT / "install.ps1"))
    cmd = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:PADIEM_INSTALLER_SOURCE,[ref]$tokens,[ref]$errors) | Out-Null; "
        "if($errors.Count -gt 0){$errors | ForEach-Object {$_.Message};exit 1}"
    )
    outcome = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        env=env, capture_output=True, text=True, check=False, timeout=25,
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
