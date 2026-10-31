"""#5574 regression: a listing-only request whose model wrongly answers read.

The Chat lane always ships the trusted list+read plan hint
(``tool_arguments == {"files": ...}``) together with a two-step plan
(``list_files`` + ``read_file``); it never ships the list-only
(``files_list``) hint and it does not classify the request. This file drives
the REAL engine composition (``build_live_pc_query_driver``) with a model
that wrongly answers a listing-only request with a read step.

The admitted hint supplies the tool ceiling. A list-only ceiling refuses
read; a full ceiling permits it with missing or read intent. Intent:list
narrows only its own step. The model never grants a permission.

A listing-only user context that still receives the full plan retains the
current production risk; model-selected plan admission is the second slice.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.claw_pc_query_step_driver import build_live_pc_query_driver
from kagent.pc_query_adapter import (
    PC_LIST_FILES_TOOL_ID,
    PC_READ_FILE_TOOL_ID,
    PCQueryStepError,
)

# The exact scope shape the Chat lane sends for every PC files turn
# (apps/padiem-chat/app/chat_pc_drive.py: tool_arguments = {"files": {...}}).
CHAT_LANE_SCOPE: dict[str, Any] = {"files": {"device_id": "office-pc"}}
# The list-only scope the Engine understands but the Chat lane never sends.
LIST_ONLY_SCOPE: dict[str, Any] = {"files_list": {"device_id": "office-pc"}}
LISTING_ONLY_REQUEST = "내PC office-pc 폴더에서 파일 목록 보여줘"


class _ScriptedModel:
    """A model that answers with the scripted steps, in order."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.requests: list[Any] = []

    async def execute(self, request: Any):  # noqa: ANN201
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else ""
        return SimpleNamespace(answer=answer)


def _driver(scope: dict[str, Any], answers: list[str]):  # noqa: ANN201
    model = _ScriptedModel(answers)
    driver = build_live_pc_query_driver(
        b14_client=model,
        model_id="test-only-model",
        tool_arguments=scope,
    )
    return driver, model


def _context():  # noqa: ANN201
    async def resolve():
        return ()

    return SimpleNamespace(input_text=LISTING_ONLY_REQUEST, resolve_tool_results=resolve)


def _list_step(intent: str | None = None) -> str:
    arguments: dict[str, Any] = {"path": "."}
    if intent is not None:
        arguments["intent"] = intent
    return json.dumps(
        {"action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID, "arguments": arguments},
        ensure_ascii=False,
    )


def _read_step(intent: str | None = None) -> str:
    arguments: dict[str, Any] = {"path": "a.txt"}
    if intent is not None:
        arguments["intent"] = intent
    return json.dumps(
        {"action": "tool", "tool_id": PC_READ_FILE_TOOL_ID, "arguments": arguments},
        ensure_ascii=False,
    )


def test_the_chat_lane_scope_allows_read_after_the_models_read_intent() -> None:
    """The legitimate read path inside the same scope hint is unchanged.

    The model selects the read tool inside the admitted ceiling. Its read
    intent neither grants permission nor changes the ceiling.
    """

    driver, _model = _driver(
        CHAT_LANE_SCOPE, [_list_step(intent="read"), _read_step()],
    )
    first = asyncio.run(driver.next_step(_context(), object()))
    assert first.invocation.tool_id == PC_LIST_FILES_TOOL_ID
    assert first.invocation.arguments == {"path": "."}

    second = asyncio.run(driver.next_step(_context(), object()))
    assert second.invocation.tool_id == PC_READ_FILE_TOOL_ID
    assert second.invocation.arguments == {"path": "a.txt"}


def test_the_list_only_hint_refuses_the_wrong_read() -> None:
    """The list-only scope is the closure the Chat lane does not use."""

    driver, _model = _driver(LIST_ONLY_SCOPE, [_list_step(), _read_step()])
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "outside this execution scope" in str(excinfo.value)
    # The scope denial has no closed diagnostic code of its own.
    assert excinfo.value.code is None


def test_the_list_only_hint_refuses_a_read_the_model_declared() -> None:
    """A model intent cannot widen the scope the plan admitted.

    The list step declares ``intent:"read"`` — the strongest thing a model can
    say — and under the list-only ceiling the read is still refused. The same
    two steps are accepted under the list+read ceiling
    (test_the_chat_lane_scope_allows_read_after_the_models_read_intent), so the
    refusal here is the ceiling, not the intent gate.
    """

    driver, _model = _driver(
        LIST_ONLY_SCOPE, [_list_step(intent="read"), _read_step()],
    )
    first = asyncio.run(driver.next_step(_context(), object()))
    assert first.invocation.tool_id == PC_LIST_FILES_TOOL_ID
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "outside this execution scope" in str(excinfo.value)
    assert excinfo.value.code is None


def test_the_models_own_list_intent_refuses_the_later_read() -> None:
    """A read step that narrows itself to listing is refused."""

    driver, _model = _driver(CHAT_LANE_SCOPE, [_list_step(), _read_step(intent="list")])
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "outside this execution scope" in str(excinfo.value)


def test_missing_intent_preserves_the_admitted_full_ceiling() -> None:
    """The gate does not classify user text or require a model intent field."""
    driver, _model = _driver(CHAT_LANE_SCOPE, [_list_step(), _read_step()])
    asyncio.run(driver.next_step(_context(), object()))
    decision = asyncio.run(driver.next_step(_context(), object()))
    assert decision.invocation.tool_id == PC_READ_FILE_TOOL_ID
