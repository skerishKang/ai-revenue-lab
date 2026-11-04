"""2026-11-04 — a PC file step answers with a job id instead of holding the call.

A folder listing on the real PC costs more than an MCP client will wait, and the
cost tracks the bytes the console has to carry, not the command itself. So the
first answer waits a bounded time, then hands the dispatch back; the same tool
continues it by that id. Nothing here ends the PC command, and a continuation
never stages a second dispatch.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_FILES_WAIT_ENV,
    PC_LIST_FILES_TOOL_ID,
    PC_READ_FILE_TOOL_ID,
    PC_WRITE_FILE_TOOL_ID,
    _make_pc_file_handler,
    _pc_files_wait_seconds,
)
from padiem_ai_core.tool_runtime import ToolHandlerError

RUN_ID = "run_261104_early"
SUBJECT = "sub_" + "6" * 32
PRODUCT = "padiem-chat"
DEVICE = "pc-com2"
DISPATCH_ID = "dsp_" + "a" * 32
LIST_OUTPUT = (
    "[{\"Name\":\"notes\",\"Length\":null,"
    "\"LastWriteTimeUtc\":\"2026-11-04T09:00:00Z\",\"PSIsContainer\":true}]"
)


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, PRODUCT, DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


async def _no_sleep(_seconds: float) -> None:
    return None


def _install(monkeypatch, *, state: str = "done", file_path: str | None = None) -> list[str]:
    modes: list[str] = []

    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        modes.append(mode)
        if mode == "dispatch":
            return {"dispatch": {"run_id": RUN_ID, "kind": "command",
                                 "dispatch_id": DISPATCH_ID}}
        if mode == "command_status":
            row = {"dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                   "kind": "command", "state": state,
                   "termination": "no_exit_code", "exit_code": None}
            if file_path is not None:
                row["file_path"] = file_path
            return {"dispatch": row}
        if mode == "result":
            encoded = LIST_OUTPUT.encode("utf-8")
            return {"dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": RUN_ID, "kind": "command",
                "output": LIST_OUTPUT,
                "result_sha256": "b" * 64, "content_sha256": "b" * 64,
                "content_bytes": len(encoded),
                "termination": "no_exit_code", "exit_code": None,
            }}
        raise AssertionError("unexpected mode " + str(mode))

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    return modes


def _handler(op: str, tool_id: str):
    return _make_pc_file_handler(
        tool_id=tool_id, op=op, service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
    )


def test_list_hands_the_job_id_back_when_the_pc_is_still_working(monkeypatch):
    modes = _install(monkeypatch, state="pending")
    monkeypatch.setattr(driver, "_pc_files_wait_seconds", lambda: 0.0)

    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    assert result["status"] == "running"
    assert result["job_id"] == DISPATCH_ID
    # The receipt is what makes the next call provably the same caller's work.
    assert result["_job_receipt"] == DISPATCH_ID
    assert result["resume"] == {"tool": PC_LIST_FILES_TOOL_ID,
                                "argument": "job_id", "job_id": DISPATCH_ID}
    assert "결과" in result["answer"]
    # The work stays staged: the executor is never cancelled from here.
    assert modes == ["dispatch", "command_status"]


def test_list_still_answers_with_the_result_inside_the_wait(monkeypatch):
    modes = _install(monkeypatch)

    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    assert "status" not in result
    listed = result["output"]
    assert listed["ok"] is True
    assert result["entry_count"] == 1
    assert modes == ["dispatch", "command_status", "result"]


def test_continuation_reads_the_same_dispatch_without_staging(monkeypatch):
    modes = _install(monkeypatch, file_path="docs")
    monkeypatch.setattr(driver, "_pc_files_wait_seconds", lambda: 0.0)

    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"job_id": DISPATCH_ID}))

    # Exactly one dispatch exists in the whole exchange, and this call made none.
    assert modes == ["command_status", "result"]
    listed = result["output"]
    # The projection uses the folder the dispatch names, as the first call would.
    assert listed["path"] == "docs"
    assert result["entry_count"] == 1


def test_continuation_of_a_read_keeps_the_read_lane(monkeypatch):
    modes = _install(monkeypatch, file_path="notes.txt")

    async def fake_call(**kwargs):
        return await _install_result(kwargs, modes)

    async def _install_result(kwargs, modes):
        mode = kwargs["mode"]
        modes.append(mode)
        if mode == "command_status":
            return {"dispatch": {"dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                                 "kind": "read", "state": "done",
                                 "file_path": "notes.txt"}}
        if mode == "result":
            body = "hello"
            encoded = body.encode("utf-8")
            return {"dispatch": {"dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                                 "kind": "read", "output": body,
                                 "result_sha256": "c" * 64, "content_sha256": "c" * 64,
                                 "content_bytes": len(encoded),
                                 "termination": "exited", "exit_code": 0}}
        raise AssertionError("unexpected mode " + str(mode))

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    result = asyncio.run(_handler("read", PC_READ_FILE_TOOL_ID)({"job_id": DISPATCH_ID}))

    assert modes == ["command_status", "result"]
    assert result["content"] == "hello"
    assert result["execution_confirmed"] is True


def test_a_mutation_may_not_continue_by_job_id(monkeypatch):
    modes = _install(monkeypatch)
    with pytest.raises(ToolHandlerError):
        asyncio.run(_handler("write", PC_WRITE_FILE_TOOL_ID)({"job_id": DISPATCH_ID}))
    assert modes == []


@pytest.mark.parametrize("arguments", [
    {"job_id": "dsp_short"},
    {"job_id": ""},
    {"job_id": DISPATCH_ID, "path": "."},
    {"job_id": 7},
])
def test_a_malformed_continuation_is_refused(monkeypatch, arguments):
    modes = _install(monkeypatch)
    with pytest.raises(ToolHandlerError):
        asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)(arguments))
    assert modes == []


def test_the_first_wait_is_settable_and_bounded(monkeypatch):
    monkeypatch.delenv(PC_FILES_WAIT_ENV, raising=False)
    assert _pc_files_wait_seconds() == 20.0
    for raw, expected in (("5", 5.0), ("0", 1.0), ("999", 120.0), ("abc", 20.0), ("", 20.0)):
        monkeypatch.setenv(PC_FILES_WAIT_ENV, raw)
        assert _pc_files_wait_seconds() == expected


def test_the_gateway_keeps_a_running_answer_truthful():
    from app.pc_gateway_action import PcGatewayAction

    action = PcGatewayAction({
        "version": 1, "source": "mcp", "token_id": "mcp_token_fixture",
        "request_id": "mcp_" + "d" * 32, "tool_id": PC_LIST_FILES_TOOL_ID,
        "arguments": {"path": "."},
    })
    action.selected = True
    decision = action.decision([{
        "tool_id": PC_LIST_FILES_TOOL_ID,
        "output": {"status": "running", "job_id": DISPATCH_ID,
                   "answer": "PC가 아직 목록을 만들고 있습니다.",
                   "resume": {"argument": "job_id"}},
    }])

    payload = json.loads(decision["answer"])
    assert payload["status"] == "running"
    assert payload["job_id"] == DISPATCH_ID
    assert payload["resume"] == {"argument": "job_id"}
