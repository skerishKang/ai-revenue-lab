"""Chat model-turn connector READ tools: bounded grant check and Engine lane.

The connected connector tools were wired only on the Engine execution path, so
the model turn never received them and answered "현재 도구로는 Drive 접근 불가".
These regressions pin the approved declaration slice:

* only a granted turn declares the two READ tools, with the Core canonical
  id/schema correspondence;
* an absent, unverified, failed or slow check declares nothing — and a slow
  check never delays the turn start;
* the per-user decision is cached for one short window and invalidated on
  disconnect/activation;
* a model tool_call executes through the Engine client with the closed
  canonical identity, and the redacted output becomes one plain follow-up
  answer turn.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest

from app import chat_connector_tools as tools_module
from app.connector_tool_engine_client import (
    CloudflareConnectorToolEngineClient,
    ConnectorToolEngineError,
)
from padiem_ai_core.calendar_capability import (
    CALENDAR_CANONICAL_TOOL_IDS,
    CALENDAR_LIST_EVENTS_TOOL_ID,
    calendar_read_tool_specs,
)
from padiem_ai_core.drive_capability import (
    DRIVE_CANONICAL_TOOL_IDS,
    DRIVE_SEARCH_FILES_TOOL_ID,
    drive_read_tool_specs,
)

_CONNECTED = ("connected", None)
_NOT_CONNECTED = ("not_connected", None)

_DRIVE_SPEC = {spec.id: spec for spec in drive_read_tool_specs()}[DRIVE_SEARCH_FILES_TOOL_ID]
_CALENDAR_SPEC = {spec.id: spec for spec in calendar_read_tool_specs()}[CALENDAR_LIST_EVENTS_TOOL_ID]


def _patch_truth(monkeypatch, *, overrides, authority, session_id="authsession:test",
                 calendar_state=None, calls=None):
    async def _reviewed_workspace_truth(request):
        if calls is not None:
            calls.append("truth")
        return overrides, "canonical_workspace_connector_not_reported", authority, session_id

    async def _reviewed_calendar_state(request, sid):
        return calendar_state

    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _reviewed_workspace_truth)
    monkeypatch.setattr(tools_module, "_reviewed_calendar_read_grant_state", _reviewed_calendar_state)


@pytest.fixture(autouse=True)
def _clean_cache():
    tools_module.invalidate_connector_tool_grant_cache()
    yield
    tools_module.invalidate_connector_tool_grant_cache()


@pytest.mark.asyncio
async def test_only_a_granted_turn_declares_the_two_connector_tools(monkeypatch):
    """Grant present → exactly the two READ declarations, canonical id/schema."""
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _CONNECTED},
        authority=True,
        calendar_state="active",
    )
    decision = await tools_module._grant_decision_for_uid(SimpleNamespace(), uid="u1")
    assert decision.reason == "granted"
    assert (decision.drive, decision.calendar) == (True, True)

    declared = tools_module._tools_for_decision(decision)
    assert [tool.name for tool in declared] == ["drive_read", "calendar_read"]
    by_name = {tool.name: tool for tool in declared}
    assert by_name["drive_read"].parameters == dict(_DRIVE_SPEC.input_schema)
    assert by_name["calendar_read"].parameters == dict(_CALENDAR_SPEC.input_schema)
    assert by_name["drive_read"].description == _DRIVE_SPEC.description

    # The alias table resolves to the Core canonical engine identities.
    drive_id, drive_app, drive_agent = tools_module.CONNECTOR_TOOL_BINDINGS["drive_read"]
    assert (drive_id, drive_app, drive_agent) == (
        DRIVE_CANONICAL_TOOL_IDS[0],
        "b54-padiem-claw-drive",
        "agent:padiem:claw_drive_reader@1",
    )
    calendar_id, calendar_app, calendar_agent = tools_module.CONNECTOR_TOOL_BINDINGS["calendar_read"]
    assert (calendar_id, calendar_app, calendar_agent) == (
        CALENDAR_CANONICAL_TOOL_IDS[2],
        tools_module.CALENDAR_REFERENCE_APP_ID,
        tools_module.CALENDAR_AGENT_ID,
    )


@pytest.mark.asyncio
async def test_drive_only_grant_declares_one_tool(monkeypatch):
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _NOT_CONNECTED},
        authority=True,
    )
    decision = await tools_module._grant_decision_for_uid(SimpleNamespace(), uid="u1")
    assert decision.reason == "granted"
    assert (decision.drive, decision.calendar) == (True, False)
    assert [tool.name for tool in tools_module._tools_for_decision(decision)] == ["drive_read"]


@pytest.mark.asyncio
async def test_unverified_not_connected_and_failed_checks_declare_nothing(monkeypatch):
    # No trusted authority: unverified, never not_connected.
    _patch_truth(monkeypatch, overrides={}, authority=False)
    decision = await tools_module._grant_decision_for_uid(SimpleNamespace(), uid="u1")
    assert decision.reason == "unverified"
    assert tools_module._tools_for_decision(decision) == ()

    # Trusted authority that reports both connectors absent.
    _patch_truth(
        monkeypatch,
        overrides={"drive": _NOT_CONNECTED, "calendar": _NOT_CONNECTED},
        authority=True,
    )
    decision = await tools_module._grant_decision_for_uid(SimpleNamespace(), uid="u1")
    assert decision.reason == "not_connected"
    assert tools_module._tools_for_decision(decision) == ()

    # A failed truth read declares nothing instead of failing the turn.
    async def _broken_truth(request):
        raise RuntimeError("truth unavailable")

    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _broken_truth)
    tools_module.invalidate_connector_tool_grant_cache()
    assert await tools_module.connector_tools_for_turn(SimpleNamespace(), uid="u1") == ()


@pytest.mark.asyncio
async def test_a_slow_truth_read_never_delays_the_turn(monkeypatch):
    calls: list[str] = []

    async def _slow_truth(request):
        calls.append("truth")
        await asyncio.sleep(1.0)
        return {"drive": _CONNECTED, "calendar": _CONNECTED}, None, True, "s"

    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _slow_truth)
    started = time.perf_counter()
    decision, elapsed_ms, timed_out = await tools_module._bounded_grant_decision(
        SimpleNamespace(), uid="u1"
    )
    elapsed = time.perf_counter() - started
    assert timed_out is True
    assert decision.reason == "timeout"
    # The budget bound the wait: the turn starts without the tools long
    # before the slow authority answered.
    assert elapsed < 0.8
    assert elapsed_ms <= 0.3 * 1000.0 + 50.0
    assert await tools_module.connector_tools_for_turn(SimpleNamespace(), uid="u1") == ()

    # A timeout is never cached: the next turn retries the check.
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _CONNECTED},
        authority=True,
        calendar_state="active",
        calls=calls,
    )
    tools_module.invalidate_connector_tool_grant_cache()
    tools = await tools_module.connector_tools_for_turn(SimpleNamespace(), uid="u1")
    assert [tool.name for tool in tools] == ["drive_read", "calendar_read"]
    # One slow read (the budget timeout) + one entry-point retry above it +
    # the fresh read after invalidation.
    assert calls.count("truth") == 3


@pytest.mark.asyncio
async def test_the_grant_decision_is_cached_until_invalidated(monkeypatch):
    calls: list[str] = []
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _CONNECTED},
        authority=True,
        calendar_state="active",
        calls=calls,
    )
    request = SimpleNamespace()
    first = await tools_module.connector_tools_for_turn(request, uid="u1")
    second = await tools_module.connector_tools_for_turn(request, uid="u1")
    assert [tool.name for tool in first] == ["drive_read", "calendar_read"]
    assert [tool.name for tool in second] == ["drive_read", "calendar_read"]
    assert calls.count("truth") == 1, "the same user inside the window reuses one decision"

    tools_module.invalidate_connector_tool_grant_cache("u1")
    await tools_module.connector_tools_for_turn(request, uid="u1")
    assert calls.count("truth") == 2, "invalidation forces a fresh grant read"


class _FakeEngineBinding:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self._status = status
        self._body = body
        self.requests: list[dict[str, Any]] = []

    async def fetch(self, request: dict[str, Any]) -> Any:
        self.requests.append(request)
        payload = json.dumps(self._body, ensure_ascii=False)

        class _Response:
            status = self._status

            async def text(self) -> str:
                return payload

        return _Response()


def _request_factory(url: str, *, method: str, headers: dict, body: str) -> Any:
    return SimpleNamespace(js_object={
        "url": url, "method": method, "headers": dict(headers), "body": body,
    })


@pytest.mark.asyncio
async def test_the_engine_client_executes_the_declared_tool_with_canonical_identity():
    binding = _FakeEngineBinding(200, {
        "ok": True,
        "tool": {"status": "completed", "canonical_tool_id": DRIVE_CANONICAL_TOOL_IDS[0],
                 "output": {"files": [{"name": "보고서"}]}},
    })
    client = CloudflareConnectorToolEngineClient(
        binding, caller_id="b54-p01-overlay-20260914-a1",
        credential="cred", request_factory=_request_factory,
    )
    tool = await client.execute(tool_name="drive_read", arguments={"query": "보고서"})
    assert tool["output"] == {"files": [{"name": "보고서"}]}

    request = binding.requests[0]
    assert request["url"].endswith("/internal/v1/tools/execute")
    assert request["headers"]["x-padiem-engine-caller"] == "b54-p01-overlay-20260914-a1"
    payload = json.loads(request["body"])
    assert payload["app_id"] == "b54-padiem-claw-drive"
    assert payload["agent_id"] == "agent:padiem:claw_drive_reader@1"
    assert payload["tool_id"] == DRIVE_CANONICAL_TOOL_IDS[0]
    assert payload["arguments"] == {"query": "보고서"}


@pytest.mark.asyncio
async def test_the_engine_client_fails_closed_on_refusal_and_undeclared_tools():
    refused = _FakeEngineBinding(403, {"ok": False, "error": {"code": "tool_not_registered"}})
    client = CloudflareConnectorToolEngineClient(
        refused, caller_id="b54-p01-overlay-20260914-a1",
        credential="cred", request_factory=_request_factory,
    )
    with pytest.raises(ConnectorToolEngineError) as refused_error:
        await client.execute(tool_name="drive_read", arguments={"query": "보고서"})
    assert refused_error.value.code == "connector_tool_refused"

    with pytest.raises(ConnectorToolEngineError) as unsupported:
        await client.execute(tool_name="gmail_read", arguments={})
    assert unsupported.value.status_code == 422


class _ScriptedFollowUpClient:
    """The B14 client the lane re-dispatches: one plain answer turn."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None,
                               tools=(), tool_choice=None, **kwargs):
        self.calls.append({
            "messages": messages,
            "context": additional_system_context,
            "tools": tools,
        })
        yield SimpleNamespace(delta_thought=None, delta_content="드라이브에서 1건을 찾았습니다.", done=False)
        yield SimpleNamespace(delta_thought=None, delta_content=None, done=True)


class _RecordingEngineClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, *, tool_name: str, arguments: dict) -> dict[str, Any]:
        self.calls.append({"tool_name": tool_name, "arguments": arguments})
        return {"status": "completed", "output": {"files": [{"name": "보고서"}]}}


class _FakeTiming:
    def __init__(self) -> None:
        self.outcomes: list[str] = []

    def set_outcome(self, value: str) -> None:
        self.outcomes.append(value)


@pytest.mark.asyncio
async def test_a_model_tool_call_executes_through_the_engine_and_answers():
    """tool_call → Engine execute (fake) → one plain follow-up answer turn."""
    engine = _RecordingEngineClient()
    client = _ScriptedFollowUpClient()
    timing = _FakeTiming()
    frames: list[bytes] = []

    async def _frame_stream():
        from app.chat_routes import _connector_tool_lane

        async for frame in _connector_tool_lane(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
                connector_tool_engine_client=engine,
            ))),
            tool_name="drive_read",
            tool_arguments={"query": "보고서"},
            client=client,
            messages=[{"role": "user", "content": "내 드라이브에서 보고서 찾아줘"}],
            skill=None,
            reference_context=None,
            conversation_id=None,
            uid="u1",
            store=None,
            latest_user="내 드라이브에서 보고서 찾아줘",
            timing=timing,
        ):
            frames.append(frame)

    await asyncio.wait_for(_frame_stream(), timeout=5)
    assert engine.calls == [{"tool_name": "drive_read", "arguments": {"query": "보고서"}}]
    # The follow-up dispatch carries the tool result as context and no tools,
    # so a connector read can never chain into another tool lane.
    assert len(client.calls) == 1
    assert client.calls[0]["tools"] == ()
    assert "[connector:drive_read 결과]" in client.calls[0]["context"]
    assert "보고서" in client.calls[0]["context"]

    text = b"".join(frames).decode("utf-8")
    assert "드라이브에서 1건을 찾았습니다." in text
    assert "event: done" in text
    assert '"done":true' in text
    assert timing.outcomes[-1] == "tool_lane"


@pytest.mark.asyncio
async def test_an_undeclared_tool_call_fails_closed_without_touching_the_engine():
    engine = _RecordingEngineClient()
    client = _ScriptedFollowUpClient()
    timing = _FakeTiming()
    frames: list[bytes] = []

    from app.chat_routes import _connector_tool_lane

    async for frame in _connector_tool_lane(
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            connector_tool_engine_client=engine,
        ))),
        tool_name="files_write",
        tool_arguments={},
        client=client,
        messages=[{"role": "user", "content": "x"}],
        skill=None,
        reference_context=None,
        conversation_id=None,
        uid="u1",
        store=None,
        latest_user="x",
        timing=timing,
    ):
        frames.append(frame)

    assert engine.calls == [] and client.calls == []
    text = b"".join(frames).decode("utf-8")
    assert "connector_tool_unsupported" in text
    assert timing.outcomes == ["error"]
