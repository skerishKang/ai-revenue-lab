"""MCP shell reuses Claw dispatch state, cancellation and OutputStore handles."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from types import SimpleNamespace

import pytest

from app import mcp_gateway_shell as shell

UID = "usr_" + "a" * 32
OTHER_UID = "usr_" + "d" * 32
DEVICE = "dev_" + "c" * 32
OTHER_DEVICE = "dev_" + "e" * 32
TOKEN = "mcp_" + "f" * 32
JOB_ID = "dsp_" + "b" * 32
RUN_ID = "run_fixture"
SUBJECT = "sub_" + "7" * 32


def _response(payload, status=200):
    return SimpleNamespace(status_code=status, body=json.dumps(payload).encode("utf-8"))


class ReceiptStore:
    def __init__(self):
        self.job_id = None
        self.identity = None

    async def owns_job_receipt(self, *, identity, job_id):
        return job_id == self.job_id and identity == self.identity


class CommonHistory:
    def __init__(self):
        self.state = "pending"
        self.claimed = True
        self.termination = None
        self.exit_code = None
        self.output = "hello world"
        self.output_ref = None
        self.read_calls = []
        self.cancelled_runs = []

    def _row(self):
        raw = self.output.encode("utf-8")
        return {
            "dispatch_id": JOB_ID, "user_id": UID, "device_id": DEVICE,
            "run_id": RUN_ID, "kind": "command", "state": self.state,
            "claimed": self.claimed, "termination": self.termination,
            "exit_code": self.exit_code, "command_id": "oracle_mesh_cmd_" + "1" * 32,
            "revision_ref": "rev_1", "result_sha256": hashlib.sha256(raw).hexdigest(),
            "result_bytes": len(raw),
        }

    async def get_oracle_mesh_dispatch_for_owner(self, *, user_id, dispatch_id):
        if user_id == UID and dispatch_id == JOB_ID:
            return self._row()
        return None

    async def get_pc_output_dispatch_for_owner(self, *, user_id, dispatch_id):
        return await self.get_oracle_mesh_dispatch_for_owner(user_id=user_id, dispatch_id=dispatch_id)

    async def get_claw_run(self, user_id, run_id):
        if user_id == UID and run_id == RUN_ID:
            return {"run_id": RUN_ID, "conversation_id": "conv_fixture"}
        return None

    async def store_pc_output(self, **kwargs):
        assert kwargs["user_id"] == UID and kwargs["device_id"] == DEVICE
        assert kwargs["run_id"] == RUN_ID and kwargs["dispatch_id"] == JOB_ID
        assert kwargs["source"] == "mcp_shell"
        self.output_ref = {"handle": "a" * 64, "size": len(kwargs["content"].encode("utf-8")),
                           "truncated": False}
        self.output = kwargs["content"]
        return self.output_ref

    async def read_pc_output(self, **kwargs):
        self.read_calls.append(dict(kwargs))
        raw = self.output.encode("utf-8")
        data = raw[kwargs["offset"]:kwargs["offset"] + kwargs["length"]]
        return {"handle": kwargs["handle"], "content": data.decode("utf-8")}

    async def cancel_oracle_mesh_dispatches_for_run(self, *, user_id, run_id):
        self.cancelled_runs.append((user_id, run_id))
        if user_id != UID or run_id != RUN_ID or self.state != "pending":
            return 0
        self.state, self.termination = "failed", "cancelled"
        return 1


def _request(history=None, receipts=None):
    state = SimpleNamespace(
        history_store=history or CommonHistory(),
        mcp_gateway_store=receipts or ReceiptStore(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_closed_schemas_accept_only_the_common_dispatch_id_and_bounded_ranges():
    assert shell.validate_pc_shell_arguments({"command": "git status"})
    assert shell.normalize_pc_shell_arguments({"command": "git status"}) == {
        "command": "git status", "cwd": None, "shell": "powershell", "wait_seconds": 120,
        "mode": "system",
    }
    assert shell.validate_pc_shell_start_arguments({"command": "sleep"})
    assert shell.validate_pc_shell_read_arguments({"job_id": JOB_ID, "offset": 10, "length": 4})
    assert shell.validate_pc_shell_stop_arguments({"job_id": JOB_ID})
    assert not shell.validate_pc_shell_read_arguments({"job_id": "oracle_mesh_cmd_" + "b" * 32})
    for bad in (
        {"command": "x", "timeout_seconds": 10}, {"command": "x", "wait_seconds": 0},
        {"command": "x", "wait_seconds": 151}, {"command": "x", "wait_seconds": True},
        {"command": "x", "shell": "zsh"}, {"command": "x", "unknown": 1},
        {"job_id": JOB_ID, "offset": -1}, {"job_id": JOB_ID, "length": 65_537},
        {"job_id": JOB_ID, "device_id": DEVICE},
    ):
        if "command" in bad:
            assert not (shell.validate_pc_shell_start_arguments(bad)
                        if "wait_seconds" not in bad and "timeout_seconds" not in bad
                        else shell.validate_pc_shell_arguments(bad))
        else:
            assert not shell.validate_pc_shell_read_arguments(bad)


def test_command_is_encoded_and_uses_the_common_executor_without_mcp_files_or_deadline():
    secret = "Write-Output 'private-command-material'; Start-Sleep 999"
    command = shell.build_pc_shell_command({"command": secret, "cwd": r"C:\work"})
    assert "\n" not in command and "\r" not in command
    assert secret not in command and "private-command-material" not in command
    assert "PADIEM_MCP_COMMAND_B64" in command and "PADIEM_MCP_CWD_B64" in command
    assert "padiem-mcp-jobs" not in command.lower()
    assert "timeout" not in command.lower() and "taskkill" not in command.lower()
    script_b64 = command.rsplit("-EncodedCommand ", 1)[1]
    script = base64.b64decode(script_b64).decode("utf-16-le")
    assert "$inner=[Convert]::ToBase64String" in script
    assert "-EncodedCommand $inner" in script and "& $file @args" in script
    assert "Start-Process" not in script
    # The executor wraps this command and reads its envelope from the same
    # PowerShell session; an outer exit would end the wrapper first.
    assert not command.endswith(";exit $LASTEXITCODE")
    assert "exit" not in command.split("-EncodedCommand ", 1)[0].lower()
    assert len(shell.build_pc_shell_command({"command": "x" * shell.PC_SHELL_MAX_COMMAND_CHARS})) < 120_000


def test_nested_powershell_asks_for_text_output_and_pins_utf8_output():
    """#7068: the nested call must not invite CliXml, and its bytes stay UTF-8.

    Measured on the live PC (11-07): the dispatcher's nested
    ``powershell.exe -EncodedCommand`` made the outer console fail with
    ProcessStreamReader_CliXmlError on a Korean-locale console. Text output is
    asked for explicitly, and the console encoding is pinned so the answer is not
    read in the code page it was not written in.
    """
    script = base64.b64decode(
        shell.build_pc_shell_command({"command": "Write-Output ok"})
        .rsplit("-EncodedCommand ", 1)[1]
    ).decode("utf-16-le")
    assert "-OutputFormat Text -EncodedCommand $inner" in script
    assert "[Console]::OutputEncoding=[Text.Encoding]::UTF8" in script
    # The cmd/bash branch keeps the same nested shape; nothing is redirected
    # into a pipeline the console would try to deserialize.
    cmd_script = base64.b64decode(
        shell.build_pc_shell_command({"command": "echo ok", "shell": "cmd"})
        .rsplit("-EncodedCommand ", 1)[1]
    ).decode("utf-16-le")
    assert "$file='cmd.exe'" in cmd_script and "& $file @args" in cmd_script
    assert "ConvertTo-CliXml" not in cmd_script and "Export-Clixml" not in cmd_script


def test_common_dispatch_is_background_with_actual_dsp_receipt_format(monkeypatch):
    from app import oracle_mesh_read_return_routes as routes

    seen = {}

    async def dispatch(request, **kwargs):
        seen.update(kwargs)
        return _response({"dispatch": {"dispatch_id": JOB_ID}})

    monkeypatch.setattr(routes, "dispatch_oracle_mesh_command_intent", dispatch)
    response = asyncio.run(shell._dispatch_command(
        object(), command="encoded", run_id=RUN_ID, device_id=DEVICE,
        trusted_owner=(SimpleNamespace(tenant_id="tenant"), UID, "workspace"),
    ))
    assert response.status_code == 200
    assert seen["background"] is True
    assert seen["ttl_seconds"] == 3600
    assert seen["wire"] == {"run_id": RUN_ID, "device_id": DEVICE, "confirmed": True}
    assert shell._valid_job_id(JOB_ID)
    assert not shell._valid_job_id("oracle_mesh_cmd_" + "b" * 32)


def test_one_receipt_starts_reads_output_store_range_and_cancels_common_run(monkeypatch):
    history, receipts = CommonHistory(), ReceiptStore()
    request = _request(history, receipts)
    receipts.job_id = JOB_ID
    receipts.identity = {"user_id": UID, "device_id": DEVICE, "token_id": TOKEN}
    async def dispatch(_request, **kwargs):
        assert kwargs["run_id"] == RUN_ID and kwargs["device_id"] == DEVICE
        return _response({"dispatch": {"dispatch_id": JOB_ID, "run_id": RUN_ID,
                                        "device_id": DEVICE}})
    async def original(_request, *, uid, dispatch, run_row):
        assert uid == UID and dispatch["dispatch_id"] == JOB_ID
        return history.output
    monkeypatch.setattr(shell, "_dispatch_command", dispatch)
    monkeypatch.setattr(shell, "_read_original", original)
    started = asyncio.run(shell.execute_pc_shell_start(
        request, uid=UID, workspace_id="workspace", device_id=DEVICE, run_id=RUN_ID,
        session=SimpleNamespace(), conversation_id="conv_fixture",
        arguments={"command": "sleep", "shell": "powershell"},
    ))
    assert started["status"] == "running" and started["job_id"] == JOB_ID
    assert started["_job_receipt"] == JOB_ID

    identity = {"user_id": UID, "device_id": DEVICE, "token_id": TOKEN}
    running = asyncio.run(shell.execute_pc_shell_read(
        request, identity=identity, subject_id=SUBJECT,
        arguments={"job_id": JOB_ID, "offset": 0, "length": 5},
    ))
    assert running["status"] == "running" and running["output"] == ""

    history.state, history.exit_code, history.termination = "done", 0, "exited"
    read = asyncio.run(shell.execute_pc_shell_read(
        request, identity=identity, subject_id=SUBJECT,
        arguments={"job_id": JOB_ID, "offset": 0, "length": 5},
    ))
    assert read["status"] == "completed" and read["job_id"] == JOB_ID
    assert read["output"] == "hello" and read["next_offset"] == 5
    assert read["output_ref"] == {"handle": "a" * 64, "size": 11, "truncated": False}
    assert read["audit"] == {"exit_code": 0, "output_bytes": 11, "output_truncated": False}
    assert history.read_calls[0]["handle"] == "a" * 64
    assert history.read_calls[0]["run_id"] == RUN_ID

    history.state = "pending"
    stopped = asyncio.run(shell.execute_pc_shell_stop(request, identity=identity, job_id=JOB_ID))
    assert stopped["status"] == "cancelled" and stopped["job_id"] == JOB_ID
    assert history.cancelled_runs == [(UID, RUN_ID)]
    assert history.state == "failed" and history.termination == "cancelled"


@pytest.mark.parametrize("identity", [
    # 2026-11-04: 같은 토큰이 다른 PC에서 시작한 자기 작업은 읽고 중지할 수
    # 있다(멀티디바이스 계약). 다른 계정·다른 토큰은 거절 유지.
    {"user_id": OTHER_UID, "device_id": DEVICE, "token_id": TOKEN},
    {"user_id": UID, "device_id": DEVICE, "token_id": "mcp_" + "0" * 32},
])
def test_other_account_pc_or_token_cannot_read_or_stop_receipt(identity):
    history, receipts = CommonHistory(), ReceiptStore()
    receipts.job_id = JOB_ID
    receipts.identity = {"user_id": UID, "device_id": DEVICE, "token_id": TOKEN}
    request = _request(history, receipts)
    read = asyncio.run(shell.execute_pc_shell_read(
        request, identity=identity, subject_id=SUBJECT,
        arguments={"job_id": JOB_ID},
    ))
    stop = asyncio.run(shell.execute_pc_shell_stop(request, identity=identity, job_id=JOB_ID))
    assert read["status"] == "denied" and stop["status"] == "denied"
    assert history.cancelled_runs == []


def test_wait_window_returns_same_running_job_without_cancelling_it(monkeypatch):
    history, receipts = CommonHistory(), ReceiptStore()
    request = _request(history, receipts)
    receipts.job_id = JOB_ID
    receipts.identity = {"user_id": UID, "device_id": DEVICE, "token_id": TOKEN}
    async def dispatch(_request, **kwargs):
        return _response({"dispatch": {"dispatch_id": JOB_ID, "run_id": RUN_ID,
                                        "device_id": DEVICE}})
    ticks = [0.0]
    def now():
        ticks[0] += 60
        return ticks[0]
    monkeypatch.setattr(shell, "_dispatch_command", dispatch)
    monkeypatch.setattr(shell, "_NOW", now)
    monkeypatch.setattr(shell, "PC_SHELL_POLL_SECONDS", 0)
    result = asyncio.run(shell.execute_pc_shell(
        request, uid=UID, subject_id=SUBJECT, workspace_id="workspace", device_id=DEVICE,
        token_id=TOKEN, run_id=RUN_ID, session=SimpleNamespace(), conversation_id="conv_fixture",
        arguments={"command": "sleep", "cwd": None, "shell": "powershell", "wait_seconds": 1},
    ))
    assert result["status"] == "running" and result["job_id"] == JOB_ID
    assert history.state == "pending" and history.cancelled_runs == []


def test_terminal_output_is_verified_against_the_common_dispatch_hash():
    content = "공통 Claw 출력"
    raw = content.encode("utf-8")
    seen = []

    class OriginalStore:
        async def read_oracle_mesh_original(self, **kwargs):
            seen.append(kwargs)
            return raw, hashlib.sha256(raw).hexdigest()

    request = _request(OriginalStore())
    dispatch = {"dispatch_id": JOB_ID, "command_id": "oracle_mesh_cmd_" + "1" * 32,
                "revision_ref": "rev_1", "result_sha256": hashlib.sha256(raw).hexdigest(),
                "result_bytes": len(raw)}
    run = {"conversation_id": "chat_" + "7" * 32}
    result = asyncio.run(shell._read_original(request, uid=UID, dispatch=dispatch, run_row=run))
    assert result == content
    assert seen[0]["dispatch_id"] == JOB_ID and seen[0]["user_id"] == UID
    assert not any("command" in key or "output" in key for key in seen[0])
    tampered = {**dispatch, "result_sha256": "0" * 64}
    assert asyncio.run(shell._read_original(request, uid=UID, dispatch=tampered, run_row=run)) is None


def test_stale_selected_pc_returns_offline_answer_without_creating_a_run(monkeypatch):
    from app import mcp_gateway_execution as execution
    from test_mcp_gateway_execution import harness

    request, _transport, history, _calls = harness(monkeypatch)
    request.app.state.settings = SimpleNamespace(mcp_pc_shell_enabled=True)

    async def offline(*args, **kwargs):
        return SimpleNamespace(selection_offline=True, selected_device_id=DEVICE,
                               selected_confirmed=False, tool_available=False,
                               execution_device_id=None)

    monkeypatch.setattr(execution, "resolve_pc_work_context", offline)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, {"owner_id": UID, "device_id": DEVICE, "token_id": TOKEN},
        "pc_shell_start", {"command": "Get-Date"},
    ))
    assert result == {"status": "unavailable", "code": "pc_offline",
                      "answer": "선택한 PC가 꺼져 있음"}
    assert history.runs == []


@pytest.mark.parametrize("denial", ["selection", "grant", "tool"])
def test_unavailable_or_undelegated_pc_never_creates_a_common_dispatch(monkeypatch, denial):
    from app import mcp_gateway_execution as execution
    from test_mcp_gateway_execution import harness

    request, transport, history, _calls = harness(monkeypatch)
    request.app.state.settings = SimpleNamespace(mcp_pc_shell_enabled=True)
    if denial == "selection":
        context = SimpleNamespace(selection_offline=False, selected_device_id=OTHER_DEVICE,
                                  selected_confirmed=True, tool_available=True,
                                  execution_device_id=DEVICE)
    elif denial == "tool":
        context = SimpleNamespace(selection_offline=False, selected_device_id=DEVICE,
                                  selected_confirmed=True, tool_available=False,
                                  execution_device_id=DEVICE)
    else:
        context = SimpleNamespace(selection_offline=False, selected_device_id=DEVICE,
                                  selected_confirmed=True, tool_available=True,
                                  execution_device_id=DEVICE)

    async def selected_context(*args, **kwargs):
        return context

    async def grant(*args, **kwargs):
        return denial != "grant"

    dispatches = []

    async def dispatch(_request, **kwargs):
        dispatches.append(kwargs)
        return _response({"dispatch": {"dispatch_id": JOB_ID,
                                        "run_id": kwargs["run_id"],
                                        "device_id": DEVICE}})

    monkeypatch.setattr(execution, "resolve_pc_work_context", selected_context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(shell, "_dispatch_command", dispatch)
    principal = {"owner_id": UID, "device_id": DEVICE, "token_id": TOKEN}
    if denial == "selection":
        result = asyncio.run(execution.execute_mcp_pc_tool(
            request, principal, "pc_shell_start", {"command": "Get-Date"},
        ))
        assert result == {"status": "unavailable", "code": "pc_offline",
                          "answer": "선택한 PC가 꺼져 있음"}
    else:
        with pytest.raises(execution.ChatPCDriveError) as caught:
            asyncio.run(execution.execute_mcp_pc_tool(
                request, principal, "pc_shell_start", {"command": "Get-Date"},
            ))
        assert caught.value.code == "chat_pc_target_unavailable"
    assert not dispatches and not history.runs and not transport.calls


def test_shell_execution_uses_existing_owner_gates_and_bypasses_engine(monkeypatch):
    from app import mcp_gateway_execution as execution
    from test_mcp_gateway_execution import harness

    request, transport, history, calls = harness(monkeypatch)
    request.app.state.settings = SimpleNamespace(mcp_pc_shell_enabled=True)
    context = SimpleNamespace(selection_offline=False, selected_device_id=DEVICE,
                              selected_confirmed=True, tool_available=True,
                              execution_device_id=DEVICE)
    context_calls = []
    async def selected_context(*args, **kwargs):
        context_calls.append(kwargs)
        return context
    dispatches = []
    async def dispatch(_request, **kwargs):
        dispatches.append(kwargs)
        return _response({"dispatch": {"dispatch_id": JOB_ID,
                                        "run_id": kwargs["run_id"],
                                        "device_id": DEVICE}})
    monkeypatch.setattr(execution, "resolve_pc_work_context", selected_context)
    monkeypatch.setattr(shell, "_dispatch_command", dispatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, {"owner_id": UID, "device_id": DEVICE, "token_id": TOKEN},
        "pc_shell_start", {"command": "private-command-material"},
    ))
    assert result["status"] == "running" and result["job_id"] == JOB_ID
    assert result["_job_receipt"] == JOB_ID
    assert [call[0] for call in calls] == ["identity", "grant"]
    assert len(context_calls) == 1 and context_calls[0]["selected_device_id"] == DEVICE
    assert history.runs[0]["action"] == "pc_files_query"
    assert history.runs[0]["user_text"] == "외부 AI 도구 요청: pc_shell_start"
    assert len(dispatches) == 1 and dispatches[0]["device_id"] == DEVICE
    assert dispatches[0]["trusted_owner"][1] == UID
    assert "private-command-material" not in dispatches[0]["command"]
    assert not transport.calls


def test_audit_log_carries_numeric_metadata_without_command_or_output():
    from app.mcp_gateway_dispatch import _log_operation

    audit = {"tool_name": "pc_shell", "arguments": {"command": "secret-command"},
             "approval_id": None}
    outcome = {"run_id": "run_fixture", "status": "completed",
               "output": "secret-output", "audit": {
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


def test_shell_ignores_approval_receipts_and_never_creates_one():
    from app.mcp_gateway_dispatch import dispatch_mcp_tool

    class AuditStore:
        def __init__(self):
            self.records = []
        async def audit(self, **kwargs):
            self.records.append(kwargs)
        async def consume_approval(self, **kwargs):
            raise AssertionError("shell must not consume an approval")
        async def consume_matching_approval(self, **kwargs):
            raise AssertionError("shell must not look up an approval")
        async def create_approval(self, **kwargs):
            raise AssertionError("shell must not create an approval")

    store = AuditStore()
    async def executor(_request, _principal, _tool_name, _arguments, *, approval):
        assert approval is None
        return {"status": "running", "run_id": RUN_ID,
                "job_id": JOB_ID, "_job_receipt": JOB_ID}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        mcp_gateway_store=store, mcp_gateway_executor=executor,
        history_store=CommonHistory(),
    )))
    result = asyncio.run(dispatch_mcp_tool(
        request,
        {"owner_id": UID, "device_id": DEVICE, "token_id": TOKEN},
        "pc_shell_start", {"command": "private-command"},
        approval_id="mcpa_" + "a" * 32,
    ))
    assert result["status"] == "running" and result["job_id"] == JOB_ID
    assert [record["status"] for record in store.records] == ["requested", "running"]
    assert all(record["approval_id"] is None for record in store.records)
    assert store.records[-1]["job_receipt_id"] == JOB_ID




def test_the_shell_wait_poll_interval_grows_and_caps_at_five_seconds(monkeypatch):
    """대표 결정(2026-11-07): the shell wait polls start fast and grow
    (0.5 → 1 → 2 → 4, capped at 5 s) so a running PC job stops hammering the
    host while the wait window runs. The total wait window is unchanged."""
    history, receipts = CommonHistory(), ReceiptStore()
    request = _request(history, receipts)
    receipts.job_id = JOB_ID
    receipts.identity = {"user_id": UID, "device_id": DEVICE, "token_id": TOKEN}

    async def dispatch(_request, **kwargs):
        return _response({"dispatch": {"dispatch_id": JOB_ID, "run_id": RUN_ID,
                                        "device_id": DEVICE}})
    sleeps: list[float] = []

    async def recording_sleep(seconds):
        sleeps.append(seconds)

    clock = [0.0]

    def now():
        clock[0] += 0.5
        return clock[0]

    monkeypatch.setattr(shell, "_dispatch_command", dispatch)
    monkeypatch.setattr(shell, "_NOW", now)
    monkeypatch.setattr(shell.asyncio, "sleep", recording_sleep)

    result = asyncio.run(shell.execute_pc_shell(
        request, uid=UID, subject_id=SUBJECT, workspace_id="workspace", device_id=DEVICE,
        token_id=TOKEN, run_id=RUN_ID, session=SimpleNamespace(), conversation_id="conv_fixture",
        arguments={"command": "sleep", "cwd": None, "shell": "powershell", "wait_seconds": 30},
    ))

    assert result["status"] == "running"
    # The polls start fast and grow 2× up to the 5 s cap.
    assert sleeps[:4] == [0.5, 1.0, 2.0, 4.0]
    assert max(sleeps) <= 5.0


def test_the_shell_wait_ends_the_moment_the_job_finishes(monkeypatch):
    """결과가 도착하면 그 폴링에서 바로 돌아간다 — 추가 대기 없음."""
    history, receipts = CommonHistory(), ReceiptStore()
    request = _request(history, receipts)
    receipts.job_id = JOB_ID
    receipts.identity = {"user_id": UID, "device_id": DEVICE, "token_id": TOKEN}
    history.state = "done"
    history.exit_code = 0

    async def dispatch(_request, **kwargs):
        return _response({"dispatch": {"dispatch_id": JOB_ID, "run_id": RUN_ID,
                                        "device_id": DEVICE}})
    async def original(_request, *, uid, dispatch, run_row):
        return history.output
    sleeps: list[float] = []

    async def recording_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(shell, "_dispatch_command", dispatch)
    monkeypatch.setattr(shell, "_read_original", original)
    monkeypatch.setattr(shell.asyncio, "sleep", recording_sleep)

    result = asyncio.run(shell.execute_pc_shell(
        request, uid=UID, subject_id=SUBJECT, workspace_id="workspace", device_id=DEVICE,
        token_id=TOKEN, run_id=RUN_ID, session=SimpleNamespace(), conversation_id="conv_fixture",
        arguments={"command": "sleep", "cwd": None, "shell": "powershell", "wait_seconds": 30},
    ))

    assert result["status"] == "completed"
    assert sleeps == []
