"""pc_shell contract, execution adapter and Windows worker tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import mcp_gateway_execution as execution
from app import mcp_gateway_shell as shell
from app.mcp_gateway_dispatch import _log_operation


UID = "usr_" + "a" * 32
DEVICE = "dev_" + "c" * 32
PRINCIPAL = {"owner_id": UID, "device_id": DEVICE, "token_id": "mcp_token_fixture"}
DISPATCH_ID = "oracle_mesh_cmd_" + "b" * 32


def _envelope(**overrides):
    data = {
        "exit_code": 0,
        "timed_out": False,
        "stdout": "ok\n",
        "stderr": "",
        "stdout_bytes": 3,
        "stderr_bytes": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "duration_ms": 25,
    }
    data.update(overrides)
    return data


def _response(payload, status=200):
    return SimpleNamespace(status_code=status, body=json.dumps(payload).encode())


def _install_fakes(monkeypatch, *, envelope, state="done", cancellation=None):
    seen = {"commands": [], "cancel": 0}

    async def dispatch(request, **kwargs):
        seen["commands"].append(kwargs)
        return _response({"ok": True, "dispatch": {"dispatch_id": DISPATCH_ID}})

    async def row(request, **kwargs):
        return {"state": state, "termination": "exited", "command_id": "cmd_1",
                "revision_ref": "rev_1", "result_sha256": "0" * 64, "result_bytes": 1}

    raw = json.dumps(envelope, ensure_ascii=False).encode()

    async def original(request, **kwargs):
        return raw, hashlib.sha256(raw).hexdigest()

    async def cancel(request, **kwargs):
        seen["cancel"] += 1
        return 1

    monkeypatch.setattr(shell, "_dispatch_command", dispatch)
    monkeypatch.setattr(shell, "_dispatch_row", row)
    monkeypatch.setattr(shell, "_read_original", original)
    monkeypatch.setattr(shell, "_cancel_run", cancel)
    return seen


def _execute(arguments):
    return asyncio.run(shell.execute_pc_shell(
        object(), session=SimpleNamespace(), uid=UID, workspace_id="workspace_fixture",
        device_id=DEVICE, run_id="run_fixture", conversation_id="chat_fixture",
        arguments=arguments,
    ))


def test_schema_accepts_only_bounded_known_values():
    assert shell.validate_pc_shell_arguments({"command": "git status"})
    assert shell.normalize_pc_shell_arguments({"command": "git status"}) == {
        "command": "git status", "cwd": None, "shell": "powershell", "timeout_seconds": 120,
    }
    assert shell.normalize_pc_shell_arguments({
        "command": "git status", "cwd": "C:/work", "shell": "cmd", "timeout_seconds": 600,
    })["timeout_seconds"] == 600
    for bad in (
        {}, {"command": ""}, {"command": "x", "shell": "zsh"},
        {"command": "x", "timeout_seconds": 0}, {"command": "x", "timeout_seconds": 601},
        {"command": "x", "timeout_seconds": True}, {"command": "x", "cwd": "bad\x01path"},
        {"command": "x", "device_id": DEVICE}, {"command": "x", "extra": "value"},
        {"command": "x" * (shell.PC_SHELL_MAX_COMMAND_CHARS + 1)},
    ):
        assert not shell.validate_pc_shell_arguments(bad)


def test_dispatch_command_is_one_line_and_never_carries_raw_command():
    command = "Write-Output 'secret-value'; exit 0"
    built = shell.build_pc_shell_command({
        "command": command, "cwd": r"C:\work", "shell": "powershell", "timeout_seconds": 30,
    })
    assert "\n" not in built and "\r" not in built
    assert "secret-value" not in built
    assert "PADIEM_PC_SHELL_COMMAND_B64" in built
    assert "PADIEM_PC_SHELL_CWD_B64" in built
    longest = shell.build_pc_shell_command({"command": "x" * shell.PC_SHELL_MAX_COMMAND_CHARS})
    assert len(longest) < 120_000


def test_result_parser_accepts_bounded_worker_json_only():
    assert shell.parse_pc_shell_result(json.dumps(_envelope()))["stdout"] == "ok\n"
    for bad in (
        {}, {"exit_code": True}, {"timed_out": "no"}, {"stdout": 1},
        _envelope(stdout_bytes=-1), _envelope(stdout_truncated="no"),
        _envelope(error="not_a_worker_code"),
    ):
        with pytest.raises((ValueError, TypeError)):
            shell.parse_pc_shell_result(json.dumps(bad))


def test_completed_result_returns_streams_exit_code_and_numeric_audit(monkeypatch):
    seen = _install_fakes(monkeypatch, envelope=_envelope(exit_code=7, stderr="warn\n",
                                                          stderr_bytes=5))
    result = _execute({"command": "echo ok"})
    assert result["status"] == "completed"
    assert result["exit_code"] == 7 and result["timed_out"] is False
    assert result["stdout"] == "ok\n" and result["stderr"] == "warn\n"
    assert result["audit"] == {"exit_code": 7, "duration_ms": result["audit"]["duration_ms"],
                               "output_bytes": 8, "output_truncated": False}
    assert "command" not in result["audit"] and "stdout" not in result["audit"]
    command = seen["commands"][0]["command"]
    assert "echo ok" not in command and "PADIEM_PC_SHELL_COMMAND_B64" in command
    assert seen["commands"][0]["ttl_seconds"] == 180


def test_truncated_result_is_reported_without_changing_the_exit_code(monkeypatch):
    _install_fakes(monkeypatch, envelope=_envelope(
        stdout="head\n...[중간 생략]...\ntail\n", stdout_bytes=30_000, stdout_truncated=True,
    ))
    result = _execute({"command": "big"})
    assert result["status"] == "completed" and result["exit_code"] == 0
    assert result["truncated"] is True
    assert result["audit"]["output_truncated"] is True
    assert result["audit"]["output_bytes"] == 30_000


def test_worker_error_is_a_failed_result_with_its_code(monkeypatch):
    _install_fakes(monkeypatch, envelope=_envelope(exit_code=None, error="cwd_invalid"))
    result = _execute({"command": "echo ok", "cwd": "C:/missing"})
    assert result["status"] == "failed" and result["code"] == "pc_shell_cwd_invalid"
    assert result["audit"]["exit_code"] is None


def test_dispatch_poll_timeout_cancels_the_run(monkeypatch):
    seen = _install_fakes(monkeypatch, envelope=_envelope(), state="pending")
    ticks = [0.0]

    def fake_now():
        ticks[0] += 10.0
        return ticks[0]

    monkeypatch.setattr(shell, "_NOW", fake_now)
    monkeypatch.setattr(shell, "PC_SHELL_POLL_SECONDS", 0)
    result = _execute({"command": "sleep", "timeout_seconds": 1})
    assert result["status"] == "failed" and result["code"] == "pc_shell_timeout"
    assert seen["cancel"] == 1


def test_shell_bypasses_engine_and_records_existing_pc_run(monkeypatch):
    from test_mcp_gateway_execution import harness

    request, transport, history, calls = harness(monkeypatch)
    captured = {}

    async def fake_shell(request, **kwargs):
        captured.update(kwargs)
        return {"status": "completed", "answer": "PC 명령이 끝났습니다.", "exit_code": 0,
                "stdout": "ok\n", "audit": {"exit_code": 0, "duration_ms": 1,
                                             "output_bytes": 3, "output_truncated": False}}

    monkeypatch.setattr(execution, "execute_pc_shell", fake_shell)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_shell", {"command": "echo ok"},
    ))
    assert result["status"] == "completed"
    assert result["exit_code"] == 0 and result["stdout"] == "ok\n"
    assert transport.calls == []
    assert history.runs[0]["action"] == "pc_files_query"
    assert history.runs[0]["user_text"] == "외부 AI 도구 요청: pc_shell"
    assert captured["arguments"] == {"command": "echo ok", "cwd": None,
                                     "shell": "powershell", "timeout_seconds": 120}
    assert captured["device_id"] == DEVICE


@pytest.mark.parametrize("denial", ["matching", "grant", "tool"])
def test_unavailable_or_undelegated_pc_never_dispatches(monkeypatch, denial):
    from test_mcp_gateway_execution import harness

    request, transport, history, _ = harness(monkeypatch, matching=denial != "matching")
    if denial == "grant":
        async def deny(request, session, **kwargs):
            return False
        monkeypatch.setattr(execution, "_check_mesh_grant", deny)
    if denial == "tool":
        async def unavailable(request, **kwargs):
            return SimpleNamespace(selected_confirmed=True, tool_available=False,
                                   execution_device_id=DEVICE)
        monkeypatch.setattr(execution, "resolve_pc_work_context", unavailable)
    called = []
    async def fake_shell(request, **kwargs):
        called.append(True)
        return {"status": "completed"}
    monkeypatch.setattr(execution, "execute_pc_shell", fake_shell)
    with pytest.raises(execution.ChatPCDriveError) as caught:
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_shell", {"command": "echo ok"},
        ))
    assert caught.value.code == "chat_pc_target_unavailable"
    assert called == [] and history.runs == [] and transport.calls == []


def test_audit_log_carries_numbers_not_command_or_output():
    audit = {"tool_name": "pc_shell", "arguments": {"command": "secret-command"},
             "approval_id": None}
    outcome = {"run_id": "run_fixture", "status": "completed",
               "stdout": "secret-output", "audit": {
                   "exit_code": 0, "duration_ms": 12, "output_bytes": 3,
                   "output_truncated": False}}
    messages = []

    class Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger = logging.getLogger("padiem_chat.request")
    handler = Capture()
    logger.addHandler(handler)
    try:
        _log_operation(audit, "completed", outcome=outcome)
    finally:
        logger.removeHandler(handler)
    logged = "\n".join(messages)
    assert "secret-command" not in logged and "secret-output" not in logged
    assert '"tool":"pc_shell"' in logged
    assert '"exit_code":0' in logged
    assert '"duration_ms":12' in logged
    assert '"output_bytes":3' in logged
    assert '"output_truncated":false' in logged


def test_database_audit_stores_only_numeric_metadata():
    from test_mcp_gateway_account import DEVICE as MCP_DEVICE, issued, setup

    db, owner, _other, store = setup()

    async def scenario():
        token, _identity = await issued(store, owner)
        return await store.audit(
            identity={"user_id": owner, "device_id": MCP_DEVICE, "token_id": token["id"]},
            tool_name="pc_shell", arguments={"command": "secret-command"},
            status="completed", exit_code=0, duration_ms=12, output_bytes=5,
            output_truncated=False,
        )

    asyncio.run(scenario())
    row = dict(db.conn.execute("SELECT * FROM padiem_mcp_audit").fetchone())
    assert "secret-command" not in json.dumps(row, ensure_ascii=False)
    assert row["exit_code"] == 0 and row["duration_ms"] == 12
    assert row["output_bytes"] == 5 and row["output_truncated"] == 0
    assert len(row["request_digest"]) == 64


def _run_worker(arguments, timeout=45):
    outer = shell.build_pc_shell_command(arguments)
    wrapped = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; & { " + outer + " } 2>&1 | Out-String"
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", wrapped],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    text = completed.stdout
    start, end = text.find("{"), text.rfind("}")
    assert start >= 0 and end > start, completed.stderr
    return json.loads(text[start:end + 1])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows worker test")
def test_windows_worker_returns_exit_code_streams_cwd_and_truncation():
    result = _run_worker({"command": "Write-Output 'hello'; Write-Error 'bad'; exit 3"})
    assert result["exit_code"] == 3 and result["timed_out"] is False
    assert "hello" in result["stdout"] and "bad" in result["stderr"]
    cwd = _run_worker({"command": "(Get-Location).Path", "cwd": os.environ.get("WINDIR", r"C:\Windows")})
    assert "Windows" in cwd["stdout"]
    big = _run_worker({"command": "$s = 'a' * 20000; Write-Output $s"})
    assert big["stdout_truncated"] is True and big["stdout_bytes"] >= 20_000
    assert shell.PC_SHELL_TRUNCATION_MARKER.strip() in big["stdout"]
    bad = _run_worker({"command": "Write-Output x", "cwd": r"C:\does-not-exist-261103"})
    assert bad["error"] == "cwd_invalid"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows worker test")
def test_windows_worker_timeout_and_cmd_shell():
    timed = _run_worker({"command": "Start-Sleep -Seconds 5; Write-Output done", "timeout_seconds": 1})
    assert timed["timed_out"] is True and timed["exit_code"] is None
    if shutil.which("cmd.exe"):
        cmd = _run_worker({"command": "echo hello & echo bad 1>&2 & exit /b 2", "shell": "cmd"})
        assert cmd["exit_code"] == 2 and "hello" in cmd["stdout"] and "bad" in cmd["stderr"]


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("bash.exe"),
                    reason="bash worker test")
def test_windows_worker_bash_shell():
    bash = _run_worker({"command": "echo hello; echo bad >&2; exit 4", "shell": "bash"})
    assert bash["exit_code"] == 4 and "hello" in bash["stdout"] and "bad" in bash["stderr"]
