from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[3]
CHECK = ROOT / "scripts/ops/windows_runtime_retire_check.ps1"

def test_registered_tasks_are_in_the_readonly_check():
    # #7404: the retire runbook moved to the private operations records; the
    # shipped read-only check stays the enforced surface for the task names.
    registered = set()
    for filename in ("com2_runtime.py", "com2_periodic_sync.py", "com2_backup_schedule.py"):
        path = ROOT / "scripts/ops" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "DEFAULT_TASK_NAME" for t in node.targets)
                 and isinstance(node.value, ast.Constant)]
        assert len(names) == 1
        registered.add(names[0])
    expected = registered | {"PADIEM-Local-AI-OnLogon", "PADIEM-Local-AI-Watchdog"}
    script = CHECK.read_text(encoding="utf-8")
    assert set(re.findall(r"'(PADIEM-[^']+)'", script)) == expected
    assert "PADIEM-Mesh-Tunnel" not in script

def test_check_is_read_only_and_includes_all_three_ports():
    script = CHECK.read_text(encoding="utf-8")
    assert all(str(port) in script for port in (18764, 18717, 18731))
    assert "Get-ScheduledTask" in script and "Get-NetTCPConnection" in script
    assert not re.search(r"(?i)\b(?:disable|enable|unregister|register|stop|start)-", script)
