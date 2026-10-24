"""#5573 interim PC entry over the real POST /api/orchestration route.

Explicit PC requests carry the whole turn into Engine; the model and Engine seams are fakes,
so no provider and no PC is contacted.
"""

from __future__ import annotations

import httpx
import pytest

import app.chat_pc_drive as lane
import app.pc_work_context as pc_work_context
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app.orchestration_routes import install_orchestration_routes

ORIGIN = "https://chat.example.test"
OWNER = "usr_" + "4" * 32
SESSION_SECRET = "issue-5573-http-boundary-session-secret-000000000000"
DEVICE = "node/meshdomain1/owner-pc"
POSSESSIVE = "PC\uc758 "
INNER = "\ub0b4 PC\uc758 "
DEEP = "C:\\Users\\limone\\AppData\\Local\\Padiem\\MeshCentralTrial\\5015-conditions-20261022 "
LIST = "\ud3f4\ub354\uc5d0 \uc788\ub294 \ud30c\uc77c \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock", auth_mode="google", public_base_url=ORIGIN,
        google_client_id="unit-test-client.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET, session_max_age_seconds=3600,
    )


class _Store:
    scope_notice = None

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

    async def get_pc_run_scope_notice(self, *, user_id: str, run_id: str):
        return self.scope_notice


class _B14:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, skill=None, additional_system_context=None):
        self.calls.append(additional_system_context)
        return {"answer": "general answer"}


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


def _wire(monkeypatch, *, selected=True, devices=True, owner_raises=False, scope_notice=None):
    store = _Store()
    store.scope_notice = scope_notice
    app = create_app(settings=_settings(), history_store=store)
    install_orchestration_routes(app, None)
    b14 = _B14()
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
        if selected is True:
            return type("Sel", (), {"status": pc_work_context.SAVED_SELECTION_SELECTED, "device_id": DEVICE})()
        if selected is False:
            return type("Sel", (), {"status": pc_work_context.SAVED_SELECTION_UNAVAILABLE, "device_id": None})()
        return type("Sel", (), {"status": pc_work_context.SAVED_SELECTION_NONE, "device_id": None})()

    async def _resolve(request, **kwargs):
        rows = [type("D", (), {"device_id": DEVICE, "state": "READY"})()] if devices else []
        return type("Ctx", (), {
            "devices": rows, "selected_confirmed": True, "tool_available": True,
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


async def _post(app, messages, *, device_id=None, pc_run_id=None):
    body = {"messages": messages, "skill": "auto"}
    if device_id is not None:
        body["device_id"] = device_id
    if pc_run_id is not None:
        body["pc_run_id"] = pc_run_id
    async with _client(app) as client:
        return await client.post("/api/orchestration", headers={"Origin": ORIGIN}, json=body)


def _pc_plan_requests(bridge):
    return [req for req in bridge.requests if "agent_plan" in req]


@pytest.mark.parametrize("qualifier, expected_pc_calls", [(POSSESSIVE, 0), (INNER, 1)])
async def test_interim_pc_qualifier_controls_pc_lane_entry(monkeypatch, qualifier, expected_pc_calls):
    app, b14, bridge = _wire(monkeypatch)
    response = await _post(app, [{"role": "user", "content": qualifier + DEEP + LIST}])
    assert response.status_code == 200, response.text
    requests = _pc_plan_requests(bridge)
    assert len(requests) == expected_pc_calls
    if expected_pc_calls:
        assert requests[0]["tool_arguments"] == {"files": {"device_id": DEVICE}}
        assert [step["tool_id"] for step in requests[0]["agent_plan"]["steps"]] == [
            "claw.pc.list_files", "claw.pc.read_file",
        ]
    assert b14.calls == []


async def test_inner_qualifier_read_request_keeps_the_read_plan(monkeypatch):
    app, b14, bridge = _wire(monkeypatch)
    response = await _post(app, [{"role": "user", "content": INNER + "sample.txt \ud30c\uc77c \ub0b4\uc6a9\uc744 \uc77d\uc5b4\uc918"}])
    assert response.status_code == 200, response.text
    requests = _pc_plan_requests(bridge)
    assert len(requests) == 1
    assert requests[0]["tool_arguments"] == {"files": {"device_id": DEVICE}}
    assert b14.calls == []


async def test_explicit_pc_follow_up_carries_the_prior_turns(monkeypatch):
    app, b14, bridge = _wire(monkeypatch)
    messages = [
        {"role": "user", "content": "5015-conditions-20261022 \ud3f4\ub354\ub97c \ubd24\uc5b4"},
        {"role": "assistant", "content": "\ubaa9\ub85d\uc744 \ud655\uc778\ud588\uc2b5\ub2c8\ub2e4."},
        {"role": "user", "content": INNER + "\uadf8 \ud3f4\ub354 \ud30c\uc77c \ubaa9\ub85d \ubcf4\uc5ec\uc918"},
    ]
    response = await _post(app, messages)
    assert response.status_code == 200, response.text
    requests = _pc_plan_requests(bridge)
    assert len(requests) == 1
    context = requests[0]["additional_system_context"]
    assert messages[0]["content"] in context
    assert messages[1]["content"] in context
    assert b14.calls == []


async def test_account_without_a_verified_pc_keeps_the_general_path(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, selected=None, devices=False)
    response = await _post(app, [{"role": "user", "content": "\uc624\ub298 \ub0a0\uc528 \uc5b4\ub54c?"}])
    assert response.status_code == 200, response.text
    assert _pc_plan_requests(bridge) == []


async def test_unreadable_selection_fails_closed_before_any_call(monkeypatch):
    app, b14, bridge = _wire(monkeypatch, selected=False)
    response = await _post(app, [{"role": "user", "content": INNER + DEEP + LIST}])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "chat_pc_selection_unavailable"
    assert bridge.requests == []
    assert b14.calls == []


async def test_browser_target_override_is_refused(monkeypatch):
    app, b14, bridge = _wire(monkeypatch)
    response = await _post(
        app, [{"role": "user", "content": INNER + DEEP + LIST}],
        device_id="node/meshdomain1/other-owner-pc",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "chat_pc_selection_stale"
    assert bridge.requests == []


PC_RUN = "chat_pcq_" + "a" * 32


async def test_completed_pc_lane_post_carries_the_pinned_scope_notice(monkeypatch):
    """#5573: the browser's live completion path carries the pinned scope."""
    from app.history import PC_SCOPE_NOTICE_LABELS

    app, b14, bridge = _wire(
        monkeypatch, scope_notice=PC_SCOPE_NOTICE_LABELS["files_list"],
    )
    response = await _post(
        app, [{"role": "user", "content": INNER + DEEP + LIST}],
        pc_run_id=PC_RUN,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope_notice"] == PC_SCOPE_NOTICE_LABELS["files_list"]
    assert body["scope_notice"] == "목록만 조회합니다. 파일 내용은 읽지 않습니다."
    assert body["answer"] == "ok"
    # The notice is its own field; the answer text never carries it.
    assert body["scope_notice"] not in body["answer"]
    assert len(_pc_plan_requests(bridge)) == 1


async def test_completed_pc_lane_post_without_a_scope_keeps_its_shape(monkeypatch):
    """#5573: no pinned scope means the response gains no field at all."""
    app, b14, bridge = _wire(monkeypatch)
    response = await _post(
        app, [{"role": "user", "content": INNER + DEEP + LIST}],
        pc_run_id=PC_RUN,
    )
    assert response.status_code == 200, response.text
    assert set(response.json()) == {
        "orchestration", "answer", "decision_status", "conversation_id",
    }
    assert b"scope_notice" not in response.content
    assert len(_pc_plan_requests(bridge)) == 1


@pytest.mark.parametrize("engine_code", ["unsupported_orchestration_field", "upstream_auth_error"])
async def test_pc_http_error_preserves_only_the_bounded_engine_cause(monkeypatch, engine_code):
    from app.orchestration_bridge import B62OrchestrationError
    app, b14, bridge = _wire(monkeypatch)
    async def fail(**fields):
        raise B62OrchestrationError(engine_code, "AI 작업을 처리하지 못했습니다.", status_code=400)
    async def notice(*args, **kwargs):
        return None
    monkeypatch.setattr(bridge, "start", fail)
    monkeypatch.setattr(lane, "_append_lane_notice", notice)
    response = await _post(app, [{"role": "user", "content": INNER + DEEP + LIST}])
    assert response.status_code == 400
    assert response.json()["error"] == {"code": "chat_pc_engine_unavailable",
        "message": "AI 작업을 처리하지 못했습니다.", "cause": engine_code}
    assert b14.calls == []


def test_pc_error_cause_rejects_unbounded_provider_material():
    error = lane.ChatPCDriveError("chat_pc_engine_unavailable", "failed", 400,
                                  cause="private-provider-response: " + "x" * 100)
    assert lane._error_response(error).body == b'{"ok":false,"error":{"code":"chat_pc_engine_unavailable","message":"failed"}}'
