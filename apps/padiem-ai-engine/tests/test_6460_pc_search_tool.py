"""#6460: PC file-name and content search inside the existing PC tool ceiling.

The search tools ride the same signed Chat endpoint as list/read; only the
operation and the bounded result projection are new. These tests drive the
real handler and the real step policy with an in-process wire fake.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    CLAW_APP_ID,
    PC_LIST_FILES_TOOL_ID,
    PC_QUERY_SCOPE,
    PC_READ_FILE_TOOL_ID,
    PC_SEARCH_CONTENT_TOOL_ID,
    PC_SEARCH_FILES_TOOL_ID,
    PCQueryStepError,
    StructuredPCQueryStepDriver,
    _make_pc_search_handler,
    _pc_search_projection,
    _scope_allowed_tool_ids,
)
from padiem_ai_core.agent_runtime import AgentStepContext
from padiem_ai_core.tool_runtime import ToolInvocation

RUN_ID = "run_6460_search"
SUBJECT = "sub_" + "6" * 32
PRODUCT = "b54-padiem-claw"
DEVICE = "pc-com1"
DISPATCH_ID = "dsp_6460"


def search_answer(*, engine="list", entries=None, count=None, **extra):
    rows = entries if entries is not None else []
    body = {
        "ok": True, "mode": "name", "query": "견적", "engine": engine,
        "office": "none",
        "count": len(rows) if count is None else count,
        "truncated": False, "scan_truncated": False, "entries": rows,
    }
    body.update(extra)
    return json.dumps(body, ensure_ascii=False)


def row(**overrides):
    base = {
        "path": "문서\\견적서.xlsx", "size_bytes": 1024,
        "modified_utc": "2026-11-01T01:02:03.0000000Z",
        "content_state": "name_only", "line": None, "snippet": "", "reason": "",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, PRODUCT, DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


async def _no_sleep(_seconds: float) -> None:
    return None


def _install_wire(monkeypatch, output: str, *, state="done", captured=None):
    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        if captured is not None and mode == "dispatch":
            captured.append(dict(kwargs["payload"]))
        if mode == "dispatch":
            return {"dispatch": {
                "run_id": RUN_ID, "kind": "command", "dispatch_id": DISPATCH_ID,
            }}
        if mode == "command_status":
            return {"dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                "kind": "command", "state": state,
            }}
        if mode == "result":
            return {"dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": RUN_ID, "kind": "command",
                "output": output, "result_sha256": "a" * 64,
                "termination": "exited", "exit_code": 0,
            }}
        raise AssertionError("unexpected mode " + str(mode))

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


def _handler(tool_id: str, search_mode: str):
    return _make_pc_search_handler(
        tool_id=tool_id, search_mode=search_mode, service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
    )


def test_search_ceiling_comes_from_the_shared_scope_table():
    files_list = _scope_allowed_tool_ids({"files_list": {"device_id": DEVICE}})
    files = _scope_allowed_tool_ids({"files": {"device_id": DEVICE}})
    assert files_list == {PC_LIST_FILES_TOOL_ID, PC_SEARCH_FILES_TOOL_ID}
    assert PC_SEARCH_CONTENT_TOOL_ID not in files_list
    assert files == {
        PC_LIST_FILES_TOOL_ID, PC_READ_FILE_TOOL_ID,
        PC_SEARCH_FILES_TOOL_ID, PC_SEARCH_CONTENT_TOOL_ID,
        driver.PC_READ_CHUNK_TOOL_ID,
    }
    # A write plan keeps its previous behaviour: its own plan ceiling, never a
    # broader read/search ceiling invented here.
    assert _scope_allowed_tool_ids({"files_write": {"device_id": DEVICE}}) is None


@pytest.mark.asyncio
async def test_file_name_search_dispatches_one_bounded_query(monkeypatch):
    captured: list[dict] = []
    _install_wire(monkeypatch, search_answer(entries=[row()]), captured=captured)
    result = await _handler(PC_SEARCH_FILES_TOOL_ID, "name")({"query": "  견적  "})

    assert captured == [{
        "op": "search", "path": ".", "query": "견적",
        "search_mode": "name", "tool_call_ref": captured[0]["tool_call_ref"],
    }]
    assert captured[0]["tool_call_ref"].startswith(RUN_ID + ":search_files:")
    projected = json.loads(result["output"])
    assert projected["ok"] is True and projected["mode"] == "name"
    assert projected["count"] == 1
    assert projected["entries"] == [row()]
    assert result["count"] == 1 and result["truncated"] is False
    assert result["execution_confirmed"] is True
    assert result["termination"] == "exited" and result["exit_code"] == 0


@pytest.mark.asyncio
async def test_content_search_keeps_match_line_and_cloud_state(monkeypatch):
    entries = [
        row(path="보고서.md", content_state="matched", line=12,
            snippet="장성군 견적 요청"),
        row(path="견적서.xlsx", content_state="deferred", line=None, snippet=""),
        row(path="OneDrive\\견적서.docx", content_state="not_downloaded",
            line=None, snippet=""),
    ]
    captured: list[dict] = []
    _install_wire(monkeypatch, search_answer(
        engine="ripgrep", entries=entries,
    ), captured=captured)
    result = await _handler(PC_SEARCH_CONTENT_TOOL_ID, "content")(
        {"query": "장성군"},
    )

    assert captured[0]["search_mode"] == "content"
    assert captured[0]["query"] == "장성군"
    projected = json.loads(result["output"])
    assert [entry["content_state"] for entry in projected["entries"]] == [
        "matched", "deferred", "not_downloaded",
    ]
    assert projected["entries"][0]["line"] == 12
    assert projected["engine"] == "ripgrep"
    assert result["engine"] == "ripgrep"


@pytest.mark.asyncio
async def test_search_step_policy_requires_exactly_one_query():
    seen = []

    async def select_step(*, context, compiled_profile, observations):
        seen.append(observations)
        if not observations:
            return {"action": "tool", "tool_id": PC_SEARCH_FILES_TOOL_ID,
                    "arguments": {"query": "견적"}}
        return {"action": "complete", "answer": "찾았습니다."}

    step = StructuredPCQueryStepDriver(
        select_step=select_step,
        allowed_tool_ids=frozenset({PC_LIST_FILES_TOOL_ID, PC_SEARCH_FILES_TOOL_ID}),
    )
    context = AgentStepContext.with_results(
        run_id="run_6460_policy", step_index=1, input_text="견적 찾아줘", results=(),
    )
    decision = await step.next_step(context, object())
    assert decision.invocation == ToolInvocation(
        tool_id=PC_SEARCH_FILES_TOOL_ID, arguments={"query": "견적"},
    )


@pytest.mark.parametrize("arguments", [
    {"query": ""}, {"query": "x" * 201}, {"query": "a\x00b"},
    {"query": "x", "mode": "content"}, {"query": 3}, {},
    {"query": "x", "path": 5}, {"query": "x", "path": "a\x01b"},
])
def test_search_arguments_are_closed(arguments):
    async def select_step(**kwargs):
        return {"action": "tool", "tool_id": PC_SEARCH_FILES_TOOL_ID,
                "arguments": arguments}

    step = StructuredPCQueryStepDriver(
        select_step=select_step,
        allowed_tool_ids=frozenset({PC_SEARCH_FILES_TOOL_ID}),
    )
    context = AgentStepContext.with_results(
        run_id="run_6460_closed", step_index=1, input_text="x", results=(),
    )
    with pytest.raises(PCQueryStepError):
        asyncio.run(step.next_step(context, object()))


def test_content_search_is_outside_a_listing_only_ceiling():
    async def select_step(**kwargs):
        return {"action": "tool", "tool_id": PC_SEARCH_CONTENT_TOOL_ID,
                "arguments": {"query": "견적"}}

    step = StructuredPCQueryStepDriver(
        select_step=select_step,
        allowed_tool_ids=frozenset({PC_LIST_FILES_TOOL_ID, PC_SEARCH_FILES_TOOL_ID}),
    )
    context = AgentStepContext.with_results(
        run_id="run_6460_ceiling", step_index=1, input_text="x", results=(),
    )
    with pytest.raises(PCQueryStepError):
        asyncio.run(step.next_step(context, object()))


def test_scope_claim_reports_search_capabilities():
    from padiem_ai_core.tool_runtime import ToolAuthorizationContext

    async def select_step(**kwargs):
        return {"action": "complete", "answer": "done"}

    step = StructuredPCQueryStepDriver(select_step=select_step)
    step.configure_request_scope(
        ToolAuthorizationContext(
            app_id=CLAW_APP_ID, agent_id="pc-test",
            granted_auth_scopes=(
                PC_QUERY_SCOPE, "claw.pc.list_files", "claw.pc.read_file",
                "claw.pc.search_files", "claw.pc.search_contents",
                "claw.pc.read_file_chunk",
            ),
            externally_authorized_tools=frozenset({
                PC_LIST_FILES_TOOL_ID, PC_READ_FILE_TOOL_ID,
                PC_SEARCH_FILES_TOOL_ID, PC_SEARCH_CONTENT_TOOL_ID,
                driver.PC_READ_CHUNK_TOOL_ID,
            }),
        ),
        declared_plan="files",
        ceiling_tool_ids=_scope_allowed_tool_ids({"files": {}}),
    )
    context = AgentStepContext.with_results(
        run_id="run_6460_claim", step_index=1, input_text="x", results=(),
    )
    asyncio.run(step.next_step(context, object()))
    claim = step.scope_state["claim"]
    assert claim["requested"] == claim["admitted"] == "files"
    assert claim["ops"] == ["list", "read", "search_name", "search_content"]


def test_projection_refuses_oversize_and_malformed_answers():
    with pytest.raises(Exception):
        _pc_search_projection(
            search_answer(entries=[row() for _ in range(51)]),
            query="견적", mode="name",
        )
    cases = (
        search_answer(engine="magic"),
        search_answer(entries=[row()], count=2),
        search_answer(entries=[row(content_state="copied")]),
        search_answer(entries=[row(snippet="x" * 201)]),
        search_answer(entries=[row(path="a\x01b")]),
        search_answer(entries=[row(size_bytes="10")]),
        "not json",
        json.dumps({"ok": False, "entries": []}),
    )
    for answer in cases:
        with pytest.raises(Exception):
            _pc_search_projection(answer, query="견적", mode="name")


def test_failed_dispatch_is_never_reported_as_a_result(monkeypatch):
    _install_wire(monkeypatch, "", state="failed")
    with pytest.raises(Exception):
        asyncio.run(_handler(PC_SEARCH_FILES_TOOL_ID, "name")({"query": "견적"}))


@pytest.mark.asyncio
async def test_a_named_folder_travels_as_the_dispatch_path(monkeypatch):
    captured: list[dict] = []
    _install_wire(monkeypatch, search_answer(entries=[row()]), captured=captured)
    await _handler(PC_SEARCH_FILES_TOOL_ID, "name")({"query": "견적", "path": "문서"})
    assert captured[0]["path"] == "문서"

    captured.clear()
    _install_wire(monkeypatch, search_answer(entries=[row()]), captured=captured)
    await _handler(PC_SEARCH_FILES_TOOL_ID, "name")({"query": "견적"})
    assert captured[0]["path"] == "."

    captured.clear()
    _install_wire(monkeypatch, search_answer(entries=[row()]), captured=captured)
    await _handler(PC_SEARCH_FILES_TOOL_ID, "name")({"query": "견적", "path": "."})
    assert captured[0]["path"] == "."


def test_office_rows_keep_partial_state_and_a_bounded_reason():
    answer = search_answer(
        engine="ripgrep", office="parser",
        entries=[
            row(path="문서/보고서.pdf", content_state="partial",
                reason="prefix_only"),
            row(path="문서/계약.hwpx", content_state="deferred",
                reason="extractor_unavailable"),
        ],
    )
    projected = _pc_search_projection(answer, query="견적", mode="content")
    assert projected["office"] == "parser"
    assert [entry["content_state"] for entry in projected["entries"]] == [
        "partial", "deferred",
    ]
    assert projected["entries"][0]["reason"] == "prefix_only"


def test_a_free_text_reason_is_refused():
    answer = search_answer(
        entries=[row(content_state="partial", reason="읽지 못했습니다")],
    )
    with pytest.raises(Exception):
        _pc_search_projection(answer, query="견적", mode="content")
    with pytest.raises(Exception):
        _pc_search_projection(
            search_answer(
                entries=[row(content_state="partial", reason="x" * 41)],
            ),
            query="견적", mode="content",
        )


def test_an_unknown_office_reader_is_refused():
    with pytest.raises(Exception):
        _pc_search_projection(
            search_answer(office="docx"), query="견적", mode="content",
        )


def test_the_slow_name_search_carries_one_install_hint():
    listing = search_answer(engine="list", entries=[row()])
    projected = _pc_search_projection(listing, query="견적", mode="name")
    assert projected["hint"] == driver.PC_SEARCH_INSTALL_HINT
    fast = search_answer(engine="everything", entries=[row()])
    assert "hint" not in _pc_search_projection(fast, query="견적", mode="name")
    content = search_answer(engine="list", entries=[row()])
    assert "hint" not in _pc_search_projection(content, query="견적", mode="content")


def test_a_search_may_name_one_folder():
    async def select_step(**kwargs):
        return {"action": "tool", "tool_id": PC_SEARCH_FILES_TOOL_ID,
                "arguments": {"query": "견적", "path": "문서/2026"}}

    step = StructuredPCQueryStepDriver(
        select_step=select_step,
        allowed_tool_ids=frozenset({PC_SEARCH_FILES_TOOL_ID}),
    )
    context = AgentStepContext.with_results(
        run_id="run_6460_folder", step_index=1, input_text="문서/2026에서 찾아줘",
        results=(),
    )
    decision = asyncio.run(step.next_step(context, object()))
    assert decision.invocation == ToolInvocation(
        tool_id=PC_SEARCH_FILES_TOOL_ID,
        arguments={"query": "견적", "path": "문서/2026"},
    )


def test_a_search_folder_cannot_be_absolute():
    async def select_step(**kwargs):
        return {"action": "tool", "tool_id": PC_SEARCH_FILES_TOOL_ID,
                "arguments": {"query": "견적", "path": "C:/Windows"}}

    step = StructuredPCQueryStepDriver(
        select_step=select_step,
        allowed_tool_ids=frozenset({PC_SEARCH_FILES_TOOL_ID}),
    )
    context = AgentStepContext.with_results(
        run_id="run_6460_abs", step_index=1, input_text="x", results=(),
    )
    with pytest.raises(PCQueryStepError):
        asyncio.run(step.next_step(context, object()))


def test_native_pc_tools_offer_search_inside_the_existing_scopes():
    from app import pc_tools_turn

    listing = {"device_id": DEVICE, "allowed_scopes": ["files_list"]}
    files = {"device_id": DEVICE, "allowed_scopes": ["files"]}
    listing_names = pc_tools_turn.tool_names(listing)
    files_names = pc_tools_turn.tool_names(files)
    assert "search_files" in listing_names
    assert "search_contents" not in listing_names
    assert {"search_files", "search_contents"} <= set(files_names)

    listing_defs = {d.name: d for d in pc_tools_turn.definitions(listing)}
    files_defs = {d.name: d for d in pc_tools_turn.definitions(files)}
    assert set(listing_defs) == {"files_list", "search_files"}
    assert {"files_list", "files", "search_files", "search_contents"} <= set(files_defs)
    schema = listing_defs["search_files"].parameters
    assert tuple(schema["required"]) == ("query",)
    assert set(schema["properties"]) == {"query", "path"}
    # One native name per scope: a content search is never offered to a
    # listing-only grant.
    assert pc_tools_turn.SEARCH_TOOL_SCOPES == {
        "search_files": "files_list", "search_contents": "files",
    }
