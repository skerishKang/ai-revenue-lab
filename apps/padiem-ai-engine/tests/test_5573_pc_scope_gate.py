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


def _driver(tool_id: str, allowed, *, legacy=False):
    async def select(**kwargs):
        return {"action": "tool", "tool_id": tool_id, "arguments": {"path": "."}}

    return StructuredPCQueryStepDriver(
        select_step=select, static_arguments={}, allowed_tool_ids=allowed,
        legacy_read_allowed=legacy,
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


def test_read_is_allowed_when_the_scope_includes_it():
    driver = _driver(PC_READ_FILE_TOOL_ID, LIST_AND_READ, legacy=True)
    decision = asyncio.run(driver.next_step(_context(), object()))
    assert decision.invocation.tool_id == PC_READ_FILE_TOOL_ID


def test_unrestricted_driver_keeps_the_legacy_behaviour():
    driver = _driver(PC_READ_FILE_TOOL_ID, None, legacy=True)
    decision = asyncio.run(driver.next_step(_context(), object()))
    assert decision.invocation.tool_id == PC_READ_FILE_TOOL_ID


def test_scope_hint_maps_to_the_closed_tool_sets():
    from app.claw_pc_query_step_driver import _scope_allowed_tool_ids

    assert _scope_allowed_tool_ids({"files_list": {"device_id": "x"}}) == LIST_ONLY
    assert _scope_allowed_tool_ids({"files": {"device_id": "x"}}) == LIST_AND_READ
    assert _scope_allowed_tool_ids(None) is None
    assert _scope_allowed_tool_ids({}) is None


def _sequence(steps, *, legacy=False):
    it = iter(steps)

    async def select(**kwargs):
        return next(it)

    return StructuredPCQueryStepDriver(
        select_step=select, static_arguments={}, allowed_tool_ids=None,
        legacy_read_allowed=legacy,
    )


def _list(intent):
    arguments = {"path": "."}
    if intent is not None:
        arguments["intent"] = intent
    return {"action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID, "arguments": arguments}


def _read():
    return {"action": "tool", "tool_id": PC_READ_FILE_TOOL_ID, "arguments": {"path": "a.txt"}}


def test_list_intent_blocks_the_read_step():
    driver = _sequence([_list("list"), _read()])
    first = asyncio.run(driver.next_step(_context(), object()))
    assert first.invocation.tool_id == PC_LIST_FILES_TOOL_ID
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)


def test_read_intent_allows_the_read_step():
    driver = _sequence([_list("read"), _read()])
    asyncio.run(driver.next_step(_context(), object()))
    second = asyncio.run(driver.next_step(_context(), object()))
    assert second.invocation.tool_id == PC_READ_FILE_TOOL_ID


def test_legacy_plan_without_intent_keeps_the_read_step():
    driver = _sequence([_list(None), _read()], legacy=True)
    asyncio.run(driver.next_step(_context(), object()))
    second = asyncio.run(driver.next_step(_context(), object()))
    assert second.invocation.tool_id == PC_READ_FILE_TOOL_ID


def test_unknown_intent_is_refused():
    driver = _sequence([_list("everything")])
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "invalid or unauthorized" in str(excinfo.value)


def test_missing_intent_does_not_grant_read_outside_the_legacy_plan():
    driver = _sequence([_list(None), _read()])
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "execution scope" in str(excinfo.value)
