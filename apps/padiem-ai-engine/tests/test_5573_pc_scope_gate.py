"""#5573: the trusted plan fixes the tool scope before any dispatch."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from kagent.pc_query_adapter import (
    PC_LIST_FILES_TOOL_ID,
    PC_QUERY_OWNER,
    PC_READ_FILE_TOOL_ID,
    PCQueryStepError,
    StructuredPCQueryStepDriver,
)

LIST_ONLY = frozenset({PC_LIST_FILES_TOOL_ID})
LIST_AND_READ = frozenset({PC_LIST_FILES_TOOL_ID, PC_READ_FILE_TOOL_ID})


def _context():
    async def resolve():
        return ()

    return SimpleNamespace(input_text="request", resolve_tool_results=resolve)


def _driver(tool_id: str, allowed):
    async def select(**kwargs):
        return {"action": "tool", "tool_id": tool_id, "arguments": {"path": "."}}

    return StructuredPCQueryStepDriver(
        select_step=select, static_arguments={}, allowed_tool_ids=allowed,
    )


def test_read_is_refused_in_a_list_only_scope():
    driver = _driver(PC_READ_FILE_TOOL_ID, LIST_ONLY)
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)


def test_list_is_allowed_in_a_list_only_scope():
    driver = _driver(PC_LIST_FILES_TOOL_ID, LIST_ONLY)
    decision = asyncio.run(driver.next_step(_context(), object()))
    assert decision.invocation.tool_id == PC_LIST_FILES_TOOL_ID


def test_read_without_intent_uses_the_admitted_full_ceiling():
    driver = _driver(PC_READ_FILE_TOOL_ID, LIST_AND_READ)
    decision = asyncio.run(driver.next_step(_context(), object()))
    assert decision.invocation.tool_id == PC_READ_FILE_TOOL_ID


def test_read_without_intent_is_refused_without_an_allowlist():
    # A missing ceiling cannot acquire read permission from the model.
    driver = _driver(PC_READ_FILE_TOOL_ID, None)
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)


def test_scope_hint_maps_to_the_closed_tool_sets():
    from app.claw_pc_query_step_driver import _scope_allowed_tool_ids

    assert _scope_allowed_tool_ids({"files_list": {"device_id": "x"}}) == LIST_ONLY
    assert _scope_allowed_tool_ids({"files": {"device_id": "x"}}) == LIST_AND_READ
    assert _scope_allowed_tool_ids(None) is None
    assert _scope_allowed_tool_ids({}) is None


def _sequence(steps, *, allowed=None):
    it = iter(steps)

    async def select(**kwargs):
        return next(it)

    return StructuredPCQueryStepDriver(
        select_step=select, static_arguments={}, allowed_tool_ids=allowed,
    )


def _list(intent):
    arguments = {"path": "."}
    if intent is not None:
        arguments["intent"] = intent
    return {"action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID, "arguments": arguments}


def _read():
    return {"action": "tool", "tool_id": PC_READ_FILE_TOOL_ID, "arguments": {"path": "a.txt"}}


def test_list_intent_blocks_the_read_step():
    # The ceiling permits read; the model's own list intent is what refuses it.
    driver = _sequence([_list("list"), _read(intent="list")], allowed=LIST_AND_READ)
    first = asyncio.run(driver.next_step(_context(), object()))
    assert first.invocation.tool_id == PC_LIST_FILES_TOOL_ID
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)


def _read(path: str = "a.txt", intent: str | None = None):
    arguments = {"path": path}
    if intent is not None:
        arguments["intent"] = intent
    return {"action": "tool", "tool_id": PC_READ_FILE_TOOL_ID, "arguments": arguments}


def test_the_ceiling_is_checked_before_the_intent_and_path_rules():
    """Which check refuses a read in a list-only scope, measured by ordering.

    The step is invalid twice over: the tool is outside the ceiling AND the
    intent is not a reviewed value. The message that comes back names the check
    that actually ran first, so a model cannot trade an invalid intent for an
    in-scope tool.
    """
    outside = _sequence([_read(intent="everything")], allowed=LIST_ONLY)
    with pytest.raises(PCQueryStepError) as ceiling:
        asyncio.run(outside.next_step(_context(), object()))
    assert "outside this execution scope" in str(ceiling.value)

    inside = _sequence([_read(intent="everything")], allowed=LIST_AND_READ)
    with pytest.raises(PCQueryStepError) as intent_rule:
        asyncio.run(inside.next_step(_context(), object()))
    assert "invalid or unauthorized" in str(intent_rule.value)


def test_a_read_intent_cannot_widen_a_list_only_ceiling():
    """The ceiling, not the model, decides whether read exists this turn.

    A read intent has no widening effect. The same steps are accepted under
    the list+read ceiling (test_read_intent_allows_the_read_step), so only the
    admitted ceiling refuses this read.
    """
    driver = _sequence([_list("read"), _read()], allowed=LIST_ONLY)
    first = asyncio.run(driver.next_step(_context(), object()))
    assert first.invocation.tool_id == PC_LIST_FILES_TOOL_ID
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "outside this execution scope" in str(excinfo.value)


def test_the_read_gate_refuses_before_the_invocation_is_built():
    """Under the list+read ceiling the gate is the refusing check, and it runs
    before the path rules: a read whose path would also be invalid is refused
    as a scope denial, so no invocation is ever assembled for the handler.
    """
    driver = _sequence([_list(None), _read(path="a\tb.txt", intent="list")], allowed=LIST_AND_READ)
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "outside this execution scope" in str(excinfo.value)


def test_read_intent_allows_the_read_step():
    driver = _sequence([_list("read"), _read()], allowed=LIST_AND_READ)
    asyncio.run(driver.next_step(_context(), object()))
    second = asyncio.run(driver.next_step(_context(), object()))
    assert second.invocation.tool_id == PC_READ_FILE_TOOL_ID


def test_list_intent_narrows_only_its_step():
    driver = _sequence(
        [_read(intent="list"), _read()], allowed=LIST_AND_READ,
    )
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)
    decision = asyncio.run(driver.next_step(_context(), object()))
    assert decision.invocation.tool_id == PC_READ_FILE_TOOL_ID


@pytest.mark.parametrize("intent", ["everything", "", None, [], {}])
def test_unknown_intent_is_refused(intent):
    step = _list(None)
    step["arguments"]["intent"] = intent
    driver = _sequence([step], allowed=LIST_AND_READ)
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "invalid or unauthorized" in str(excinfo.value)


def test_missing_intent_does_not_widen_a_list_only_ceiling():
    driver = _sequence([_list(None), _read()], allowed=LIST_ONLY)
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)
