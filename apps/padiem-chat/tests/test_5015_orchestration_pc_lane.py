"""#5015/#5573: the orchestration surface and the model-tool PC entry.

The server offers PC tools on its existing Engine turn. Only a signed tool
callback may promote the stored user turn into a PC run. Wording never selects
this transport and the browser never supplies an admitted plan.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from starlette.requests import Request

from app import orchestration_routes as routes
from app.chat_pc_drive import ChatPCDriveError


PC_TEXT = "내 PC의 MeshCentralTrial 폴더에서 파일 목록을 보고, meshcentral-padiem-trial.txt 파일 내용을 읽어줘"
PLAIN_TEXT = "3과 5의 최소공배수를 한 문장으로 답해줘"
DEVICE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"


class _Lane:
    """The existing PC lane, recorded instead of executed."""

    def __init__(self, outcome=None, error: ChatPCDriveError | None = None) -> None:
        self.outcome = outcome
        self.error = error
        self.calls: list[dict] = []

    async def __call__(self, request, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.outcome


class _Bridge:
    """A ready orchestration bridge with a recorded generic call."""

    ready = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            conversation_id="chat_generic",
            user_text=kwargs.get("user_text"),
            answer="일반 답변",
            orchestration={"status": "completed"},
            decision_status="completed",
        )


    async def start_stream(self, **kwargs):
        self.calls.append(kwargs)
        events = [dict(event_id="evt_" + str(n), run_id="engine_1", trace_id="trace_1",
            app_id="padiem-chat", kind=kind, sequence=n)
            for n, kind in enumerate(("run_started", "run_completed"), 1)]
        for event in events:
            yield {"event": event}
        yield {"result": SimpleNamespace(
            orchestration=dict(events=events, approval_pause=None), answer="answer")}


class _Store:
    async def begin_chat_stream_turn(self, **fields):
        return "chat_generic"
    async def finish_chat_stream_turn(self, **fields):
        return "chat_generic"


def _call(request):
    async def run():
        response = await routes.api_orchestration(request)
        if hasattr(response, "body_iterator"):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk.encode() if isinstance(chunk, str) else chunk
            return SimpleNamespace(status_code=response.status_code, body=body)
        return response
    return asyncio.run(run())


def _install(monkeypatch, lane: _Lane, *, pc_entry: bool = False) -> _Bridge:
    import app.chat_pc_drive as chat_pc_drive

    bridge = _Bridge()
    monkeypatch.setattr(chat_pc_drive, "execute_chat_pc_drive_lane", lane)

    async def _available(request, *, uid, requested_device_id=None, user_text=None):
        if not pc_entry or (requested_device_id is not None and requested_device_id != DEVICE_ID):
            return None
        return {"pc_tools": {"device_id": DEVICE_ID, "allowed_scopes": ["files_list"]},
                "subject_id": "subject_1", "workspace_id": "workspace_1"}

    monkeypatch.setattr(chat_pc_drive, "resolve_chat_pc_stream_context", _available)
    # The route's readiness guard requires the concrete bridge contract; this
    # test owns the routing question, so it supplies a ready bridge directly.
    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "owner")
    return bridge


def _request(payload: dict, bridge: _Bridge) -> Request:
    request = Request({
        "type": "http", "method": "POST", "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=bridge,
            history_store=_Store(),
            usage_gate_enforced=False,
            usage_gate=None,
            settings=SimpleNamespace(runtime_mode="mock"),
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def test_a_pc_capable_turn_uses_the_same_engine_stream(monkeypatch):
    """Offer tools on the same Engine turn without a second Chat executor."""
    lane = _Lane(outcome=("PC 파일 목록 결과", "chat_pc"))
    bridge = _install(monkeypatch, lane, pc_entry=True)

    response = _call(_request({
        "messages": [{"role": "user", "content": PC_TEXT}],
        "tier": "plus",
        "device_id": DEVICE_ID,
    }, bridge))
    assert response.status_code == 200
    assert b"event: done" in response.body
    assert len(bridge.calls) == 1 and lane.calls == []
    assert bridge.calls[0]["pc_tools"]["device_id"] == DEVICE_ID
    assert "agent_plan" not in bridge.calls[0]


@pytest.mark.parametrize("text", [PC_TEXT, PLAIN_TEXT])
def test_no_wording_decides_whether_the_engine_gets_pc_tools(monkeypatch, text):
    """A PC sentence and an ordinary question offer the same verified tools."""
    lane = _Lane(outcome=None)
    bridge = _install(monkeypatch, lane, pc_entry=True)

    response = _call(_request({
        "messages": [{"role": "user", "content": text}],
    }, bridge))
    assert response.status_code == 200
    assert len(bridge.calls) == 1 and lane.calls == []
    assert bridge.calls[0]["pc_tools"]["allowed_scopes"] == ["files_list"]


def test_a_non_pc_turn_keeps_the_ordinary_orchestration_path(monkeypatch):
    lane = _Lane(outcome=None)
    bridge = _install(monkeypatch, lane)

    response = _call(_request({
        "messages": [{"role": "user", "content": PLAIN_TEXT}],
    }, bridge))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["answer"] == "일반 답변"
    # Without a verified PC the generic bridge body remains unchanged.
    assert len(bridge.calls) == 1
    assert lane.calls == []


def test_browser_handles_never_become_a_plan_or_execution_grant(monkeypatch):
    bridge = _install(monkeypatch, _Lane(outcome=None), pc_entry=True)

    response = _call(_request({
        "messages": [{"role": "user", "content": PC_TEXT}],
        "device_id": DEVICE_ID,
        "pc_run_id": "chat_pcq_" + "f" * 32,
    }, bridge))
    assert response.status_code == 200
    assert len(bridge.calls) == 1
    assert bridge.calls[0]["session_id"] == "chat_pcq_" + "f" * 32
    assert bridge.calls[0]["pc_tools"] == {"device_id": DEVICE_ID, "allowed_scopes": ["files_list"]}
    assert "agent_plan" not in bridge.calls[0] and "tool_arguments" not in bridge.calls[0]


def test_the_surface_has_no_second_pc_executor_or_target_store():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"
    ).read_text(encoding="utf-8")
    # The surface offers server-authored context, not another executor or plan.
    assert "from .chat_pc_drive import resolve_chat_pc_stream_context" in source
    assert "execute_chat_pc_drive_lane" not in source
    assert "agent_plan" not in source
    assert "tool_arguments" not in source
    assert "_CHAT_PC_MARKERS" not in source


@pytest.mark.parametrize('pc_entry', [False, True])
def test_byok_opt_in_uses_same_engine_turn_with_verified_pc_context(monkeypatch, pc_entry):
    import app.byok_bridge as byok
    from app.byok_credentials import CUSTOM_PROVIDERS
    lane = _Lane()
    bridge = _install(monkeypatch, lane, pc_entry=pc_entry)
    async def credential(state, *, uid, selection):
        assert uid == 'owner'
        return SimpleNamespace(endpoint=CUSTOM_PROVIDERS['gemini'].base_origin, api_key='unit-byok-not-real-secret')
    monkeypatch.setattr(byok, 'resolve_owner_custom_credential', credential)
    request = _request({'messages':[{'role':'user','content':PC_TEXT}],
        'custom':{'provider':'gemini','model':'gemini-unit-model'}, 'device_id':DEVICE_ID}, bridge)
    request.app.state.settings.byok_via_b14 = True
    response = _call(request)
    assert response.status_code == 200
    assert b'unit-byok-not-real-secret' not in response.body
    assert len(bridge.calls) == 1 and lane.calls == []
    sent = bridge.calls[0]
    assert sent['model_id'] == 'google/gemini-unit-model'
    assert json.loads(sent['user_credential_ref'])['provider'] == 'google'
    assert (sent['pc_tools'] is not None) == pc_entry
    if pc_entry:
        assert sent['pc_tools'] == {'device_id':DEVICE_ID,'allowed_scopes':['files_list']}


def test_byok_default_off_refuses_orchestration_before_key_resolution(monkeypatch):
    import app.byok_bridge as byok
    bridge = _install(monkeypatch, _Lane(), pc_entry=True)
    async def forbidden(*args, **kwargs):
        raise AssertionError('off must not resolve a credential')
    monkeypatch.setattr(byok, 'resolve_owner_custom_credential', forbidden)
    response = _call(_request({'messages':[{'role':'user','content':PLAIN_TEXT}],
        'custom':{'provider':'gemini','model':'gemini-unit-model'}}, bridge))
    assert response.status_code == 409
    assert json.loads(response.body)['error']['code'] == 'orchestration_not_applicable'
    assert bridge.calls == []
