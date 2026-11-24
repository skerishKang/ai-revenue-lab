"""#8359 (2026-11-24): a failed SYSTEM refresh names one bounded cause."""
import shutil
import subprocess

import pytest
from app.pc_helper_registration import (
    command_finished,
    is_fixed_system_refresh_command,
    parse_receipt,
    parse_refresh_detail,
    registration_command,
)

FAILED = "PADIEM_HELPER_REFRESH:failed:registration_failed\r\n"


@pytest.mark.parametrize(("dispatch", "finished"), [
    ({"state": "done", "exit_code": 0, "termination": "exited"}, True),
    ({"state": "done", "exit_code": None, "termination": "no_exit_code"}, True),
    ({"state": "done", "exit_code": 1, "termination": "exited"}, False),
    ({"state": "done", "exit_code": None, "termination": "timed_out"}, False),
    ({"state": "done", "exit_code": None}, False),
    ({"state": "failed", "exit_code": None, "termination": "no_exit_code"}, False),
    ({"state": "pending", "exit_code": 0}, False),
    (None, False),
])
def test_command_finished(dispatch, finished):
    assert command_finished(dispatch) is finished


def test_detail_is_one_bounded_token_and_never_a_second_marker():
    assert parse_refresh_detail(FAILED + "PADIEM_HELPER_REFRESH_DETAIL:unexpected_helper_task\r\n") == \
        "unexpected_helper_task"
    assert parse_refresh_detail(FAILED) is None
    assert parse_refresh_detail(FAILED + "PADIEM_HELPER_REFRESH_DETAIL:a\nPADIEM_HELPER_REFRESH_DETAIL:b") is None
    assert parse_refresh_detail("PADIEM_HELPER_REFRESH_DETAIL:C:\\Users\\x") is None
    assert parse_refresh_detail("PADIEM_HELPER_REFRESH_DETAIL:" + "a" * 61) is None
    # The detail line never changes the receipt itself.
    assert parse_receipt(FAILED + "PADIEM_HELPER_REFRESH_DETAIL:updater_running") == \
        {"action": "failed", "reason": "registration_failed"}


def _catch_block():
    command = registration_command()
    return command[command.index("}catch{Write-Output 'PADIEM_HELPER_REFRESH:failed:registration_failed'") + 1:]


def test_fixed_command_prints_the_detail_only_from_its_catch():
    command = registration_command()
    assert command.count("PADIEM_HELPER_REFRESH_DETAIL:") == 1
    assert "PADIEM_HELPER_REFRESH_DETAIL:" in _catch_block()
    assert is_fixed_system_refresh_command(command, user_mode=False)


_SHELL = shutil.which("powershell") or shutil.which("pwsh")


@pytest.mark.skipif(not _SHELL, reason="PowerShell not available")
@pytest.mark.parametrize(("throw", "expected"), [
    ("throw 'unexpected_helper_task'", "unexpected_helper_task"),
    ("throw 'Access to C:\\Secret is denied'", "unexpected_runtimeexception"),
    ("[void][IO.File]::ReadAllText('Z:\\padiem-missing-8359.txt')", None),
])
def test_catch_block_runs_and_prints_one_bounded_token(throw, expected):
    script = "& {$ErrorActionPreference='Stop';try{" + throw + "}" + _catch_block()
    out = subprocess.run([_SHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=60, check=False).stdout
    assert parse_receipt(out) == {"action": "failed", "reason": "registration_failed"}
    detail = parse_refresh_detail(out)
    if expected is None:
        assert detail is not None and detail.startswith("unexpected_")
    else:
        assert detail == expected
    assert "Secret" not in out and "padiem-missing" not in out