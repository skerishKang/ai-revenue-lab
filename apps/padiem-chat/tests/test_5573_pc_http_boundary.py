"""#5573 (3-C-2) boundary: the orchestration surface and the model-tool PC entry.

These drive the real ``POST /api/orchestration`` route with a fake Engine
bridge and fake PC-context sources, so no provider, no Engine and no PC is
contacted. What they pin:

* a server-verified PC offers context to one Engine stream, where the model
  selects a tool; ordinary text creates no PC run;
* no wording decides that deferral, in either direction;
* an unverified PC, or a route without the ``tools`` capability, keeps the
  ordinary Engine turn and never reaches a PC plan;
* a browser-supplied target or recovery handle is never a plan, a target or a
  grant on this surface;
* the surface keeps no second PC executor, no second target store and no
  natural-language table that could drift back into a keyword gate.
"""

from __future__ import annotations

import httpx
import pytest

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

    async def _grant(request, session, *, device_id=None):
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
        SESSION_COOKIE, create_session_token(_settings(), OWNER),
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
        "device_id": DEVICE, "allowed_scopes": ["query_drives", "files_list", "files"],
    }
    assert bridge.requests[0]["session_id"] == PC_RUN
    assert store.staged == []
    assert len(store.pending_turns) == len(store.answers) == 1


async def test_no_wording_decides_the_engine_pc_tools_offer(monkeypatch):
    for text in (PC_TEXT, LIST_ONLY, PLAIN_TEXT):
        app, bridge, store = _wire(monkeypatch)
        response = await _post(app, text, pc_run_id=PC_RUN)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        assert len(bridge.requests) == 1
        assert bridge.requests[0]["pc_tools"]["device_id"] == DEVICE
        # A user turn receipt is not a PC run. Only an actual signed tool
        # callback can promote one; an ordinary text answer stages none.
        assert store.staged == []


async def test_route_capability_is_left_to_the_engine_without_a_classifier_call(monkeypatch):
    app, bridge, store = _wire(monkeypatch, tools_declared=False)
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("No Chat classification/model request permitted")
    monkeypatch.setattr(lane, "chat_pc_route_declares_tools", forbidden)
    monkeypatch.setattr(lane, "execute_chat_pc_drive_lane", forbidden)
    response = await _post(app, PLAIN_TEXT, pc_run_id=PC_RUN)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(bridge.requests) == 1 and calls == []
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


def test_the_surface_keeps_no_pc_execution_path_of_its_own():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"
    ).read_text(encoding="utf-8")
    # The surface reads the one existing availability decision and nothing else:
    # no lane call, no plan, no target hint, no natural-language table.
    assert "from .chat_pc_drive import resolve_chat_pc_stream_context" in source
    assert "execute_chat_pc_drive_lane" not in source
    assert "agent_plan" not in source
    assert "tool_arguments" not in source
    assert "_CHAT_PC_MARKERS" not in source

def test_pc_error_cause_keeps_only_an_internal_code_below_503():
    """#5742's bounded-cause contract, on the envelope this lane now uses."""
    error = lane.ChatPCDriveError(
        "chat_pc_engine_unavailable", "failed", 400,
        cause="private-provider-response: " + "x" * 100,
    )
    assert error.public_error() == {
        "code": "chat_pc_engine_unavailable", "message": "failed",
    }


@pytest.mark.parametrize("code", [
    "chat_pc_run_id_unavailable", "chat_pc_identity_unavailable",
    "chat_pc_store_unavailable", "chat_pc_selection_unavailable",
    "chat_pc_files_unavailable", "chat_pc_engine_unavailable",
])
def test_pc_503_cause_keeps_the_chained_exception_class_and_safe_message(code):
    """#5742: a 503 keeps the exception class and a safe first line.

    ``chat_pc_decision_invalid`` and ``chat_pc_model_unavailable`` are dropped
    from this list because #5573 (3-C-2) removed the Chat-side decision and
    completion calls that could raise them; every code kept here is still
    reachable from the lane.
    """
    original = RuntimeError("D1_ERROR: database is locked")
    error = lane.ChatPCDriveError(code, "PC 작업을 완료하지 못했습니다.")
    error.__cause__ = original
    assert error.status_code == 503
    assert error.public_error()["cause"] == (
        "RuntimeError: D1_ERROR: database is locked"
    )


@pytest.mark.parametrize("message, private", [
    ("authorization: Bearer synthetic-private-token", "synthetic-private-token"),
    ("failed token=synthetic-private-token", "synthetic-private-token"),
    ("failed access_token=private-value", "private-value"),
    ("failed refresh_token=private-value", "private-value"),
    ("failed client_secret=private-value", "private-value"),
    ("failed api key=private-value", "private-value"),
    ("failed session_id=private-value", "private-value"),
    ("failed Bearer synthetic-private-token", "synthetic-private-token"),
    ("failed https://example.test/path?key=synthetic-private-token", "example.test"),
    ("failed 'private-file-content'", "private-file-content"),
    (r"failed C:\Users\private-user\private-file.txt", "private-user"),
    ("failed /home/private-user/private-file.txt", "private-user"),
    ("failed private-user@example.test", "private-user"),
    ("failed syntheticOpaqueCredential0123456789012345", "syntheticOpaqueCredential"),
    ("database locked\nprivate-second-line", "private-second-line"),
])
def test_pc_503_cause_redacts_private_values_before_truncation(message, private):
    error = lane.ChatPCDriveError("chat_pc_store_unavailable", "unavailable")
    error.__cause__ = RuntimeError(message)
    cause = error.public_error()["cause"]
    assert cause.startswith("RuntimeError: ")
    assert private not in cause
    assert len(cause.removeprefix("RuntimeError: ")) <= 120


def test_pc_503_cause_is_bounded_and_present_without_an_underlying_exception():
    error = lane.ChatPCDriveError(
        "chat_pc_store_unavailable", "database is locked; " * 20,
    )
    assert error.cause == "ChatPCDriveError: " + ("database is locked; " * 20)[:120]


@pytest.mark.parametrize("method", [
    "record_chat_pc_drive_run", "get_claw_run",
    "seal_run_terminal", "append_local_task_result",
])
async def test_a_store_failure_keeps_its_redacted_cause_on_the_tool_turn(
    monkeypatch, method,
):
    """#5742 on the #5573 entry: every lane failure stays diagnosable.

    The keyword route that used to produce this 503 is gone, so the same store
    seams are driven through a model-selected tool. Each one must still surface
    one 503 carrying the chained exception class and a redacted message.
    """
    app, bridge, store = _wire(monkeypatch)
    store.run_row = {
        "conversation_id": "chat_" + "s" * 32,
        "result_summary": "verified output",
        "action": "pc_files_query" if method == "seal_run_terminal"
                  else "pc_drive_query",
    }
    store.fail = method
    monkeypatch.setattr(lane, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane, "current_user_id", lambda request: OWNER)
    request = SimpleNamespace(app=SimpleNamespace(state=app.state), cookies={})

    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        await lane.execute_chat_pc_drive_lane(
            request, user_text=LIST_ONLY, skill=None, model_id="m",
            conversation_id=None, selected_tool="files",
        )

    error = excinfo.value
    assert error.status_code == 503
    assert error.public_error() == {
        "code": "chat_pc_store_unavailable",
        "message": "대화 기록을 현재 사용할 수 없습니다.",
        "cause": "RuntimeError: D1_ERROR: database is locked",
    }
    # A staging failure stops before the Engine; a result-leg failure does not.
    assert len(bridge.requests) == (0 if method == "record_chat_pc_drive_run" else 1)


async def test_a_lane_engine_503_retains_the_original_engine_code(monkeypatch):
    """The engine's own code survives inside the redacted cause."""
    from app.orchestration_bridge import B62OrchestrationError

    app, bridge, store = _wire(monkeypatch)

    async def fail(**fields):
        raise B62OrchestrationError(
            "upstream_unavailable", "AI unavailable", status_code=503,
        )

    bridge.start = fail
    monkeypatch.setattr(lane, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane, "current_user_id", lambda request: OWNER)
    request = SimpleNamespace(app=SimpleNamespace(state=app.state), cookies={})

    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        await lane.execute_chat_pc_drive_lane(
            request, user_text=LIST_ONLY, skill=None, model_id="m",
            conversation_id=None, selected_tool="files",
        )

    assert excinfo.value.status_code == 503
    assert excinfo.value.public_error()["cause"] == (
        "B62OrchestrationError: upstream_unavailable: AI unavailable"
    )


async def test_invalid_stream_recovery_handle_is_refused_before_any_engine_or_history_call(monkeypatch):
    app, bridge, store = _wire(monkeypatch)
    response = await _post(app, PLAIN_TEXT, pc_run_id="noncanonical")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_request"
    assert bridge.requests == [] and store.pending_turns == [] and store.staged == []


async def test_resumed_stream_appends_only_the_answer_to_the_original_user_turn(monkeypatch):
    app, bridge, store = _wire(monkeypatch)
    calls = []
    async def resume(**fields):
        return SimpleNamespace(stream_run_id=PC_RUN, conversation_id="chat_saved", answer="resumed",
            user_text=PLAIN_TEXT, orchestration={"events": [], "approval_pause": None}, decision_status=None)
    async def finish(**fields):
        calls.append(fields)
        return "chat_saved"
    async def forbidden_exchange(*args, **kwargs):
        raise AssertionError("the already stored user turn must not be appended again")
    bridge.resume = resume
    store.finish_chat_stream_turn = finish
    store.append_exchange = forbidden_exchange
    async with _client(app) as client:
        response = await client.post("/api/orchestration/resume", headers={"Origin": ORIGIN}, json={
            "continuationRef": "cont_abcdefgh12345678", "pauseId": "pause_1", "outcome": "approved", "requiresTrustedDecision": True})
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "resumed"
    assert calls == [{"user_id": OWNER, "run_id": PC_RUN, "answer": "resumed"}]


async def test_stream_user_turn_store_failure_preserves_only_the_existing_redacted_cause(monkeypatch):
    app, bridge, store = _wire(monkeypatch)
    async def fail(**fields):
        raise RuntimeError("database locked token=synthetic-private-token")
    store.begin_chat_stream_turn = fail
    response = await _post(app, PLAIN_TEXT, pc_run_id=PC_RUN)
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "chat_pc_store_unavailable"
    assert error["cause"].startswith("RuntimeError: database locked")
    assert "synthetic-private-token" not in response.text
    assert bridge.requests == [] and store.staged == []


async def test_orchestration_terminal_error_marks_its_owner_pc_run_failed(monkeypatch):
    from app.orchestration_bridge import B62OrchestrationError
    app, bridge, store = _wire(monkeypatch)
    settled = []
    async def update(user_id, run_id, status):
        settled.append((user_id, run_id, status))
        return True
    async def failed_stream(**fields):
        raise B62OrchestrationError("upstream_auth_error", "safe error", status_code=403)
        yield
    store.update_claw_run_status = update
    bridge.start_stream = failed_stream
    async with _client(app) as client:
        response = await client.post("/api/orchestration", json={
            "messages": [{"role": "user", "content": PLAIN_TEXT}],
            "tier": "free", "pc_run_id": PC_RUN,
        })
    assert response.status_code == 200
    assert "event: error" in response.text
    assert settled == [(OWNER, PC_RUN, "failed")]
    assert not store.answers
