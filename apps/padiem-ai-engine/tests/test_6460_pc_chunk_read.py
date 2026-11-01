"""#6460-4: bounded range reads of a large file on the verified PC.

The range handler, the read_file fallback and the search byte offset are driven
with an in-process wire fake; no Mesh, Identity or PC is contacted.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_CHUNK_DEFAULT_BYTES,
    PC_CHUNK_MAX_BYTES,
    PC_LIST_FILES_TOOL_ID,
    PC_READ_CHUNK_TOOL_ID,
    PC_READ_FILE_TOOL_ID,
    PC_SEARCH_FILES_TOOL_ID,
    PCQueryStepError,
    StructuredPCQueryStepDriver,
    _make_pc_file_handler,
    _make_pc_read_chunk_handler,
    _pc_chunk_projection,
    _pc_search_projection,
    _scope_allowed_tool_ids,
    pc_chunk_bytes,
)
from padiem_ai_core.agent_runtime import AgentStepContext
from padiem_ai_core.tool_runtime import ToolInvocation

RUN_ID = "run_6460_chunk"
SUBJECT = "sub_" + "7" * 32
PRODUCT = "b54-padiem-claw"
DEVICE = "pc-com1"
DISPATCH_ID = "dsp_chunk"


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, PRODUCT, DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


async def _no_sleep(_seconds: float) -> None:
    return None


def chunk_answer(*, text="가나다", offset=0, next_offset=9, size=1234, eof=False,
                 unit="bytes", **extra):
    body = {
        "ok": True, "unit": unit, "size_bytes": size, "offset": offset,
        "next_offset": next_offset, "eof": eof, "text": text,
    }
    body.update(extra)
    return json.dumps(body, ensure_ascii=False)


def _install_wire(monkeypatch, answers, captured=None):
    """One queue of dispatch outputs; every dispatch/status/result leg answers."""
    queue = list(answers)
    lane = {"kind": "command"}

    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        payload = kwargs.get("payload") or {}
        if payload.get("op"):
            lane["kind"] = "read" if payload["op"] == "read" else "command"
        kind = lane["kind"]
        if captured is not None and mode == "dispatch":
            captured.append(dict(payload))
        if mode == "dispatch":
            return {"dispatch": {
                "run_id": RUN_ID, "kind": kind, "dispatch_id": DISPATCH_ID,
            }}
        if mode == "command_status":
            return {"dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                "kind": kind, "state": "done",
            }}
        if mode == "result":
            output = queue.pop(0) if queue else ""
            return {"dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": RUN_ID, "kind": kind,
                "output": output, "result_sha256": "a" * 64,
                "content_bytes": len(output.encode("utf-8")),
                "termination": "exited", "exit_code": 0,
            }}
        raise AssertionError("unexpected mode " + str(mode))

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


def _chunk_handler():
    return _make_pc_read_chunk_handler(
        service=object(), request_factory=lambda *a, **k: None, secret="s" * 40,
    )


@pytest.mark.asyncio
async def test_one_range_dispatches_and_projects(monkeypatch):
    captured: list[dict] = []
    _install_wire(monkeypatch, [chunk_answer()], captured=captured)
    result = await _chunk_handler()({"path": "big.txt", "offset": 0, "length": 9})

    assert captured == [{
        "op": "read_chunk", "path": "big.txt", "offset": 0, "length": 9,
        "tool_call_ref": captured[0]["tool_call_ref"],
    }]
    projection = json.loads(result["output"])
    assert projection == {
        "ok": True, "unit": "bytes", "size_bytes": 1234, "offset": 0,
        "next_offset": 9, "eof": False, "text": "가나다",
    }
    assert result["next_offset"] == 9 and result["eof"] is False
    assert result["execution_confirmed"] is True


@pytest.mark.asyncio
async def test_the_length_defaults_to_the_server_setting(monkeypatch):
    monkeypatch.setenv("PADIEM_ENGINE_PC_CHUNK_BYTES", "8192")
    assert pc_chunk_bytes() == 8192
    captured: list[dict] = []
    _install_wire(
        monkeypatch, [chunk_answer(next_offset=8192, size=20000)], captured=captured,
    )
    await _chunk_handler()({"path": "big.txt", "offset": 0})
    assert captured[0]["length"] == 8192

    monkeypatch.setenv("PADIEM_ENGINE_PC_CHUNK_BYTES", "1")
    assert pc_chunk_bytes() == PC_CHUNK_DEFAULT_BYTES
    monkeypatch.setenv("PADIEM_ENGINE_PC_CHUNK_BYTES", "not-a-number")
    assert pc_chunk_bytes() == PC_CHUNK_DEFAULT_BYTES
    monkeypatch.delenv("PADIEM_ENGINE_PC_CHUNK_BYTES")
    assert pc_chunk_bytes() == PC_CHUNK_DEFAULT_BYTES


@pytest.mark.asyncio
async def test_arguments_are_closed():
    handler = _chunk_handler()
    for arguments in (
        {"offset": 0},
        {"path": "a.txt"},
        {"path": "a.txt", "offset": -1},
        {"path": "a.txt", "offset": 0, "length": 0},
        {"path": "a.txt", "offset": 0, "length": PC_CHUNK_MAX_BYTES + 1},
        {"path": "a.txt", "offset": 0, "extra": 1},
        {"path": "", "offset": 0},
        {"path": "a.txt", "offset": True},
    ):
        with pytest.raises(Exception):
            await handler(arguments)


def test_a_range_never_exceeds_the_requested_units():
    # A byte range may round up to a character boundary (at most 3 bytes).
    _pc_chunk_projection(chunk_answer(text="가" * 3, next_offset=9), offset=0, length=9)
    with pytest.raises(Exception):
        _pc_chunk_projection(chunk_answer(text="x" * 13, next_offset=13), offset=0, length=9)
    # A document range is characters and never longer than the request.
    _pc_chunk_projection(
        chunk_answer(unit="chars", text="가" * 5, next_offset=5), offset=0, length=5,
    )
    with pytest.raises(Exception):
        _pc_chunk_projection(
            chunk_answer(unit="chars", text="가" * 6, next_offset=6), offset=0, length=5,
        )


def test_malformed_answers_are_refused():
    cases = (
        "not json",
        json.dumps({"ok": False, "error": "extractor_unavailable"}),
        chunk_answer(offset=5),                      # offset drift
        chunk_answer(next_offset=2, offset=5, text="x"),
        chunk_answer(unit="lines"),
        chunk_answer(eof="no"),
        chunk_answer(next_offset=99999, size=1234),  # past the end
        chunk_answer(partial="x"),
    )
    for answer in cases:
        with pytest.raises(Exception):
            _pc_chunk_projection(answer, offset=0, length=9)


def test_an_error_code_becomes_a_bounded_stage():
    with pytest.raises(Exception) as excinfo:
        _pc_chunk_projection(
            json.dumps({"ok": False, "error": "extractor_unavailable"}),
            offset=0, length=9,
        )
    assert "pc_chunk_extractor_unavailable" in str(getattr(excinfo.value, "code", ""))


@pytest.mark.asyncio
async def test_read_file_over_the_cap_answers_with_its_first_range(monkeypatch):
    """The 20MB read cap is one answer's size, not the file's."""
    chunk = chunk_answer(text="head", next_offset=4, size=150_000_000)
    captured: list[dict] = []
    _install_wire(
        monkeypatch,
        ["PADIEM_PC_FILE_ERROR:too_large", chunk],
        captured=captured,
    )
    read_handler = _make_pc_file_handler(
        tool_id=PC_READ_FILE_TOOL_ID, op="read", service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
        first_chunk=_chunk_handler(),
    )
    result = await read_handler({"path": "huge.txt"})

    assert captured[0]["op"] == "read"
    assert captured[1] == {
        "op": "read_chunk", "path": "huge.txt", "offset": 0,
        "length": PC_CHUNK_DEFAULT_BYTES,
        "tool_call_ref": captured[1]["tool_call_ref"],
    }
    assert result["continued"] is True
    assert result["why"] == "file_over_single_read_cap"
    assert json.loads(result["output"])["text"] == "head"


@pytest.mark.asyncio
async def test_a_small_read_is_unchanged(monkeypatch):
    captured: list[dict] = []
    _install_wire(monkeypatch, ["hello"], captured=captured)
    read_handler = _make_pc_file_handler(
        tool_id=PC_READ_FILE_TOOL_ID, op="read", service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
        first_chunk=_chunk_handler(),
    )
    result = await read_handler({"path": "notes.txt"})
    assert result["content"] == "hello"
    assert len(captured) == 1 and captured[0]["op"] == "read"


def test_the_chunk_tool_rides_the_read_scope_only():
    files = _scope_allowed_tool_ids({"files": {}})
    listing = _scope_allowed_tool_ids({"files_list": {}})
    assert PC_READ_CHUNK_TOOL_ID in files
    assert PC_READ_CHUNK_TOOL_ID not in listing
    assert PC_SEARCH_FILES_TOOL_ID in listing
    assert PC_LIST_FILES_TOOL_ID in files


def test_a_range_step_names_a_path_an_offset_and_an_optional_length():
    async def select_step(**kwargs):
        return {"action": "tool", "tool_id": PC_READ_CHUNK_TOOL_ID,
                "arguments": {"path": "문서/big.txt", "offset": 120, "length": 4096}}

    step = StructuredPCQueryStepDriver(
        select_step=select_step,
        allowed_tool_ids=frozenset({PC_READ_CHUNK_TOOL_ID}),
    )
    context = AgentStepContext.with_results(
        run_id="run_6460_chunk_step", step_index=1, input_text="이어서 읽어줘", results=(),
    )
    decision = asyncio.run(step.next_step(context, object()))
    assert decision.invocation == ToolInvocation(
        tool_id=PC_READ_CHUNK_TOOL_ID,
        arguments={"path": "문서/big.txt", "offset": 120, "length": 4096},
    )


def test_a_range_step_is_closed():
    async def step_with(arguments):
        async def select_step(**kwargs):
            return {"action": "tool", "tool_id": PC_READ_CHUNK_TOOL_ID,
                    "arguments": arguments}
        return StructuredPCQueryStepDriver(
            select_step=select_step,
            allowed_tool_ids=frozenset({PC_READ_CHUNK_TOOL_ID}),
        )

    for arguments in (
        {"path": "a.txt"},
        {"path": "a.txt", "offset": -1},
        {"path": "a.txt", "offset": 0, "length": 0},
        {"path": "a.txt", "offset": 0, "query": "x"},
        {"path": 7, "offset": 0},
    ):
        driver_step = asyncio.run(step_with(arguments))
        context = AgentStepContext.with_results(
            run_id="run_6460_chunk_closed", step_index=1, input_text="x", results=(),
        )
        with pytest.raises(PCQueryStepError):
            asyncio.run(driver_step.next_step(context, object()))


def test_a_search_match_carries_the_byte_offset_of_the_text_file_match():
    answer = json.dumps({
        "ok": True, "mode": "content", "query": "견적", "engine": "ripgrep",
        "office": "none", "count": 2, "truncated": False, "scan_truncated": False,
        "entries": [
            {"path": "a.md", "size_bytes": 10,
             "modified_utc": "2026-11-01T00:00:00Z", "content_state": "matched",
             "line": 4, "snippet": "견적", "reason": "", "byte_offset": 83},
            {"path": "b.pdf", "size_bytes": 10,
             "modified_utc": "2026-11-01T00:00:00Z", "content_state": "matched",
             "line": None, "snippet": "견적", "reason": "", "byte_offset": None},
        ],
    }, ensure_ascii=False)
    projected = _pc_search_projection(answer, query="견적", mode="content")
    assert projected["entries"][0]["byte_offset"] == 83
    assert "byte_offset" not in projected["entries"][1]
