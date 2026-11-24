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
    assert parse_refresh_detail(FAILED + "PADIEM_HELPER_REFRESH_DETAIL:unexpected_helper_task_12_getitem\r\n") == \
        "unexpected_helper_task_12_getitem"
    assert parse_refresh_detail(FAILED + "PADIEM_HELPER_REFRESH_DETAIL:unexpected_runtimeexception_7_\r\n") == \
        "unexpected_runtimeexception_7_"
    assert parse_refresh_detail(FAILED) is None
    assert parse_refresh_detail(FAILED + "PADIEM_HELPER_REFRESH_DETAIL:a_1_b\nPADIEM_HELPER_REFRESH_DETAIL:c_2_d") is None
    # The old cause-only form is not the new format, and neither are paths,
    # uppercase, oversized tokens or a missing location.
    assert parse_refresh_detail("PADIEM_HELPER_REFRESH_DETAIL:unexpected_helper_task") is None
    assert parse_refresh_detail("PADIEM_HELPER_REFRESH_DETAIL:C:\\Users\\x_3_getitem") is None
    assert parse_refresh_detail("PADIEM_HELPER_REFRESH_DETAIL:unexpected_helper_task_12_Get-Item") is None
    assert parse_refresh_detail("PADIEM_HELPER_REFRESH_DETAIL:" + "a" * 81) is None
    assert parse_refresh_detail("PADIEM_HELPER_REFRESH_DETAIL:unexpected_helper_task_12_" + "c" * 60) is None
    # The detail line never changes the receipt itself.
    assert parse_receipt(FAILED + "PADIEM_HELPER_REFRESH_DETAIL:updater_running_1_") == \
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
    ("throw 'unexpected_helper_task'", "unexpected_helper_task_1_"),
    ("throw 'Access to C:\\Secret is denied'", "unexpected_runtimeexception_1_"),
    ("[void][IO.File]::ReadAllText('Z:\\padiem-missing-8359.txt')",
     "unexpected_methodinvocationexception_1_"),
])
def test_catch_block_runs_and_prints_one_bounded_token(throw, expected):
    script = "& {$ErrorActionPreference='Stop';try{" + throw + "}" + _catch_block()
    out = subprocess.run([_SHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=60, check=False).stdout
    assert parse_receipt(out) == {"action": "failed", "reason": "registration_failed"}
    assert parse_refresh_detail(out) == expected
    assert "Secret" not in out and "padiem-missing" not in out


@pytest.mark.skipif(not _SHELL, reason="PowerShell not available")
@pytest.mark.parametrize(("throw", "command"), [
    ("Get-Date -Date 'not-a-date'", "getdate"),       # cmdlet 인자 변환 오류
    ("[datetime]::Parse('not-a-date')", ""),           # .NET 메서드 오류
])
def test_catch_block_reports_line_and_command_from_real_powershell(throw, command):
    """실제 PowerShell에서 던진 줄번호와 명령이름이 토큰에 들어가는지 확인한다."""
    script = ("& {\n$ErrorActionPreference='Stop'\ntry {\n" + throw + "\n}\n" + _catch_block())
    out = subprocess.run([_SHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=60, check=False).stdout
    assert parse_receipt(out) == {"action": "failed", "reason": "registration_failed"}
    detail = parse_refresh_detail(out)
    assert detail is not None
    # 오류를 일으킨 문장은 스크립트의 4번째 줄이다.
    assert f"_4_{command}" in detail
    assert "not-a-date" not in out