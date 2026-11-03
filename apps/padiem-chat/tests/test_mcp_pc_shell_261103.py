"""pc_shell contract, wait-to-job handoff and Windows worker tests."""
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
OTHER = "usr_" + "b" * 32
DEVICE = "dev_" + "c" * 32
OTHER_DEVICE = "dev_" + "d" * 32
PRINCIPAL = {"owner_id": UID, "device_id": DEVICE, "token_id": "mcp_" + "e" * 32}
# history mints dsp_<32hex>; oracle_mesh_cmd_* is a command id, never a dispatch id.
DISPATCH_ID = "dsp_" + "b" * 32
JOB_ID = "mcpjob_" + "f" * 32


class Jobs:
    """The same closed job lifecycle D1McpGatewayStore implements."""

    def __init__(self):
        self.rows = {}
        self.created = []

    async def create_shell_job(self, *, identity, job_id, run_id, command_sha256, shell,
                               now=None):
        self.created.append({"job_id": job_id, "identity": identity, "run_id": run_id,
                             "command_sha256": command_sha256})
        self.rows[job_id] = {"id": job_id, "user_id": identity["user_id"],
                             "token_id": identity["token_id"], "device_id": identity["device_id"],
                             "run_id": run_id, "dispatch_id": None,
                             "command_sha256": command_sha256, "shell": shell, "state": "queued",
                             "exit_code": None, "created_at": "t", "updated_at": "t",
                             "finished_at": None}
        return dict(self.rows[job_id])

    async def attach_shell_job_dispatch(self, *, user_id, job_id, dispatch_id, now=None):
        row = self.rows.get(job_id)
        if row is None or row["user_id"] != user_id or row["dispatch_id"] is not None:
            return False
        row["dispatch_id"] = dispatch_id
        return True

    async def get_shell_job(self, *, user_id, job_id):
        row = self.rows.get(job_id)
        return dict(row) if isinstance(row, dict) and row["user_id"] == user_id else None

    async def finish_shell_job(self, *, user_id, job_id, state, exit_code=None, now=None):
        row = self.rows.get(job_id)
        if row is None or row["user_id"] != user_id:
            return None
        if state != "queued" and row["state"] in ("exited", "cancelled", "lost"):
            return dict(row)
        row["state"] = state
        row["exit_code"] = exit_code
        return dict(row)


class Presence:
    def __init__(self, rows):
        self.rows = rows

    def load(self, *, device_id):
        return self.rows.get(device_id)


def _request(jobs=None, presence=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        mcp_gateway_store=jobs, mesh_device_presence_store=presence)))


def _envelope(**overrides):
    data = {
        "job_id": JOB_ID,
        "state": "exited",
        "exit_code": 0,
        "elapsed_ms": 25,
        "stdout": "ok\n",
        "stderr": "",
        "stdout_bytes": 3,
        "stderr_bytes": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_next_offset": 3,
        "stderr_next_offset": 0,
        "duration_ms": 25,
    }
    data.update(overrides)
    return data


def _read_envelope(**overrides):
    data = {"job_id": JOB_ID, "state": "running", "exit_code": None, "elapsed_ms": 5_000,
            "stream": "stdout", "output": "chunk", "output_bytes": 5, "total_bytes": 5,
            "next_offset": 5, "eof": True, "large": False, "duration_ms": 12}
    data.update(overrides)
    return data


def _stop_envelope(**overrides):
    data = {"job_id": JOB_ID, "state": "cancelled", "exit_code": None, "elapsed_ms": 9_000,
            "killed": True, "duration_ms": 14}
    data.update(overrides)
    return data


def _response(payload, status=200):
    return SimpleNamespace(status_code=status, body=json.dumps(payload).encode())


def _install(monkeypatch, *, envelopes=None, state="done", row_state=None, cancellation=None,
             termination="exited"):
    """Fake the command lane: dispatch, dispatch-row poll, original read, cancel."""
    envelopes = list(envelopes if envelopes is not None else [_envelope()])
    seen = {"commands": [], "cancel": 0, "dispatches": 0}

    async def dispatch(request, **kwargs):
        seen["commands"].append(kwargs)
        seen["dispatches"] += 1
        return _response({"ok": True, "dispatch": {"dispatch_id": DISPATCH_ID}})

    async def row(request, **kwargs):
        return {"state": row_state or state, "termination": termination, "command_id": "cmd_1",
                "revision_ref": "rev_1", "result_sha256": "0" * 64, "result_bytes": 1}

    async def original(request, **kwargs):
        payload = envelopes[0] if len(envelopes) == 1 else envelopes.pop(0)
        raw = json.dumps(payload, ensure_ascii=False).encode()
        return raw, hashlib.sha256(raw).hexdigest()

    async def cancel(request, **kwargs):
        seen["cancel"] += 1
        return 1

    monkeypatch.setattr(shell, "_dispatch_command", dispatch)
    monkeypatch.setattr(shell, "_dispatch_row", row)
    monkeypatch.setattr(shell, "_read_original", original)
    monkeypatch.setattr(shell, "_cancel_run", cancel)
    monkeypatch.setattr(shell, "new_shell_job_id", lambda: JOB_ID)
    monkeypatch.setattr(shell, "PC_SHELL_POLL_SECONDS", 0)
    return seen


def _execute(tool="pc_shell", arguments=None, *, jobs=None, presence=None, request=None):
    if isinstance(tool, dict):
        tool, arguments = "pc_shell", tool
    jobs = jobs if jobs is not None else Jobs()
    request = request or _request(jobs, presence)
    executor = {
        "pc_shell": shell.execute_pc_shell,
        "pc_shell_start": shell.execute_pc_shell_start,
        "pc_shell_read": shell.execute_pc_shell_read,
        "pc_shell_stop": shell.execute_pc_shell_stop,
    }[tool]
    result = asyncio.run(executor(
        request, session=SimpleNamespace(), uid=UID, workspace_id="workspace_fixture",
        device_id=DEVICE, token_id=PRINCIPAL["token_id"], run_id="run_fixture",
        conversation_id="chat_fixture",
        arguments=arguments if arguments is not None else {"command": "echo ok"},
    ))
    return result, jobs


def test_schema_accepts_only_bounded_known_values():
    assert shell.validate_pc_shell_arguments({"command": "git status"})
    assert shell.normalize_pc_shell_arguments({"command": "git status"}) == {
        "command": "git status", "cwd": None, "shell": "powershell", "wait_seconds": 120,
    }
    assert shell.normalize_pc_shell_arguments({
        "command": "git status", "cwd": "C:/work", "shell": "cmd", "wait_seconds": 600,
    })["wait_seconds"] == 600
    assert shell.normalize_pc_shell_start_arguments({"command": "build"}) == {
        "command": "build", "cwd": None, "shell": "powershell",
    }
    assert shell.normalize_pc_shell_read_arguments({"job_id": JOB_ID}) == {
        "job_id": JOB_ID, "offset": 0, "length": shell.PC_SHELL_READ_DEFAULT_BYTES,
        "stream": "stdout",
    }
    assert shell.normalize_pc_shell_stop_arguments({"job_id": JOB_ID}) == {"job_id": JOB_ID}
    for bad in (
        {}, {"command": ""}, {"command": "x", "shell": "zsh"},
        {"command": "x", "wait_seconds": 0}, {"command": "x", "wait_seconds": 601},
        {"command": "x", "wait_seconds": True}, {"command": "x", "timeout_seconds": 30},
        {"command": "x", "cwd": "bad\x01path"}, {"command": "x", "device_id": DEVICE},
        {"command": "x", "extra": "value"}, {"command": "x" * (shell.PC_SHELL_MAX_COMMAND_CHARS + 1)},
    ):
        assert not shell.validate_pc_shell_arguments(bad)
    for name, bad in (
        ("pc_shell_start", {"command": "x", "wait_seconds": 5}),
        ("pc_shell_start", {"shell": "cmd"}),
        ("pc_shell_read", {"job_id": "mcpjob_short"}),
        ("pc_shell_read", {"job_id": JOB_ID, "offset": -1}),
        ("pc_shell_read", {"job_id": JOB_ID, "length": shell.PC_SHELL_READ_MAX_BYTES + 1}),
        ("pc_shell_read", {"job_id": JOB_ID, "stream": "both"}),
        ("pc_shell_read", {"job_id": JOB_ID, "device_id": DEVICE}),
        ("pc_shell_stop", {"job_id": "mcpjob_" + "0" * 31 + "Z"}),
        ("pc_shell_stop", {"job_id": JOB_ID, "force": True}),
    ):
        assert not shell.validate_shell_tool_arguments(name, bad)


def test_dispatch_commands_never_carry_the_raw_command():
    command = "Write-Output 'secret-value'; exit 0"
    built = shell.build_pc_shell_command(
        {"command": command, "cwd": r"C:\work", "shell": "powershell", "wait_seconds": 30},
        job_id=JOB_ID)
    assert "\n" not in built and "\r" not in built
    assert "secret-value" not in built
    assert "PADIEM_PC_SHELL_MODE='run'" in built
    assert "PADIEM_PC_SHELL_JOB_ID='" + JOB_ID in built
    assert "PADIEM_PC_SHELL_COMMAND_B64" in built
    assert "PADIEM_PC_SHELL_WAIT_MS='30000'" in built
    start = shell.build_pc_shell_start_command({"command": command}, job_id=JOB_ID)
    assert "PADIEM_PC_SHELL_WAIT_MS='0'" in start
    longest = shell.build_pc_shell_command(
        {"command": "x" * shell.PC_SHELL_MAX_COMMAND_CHARS}, job_id=JOB_ID)
    assert len(longest) < 120_000
    read = shell.build_pc_shell_read_command(
        {"job_id": JOB_ID, "offset": 4096, "length": 1024, "stream": "stderr"})
    assert "PADIEM_PC_SHELL_MODE='read'" in read and "PADIEM_PC_SHELL_OFFSET='4096'" in read
    assert "PADIEM_PC_SHELL_STREAM='stderr'" in read and "exit 0" not in read
    stop = shell.build_pc_shell_stop_command({"job_id": JOB_ID})
    assert "PADIEM_PC_SHELL_MODE='stop'" in stop and "COMMAND_B64" not in stop


def test_result_parsers_accept_bounded_worker_json_only():
    assert shell.parse_pc_shell_result(json.dumps(_envelope()))["stdout"] == "ok\n"
    assert shell.parse_pc_shell_output_result(json.dumps(_read_envelope()))["next_offset"] == 5
    assert shell.parse_pc_shell_stop_result(json.dumps(_stop_envelope()))["killed"] is True
    for bad in (
        {}, {"exit_code": True}, {"stdout": 1}, _envelope(stdout_bytes=-1),
        _envelope(stdout_truncated="no"), _envelope(state="paused"),
        _envelope(error="not_a_worker_code"), _envelope(job_id="mcpjob_short"),
    ):
        with pytest.raises((ValueError, TypeError)):
            shell.parse_pc_shell_result(json.dumps(bad))
    for bad in (
        {}, _read_envelope(stream="both"), _read_envelope(next_offset=-1),
        _read_envelope(eof="no"), _read_envelope(job_id="x"),
    ):
        with pytest.raises((ValueError, TypeError)):
            shell.parse_pc_shell_output_result(json.dumps(bad))
    for bad in ({}, _stop_envelope(killed="no"), _stop_envelope(state="exited2")):
        with pytest.raises((ValueError, TypeError)):
            shell.parse_pc_shell_stop_result(json.dumps(bad))
    assert shell.parse_pc_shell_result(json.dumps(
        {"job_id": JOB_ID, "error": "cwd_invalid"}))["error"] == "cwd_invalid"


def test_real_dispatch_id_shape_is_accepted_and_a_command_id_is_not(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_envelope()])
    result, _jobs = _execute({"command": "echo ok"})
    assert result["status"] == "completed" and seen["dispatches"] == 1
    for foreign in ("oracle_mesh_cmd_" + "b" * 32, "dsp_short", "dsp_" + "Z" * 32):
        async def refuse(request, **kwargs):
            seen["commands"].append(kwargs)
            return _response({"ok": True, "dispatch": {"dispatch_id": foreign}})
        monkeypatch.setattr(shell, "_dispatch_command", refuse)
        failed, _ = _execute({"command": "echo ok"})
        assert failed["status"] == "failed" and failed["code"] == "pc_shell_dispatch_refused"


def test_completed_result_returns_streams_exit_code_and_numeric_audit(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_envelope(exit_code=7, stderr="warn\n", stderr_bytes=5)])
    result, jobs = _execute({"command": "echo ok"})
    assert result["status"] == "completed"
    assert result["exit_code"] == 7 and result["running"] is False
    assert result["stdout"] == "ok\n" and result["stderr"] == "warn\n"
    assert result["job_id"] == JOB_ID
    assert result["audit"] == {"exit_code": 7, "duration_ms": result["audit"]["duration_ms"],
                               "output_bytes": 8, "output_truncated": False}
    assert "command" not in result["audit"] and "stdout" not in result["audit"]
    command = seen["commands"][0]["command"]
    assert "echo ok" not in command and "PADIEM_PC_SHELL_COMMAND_B64" in command
    assert seen["commands"][0]["ttl_seconds"] == 180
    assert jobs.rows[JOB_ID]["state"] == "exited" and jobs.rows[JOB_ID]["exit_code"] == 7
    assert jobs.rows[JOB_ID]["dispatch_id"] == DISPATCH_ID
    assert jobs.rows[JOB_ID]["command_sha256"] == hashlib.sha256(b"echo ok").hexdigest()
    assert "echo ok".encode() not in json.dumps(jobs.rows[JOB_ID]).encode()


def test_truncated_result_is_reported_without_changing_the_exit_code(monkeypatch):
    _install(monkeypatch, envelopes=[_envelope(
        stdout="head\n...[중간 생략]...\ntail\n", stdout_bytes=30_000, stdout_truncated=True,
        stdout_next_offset=30_000)])
    result, _ = _execute({"command": "big"})
    assert result["status"] == "completed" and result["exit_code"] == 0
    assert result["truncated"] is True
    assert result["audit"]["output_truncated"] is True
    assert result["audit"]["output_bytes"] == 30_000


def test_worker_error_is_a_failed_result_with_its_code(monkeypatch):
    _install(monkeypatch, envelopes=[{"job_id": JOB_ID, "error": "cwd_invalid"}])
    result, jobs = _execute({"command": "echo ok", "cwd": "C:/missing"})
    assert result["status"] == "failed" and result["code"] == "pc_shell_cwd_invalid"
    assert result["audit"]["exit_code"] is None
    assert jobs.rows[JOB_ID]["state"] == "lost"


def test_wait_window_elapsed_hands_the_job_over_instead_of_failing(monkeypatch):
    # The worker waited its full window, the command is still running, and the
    # answer carries the job number plus the output produced so far.
    seen = _install(monkeypatch, envelopes=[_envelope(state="running", exit_code=None,
                                                      stdout="partial\n", stdout_bytes=8,
                                                      stdout_next_offset=8)])
    result, jobs = _execute({"command": "long build", "wait_seconds": 1})
    assert result["status"] == "completed"
    assert result["running"] is True and result["job_id"] == JOB_ID
    assert result["next_step"] == "pc_shell_read"
    assert result["stdout"] == "partial\n" and result["next_offset"] == 8
    assert "pc_shell_read" in result["answer"] and "실행 중" in result["answer"]
    # The command is never cancelled by a wait that merely elapsed.
    assert seen["cancel"] == 0
    assert jobs.rows[JOB_ID]["state"] == "running"


def test_dispatch_row_still_pending_handovers_as_queued(monkeypatch):
    _install(monkeypatch, envelopes=[_envelope()], row_state="pending")
    ticks = [0.0]

    def fake_now():
        ticks[0] += 10.0
        return ticks[0]

    monkeypatch.setattr(shell, "_NOW", fake_now)
    result, jobs = _execute({"command": "sleep", "wait_seconds": 1})
    assert result["status"] == "completed" and result["state"] == "queued"
    assert jobs.rows[JOB_ID]["state"] == "queued"


def test_offline_pc_refuses_a_waiting_call_without_dispatching(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_envelope()])
    presence = Presence({DEVICE: {"connected": False,
                                  "received_at": "2026-11-03T00:00:00.000Z"}})
    result, jobs = _execute({"command": "echo ok"}, presence=presence)
    assert result["status"] == "failed" and result["code"] == "pc_shell_pc_offline"
    assert seen["commands"] == [] and jobs.rows == {}


@pytest.mark.parametrize("row,expected", [
    ({"connected": True, "received_at": "FRESH"}, True),
    ({"connected": True, "received_at": "STALE"}, False),
    ({"connected": False, "received_at": "FRESH"}, False),
    ({"connected": True, "received_at": "not-a-stamp"}, False),
])
def test_fresh_mesh_beat_is_live_and_a_stale_one_is_not(monkeypatch, row, expected):
    from datetime import datetime, timedelta, timezone
    _install(monkeypatch, envelopes=[_envelope()])
    now = datetime.now(timezone.utc)
    stamps = {
        "FRESH": (now - timedelta(seconds=30)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "STALE": (now - timedelta(seconds=shell.PC_SHELL_PRESENCE_MAX_AGE_SECONDS + 30))
        .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    row = dict(row, received_at=stamps.get(row["received_at"], row["received_at"]))
    assert asyncio.run(shell._pc_lane_is_live(
        _request(Jobs(), Presence({DEVICE: row})), DEVICE)) is expected
    # A lane with no presence store cannot say: the call is not refused for it.
    assert asyncio.run(shell._pc_lane_is_live(_request(Jobs(), None), DEVICE)) is None


def test_start_returns_the_job_number_without_waiting_for_the_command(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_envelope(state="running", exit_code=None,
                                                      stdout="", stdout_bytes=0,
                                                      stdout_next_offset=0)])
    result, jobs = _execute("pc_shell_start", {"command": "python -m http.server"})
    assert result["status"] == "completed" and result["job_id"] == JOB_ID
    assert result["running"] is True and result["exit_code"] is None
    assert "pc_shell_read" in result["answer"]
    assert seen["commands"][0]["ttl_seconds"] == shell.PC_SHELL_START_TTL_SECONDS
    assert jobs.rows[JOB_ID]["state"] == "running"


def test_start_is_queued_rather_than_refused_while_the_pc_is_away(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_envelope()], row_state="pending")
    ticks = [0.0]

    def fake_now():
        ticks[0] += 10.0
        return ticks[0]

    monkeypatch.setattr(shell, "_NOW", fake_now)
    away = Presence({DEVICE: {"connected": False, "received_at": "2026-11-03T00:00:00.000Z"}})
    result, jobs = _execute("pc_shell_start", {"command": "python -m http.server"},
                            presence=away)
    assert result["status"] == "completed" and result["state"] == "queued"
    assert result["running"] is True and result["next_step"] == "pc_shell_read"
    assert seen["commands"][0]["ttl_seconds"] == shell.PC_SHELL_START_TTL_SECONDS
    assert jobs.rows[JOB_ID]["dispatch_id"] == DISPATCH_ID


def _seed(jobs, *, job_id=JOB_ID, device_id=DEVICE, state="running", run_id="run_fixture"):
    """Put one job row through the same staged -> dispatched -> running path."""
    async def scenario():
        await jobs.create_shell_job(identity={"user_id": UID, "device_id": device_id,
                                              "token_id": PRINCIPAL["token_id"]},
                                    job_id=job_id, run_id=run_id,
                                    command_sha256="0" * 64, shell="powershell")
        await jobs.attach_shell_job_dispatch(user_id=UID, job_id=job_id, dispatch_id=DISPATCH_ID)
        if state != "queued":
            await jobs.finish_shell_job(user_id=UID, job_id=job_id, state=state)

    asyncio.run(scenario())
    return jobs


def test_read_follows_the_offset_cursor_and_reports_the_exit_code(monkeypatch):
    jobs = _seed(Jobs())
    _install(monkeypatch, envelopes=[
        _read_envelope(output="first", output_bytes=5, total_bytes=12, next_offset=5, eof=False),
        _read_envelope(output="second", output_bytes=6, total_bytes=12, next_offset=11, eof=False),
        _read_envelope(output="third", output_bytes=1, total_bytes=12, next_offset=12, eof=True),
        _read_envelope(state="exited", exit_code=3, output="", output_bytes=0, total_bytes=12,
                       next_offset=12, eof=True, elapsed_ms=90_000),
    ])
    offset = 0
    collected = ""
    for expected_eof in (False, False, True, True):
        result, _ = _execute("pc_shell_read", {"job_id": JOB_ID, "offset": offset, "length": 8},
                             jobs=jobs)
        assert result["status"] == "completed" and result["eof"] is expected_eof
        collected += result["output"]
        offset = result["next_offset"]
    assert collected == "firstsecondthird" and offset == 12
    assert result["state"] == "exited" and result["exit_code"] == 3
    assert "1분" in result["answer"]
    assert jobs.rows[JOB_ID]["state"] == "exited" and jobs.rows[JOB_ID]["exit_code"] == 3


def test_read_is_owner_and_device_scoped(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_read_envelope()])
    jobs = Jobs()

    async def foreign_owner():
        await jobs.create_shell_job(identity={"user_id": OTHER, "device_id": DEVICE,
                                              "token_id": PRINCIPAL["token_id"]},
                                    job_id=JOB_ID, run_id="run_other",
                                    command_sha256="0" * 64, shell="powershell")

    asyncio.run(foreign_owner())
    denied, _ = _execute("pc_shell_read", {"job_id": JOB_ID}, jobs=jobs)
    assert denied["status"] == "failed" and denied["code"] == "pc_shell_job_not_found"
    assert seen["commands"] == []

    other_pc = _seed(Jobs(), device_id=OTHER_DEVICE)
    refused, _ = _execute("pc_shell_read", {"job_id": JOB_ID}, jobs=other_pc)
    assert refused["status"] == "failed" and refused["code"] == "pc_shell_job_not_found"
    assert seen["commands"] == []
    stopped, _ = _execute("pc_shell_stop", {"job_id": JOB_ID}, jobs=other_pc)
    assert stopped["status"] == "failed" and stopped["code"] == "pc_shell_job_not_found"
    assert seen["commands"] == []


def test_read_of_an_unknown_job_id_shape_never_dispatches(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_read_envelope()])
    with pytest.raises(ValueError):
        _execute("pc_shell_read", {"job_id": "mcpjob_" + "0" * 31 + "Z"})
    assert seen["commands"] == []


def test_read_while_the_pc_is_away_answers_from_the_durable_row(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_read_envelope()])
    jobs = _seed(Jobs(), state="queued")
    away = Presence({DEVICE: {"connected": False, "received_at": "2026-11-03T00:00:00.000Z"}})
    result, _ = _execute("pc_shell_read", {"job_id": JOB_ID, "offset": 4096}, jobs=jobs,
                         presence=away)
    assert result["status"] == "completed" and result["state"] == "queued"
    assert result["next_offset"] == 4096 and result["output"] == ""
    assert seen["commands"] == []


def test_stop_kills_the_process_tree_and_marks_the_job(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_stop_envelope()])
    jobs = _seed(Jobs())
    result, jobs = _execute("pc_shell_stop", {"job_id": JOB_ID}, jobs=jobs)
    assert result["status"] == "completed" and result["killed"] is True
    assert result["state"] == "cancelled" and "중지했습니다" in result["answer"]
    # The mode travels; the worker's own taskkill text stays inside the encoded script.
    assert "taskkill" not in seen["commands"][0]["command"]
    assert "PADIEM_PC_SHELL_MODE='stop'" in seen["commands"][0]["command"]
    assert jobs.rows[JOB_ID]["state"] == "cancelled"


def test_stop_cancels_a_queued_job_while_the_pc_is_away(monkeypatch):
    seen = _install(monkeypatch, envelopes=[_stop_envelope()], row_state="pending")
    jobs = _seed(Jobs(), state="queued")
    away = Presence({DEVICE: {"connected": False, "received_at": "2026-11-03T00:00:00.000Z"}})
    result, _ = _execute("pc_shell_stop", {"job_id": JOB_ID}, jobs=jobs, presence=away)
    assert result["status"] == "completed" and result["state"] == "cancelled"
    assert seen["commands"] == [] and seen["cancel"] == 1
    assert jobs.rows[JOB_ID]["state"] == "cancelled"


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
                                     "shell": "powershell", "wait_seconds": 120}
    assert captured["device_id"] == DEVICE and captured["token_id"] == PRINCIPAL["token_id"]


def test_read_poll_does_not_append_a_conversation_notice(monkeypatch):
    from test_mcp_gateway_execution import harness

    request, _transport, history, calls = harness(monkeypatch)

    async def fake_read(request, **kwargs):
        return {"status": "completed", "answer": "PC에서 실행 중입니다.", "state": "running",
                "output": "x", "audit": {"exit_code": None, "duration_ms": 1,
                                          "output_bytes": 1, "output_truncated": False}}

    monkeypatch.setattr(execution, "execute_pc_shell_read", fake_read)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_shell_read", {"job_id": JOB_ID},
    ))
    assert result["status"] == "completed"
    assert [name for name, _ in calls if name == "notice"] == []


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

    for name, arguments in (("pc_shell", {"command": "echo ok"}),
                            ("pc_shell_start", {"command": "echo ok"}),
                            ("pc_shell_read", {"job_id": JOB_ID}),
                            ("pc_shell_stop", {"job_id": JOB_ID})):
        monkeypatch.setattr(execution, "execute_" + name, fake_shell)
        with pytest.raises(execution.ChatPCDriveError) as caught:
            asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, name, arguments))
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
        for name, arguments in (("pc_shell_start", {"command": "secret-command"}),
                                ("pc_shell_read", {"job_id": "mcpjob_" + "a" * 32, "offset": 0}),
                                ("pc_shell_stop", {"job_id": "mcpjob_" + "a" * 32})):
            await store.audit(
                identity={"user_id": owner, "device_id": MCP_DEVICE, "token_id": token["id"]},
                tool_name=name, arguments=arguments,
                status="completed", exit_code=0, duration_ms=12, output_bytes=5,
                output_truncated=False,
            )

    asyncio.run(scenario())
    rows = [dict(row) for row in db.conn.execute("SELECT * FROM padiem_mcp_audit")]
    assert len(rows) == 3
    assert "secret-command" not in json.dumps(rows, ensure_ascii=False)
    for row in rows:
        assert row["exit_code"] == 0 and row["duration_ms"] == 12
        assert row["output_bytes"] == 5 and row["output_truncated"] == 0
        assert len(row["request_digest"]) == 64


def test_job_rows_are_durable_and_owner_scoped_in_sqlite():
    from test_mcp_gateway_account import DEVICE as MCP_DEVICE, issued, setup

    db, owner, other, store = setup()
    token, _identity = asyncio.run(issued(store, owner))
    job_id = "mcpjob_" + "a" * 32

    async def scenario():
        created = await store.create_shell_job(
            identity={"user_id": owner, "device_id": MCP_DEVICE, "token_id": token["id"]},
            job_id=job_id, run_id="run_fixture",
            command_sha256=hashlib.sha256(b"secret-command").hexdigest(), shell="powershell")
        assert created["state"] == "queued" and created["dispatch_id"] is None
        assert await store.attach_shell_job_dispatch(user_id=owner, job_id=job_id,
                                                     dispatch_id=DISPATCH_ID) is True
        assert await store.attach_shell_job_dispatch(user_id=owner, job_id=job_id,
                                                     dispatch_id="dsp_" + "9" * 32) is False
        assert await store.get_shell_job(user_id=other, job_id=job_id) is None
        assert await store.get_shell_job(user_id=owner, job_id="mcpjob_" + "b" * 32) is None
        finished = await store.finish_shell_job(user_id=owner, job_id=job_id, state="exited",
                                                exit_code=4)
        assert finished["state"] == "exited" and finished["exit_code"] == 4
        reopened = await store.finish_shell_job(user_id=owner, job_id=job_id, state="running")
        assert reopened["state"] == "exited"
        return finished

    finished = asyncio.run(scenario())
    row = dict(db.conn.execute("SELECT * FROM padiem_mcp_shell_jobs").fetchone())
    assert "secret-command" not in json.dumps(row, ensure_ascii=False)
    assert row["state"] == "exited" and row["exit_code"] == 4
    assert row["device_id"] == MCP_DEVICE and row["token_id"] == token["id"]
    assert row["dispatch_id"] == DISPATCH_ID
    assert finished["run_id"] == "run_fixture"


def test_shell_job_ids_are_random_and_bounded():
    values = {shell.new_shell_job_id() for _ in range(50)}
    assert len(values) == 50
    for value in values:
        assert value.startswith("mcpjob_") and len(value) == len("mcpjob_") + 32
        assert shell._JOB_ID.fullmatch(value) is not None


def _run_worker(built, timeout=60, *, job_dir=None):
    environment = dict(os.environ)
    if job_dir is not None:
        environment["LOCALAPPDATA"] = str(job_dir)
    wrapped = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; & { " + built
               + " } 2>&1 | Out-String")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", wrapped],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        env=environment,
    )
    text = completed.stdout
    start, end = text.find("{"), text.rfind("}")
    assert start >= 0 and end > start, completed.stdout + completed.stderr
    return json.loads(text[start:end + 1])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows worker test")
def test_windows_worker_returns_exit_code_streams_cwd_and_truncation(tmp_path):
    built = shell.build_pc_shell_command(
        {"command": "Write-Output 'hello'; Write-Error 'bad'; exit 3", "cwd": None,
         "shell": "powershell", "wait_seconds": 30}, job_id=JOB_ID)
    result = _run_worker(built, job_dir=tmp_path)
    assert result["state"] == "exited" and result["exit_code"] == 3
    assert "hello" in result["stdout"]
    # PowerShell wraps long error records at the console width, so the check is
    # that stderr arrived on its own: bytes present and none of stdout's text.
    assert result["stderr_bytes"] > 0 and "hello" not in result["stderr"]
    assert result["job_id"] == JOB_ID and result["elapsed_ms"] >= 0

    cwd_command = shell.build_pc_shell_command(
        {"command": "(Get-Location).Path", "cwd": os.environ.get("WINDIR", r"C:\Windows"),
         "shell": "powershell", "wait_seconds": 30}, job_id="mcpjob_" + "1" * 32)
    inside = _run_worker(cwd_command, job_dir=tmp_path)
    assert "Windows" in inside["stdout"]

    big = shell.build_pc_shell_command(
        {"command": "$s = 'a' * 20000; Write-Output $s", "cwd": None, "shell": "powershell",
         "wait_seconds": 30}, job_id="mcpjob_" + "2" * 32)
    cut = _run_worker(big, job_dir=tmp_path)
    assert cut["stdout_truncated"] is True and cut["stdout_bytes"] >= 20_000
    assert shell.PC_SHELL_TRUNCATION_MARKER.strip() in cut["stdout"]

    bad = shell.build_pc_shell_command(
        {"command": "Write-Output x", "cwd": r"C:\does-not-exist-261103", "shell": "powershell",
         "wait_seconds": 30}, job_id="mcpjob_" + "3" * 32)
    assert _run_worker(bad, job_dir=tmp_path)["error"] == "cwd_invalid"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows worker test")
def test_windows_job_survives_the_worker_and_reads_by_offset(tmp_path):
    import time as _time
    job_id = "mcpjob_" + "4" * 32
    start = shell.build_pc_shell_start_command(
        {"command": "1..6 | ForEach-Object { Write-Output ('line' + $_ + 'x'); "
                    "Start-Sleep -Milliseconds 250 }",
         "cwd": None, "shell": "powershell"}, job_id=job_id)
    launched = _run_worker(start, job_dir=tmp_path)
    assert launched["state"] == "running" and launched["exit_code"] is None
    # The worker that produced this answer has already ended; the detached child
    # has not, and its output file keeps growing while the caller polls.
    collected = ""
    offset = 0
    deadline = _time.monotonic() + 40
    while _time.monotonic() < deadline:
        page = _run_worker(shell.build_pc_shell_read_command(
            {"job_id": job_id, "offset": offset, "length": 64, "stream": "stdout"}),
            job_dir=tmp_path)
        assert page["next_offset"] == offset + page["output_bytes"]
        collected += page["output"]
        offset = page["next_offset"]
        if page["state"] == "exited" and page["eof"]:
            break
        _time.sleep(0.2)
    assert page["state"] == "exited" and page["exit_code"] == 0
    lines = [line for line in collected.replace("\r\n", "\n").split("\n") if line]
    assert lines == ["line%dx" % number for number in range(1, 7)]
    assert collected.endswith("\n") or collected.endswith("\r\n")
    after = _run_worker(shell.build_pc_shell_read_command(
        {"job_id": job_id, "offset": offset, "length": 4, "stream": "stdout"}), job_dir=tmp_path)
    assert after["output"] == "" and after["eof"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows worker test")
def test_windows_stop_ends_the_process_tree(tmp_path):
    job_id = "mcpjob_" + "5" * 32
    started = _run_worker(shell.build_pc_shell_start_command(
        {"command": "Start-Sleep -Seconds 60", "cwd": None, "shell": "powershell"},
        job_id=job_id), job_dir=tmp_path)
    assert started["state"] == "running"
    meta = json.loads((tmp_path / "padiem-mcp-jobs" / (job_id + ".meta")).read_text(encoding="utf-8"))
    stopped = _run_worker(shell.build_pc_shell_stop_command({"job_id": job_id}),
                          job_dir=tmp_path)
    assert stopped["killed"] is True and stopped["state"] == "cancelled"
    listing = subprocess.run(["tasklist.exe", "/FI", "PID eq " + str(meta["pid"]), "/NH"],
                             capture_output=True, text=True, timeout=30)
    assert str(meta["pid"]) not in listing.stdout
    again = _run_worker(shell.build_pc_shell_read_command(
        {"job_id": job_id, "offset": 0, "length": 64, "stream": "stdout"}), job_dir=tmp_path)
    assert again["state"] == "cancelled"


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("cmd.exe"),
                    reason="cmd worker test")
def test_windows_worker_cmd_shell_and_exit_codes(tmp_path):
    built = shell.build_pc_shell_command(
        {"command": "echo hello & echo bad 1>&2 & exit /b 2", "cwd": None, "shell": "cmd",
         "wait_seconds": 30}, job_id="mcpjob_" + "6" * 32)
    result = _run_worker(built, job_dir=tmp_path)
    assert result["exit_code"] == 2 and "hello" in result["stdout"]
    assert "bad" in result["stderr"]


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("bash.exe"),
                    reason="bash worker test")
def test_windows_worker_bash_shell(tmp_path):
    built = shell.build_pc_shell_command(
        {"command": "echo hello; echo bad >&2; exit 4", "cwd": None, "shell": "bash",
         "wait_seconds": 30}, job_id="mcpjob_" + "7" * 32)
    result = _run_worker(built, job_dir=tmp_path)
    assert result["exit_code"] == 4 and "hello" in result["stdout"]
    assert "bad" in result["stderr"]


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("bash.exe"),
                    reason="bash worker test")
def test_windows_worker_rejects_a_malformed_job_id(tmp_path):
    built = shell._dispatch_line("read", job_id="mcpjob_not-hex", values={})
    assert _run_worker(built, job_dir=tmp_path)["error"] == "job_id_invalid"
