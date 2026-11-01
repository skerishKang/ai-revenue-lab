"""The Chat ExecCondition refuses a multi-worker launch contract violation.

The real invocation shape is a subprocess with the unit's environment, so these
tests run check_config.py the way systemd runs it: one process, env in, exit
code and one line out.
"""
import os
import subprocess
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "chat" / "check_config.py"

REASON = "프로세스 1개 전제 잠금: edge·tus·replay — 교차 프로세스화 전에는 1만 허용"


def _run(workers, **extra):
    environment = {
        **os.environ,
        "PADIEM_CHAT_WORKERS": workers,
        # Ready() needs a configured deployment; the fixture only cares about
        # the multi-worker verdict, so keep every other gate failing.
        "PADIEM_CHAT_PUBLIC_BASE_URL": "",
    }
    for key, value in extra.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    return subprocess.run(
        [sys.executable, PATH.as_posix()], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=environment, timeout=60,
    )


def test_two_workers_are_blocked_with_the_reason_and_exit_two():
    completed = _run("2")
    assert completed.returncode == 2
    assert completed.stdout.strip() == "CHAT_COM2_CONFIG_BLOCKED: " + REASON


def test_three_workers_are_blocked_the_same_way():
    completed = _run("3")
    assert completed.returncode == 2
    assert REASON in completed.stdout


def test_the_owner_switch_lets_the_readiness_check_run():
    completed = _run("2", PADIEM_CHAT_ALLOW_MULTI_WORKERS="1")
    assert completed.returncode == 1  # unready (no other gates), not blocked
    assert "CHAT_COM2_CONFIG_BLOCKED" not in completed.stdout
    assert "CHAT_COM2_CONFIG_READY=0" in completed.stdout


def test_single_worker_and_invalid_values_take_the_ready_path():
    for workers in ("1", "0", "abc", ""):
        completed = _run(workers)
        assert completed.returncode == 1, (workers, completed.stdout)
        assert "CHAT_COM2_CONFIG_BLOCKED" not in completed.stdout
        assert "CHAT_COM2_CONFIG_READY=0" in completed.stdout
