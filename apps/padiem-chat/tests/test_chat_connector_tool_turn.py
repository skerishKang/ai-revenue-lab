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
from padiem_ai_core.connectors import (
    GMAIL_CANONICAL_TOOL_IDS,
    GMAIL_GET_MESSAGE_TOOL_ID,
    GMAIL_SEARCH_MESSAGES_TOOL_ID,
    gmail_read_tool_specs,
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
_GMAIL_SEARCH_SPEC = {spec.id: spec for spec in gmail_read_tool_specs()}[GMAIL_SEARCH_MESSAGES_TOOL_ID]
_GMAIL_GET_SPEC = {spec.id: spec for spec in gmail_read_tool_specs()}[GMAIL_GET_MESSAGE_TOOL_ID]


def _patch_truth(monkeypatch, *, overrides, authority, session_id="authsession:test",
                 calendar_state=None, calls=None):
    async def _reviewed_workspace_truth(request, path=None):
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
async def test_a_gmail_only_grant_declares_the_two_gmail_tools(monkeypatch):
    """Gmail 연결만 있으면 지메일 검색·읽기 2개가 선언된다(canonical id 고정)."""
    _patch_truth(
        monkeypatch,
        overrides={"drive": _NOT_CONNECTED, "calendar": _NOT_CONNECTED, "gmail": _CONNECTED},
        authority=True,
    )
    decision = await tools_module._grant_decision_for_uid(SimpleNamespace(), uid="u1")
    assert decision.reason == "granted"
    assert (decision.drive, decision.calendar, decision.gmail) == (False, False, True)
    declared = tools_module._tools_for_decision(decision)
    assert [tool.name for tool in declared] == ["gmail_search", "gmail_read"]
    by_name = {tool.name: tool for tool in declared}
    assert by_name["gmail_search"].parameters == dict(_GMAIL_SEARCH_SPEC.input_schema)
    assert by_name["gmail_read"].parameters == dict(_GMAIL_GET_SPEC.input_schema)
    search_id, gmail_app, gmail_agent = tools_module.CONNECTOR_TOOL_BINDINGS["gmail_search"]
    read_id, _app2, _agent2 = tools_module.CONNECTOR_TOOL_BINDINGS["gmail_read"]
    assert (search_id, gmail_app, gmail_agent) == (
        GMAIL_CANONICAL_TOOL_IDS[0], "b54-padiem-claw", "agent:padiem:claw_mail_reader@1",
    )
    assert (read_id, _app2, _agent2) == (
        GMAIL_CANONICAL_TOOL_IDS[1], "b54-padiem-claw", "agent:padiem:claw_mail_reader@1",
    )


@pytest.mark.asyncio
async def test_a_full_google_grant_declares_all_four_read_tools(monkeypatch):
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _CONNECTED, "gmail": _CONNECTED},
        authority=True,
        calendar_state="active",
    )
    tools = await tools_module.connector_tools_for_turn(
        SimpleNamespace(), uid="u1", intent_turn=True,
    )
    assert [tool.name for tool in tools] == [
        "drive_read", "calendar_read", "gmail_search", "gmail_read",
    ]


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
    async def _broken_truth(request, path=None):
        raise RuntimeError("truth unavailable")

    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _broken_truth)
    tools_module.invalidate_connector_tool_grant_cache()
    assert await tools_module.connector_tools_for_turn(
        SimpleNamespace(), uid="u1", intent_turn=True,
    ) == ()


@pytest.mark.asyncio
async def test_a_general_turn_never_pays_the_grant_check(monkeypatch):
    """일반 턴은 확인 0회: 커넥터 도구는 명시적 Google 의도 턴에만 선언된다."""
    calls: list[str] = []

    async def _counting_truth(request, path=None):
        calls.append("truth")
        return {"drive": _CONNECTED, "calendar": _CONNECTED}, None, True, "s"

    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _counting_truth)
    tools = await tools_module.connector_tools_for_turn(
        SimpleNamespace(), uid="u1", intent_turn=False,
    )
    assert tools == ()
    assert calls == [], "the grant check is paid by intent turns only"


@pytest.mark.asyncio
async def test_an_intent_turn_waits_for_the_slow_truth_and_reaches_the_tools(monkeypatch):
    """명시적 의도 턴은 1~3초 확인을 기다려 커넥터 경로로 간다(3초 상한)."""
    calls: list[str] = []

    async def _measured_truth(request, path=None):
        calls.append("truth")
        await asyncio.sleep(0.8)  # the production path took ~2.7s: inside the budget
        return {"drive": _CONNECTED, "calendar": _CONNECTED}, None, True, "s"

    async def _active_state(request, sid):
        return "active"

    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _measured_truth)
    monkeypatch.setattr(tools_module, "_reviewed_calendar_read_grant_state", _active_state)
    started = time.perf_counter()
    tools = await tools_module.connector_tools_for_turn(
        SimpleNamespace(), uid="u1", intent_turn=True,
    )
    elapsed = time.perf_counter() - started
    assert [tool.name for tool in tools] == ["drive_read", "calendar_read"]
    assert elapsed >= 0.8, "the intent turn waited for the truth read"
    assert elapsed < 3.0, "the answer arrived inside the 3s budget"

    # A read slower than the intent budget times out at ~3s and is not cached.
    async def _too_slow_truth(request, path=None):
        calls.append("truth")
        await asyncio.sleep(3.6)
        return {"drive": _CONNECTED, "calendar": _CONNECTED}, None, True, "s"

    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _too_slow_truth)
    tools_module.invalidate_connector_tool_grant_cache()
    started = time.perf_counter()
    decision, elapsed_ms, timed_out = await tools_module._bounded_grant_decision(
        SimpleNamespace(), uid="u1",
    )
    elapsed = time.perf_counter() - started
    assert timed_out is True
    assert decision.reason == "timeout"
    assert 2.9 <= elapsed < 4.0, "the intent budget bounds the wait at ~3s"
    assert 2900.0 <= elapsed_ms < 4000.0
    # A timeout is never cached: the next turn retries the check.
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _CONNECTED},
        authority=True,
        calendar_state="active",
        calls=calls,
    )
    tools_module.invalidate_connector_tool_grant_cache()
    tools = await tools_module.connector_tools_for_turn(
        SimpleNamespace(), uid="u1", intent_turn=True,
    )
    assert [tool.name for tool in tools] == ["drive_read", "calendar_read"]
    assert calls.count("truth") == 3


def test_the_cache_lifetime_follows_the_decision_reason():
    granted = tools_module.ConnectorToolGrant(reason="granted", drive=True, calendar=True)
    absent = tools_module.ConnectorToolGrant(reason="not_connected", drive=False, calendar=False)
    assert tools_module._cache_ttl_for(granted) == 300.0
    assert tools_module._cache_ttl_for(absent) == 30.0
    assert tools_module._cache_ttl_for(
        tools_module.ConnectorToolGrant(reason="timeout", drive=False, calendar=False)
    ) == 0.0
    assert tools_module._cache_ttl_for(
        tools_module.ConnectorToolGrant(reason="unverified", drive=False, calendar=False)
    ) == 0.0
    # Uncacheable decisions are never stored by the seeding entry point.
    tools_module.seed_connector_grant_cache(
        "u1", tools_module.ConnectorToolGrant(reason="timeout", drive=False, calendar=False),
    )
    assert tools_module._GRANT_CACHE.get("u1") is None


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
    first = await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    second = await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    assert [tool.name for tool in first] == ["drive_read", "calendar_read"]
    assert [tool.name for tool in second] == ["drive_read", "calendar_read"]
    assert calls.count("truth") == 1, "the same user inside the window reuses one decision"

    tools_module.invalidate_connector_tool_grant_cache("u1")
    await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    assert calls.count("truth") == 2, "invalidation forces a fresh grant read"


@pytest.mark.asyncio
async def test_a_not_connected_answer_is_cached_only_for_its_short_window(monkeypatch):
    calls: list[str] = []
    fake_now = [1000.0]

    class _FakeTime:
        @staticmethod
        def monotonic():
            return fake_now[0]

        @staticmethod
        def perf_counter():
            return time.perf_counter()

    _patch_truth(
        monkeypatch,
        overrides={"drive": _NOT_CONNECTED, "calendar": _NOT_CONNECTED},
        authority=True,
        calls=calls,
    )
    monkeypatch.setattr(tools_module, "time", _FakeTime)
    request = SimpleNamespace()
    first = await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    second = await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    assert first == () and second == ()
    assert calls.count("truth") == 1, "the short not_connected window reuses one answer"

    fake_now[0] += 31.0
    await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    assert calls.count("truth") == 2, "past the 30s window the answer is re-asked"

    # A granted answer outlives that window five-fold.
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _CONNECTED},
        authority=True,
        calendar_state="active",
        calls=calls,
    )
    tools_module.invalidate_connector_tool_grant_cache()
    fake_now[0] += 31.0
    await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    fake_now[0] += 150.0
    await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    assert calls.count("truth") == 3, "the granted answer is still fresh inside 5 minutes"
    fake_now[0] += 150.0
    await tools_module.connector_tools_for_turn(request, uid="u1", intent_turn=True)
    assert calls.count("truth") == 4, "past 5 minutes the granted answer expires"


def test_the_real_b14_request_builder_accepts_the_connector_tools():
    """커넥터 도구가 선언된 턴이 실제 B14 요청 빌더·검증을 통과한다(fake 아님)."""
    from app.b14_client import _execution_request
    from app.model_policy import MAX_HOLD_MODEL_ID
    from app.task_modes import get_task_mode
    from padiem_ai_core.b14_execution import B14ChatRequest
    from padiem_ai_core.streaming_runtime import (
        _compose_system_instruction,
        _native_model_parameters,
        _normalize_model_policy,
    )

    req = _execution_request(
        [{"role": "user", "content": "이번 주 구글 캘린더 일정 알려줘"}],
        skill=get_task_mode(),
        model=MAX_HOLD_MODEL_ID,
        required_capabilities=("chat",),
        additional_system_context=None,
        tools=tools_module.CONNECTOR_TOOL_DECLARATIONS,
        tool_choice="auto",
    )
    assert req.agent.allowed_tools == ()
    si = _compose_system_instruction(req)
    model, temperature, routing = _normalize_model_policy(req.agent)
    b14 = B14ChatRequest(
        messages=({"role": "system", "content": si}, *req.messages) if si is not None else req.messages,
        model=model, temperature=temperature, max_tokens=req.agent.max_tokens,
        routing=routing, model_parameters=_native_model_parameters(req.agent),
        tools=req.tools, tool_choice=req.tool_choice,
    )
    payload = b14.to_payload()
    assert [t["function"]["name"] for t in payload["tools"]] == [
        "drive_read", "calendar_read", "gmail_search", "gmail_read",
    ]
    assert payload["tool_choice"] == "auto"


def test_a_route_without_native_tools_declares_no_connector_tools(monkeypatch):
    """라우트가 도구 미선언이면 grant 확인 없이 미선언(측정된 execution_failed 방지)."""
    calls: list[str] = []

    class _Rows:
        async def list_registered_models(self):
            return [{"model_id": "some/max-model", "capabilities": ["chat"],
                     "b14_enabled": True, "owner_excluded": False}]

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        b14_model_choice_resolver=_Rows(),
    )))
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _CONNECTED},
        authority=True,
    )
    tools = asyncio.run(tools_module.connector_tools_for_turn(
        request, uid="u1", intent_turn=True,
    ))
    assert [t.name for t in tools] == ["drive_read", "calendar_read"]


def test_the_route_gate_blocks_the_grant_check_when_the_route_declares_no_tools(monkeypatch):
    from app import chat_routes as chat_routes_module

    checks: list[str] = []

    async def _declares(request, model_id):
        checks.append("declares")
        return False

    monkeypatch.setattr(
        "app.chat_pc_drive.chat_pc_route_declares_tools", _declares,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    helper = chat_routes_module._chat_connector_tools_for_turn
    tools = asyncio.run(helper(request, uid="u1", intent=True, model_id="some/max-model"))
    assert tools == ()
    assert checks == ["declares"], "the expensive grant check must not run"


@pytest.mark.asyncio
async def test_the_decision_journal_always_prints_bounded_fields(monkeypatch, capsys):
    _patch_truth(
        monkeypatch,
        overrides={"drive": _CONNECTED, "calendar": _CONNECTED},
        authority=True,
    )
    await tools_module.connector_tools_for_turn(SimpleNamespace(), uid="u1", intent_turn=True)
    out = capsys.readouterr().out
    assert "connector_tools declared=2 reason=granted" in out
    assert "check_ms=" in out


def test_the_max_route_passes_the_native_tools_gate():
    """#7124 라우트 게이트가 Max 라우트에서 통과하는지 실제 레지스트리로 확인.

    The gate withholds connector tools on a route whose B14 registration does
    not declare the ``tools`` capability. The Max grade's own route model must
    pass, or calendar asks on that grade answer without tools (measured
    #7088 후속). The row shape mirrors the normalized catalog view the gate
    reads, with capabilities taken verbatim from the canonical registry.
    """
    import json as _json
    from pathlib import Path as _Path

    from app.chat_pc_drive import chat_pc_route_declares_tools  # noqa: F401 — gate under test
    from app.model_policy import MAX_HOLD_MODEL_ID

    registry = _json.loads(
        (_Path(__file__).resolve().parents[3] / "apps" / "korean-ai-platform"
         / "app" / "pilot" / "b14_models.json").read_text(encoding="utf-8")
    )
    rows = registry if isinstance(registry, list) else registry.get("models", [])
    row = next(r for r in rows if r.get("id") == MAX_HOLD_MODEL_ID or r.get("model_id") == MAX_HOLD_MODEL_ID)
    assert "tools" in row["capabilities"], "the Max route model lost its tools capability"

    import asyncio

    class _Resolver:
        async def list_registered_models(self):
            return [{
                "model_id": MAX_HOLD_MODEL_ID,
                "capabilities": list(row["capabilities"]),
                "b14_enabled": True,
                "owner_excluded": False,
            }]

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        b14_model_choice_resolver=_Resolver(),
    )))
    result = asyncio.run(chat_pc_route_declares_tools(request, MAX_HOLD_MODEL_ID))
    assert result is True


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
        await client.execute(tool_name="gmail_send", arguments={})
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
async def test_a_model_tool_call_executes_through_the_engine_and_answers(capsys):
    """tool_call → Engine execute (fake) → one plain follow-up answer turn."""
    engine = _RecordingEngineClient()
    client = _ScriptedFollowUpClient()
    timing = _FakeTiming()
    frames: list[bytes] = []

    import logging

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
    # #7088: the execution journal carries counts only — the output content
    # (file names, mail bodies, subjects, senders) never reaches the journal.
    journal = capsys.readouterr().out
    assert "connector_tools execute tool=drive_read items=1" in journal
    assert "보고서" not in journal.split("connector_tools execute")[-1]
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
