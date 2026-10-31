from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/operations/WINDOWS_RUNTIME_RETIRE_RUNBOOK_20261031.md"
CHECK = ROOT / "scripts/ops/windows_runtime_retire_check.ps1"

def test_registered_tasks_are_in_runbook_and_readonly_check():
    registered = set()
    for filename in ("com2_runtime.py", "com2_periodic_sync.py", "com2_backup_schedule.py"):
        path = ROOT / "scripts/ops" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "DEFAULT_TASK_NAME" for t in node.targets)
                 and isinstance(node.value, ast.Constant)]
        assert len(names) == 1
        registered.add(names[0])
        assert filename in DOC.read_text(encoding="utf-8")
    expected = registered | {"PADIEM-Local-AI-OnLogon", "PADIEM-Local-AI-Watchdog"}
    doc = DOC.read_text(encoding="utf-8")
    script = CHECK.read_text(encoding="utf-8")
    assert set(re.findall(r"^\| (PADIEM-[^ |]+) \|", doc, re.M)) == expected
    assert set(re.findall(r"'(PADIEM-[^']+)'", script)) == expected
    assert "PADIEM-Mesh-Tunnel" not in script

def test_check_is_read_only_and_includes_all_three_ports():
    script = CHECK.read_text(encoding="utf-8")
    assert all(str(port) in script for port in (18764, 18717, 18731))
    assert "Get-ScheduledTask" in script and "Get-NetTCPConnection" in script
    assert not re.search(r"(?i)\b(?:disable|enable|unregister|register|stop|start)-", script)
