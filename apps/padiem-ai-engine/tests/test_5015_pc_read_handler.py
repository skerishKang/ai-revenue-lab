"""#5015: the Engine PC read handler consumes the kind=read lane truthfully.

The list call stays a kind=command result. The read call must expect kind=read,
return the exact verified body, refuse more than PC_FILES_READ_MAX_BYTES
defensively, and surface a failed read's marker (or a bounded execution failure)
without completing the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_FILES_READ_MAX_BYTES,
    PC_LIST_FILES_TOOL_ID,
    PC_READ_FILE_TOOL_ID,
    _make_pc_file_handler,
)
from padiem_ai_core.tool_runtime import ToolHandlerError

RUN_ID = "run_5015_read"
SUBJECT = "sub_" + "5" * 32
PRODUCT = "padiem-chat"
DEVICE = "pc-com2"
DISPATCH_ID = "dsp_5015_read"
BODY = "PADIEM FILE BODY\nEND_OF_FILE\n"
TOO_LARGE = "PADIEM_PC_FILE_ERROR:too_large"
READ_FAILED = "PADIEM_PC_FILE_ERROR:read_failed"


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, PRODUCT, DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


async def _no_sleep(_seconds: float) -> None:
    return None


def _result_row(
    *, kind: str = "read", output: str = BODY,
    termination: str = "exited", exit_code: int | None = 0,
    content_bytes: int | None = None,
) -> dict:
    encoded = output.encode("utf-8")
    return {
        "dispatch_id": DISPATCH_ID, "run_id": RUN_ID, "kind": kind,
        "output": output,
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "content_sha256": hashlib.sha256(encoded).hexdigest(),
        "content_bytes": len(encoded) if content_bytes is None else content_bytes,
        "termination": termination,
        "exit_code": exit_code,
    }


def _install(
    monkeypatch, *, dispatch_kind: str = "read", state: str = "done",
    status_kind: str | None = None, result: dict | None = None,
    result_error: Exception | None = None, expected_op: str = "read",
) -> list[str]:
    modes: list[str] = []
    status_kind = status_kind or dispatch_kind

    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        modes.append(mode)
        if mode == "dispatch":
            assert kwargs["payload"]["op"] == expected_op
            return {"dispatch": {
                "run_id": RUN_ID, "kind": dispatch_kind,
                "dispatch_id": DISPATCH_ID,
            }}
        if mode == "command_status":
            return {"dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                "kind": status_kind, "state": state,
                "termination": "exited", "exit_code": 0,
            }}
        if mode == "result":
            if result_error is not None:
                raise result_error
            return {"dispatch": result or _result_row()}
        raise AssertionError("unexpected mode " + str(mode))

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    return modes


def _handler(op: str, tool_id: str):
    return _make_pc_file_handler(
        tool_id=tool_id, op=op, service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
    )


def test_read_dispatch_expects_kind_read_and_returns_the_exact_body(monkeypatch):
    _install(monkeypatch)
    result = asyncio.run(
        _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
    )

    assert result["content"] == BODY
    assert result["content_bytes"] == len(BODY.encode("utf-8"))
    assert result["result_sha256"] == hashlib.sha256(
        BODY.encode("utf-8")
    ).hexdigest()
    assert result["execution_confirmed"] is True


@pytest.mark.parametrize("size", [1_000_001, PC_FILES_READ_MAX_BYTES])
def test_owner_read_tier_accepts_large_verified_content_without_truncation(monkeypatch, size):
    content = "x" * size
    modes = _install(monkeypatch, result=_result_row(output=content))
    result = asyncio.run(_handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"}))
    assert result["content"] == content
    assert result["content_bytes"] == size
    assert result["result_sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert modes.count("dispatch") == 1


def test_a_read_dispatched_as_command_is_a_correlation_mismatch(monkeypatch):
    _install(monkeypatch, dispatch_kind="command")
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(
            _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
        )
    assert caught.value.code == "pc_files_dispatch_mismatch"


def test_a_read_result_dispatched_as_command_is_a_correlation_mismatch(monkeypatch):
    _install(monkeypatch, status_kind="command")
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(
            _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
        )
    assert caught.value.code == "pc_files_result_mismatch"


def test_read_output_over_the_owner_read_bound_is_refused_without_an_answer(monkeypatch):
    oversized = "x" * (PC_FILES_READ_MAX_BYTES + 1)
    _install(monkeypatch, result=_result_row(output=oversized))
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(
            _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
        )
    assert caught.value.code == "pc_files_output_too_large"


def test_read_content_length_must_match_its_bytes(monkeypatch):
    _install(monkeypatch, result=_result_row(content_bytes=3))
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(
            _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
        )
    assert caught.value.code == "pc_files_output_missing"


def test_failed_read_surfaces_the_too_large_marker(monkeypatch):
    _install(
        monkeypatch, state="failed",
        result=_result_row(
            output=TOO_LARGE, exit_code=1,
        ),
    )
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(
            _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
        )
    assert caught.value.code == "pc_file_too_large"


def test_failed_read_surfaces_read_failed(monkeypatch):
    _install(
        monkeypatch, state="failed",
        result=_result_row(output=READ_FAILED, exit_code=1),
    )
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(
            _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
        )
    assert caught.value.code == "pc_file_read_failed"


def test_failed_read_without_a_body_is_a_bounded_execution_failure(monkeypatch):
    _install(
        monkeypatch, state="failed",
        result_error=ToolHandlerError(
            "pc_files_denied", "PC file operation was denied or failed",
        ),
    )
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(
            _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
        )
    assert caught.value.code == "pc_files_execution_failed"


def test_list_still_accepts_the_command_lane_and_its_no_exit_code(monkeypatch):
    listing = json.dumps([{"Name": "notes.txt", "PSIsContainer": False}])
    _install(
        monkeypatch, dispatch_kind="command", expected_op="list",
        result=_result_row(
            kind="command", output=listing,
            termination="no_exit_code", exit_code=None,
        ),
    )
    result = asyncio.run(
        _handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."})
    )
    assert result["entry_count"] == 1
    assert json.loads(result["output"])["entries"][0]["relative_path"] == "notes.txt"

def test_a_file_body_that_looks_like_an_error_marker_is_still_content(monkeypatch):
    _install(monkeypatch, result=_result_row(output=READ_FAILED))
    result = asyncio.run(
        _handler("read", PC_READ_FILE_TOOL_ID)({"path": "notes.txt"})
    )
    assert result["content"] == READ_FAILED
    assert result["content_bytes"] == len(READ_FAILED.encode("utf-8"))
