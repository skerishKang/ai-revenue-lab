"""#7165 — Chat direct PC command lane and the verified three-state PC sentence.

The model used to answer "PADIEM is a remote AI and cannot reach your
computer" on a turn whose owner PC was connected, because the only PC sentence
available was the "not connected" one (#7181). The sentence now follows the
server's verified state, and the owner's own explicit command runs through
Claw's composer rule and dispatch instead of being refused.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import chat_pc_command as lane
from app import orchestration_routes as routes
from app.chat_pc_note import (
    PC_TOOLS_ABSENT_NOTE,
    PC_TOOLS_CONNECTED_NOTE,
    PC_TOOLS_PRESENT_NOTE,
    pc_turn_note,
)

DEVICE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
PC_TOOLS = {"device_id": DEVICE_ID, "allowed_scopes": ["query_drives"]}
CONTEXT = {"pc_tools": PC_TOOLS, "subject_id": "subject_1", "workspace_id": "workspace_1"}
COMMAND_TEXT = "내 PC에서 `whoami` 실행해"


# --- the sentence: three states, never a fixed assumption ----------------
def test_tools_present_is_the_present_sentence() -> None:
    assert pc_turn_note(PC_TOOLS) == PC_TOOLS_PRESENT_NOTE


def test_a_connected_pc_without_tools_never_reads_as_disconnected() -> None:
    note = pc_turn_note((), pc_connected=True)
    assert note == PC_TOOLS_CONNECTED_NOTE
    assert "원격 AI" in note
    assert "연결되지 않았" not in note


def test_no_verified_pc_guides_the_connection() -> None:
    note = pc_turn_note(())
    assert note == PC_TOOLS_ABSENT_NOTE
    assert "연결하는 방법" in note


# --- the command rule is Claw's rule ------------------------------------
def test_the_owners_own_backtick_command_is_authorized() -> None:
    assert lane.chat_pc_command_for_turn(COMMAND_TEXT) == "whoami"


@pytest.mark.parametrize("text", [
    "내 PC에서 whoami 실행해",              # no delimiter
    "내 PC에서 `whoami` `hostname` 실행해",  # two spans: not one command
    "내 PC 명령 실행 계획을 알려줘",          # describes, never executes
    "`whoami`",                            # no PC marker
])
def test_ambiguous_text_is_never_a_command(text: str) -> None:
    assert lane.chat_pc_command_for_turn(text) is None


def test_a_natural_pc_state_query_uses_the_same_bounded_command() -> None:
    command = lane.chat_pc_command_for_turn("내 컴퓨터에 데이터베이스가 있나?")
    assert isinstance(command, str) and "Get-ChildItem" in command


# --- dispatch: owner turn + verified PC, no other authority --------------
class _Store:
    def __init__(self) -> None:
        self.begun: list[dict] = []
        self.statuses: list[tuple] = []

    async def begin_chat_stream_turn(self, **fields):
        self.begun.append(dict(fields))
        return "chat_conversation_1"

    async def update_claw_run_status(self, uid, run_id, status):
        self.statuses.append((uid, run_id, status))


def _install_dispatch(monkeypatch, *, status: int = 200) -> dict:
    calls: dict = {}

    async def fake_dispatch(request, *, command, wire, **kwargs):
        calls.update({"command": command, "wire": wire})
        return SimpleNamespace(status_code=status)

    import app.oracle_mesh_read_return_routes as mesh

    monkeypatch.setattr(mesh, "dispatch_oracle_mesh_command_intent", fake_dispatch)
    return calls


def _dispatch(*, store: _Store):
    return asyncio.run(lane.dispatch_chat_pc_command(
        object(), uid="owner", raw={}, user_text=COMMAND_TEXT, command="whoami",
        pc_context=CONTEXT, conversation_id=None, store=store,
    ))


def test_a_dispatch_uses_the_verified_pc_and_this_owners_turn(monkeypatch) -> None:
    store = _Store()
    calls = _install_dispatch(monkeypatch)

    response = _dispatch(store=store)
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["decision_status"] == "pc_command_pending"
    assert body["pc_run_id"].startswith("chat_pcq_")
    assert body["conversation_id"] == "chat_conversation_1"
    assert calls["command"] == "whoami"
    assert calls["wire"]["confirmed"] is True
    assert calls["wire"]["device_id"] == DEVICE_ID
    assert calls["wire"]["run_id"] == body["pc_run_id"]
    assert store.begun[0]["run_id"] == body["pc_run_id"]
    assert store.begun[0]["workspace_id"] == "workspace_1"


def test_a_failed_dispatch_settles_the_staged_run(monkeypatch) -> None:
    store = _Store()
    _install_dispatch(monkeypatch, status=503)

    response = _dispatch(store=store)

    assert response.status_code == 502
    assert json.loads(response.body)["error"]["code"] == "chat_pc_command_dispatch_failed"
    assert store.statuses and store.statuses[0][2] == "failed"


# --- the route: command lane first, verified sentence otherwise ----------
class _Bridge:
    ready = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            conversation_id="chat_generic", user_text=kwargs.get("user_text"),
            answer="일반 답변", orchestration={"status": "completed"},
            decision_status="completed",
        )

    async def start_stream(self, **kwargs):  # pragma: no cover - JSON path only
        self.calls.append(dict(kwargs))
        yield {"event": dict(event_id="evt_1", run_id="engine_1", trace_id="trace_1",
                             app_id="padiem-chat", kind="run_started", sequence=1)}


def _request(payload: dict, bridge: _Bridge, *, store: _Store) -> Request:
    request = Request({
        "type": "http", "method": "POST", "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=bridge,
            history_store=store,
            usage_gate_enforced=False,
            usage_gate=None,
            settings=SimpleNamespace(runtime_mode="mock"),
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def _call(request: Request):
    async def run():
        response = await routes.api_orchestration(request)
        if hasattr(response, "body_iterator"):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk.encode() if isinstance(chunk, str) else chunk
            return SimpleNamespace(status_code=response.status_code, body=body)
        return response

    return asyncio.run(run())


def _install(monkeypatch, *, pc_context, connected: bool, dispatch=None) -> _Bridge:
    import app.chat_pc_drive as chat_pc_drive
    import app.chat_pc_command as chat_command

    bridge = _Bridge()

    async def context(request, *, uid, requested_device_id=None, user_text=None):
        return pc_context

    async def connection(request, *, uid, requested_device_id=None):
        return connected

    monkeypatch.setattr(chat_pc_drive, "resolve_chat_pc_stream_context", context)
    monkeypatch.setattr(chat_pc_drive, "chat_pc_connection_available", connection)
    # The route's readiness guard requires the concrete bridge contract; these
    # tests own the routing question, so they supply a ready bridge directly.
    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    if dispatch is not None:
        monkeypatch.setattr(chat_command, "dispatch_chat_pc_command", dispatch)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "owner")
    return bridge


def test_a_command_turn_dispatches_instead_of_answering_a_remote_ai_limit(monkeypatch) -> None:
    seen: list[dict] = []

    async def dispatch(request, **kwargs):
        seen.append(dict(kwargs))
        from starlette.responses import JSONResponse
        return JSONResponse({"answer": "실행 중", "decision_status": "pc_command_pending",
                             "pc_run_id": "chat_pcq_" + "a" * 32})

    bridge = _install(monkeypatch, pc_context=CONTEXT, connected=True, dispatch=dispatch)
    response = _call(_request({"messages": [{"role": "user", "content": COMMAND_TEXT}]},
                              bridge, store=_Store()))

    assert response.status_code == 200
    assert json.loads(response.body)["decision_status"] == "pc_command_pending"
    assert seen and seen[0]["command"] == "whoami"
    assert seen[0]["pc_context"] == CONTEXT
    assert bridge.calls == []


def test_without_a_verified_pc_the_same_command_stays_a_normal_answer(monkeypatch) -> None:
    bridge = _install(monkeypatch, pc_context=None, connected=False)
    response = _call(_request({"messages": [{"role": "user", "content": COMMAND_TEXT}]},
                              bridge, store=_Store()))

    assert response.status_code == 200
    assert json.loads(response.body)["answer"] == "일반 답변"
    assert len(bridge.calls) == 1
    context = bridge.calls[0].get("additional_system_context") or ""
    assert PC_TOOLS_ABSENT_NOTE in context
    assert "연결하는 방법" in context


def test_a_connected_pc_without_tools_carries_the_connected_sentence(monkeypatch) -> None:
    bridge = _install(monkeypatch, pc_context=None, connected=True)
    response = _call(_request(
        {"messages": [{"role": "user", "content": "내 컴퓨터 상태 알려줘"}]},
        bridge, store=_Store(),
    ))

    assert response.status_code == 200
    context = bridge.calls[0].get("additional_system_context") or ""
    assert PC_TOOLS_CONNECTED_NOTE in context
    assert PC_TOOLS_ABSENT_NOTE not in context
