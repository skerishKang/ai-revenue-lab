"""#5573: real POST /api/orchestration with a fake model and Engine bridge.

The PC lane is exercised end to end through the HTTP route. The model seam
(app.state.b14_client) and the Engine seam (app.state.orchestration_bridge)
are fakes, so no model provider and no PC are contacted.
"""

from __future__ import annotations

import json

import httpx
import pytest

import app.chat_pc_drive as lane
import app.pc_work_context as pc_work_context
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.orchestration_routes import install_orchestration_routes
from app.orchestration_bridge import B62EngineOrchestrationBridge

ORIGIN = "https://chat.example.test"
OWNER = "usr_" + "4" * 32
SESSION_SECRET = "issue-5573-http-boundary-session-secret-000000000000"
DEVICE = "node/meshdomain1/owner-pc"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="unit-test-client.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


class _Store:
    async def get_user(self, user_id):
        return None

    async def list_projects(self, user_id):
        return []

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        return {"conversation_id": conversation_id}

    async def append_exchange(self, user_id, conversation_id, user_text, answer, *, product_scope):
        return conversation_id or ("chat_" + "n" * 32)

    async def record_chat_pc_drive_run(self, **fields):
        return "chat_" + "s" * 32


class _B14:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def complete(self, messages, skill, additional_system_context=None):
        self.calls.append({"messages": tuple(messages), "contract": additional_system_context})
        return {"answer": self.answers.pop(0)}


class _Bridge(B62EngineOrchestrationBridge):
    def __init__(self):
        super().__init__(client=object(), store=object())
        self.requests = []

    async def start(self, **fields):
        self.requests.append(fields)
        return type("Outcome", (), {
            "answer": "ok", "public": {"answer": "ok"},
            "conversation_id": "chat_" + "s" * 32,
            "user_text": "request", "orchestration": {},
            "decision_status": "complete",
        })()


def _wire(monkeypatch, *, answers, selected=True, owner_raises=False):
    app = create_app(settings=_settings(), history_store=_Store())
    install_orchestration_routes(app, None)
    b14 = _B14(answers)
    bridge = _Bridge()
    app.state.b14_client = b14
    app.state.orchestration_bridge = bridge

    async def _owner(request, uid):
        if owner_raises:
            raise lane.ChatPCDriveError("chat_pc_owner_unavailable", "denied", 503)
        return type("S", (), {"session_id": "sess_5573"})(), OWNER, "tenant-1"

    async def _grant(request, session, *, device_id=None):
        return True

    async def _read(request, *, owner_id, workspace_id):
        if selected:
            return type("Sel", (), {"status": pc_work_context.SAVED_SELECTION_SELECTED, "device_id": DEVICE})()
        return type("Sel", (), {"status": pc_work_context.SAVED_SELECTION_UNAVAILABLE, "device_id": None})()

    async def _resolve(request, **kwargs):
        return type("Ctx", (), {
            "devices": [type("D", (), {"device_id": DEVICE, "state": "READY"})()],
            "selected_confirmed": True,
            "execution": type("E", (), {"ready": True})(),
        })()

    async def _save(*args, **kwargs):
        return "chat_" + "c" * 32

    async def _append(*args, **kwargs):
        return True

    monkeypatch.setattr(lane, "_resolve_chat_owner", _owner)
    monkeypatch.setattr(lane, "_check_mesh_grant", _grant)
    monkeypatch.setattr(lane, "_save_pair", _save)
    monkeypatch.setattr(lane, "_append_lane_answer", _append)
    monkeypatch.setattr(pc_work_context, "read_saved_device_selection", _read)
    monkeypatch.setattr(pc_work_context, "resolve_pc_work_context", _resolve)
    monkeypatch.setattr(pc_work_context, "render_pc_work_context", lambda ctx: "selected PC")
    return app, b14, bridge


def _client(app):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
    client.cookies.set(SESSION_COOKIE, create_session_token(_settings(), OWNER), domain="chat.example.test", path="/")
    return client


async def _post(app, text):
    async with _client(app) as client:
        return await client.post(
            "/api/orchestration",
            headers={"Origin": ORIGIN},
            json={"messages": [{"role": "user", "content": text}], "skill": "auto"},
        )


POSSESSIVE = "PC\uc758 "
INNER = "\ub0b4 PC\uc758 "
DEEP = "C:\\Users\\limone\\AppData\\Local\\Padiem\\MeshCentralTrial\\5015-conditions-20261022 "
LIST = "\ud3f4\ub354\uc5d0 \uc788\ub294 \ud30c\uc77c \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918"


async def test_possessive_qualifier_enters_the_pc_lane_through_http(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_list"}'])
    response = await _post(app, POSSESSIVE + DEEP + LIST)
    assert response.status_code == 200
    assert len(bridge.requests) == 1
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == ["claw.pc.list_files"]
    assert sent["tool_arguments"] == {"files_list": {"device_id": DEVICE}}
    assert len(b14.calls) == 1


async def test_inner_qualifier_keeps_the_list_read_plan(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_read"}'])
    response = await _post(app, INNER + "MeshCentralTrial \ud3f4\ub354\uc5d0\uc11c \ud30c\uc77c \ub0b4\uc6a9 \uc124\uba85\ud574\uc918")
    assert response.status_code == 200
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == [
        "claw.pc.list_files", "claw.pc.read_file",
    ]
    assert sent["tool_arguments"] == {"files": {"device_id": DEVICE}}


async def test_general_turn_does_not_reach_the_pc_boundary(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, answers=['{"action":"none"}', "general answer"])
    response = await _post(app, "\uc624\ub298 \ub0a0\uc528 \uc5b4\ub54c?")
    assert not any("agent_plan" in req for req in bridge.requests)
    assert response.status_code == 200, response.text


async def test_quoted_or_negative_pc_words_do_not_execute(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, answers=['{"action":"none"}', "not executed"])
    response = await _post(app, "\ub0b4 PC \ud30c\uc77c\uc740 \uc77d\uc9c0 \ub9c8\uace0 \uadf8\ubb38\uc7a5\ub9cc \uc778\uc6a9\ud574\uc918")
    assert not any("agent_plan" in req for req in bridge.requests)
    assert response.status_code == 200, response.text


async def test_ambiguous_turn_returns_a_question(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, answers=['{"action":"clarify","answer":"\uc5b4\ub290 PC\uc778\uac00\uc694?"}'])
    response = await _post(app, "\uadf8\uac83 \ubcf4\uc5ec\uc918")
    assert response.status_code == 200
    assert bridge.requests == []
    assert b14.calls and len(b14.calls) == 1


async def test_clear_pc_request_without_authority_is_a_refusal(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, answers=[], owner_raises=True)
    response = await _post(app, "\ub0b4 PC \ub4dc\ub77c\uc774\ube0c \uc54c\ub824\uc918")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "chat_pc_owner_unavailable"
    assert bridge.requests == []
    assert b14.calls == []


async def test_no_selected_pc_clear_request_is_a_refusal(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_list"}'], selected=False)
    response = await _post(app, POSSESSIVE + DEEP + LIST)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "chat_pc_selection_unavailable"
    assert bridge.requests == []
    assert len(b14.calls) == 1


async def test_browser_target_override_is_refused(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_list"}'])
    async with _client(app) as client:
        response = await client.post(
            "/api/orchestration",
            headers={"Origin": ORIGIN},
            json={
                "messages": [{"role": "user", "content": POSSESSIVE + DEEP + LIST}],
                "skill": "auto",
                "device_id": "node/meshdomain1/other-owner-pc",
            },
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "chat_pc_selection_stale"
    assert bridge.requests == []
