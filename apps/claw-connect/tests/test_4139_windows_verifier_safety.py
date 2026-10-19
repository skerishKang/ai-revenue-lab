"""Safety contract: the standalone Windows verifier cannot mutate the owner PC."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_verifier_is_scratch_only_and_does_not_launch_or_stop_tray():
    source = (ROOT / "verify_windows_live.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "TemporaryDirectory(" in source
    assert "CentralLive" in source
    assert "CLAW_CONNECT_AUTOSTART_RUN_KEY" in source
    assert "CLAW_CONNECT_AUTOSTART_PREF_KEY" in source
    assert "PadiemClawConnectSelftest" in source
    assert "Get-CimInstance" not in source
    assert "first.kill(" not in source
    assert 'subprocess.Popen(' not in source
    assert '"-Uninstall"' not in source
    assert "Remove-ItemProperty" in source  # explicit prohibition in static guard


def test_verifier_runs_only_bounded_nonproduction_contract():
    tree = ast.parse((ROOT / "verify_windows_live.py").read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)
    text = (ROOT / "verify_windows_live.py").read_text(encoding="utf-8")
    assert '"scope": "scratch_only_no_live_broker"' in text
    assert '"start"' not in text  # never launch shared singleton / tray
    assert '"stop"' not in text
