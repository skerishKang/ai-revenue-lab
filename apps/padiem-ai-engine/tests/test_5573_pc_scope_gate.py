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


def test_read_is_refused_until_the_read_intent_opens_it():
    # #5574: a list+read scope is a ceiling, not a grant.
    driver = _driver(PC_READ_FILE_TOOL_ID, LIST_AND_READ)
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)


def test_read_without_intent_is_refused_without_an_allowlist():
    # The closed default belongs to the step policy, not to one plan hint.
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
    driver = _sequence([_list("list"), _read()], allowed=LIST_AND_READ)
    first = asyncio.run(driver.next_step(_context(), object()))
    assert first.invocation.tool_id == PC_LIST_FILES_TOOL_ID
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)


def test_read_intent_allows_the_read_step():
    driver = _sequence([_list("read"), _read()], allowed=LIST_AND_READ)
    asyncio.run(driver.next_step(_context(), object()))
    second = asyncio.run(driver.next_step(_context(), object()))
    assert second.invocation.tool_id == PC_READ_FILE_TOOL_ID


def test_a_list_intent_closes_a_read_intent_the_same_turn_opened():
    driver = _sequence([_list("read"), _list("list"), _read()], allowed=LIST_AND_READ)
    asyncio.run(driver.next_step(_context(), object()))
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)


def test_unknown_intent_is_refused():
    driver = _sequence([_list("everything")])
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "invalid or unauthorized" in str(excinfo.value)


def test_missing_intent_does_not_grant_read():
    driver = _sequence([_list(None), _read()], allowed=LIST_AND_READ)
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)
