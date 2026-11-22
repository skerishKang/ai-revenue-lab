"""공용 시험 준비 — PC HTTP 경계(선택·스트림·클라이언트 공용).

test_5573_pc_http_boundary가 들고 있던 공용 준비를 여기 옮겨
시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

import httpx
from types import SimpleNamespace

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
OTHER_DEVICE = "node/meshdomain1/other-owner-pc"
SECOND = "node/meshdomain1/n0t1$K_lipvoice"
PC_TEXT = (
    "내 PC의 MeshCentralTrial 폴더에서 파일 목록을 보고, "
    "meshcentral-padiem-trial.txt 파일 내용을 읽어줘"
)
LIST_ONLY = "PC의 5015-conditions-20261022 폴더에 있는 파일 목록만 보여줘"
PLAIN_TEXT = "3과 5의 최소공배수를 한 문장으로 답해줘"
PC_RUN = "chat_pcq_" + "a" * 32


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock", auth_mode="google", public_base_url=ORIGIN,
        google_client_id="unit-test-client.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET, session_max_age_seconds=3600,
    )


class _Store:
    """Chat history that records every staging attempt, with a failable seam."""

    def __init__(self):
        self.staged = []
        self.pending_turns = []
        self.answers = []
        self.fail = None
        self.run_row = None

    def _fail(self, method):
        if self.fail == method:
            raise RuntimeError("D1_ERROR: database is locked")

    async def get_user(self, user_id):
        return None

    async def list_projects(self, user_id):
        return []

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        return {"conversation_id": conversation_id}

    async def append_exchange(
        self, user_id, conversation_id, user_text, answer, *, product_scope,
    ):
        return conversation_id or ("chat_" + "n" * 32)

    async def record_chat_pc_drive_run(self, **fields):
        self._fail("record_chat_pc_drive_run")
        self.staged.append(fields)
        return "chat_" + "s" * 32

    async def get_claw_run(self, user_id, run_id):
        self._fail("get_claw_run")
        return self.run_row

    async def seal_run_terminal(self, **fields):
        self._fail("seal_run_terminal")
        return True

    async def append_local_task_result(self, **fields):
        self._fail("append_local_task_result")
        return True

    async def begin_chat_stream_turn(self, **fields):
        self.pending_turns.append(fields)
        return "chat_" + "s" * 32

    async def finish_chat_stream_turn(self, **fields):
        self.answers.append(fields)
        return "chat_" + "s" * 32

    async def get_pc_run_scope_notice(self, *, user_id: str, run_id: str):
        return None


class _Bridge(B62EngineOrchestrationBridge):
    """The ordinary Engine turn, recorded instead of sent."""

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


    async def start_stream(self, **fields):
        from app.orchestration_bridge import B62OrchestrationResult
        self.requests.append(fields)
        events = [
            {"event_id": "evt_1", "run_id": "run_1", "trace_id": "trace_1",
             "app_id": "padiem-chat", "kind": "run_started", "sequence": 1},
            {"event_id": "evt_2", "run_id": "run_1", "trace_id": "trace_1",
             "app_id": "padiem-chat", "kind": "run_completed", "sequence": 2},
        ]
        yield {"event": events[0]}
        yield {"text_delta": {"delta": "ok"}}
        yield {"event": events[1]}
        yield {"result": B62OrchestrationResult(
            {"events": events, "approval_pause": None, "continuation_ref": None, "answer": "ok"},
            "ok", fields["user_text"], fields["conversation_id"],
        )}


def _wire(monkeypatch, *, selected=True, devices=True, mesh_ready=True,
          tools_declared=True):
    """A signed-in Chat turn over the real route, with each boundary faked.

    ``selected``/``devices``/``mesh_ready`` drive the *real* verification chain
    ``chat_pc_tools_available`` runs. Only the catalog read and the owner
    session are replaced, because no live B14 or Control Plane is contacted.
    """
    context = pc_work_context.PcWorkContext(
        broker_status="ready" if devices else "no_device",
        devices=(
            pc_work_context.PcWorkDevice(DEVICE, None, "CONNECTED", True),
        ) if devices else (),
        execution=pc_work_context.PcExecutionTarget(
            status="ready" if mesh_ready else "no_target",
            device_id=DEVICE if mesh_ready else None,
        ),
        mapping="confirmed" if mesh_ready else "unknown",
        selected_device_id=DEVICE if selected is True else None,
        saved_selection_status=(
            pc_work_context.SAVED_SELECTION_SELECTED if selected is True
            else pc_work_context.SAVED_SELECTION_UNAVAILABLE
            if selected is False else pc_work_context.SAVED_SELECTION_NONE
        ),
    )

    store = _Store()
    app = create_app(settings=_settings(), history_store=store)
    install_orchestration_routes(app, None)
    bridge = _Bridge()
    app.state.orchestration_bridge = bridge

    async def _declares(request, model_id):
        return tools_declared

    async def _owner(request, uid):
        return type("S", (), {"session_id": "sess_5573"})(), OWNER, "tenant-1"

    async def _grant(request, session, *, device_id=None, owner_ref=None):
        return True

    async def _read(request, *, owner_id, workspace_id):
        if selected is True:
            return type("Sel", (), {
                "status": pc_work_context.SAVED_SELECTION_SELECTED,
                "device_id": DEVICE,
            })()
        if selected is False:
            return type("Sel", (), {
                "status": pc_work_context.SAVED_SELECTION_UNAVAILABLE,
                "device_id": None,
            })()
        return type("Sel", (), {
            "status": pc_work_context.SAVED_SELECTION_NONE, "device_id": None,
        })()

    async def _resolve(request, **kwargs):
        return context

    async def _file_target(*args, **kwargs):
        return {"root": "C:/approved"}, None
    from app import oracle_mesh_read_return_routes as mesh_routes
    monkeypatch.setattr(mesh_routes, "_engine_pc_files_target", _file_target)
    monkeypatch.setattr(lane, "chat_pc_route_declares_tools", _declares)
    monkeypatch.setattr(lane, "_resolve_chat_owner", _owner)
    monkeypatch.setattr(lane, "_check_mesh_grant", _grant)
    monkeypatch.setattr(pc_work_context, "read_saved_device_selection", _read)
    monkeypatch.setattr(pc_work_context, "resolve_pc_work_context", _resolve)
    monkeypatch.setattr(
        pc_work_context, "render_pc_work_context",
        lambda ctx: "selected PC: " + DEVICE,
    )
    return app, bridge, store


def _client(app):
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
    )
    client.cookies.set(
        SESSION_COOKIE, create_session_token(_settings(), OWNER, canonical_session_id="session_test_a"),
        domain="chat.example.test", path="/",
    )
    return client


async def _post(app, text, *, device_id=None, pc_run_id=None):
    body = {"messages": [{"role": "user", "content": text}], "skill": "auto"}
    if device_id is not None:
        body["device_id"] = device_id
    if pc_run_id is not None:
        body["pc_run_id"] = pc_run_id
    async with _client(app) as client:
        return await client.post(
            "/api/orchestration", headers={"Origin": ORIGIN}, json=body,
        )


async def test_a_pc_capable_turn_uses_one_engine_stream_with_server_context(monkeypatch):
    app, bridge, store = _wire(monkeypatch)
    response = await _post(app, PC_TEXT, pc_run_id=PC_RUN)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: delta") == 1
    assert response.text.count('"delta":"ok"') == 1
    assert len(bridge.requests) == 1
    assert bridge.requests[0]["pc_tools"] == {
        "device_id": DEVICE, "allowed_scopes": ["query_drives", "browser", "files_list", "files"],
    }
    assert bridge.requests[0]["session_id"] == PC_RUN
    assert store.staged == []
    assert len(store.pending_turns) == len(store.answers) == 1


async def test_no_wording_decides_the_engine_pc_tools_offer(monkeypatch):
    """#6686: only a turn that names PC work attaches the PC lane.

    A PC sentence carries its tools; an ordinary question keeps the plain
    Engine turn (no tools, no PC-lane Engine admission), so a general question
    can never fail on the PC boundary.
    """
    app, bridge, store = _wire(monkeypatch)
    response = await _post(app, PC_TEXT, pc_run_id=PC_RUN)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(bridge.requests) == 1
    assert bridge.requests[0]["pc_tools"]["device_id"] == DEVICE
    # A user turn receipt is not a PC run. Only an actual signed tool
    # callback can promote one; an ordinary text answer stages none.
    assert store.staged == []

    plain_app, plain_bridge, _plain_store = _wire(monkeypatch)
    response = await _post(plain_app, PLAIN_TEXT, pc_run_id=PC_RUN)
    assert response.status_code == 200, response.text
    assert len(plain_bridge.requests) == 1
    assert "pc_tools" not in plain_bridge.requests[0]


async def test_route_capability_is_left_to_the_engine_without_a_classifier_call(monkeypatch):
    app, bridge, store = _wire(monkeypatch, tools_declared=False)
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("No Chat classification/model request permitted")
    monkeypatch.setattr(lane, "chat_pc_route_declares_tools", forbidden)
    monkeypatch.setattr(lane, "execute_chat_pc_drive_lane", forbidden)
    # The turn names PC work; the entry check (route declares tools) belongs
    # to the Chat lane and stays unconsulted here — the Engine stream carries
    # the server-authored context with no Chat classification call.
    response = await _post(app, PC_TEXT, pc_run_id=PC_RUN)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(bridge.requests) == 1 and calls == []
    assert bridge.requests[0]["pc_tools"]["device_id"] == DEVICE
    assert store.staged == []


async def test_an_unreadable_saved_target_withholds_the_entry(monkeypatch):
    """A selection that cannot be read is fail-closed: no tools, no PC run.

    The old surface answered this with a 503 refusal of the PC turn. Entry now
    belongs to the model, so this route keeps answering the turn in text and
    never executes on a target it cannot verify.
    """
    app, bridge, store = _wire(monkeypatch, selected=False)
    response = await _post(app, PC_TEXT)

    assert response.status_code == 200, response.text
    # The ordinary Engine turn ran, and it carried no PC plan and no target.
    assert len(bridge.requests) == 1
    assert "agent_plan" not in bridge.requests[0]
    assert "tool_arguments" not in bridge.requests[0]
    assert store.staged == []


async def test_a_mesh_only_account_is_not_asked_to_register_a_pc(monkeypatch):
    """Native registration stays optional: no Broker device still defers."""
    app, bridge, store = _wire(monkeypatch, devices=False)
    response = await _post(app, LIST_ONLY)

    assert response.status_code == 200, response.text
    assert bridge.requests[0]["pc_tools"]["device_id"] == DEVICE
    assert store.staged == []


async def test_no_verified_target_at_all_keeps_the_ordinary_engine_turn(monkeypatch):
    """No device and no Mesh target: the turn stays a plain Engine answer."""
    app, bridge, store = _wire(
        monkeypatch, selected=None, devices=False, mesh_ready=False,
    )
    response = await _post(app, PC_TEXT)

    assert response.status_code == 200, response.text
    assert len(bridge.requests) == 1
    assert store.staged == []


async def test_a_browser_target_and_handle_are_never_a_plan(monkeypatch):
    """A browser-selected device or recovery handle grants nothing on this surface."""
    app, bridge, store = _wire(monkeypatch)
    response = await _post(
        app, PC_TEXT, device_id=OTHER_DEVICE, pc_run_id=PC_RUN,
    )

    assert response.status_code == 200, response.text
    # A stale target cannot silently execute against a different saved PC.
    assert "pc_tools" not in bridge.requests[0]
    assert store.pending_turns == []
    assert store.staged == []
