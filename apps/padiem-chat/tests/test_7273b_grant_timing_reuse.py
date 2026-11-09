"""#7273 후속: the bounded grant check is itemized and reused within one turn.

The 3-second budget is a product constant and stays exactly as it is. What a
turn must not do is pay the same truth read twice: the tool offer and the
READ guard share one per-request answer (a timeout still declares nothing),
and every real check leaves one line naming where its milliseconds went.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import chat_connector_tools as tools

UID = "usr_" + "c" * 32


def _request() -> Request:
    request = Request({
        "type": "http", "method": "POST", "path": "/api/chat/stream", "headers": [],
    })
    request.scope["app"] = SimpleNamespace(state=SimpleNamespace())
    return request


@pytest.fixture(autouse=True)
def _clean_cache():
    tools.invalidate_connector_tool_grant_cache()
    yield
    tools.invalidate_connector_tool_grant_cache()


def test_the_budget_is_unchanged():
    assert tools.CONNECTOR_TOOL_GRANT_INTENT_BUDGET_SECONDS == 3.0


def test_the_second_call_in_one_turn_reuses_the_first(monkeypatch):
    calls: list[str] = []

    async def _truth(request, *, uid):
        calls.append(uid)
        return tools.ConnectorToolGrant(reason="granted", drive=True, calendar=True)

    monkeypatch.setattr(tools, "_grant_decision_for_uid", _truth)
    request = _request()

    first, _ms, first_timed_out = asyncio.run(
        tools._bounded_grant_decision(request, uid=UID)
    )
    second, second_ms, second_timed_out = asyncio.run(
        tools._bounded_grant_decision(request, uid=UID)
    )

    assert calls == [UID], "one truth read answers the whole turn"
    assert first == second and first.reason == "granted"
    assert first_timed_out is False and second_timed_out is False
    assert second_ms == 0.0


def test_a_timeout_is_reused_inside_the_turn_and_never_across_turns(monkeypatch):
    calls: list[str] = []

    async def _slow_truth(request, *, uid):
        calls.append(uid)
        await asyncio.sleep(0.05)
        return tools.ConnectorToolGrant(reason="granted", drive=True, calendar=True)

    monkeypatch.setattr(tools, "_grant_decision_for_uid", _slow_truth)
    request = _request()

    first, _ms, first_timed_out = asyncio.run(
        tools._bounded_grant_decision(request, uid=UID, budget=0.005)
    )
    second, second_ms, second_timed_out = asyncio.run(
        tools._bounded_grant_decision(request, uid=UID, budget=0.005)
    )

    assert first.reason == "timeout" and first_timed_out is True
    assert second.reason == "timeout" and second_timed_out is True
    assert second_ms == 0.0, "the same turn does not pay the budget twice"
    assert calls == [UID]

    # A new turn retries: a timeout is never cached across turns.
    third, _ms, third_timed_out = asyncio.run(
        tools._bounded_grant_decision(_request(), uid=UID, budget=0.005)
    )
    assert third_timed_out is True
    assert calls == [UID, UID]


def test_a_real_check_leaves_one_itemized_line(monkeypatch, caplog):
    async def _truth(request, *, uid):
        return tools.ConnectorToolGrant(reason="granted", drive=True, calendar=True)

    monkeypatch.setattr(tools, "_grant_decision_for_uid", _truth)
    logger = logging.getLogger("test.grant.timing")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    monkeypatch.setattr(tools, "_LOG", logger)

    with caplog.at_level(logging.INFO, logger="test.grant.timing"):
        asyncio.run(tools._bounded_grant_decision(_request(), uid=UID))

    lines = [r.message for r in caplog.records if "connector_grant_timing" in r.message]
    assert len(lines) == 1
    assert "budget_ms=3000" in lines[0]
    assert "reason=granted" in lines[0]
    assert "timed_out=false" in lines[0]
    for field in (
        "profile_ms=", "identity_refresh_ms=", "session_ms=",
        "identity_workspace_ms=", "state_connector_ms=", "state_calendar_ms=",
        "workspace_truth_ms=", "grant_state_ms=",
    ):
        assert field in lines[0], field
