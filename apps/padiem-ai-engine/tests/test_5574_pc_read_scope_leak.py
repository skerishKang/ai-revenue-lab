"""#5574 negative case: a listing-only request whose model wrongly answers read.

The Chat lane always ships the trusted legacy list+read plan hint
(``tool_arguments == {"files": ...}``) together with a two-step plan
(``list_files`` + ``read_file``); it never ships the list-only
(``files_list``) hint and it does not classify the request. This file drives
the REAL engine composition (``build_live_pc_query_driver``) with a model
that wrongly answers a listing-only request with a read step, and records
what the production policy actually does.

Nothing in the wrong-read case pre-fixes the model's intent: the wrongly
returned read IS the case under test. The one mechanism that narrows the
turn (the model declaring ``intent:"list"`` itself) is exercised only as a
separate contrast case, never as a way to make the wrong-read case pass.
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


def _read_step() -> str:
    return json.dumps(
        {"action": "tool", "tool_id": PC_READ_FILE_TOOL_ID, "arguments": {"path": "a.txt"}},
        ensure_ascii=False,
    )


def test_the_chat_lane_scope_lets_the_wrong_read_through() -> None:
    """ACTUAL RESULT: the wrongly returned read is NOT refused.

    The Chat lane's scope hint (``{"files": ...}``) is the trusted legacy
    list+read plan, so the read gate starts open and a missing intent does
    not close it. The read invocation is produced, which means the Engine
    would run it (the handler's own authority/path/size checks still apply).
    """

    driver, _model = _driver(CHAT_LANE_SCOPE, [_list_step(), _read_step()])
    first = asyncio.run(driver.next_step(_context(), object()))
    assert first.invocation.tool_id == PC_LIST_FILES_TOOL_ID

    second = asyncio.run(driver.next_step(_context(), object()))
    assert second.invocation.tool_id == PC_READ_FILE_TOOL_ID


def test_the_list_only_hint_refuses_the_wrong_read() -> None:
    """The list-only scope is the closure the Chat lane does not use."""

    driver, _model = _driver(LIST_ONLY_SCOPE, [_list_step(), _read_step()])
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "outside this execution scope" in str(excinfo.value)
    # The scope denial has no closed diagnostic code of its own.
    assert excinfo.value.code is None


def test_the_models_own_list_intent_refuses_the_later_read() -> None:
    """CONTRAST: the only narrowing that exists inside the Chat lane scope.

    When the model itself declares ``intent:"list"``, the read gate closes
    for the rest of the turn. This is the mechanism the product relies on
    today; it is a model behaviour, not a server guarantee.
    """

    driver, _model = _driver(CHAT_LANE_SCOPE, [_list_step(intent="list"), _read_step()])
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError) as excinfo:
        asyncio.run(driver.next_step(_context(), object()))
    assert "outside this execution scope" in str(excinfo.value)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "#5574 known gap: the Chat lane ships the legacy list+read scope for a "
        "listing-only request, so a model that wrongly answers read is not "
        "refused. Closing it needs a server-side list-only scope (or another "
        "server-side narrowing), which this change deliberately does not add."
    ),
)
def test_a_listing_only_request_must_not_produce_a_read_invocation() -> None:
    """The invariant the product wants, stated without any intent shortcut."""

    driver, _model = _driver(CHAT_LANE_SCOPE, [_list_step(), _read_step()])
    asyncio.run(driver.next_step(_context(), object()))
    with pytest.raises(PCQueryStepError):
        asyncio.run(driver.next_step(_context(), object()))
