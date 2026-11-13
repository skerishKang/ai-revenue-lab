"""Real history, queue projections and HTTP boundaries for app sessions."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request

from app import chat_pc_session as lane
from app import claw_connector_enrollment_routes as owner_routes
from app.config import ConfigError, Settings
from test_7065_chat_pc_session import app_rig, opened, UID, DEVICE, CID
from test_7065_pc_session_tools import rig
from test_4139_connector_one_click_approval import session as canonical_session
from test_7603_confirmation_card_expiry import _fixture, UID as SQL_UID, WORKSPACE

REAL_OWNER_REQUEST = owner_routes._verified_owner_request


@pytest.mark.parametrize("op", ["start", "input"])
def test_real_history_keeps_confirmation_private_and_consumes_once(tmp_path, op):
    from app.history import PRODUCT_SCOPE_CHAT

    async def scenario():
        store, db = _fixture(tmp_path)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=store)))
        owner = (SQL_UID, SimpleNamespace(session_id="fixture"), WORKSPACE)
        value = "한글\n" * 900
        operation = ({"op": "start", "interactive": True, "mode": "user", "command": value}
                     if op == "start" else {"op": "input", "job_id": "dsp_" + "a" * 32, "text": value})
        response = await lane._stage(request, owner=owner, operation=operation,
            conversation_id=None, device=DEVICE, user_text="PC 세션에 여러 줄 입력")
        cid = json.loads(response.body)["conversation_id"]
        rows = await store.list_recent_claw_runs(SQL_UID, workspace_id=WORKSPACE)
        row = rows[0]
        assert row["action"] == "pc_session_" + op and row["status"] == "waiting_approval"
        assert row["session"]["conversation_id"] == cid
        run = await store.get_claw_run(SQL_UID, row["run_id"])
        assert run["workspace_id"] == WORKSPACE and run["conversation_id"] == cid
        browser = await store.get_conversation(SQL_UID, cid, product_scope=PRODUCT_SCOPE_CHAT)
        model = await store.get_conversation_model_context(SQL_UID, cid, product_scope=PRODUCT_SCOPE_CHAT)
        search = await store.search_conversations(SQL_UID, "pc-session-confirm", product_scope=PRODUCT_SCOPE_CHAT)
        assert "pc-session-confirm:" not in repr(browser) + repr(model) + repr(search)
        pending = await lane._pending(request, owner=owner, conversation_id=cid)
        assert pending[1] == operation
        assert await store.read_pc_session_confirmation_turn(user_id="foreign", run_id=row["run_id"]) is None
        assert await store.consume_pc_command_confirmation(SQL_UID, row["run_id"], action=row["action"])
        assert not await store.consume_pc_command_confirmation(SQL_UID, row["run_id"], action=row["action"])
        assert await store.read_pc_session_confirmation_turn(user_id=SQL_UID, run_id=row["run_id"]) is None
        db.close()
    asyncio.run(scenario())


def test_real_confirmation_expires_and_an_unrelated_turn_cannot_confirm(tmp_path):
    async def scenario():
        store, db = _fixture(tmp_path)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=store)))
        owner = (SQL_UID, SimpleNamespace(session_id="fixture"), WORKSPACE)
        operation = {"op": "start", "interactive": True, "command": "x" * 201}
        result = await lane._stage(request, owner=owner, operation=operation,
            conversation_id=None, device=DEVICE, user_text="PC 세션 시작")
        cid = json.loads(result.body)["conversation_id"]
        row = (await store.list_recent_claw_runs(SQL_UID))[0]
        await store.begin_chat_stream_turn(user_id=SQL_UID, run_id="chat_pcq_" + "e" * 32,
            workspace_id=WORKSPACE, user_text="unrelated owner turn", conversation_id=cid)
        assert await lane._pending(request, owner=owner, conversation_id=cid) is None
        old = (datetime.now(timezone.utc) - timedelta(seconds=601)).isoformat()
        db.execute("UPDATE claw_run_history SET created_at=? WHERE run_id=?", (old, row["run_id"]))
        assert not await store.consume_pc_command_confirmation(SQL_UID, row["run_id"], action=row["action"])
        assert (await store.get_claw_run(SQL_UID, row["run_id"]))["status"] == "timed_out"
        db.close()
    asyncio.run(scenario())


def _queue_module(name):
    path = Path(__file__).resolve().parents[2] / "padiem-mesh-queue" / (name + ".py")
    spec = importlib.util.spec_from_file_location("session_app_test_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_queue_private_row_binds_real_app_run_and_rejects_mcp_origin(tmp_path, monkeypatch):
    from app.d1_sqlite import SqliteD1, connect
    from app.queue_store_proxy import QueueForwardingHistoryStore
    from app import pc_work_context, mcp_gateway_execution
    schema = _queue_module("schema")
    queue_class = _queue_module("background_history").QueueHistoryStore

    async def scenario():
        real, db = _fixture(tmp_path)
        qdb = connect(str(tmp_path / "queue.sqlite3"))
        schema.apply(qdb)
        async def owns(run_id, user_id):
            return await real.get_claw_run(user_id, run_id) is not None
        queue = queue_class(SqliteD1(qdb), run_ownership=owns)
        class Client:
            async def call(self, method, **fields):
                return await getattr(queue, method)(**fields)
        history = QueueForwardingHistoryStore(real, Client())
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=history)))
        owner = (SQL_UID, SimpleNamespace(session_id="fixture"), WORKSPACE)
        run_id = "chat_pcq_" + "b" * 32
        cid = await real.record_chat_pc_drive_run(user_id=SQL_UID, run_id=run_id, workspace_id=WORKSPACE,
            user_text="PC 세션 시작", conversation_id=None, action="pc_session")
        row = await history.create_oracle_mesh_dispatch(
            user_id=SQL_UID, run_id=run_id, command_id="cmd-1", tool_request_ref="t", request_id="r",
            revision_ref="rev", evidence_ref=None, request_fingerprint="f", account_ref="fixture",
            workspace_ref=WORKSPACE, device_id=DEVICE, binding_ref=None, node_ref="fixture",
            root_ref="mesh_terminal", path_relative="command", file_path="command",
            expires_at="2099-01-01T00:00:00Z", kind="command", command_text="fixture", user_mode=True,
            background=True, job_operation={"op": "session"})
        operation = {"op": "input", "job_id": row["dispatch_id"], "text": "hello"}
        private = await history.get_pc_output_dispatch_for_owner(user_id=SQL_UID, dispatch_id=row["dispatch_id"])
        assert private["run_id"] == run_id and private["user_id"] == SQL_UID
        assert await lane._target(request, owner=owner, operation=operation, conversation_id=cid) == DEVICE
        assert await lane._target(request, owner=owner, operation=operation, conversation_id="chat_" + "f" * 32) is None
        db.execute("UPDATE claw_run_history SET action='pc_files_query' WHERE run_id=?", (run_id,))
        assert await lane._target(request, owner=owner, operation=operation, conversation_id=cid) is None
        qdb.close()
        db.close()

    async def context(*args, **kwargs):
        return SimpleNamespace(selection_offline=False, selected_confirmed=True, tool_available=True,
                               selected_device_id=DEVICE, execution_device_id=DEVICE)
    async def grant(*args, **kwargs):
        return True
    monkeypatch.setattr(pc_work_context, "resolve_pc_work_context", context)
    monkeypatch.setattr(mcp_gateway_execution, "_check_mesh_grant", grant)
    asyncio.run(scenario())


def test_actual_api_mount_canonical_owner_and_origin_boundary(app_rig, monkeypatch):
    from app.app_factory import create_app
    from app.connector_owner_runtime_mount import ExactOwnerOrigin
    job = opened(app_rig)
    application = create_app(settings=Settings.from_values(
        runtime_mode="mock", public_base_url="https://chat.padiem.net",
        chat_pc_session_enabled=True, mcp_pc_session_enabled=True,
        mcp_pc_shell_enabled=True, mcp_pc_shell_user_mode_enabled=True))
    application.state.history_store = app_rig[1]
    application.state.queue_client = app_rig[3]
    application.state.fixture_user = UID
    application.state.connector_enrollment_browser_csrf = ExactOwnerOrigin()
    current = {"product_user_id": UID, "auth_session": canonical_session()}
    async def bridged(request):
        return SimpleNamespace(**current)
    monkeypatch.setattr(owner_routes, "_verified_owner_request", REAL_OWNER_REQUEST)
    monkeypatch.setattr(owner_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(owner_routes, "current_user_id", lambda request: UID)
    monkeypatch.setattr(owner_routes, "resolve_current_b54_canonical_session", bridged)

    async def post(origin):
        headers = {"Origin": origin} if origin is not None else {"x-test-no-origin": "1"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                     base_url="https://chat.padiem.net") as client:
            return await client.post(lane.API_PATH, headers=headers,
                json={"op": "read", "job_id": job, "conversation_id": CID})
    before = len(app_rig[1].staged)
    assert asyncio.run(post(None)).status_code == 403
    assert asyncio.run(post("https://evil.invalid")).status_code == 403
    current["product_user_id"] = "foreign"
    assert asyncio.run(post("https://chat.padiem.net")).status_code == 401
    current["product_user_id"] = UID
    current["auth_session"] = canonical_session(product="other-product")
    assert asyncio.run(post("https://chat.padiem.net")).status_code == 401
    assert len(app_rig[1].staged) == before
    current["auth_session"] = canonical_session()
    accepted = asyncio.run(post("https://chat.padiem.net"))
    assert accepted.status_code == 200 and accepted.json()["pc_session"]["ok"] is True


@pytest.mark.parametrize("surface", ["chat", "claw"])
@pytest.mark.parametrize("text,assistant,expected", [
    ("PC 세션 시작 `python`", False, 200),
    ("PC 세션: 내 PC에서 `echo forbidden` 실행해", False, 422),
    ("PC 세션 시작 `python`", True, 422),
    ("PC 세션 secret `fixture-private`", False, 422),
])
def test_real_entry_hooks_never_fall_through_to_command_or_model(app_rig, monkeypatch, surface, text, assistant, expected):
    from app import orchestration_routes, claw_general_routes
    from test_7165_chat_direct_pc_command import _Bridge
    state = app_rig[0].app.state
    state.settings.runtime_mode = "mock"
    state.usage_gate_enforced = False
    state.orchestration_bridge = _Bridge()
    state.usage_gate = None
    payload = {"messages": [{"role": "user", "content": text}],
               "conversation_id": CID, "device_id": DEVICE}
    if assistant:
        payload["messages"].append({"role": "assistant", "content": "previous generated answer"})
    request = Request({"type": "http", "method": "POST", "path": "/api/" + surface,
        "headers": [(b"content-type", b"application/json")], "app": app_rig[0].app})
    request._body = json.dumps(payload).encode()
    monkeypatch.setattr(orchestration_routes, "_bridge", lambda request: state.orchestration_bridge)
    monkeypatch.setattr(orchestration_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(orchestration_routes, "current_user_id", lambda request: UID)
    monkeypatch.setattr(claw_general_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(claw_general_routes, "current_user_id", lambda request: UID)
    async def forbidden(*args, **kwargs):
        raise AssertionError("session syntax reached the ordinary command lane")
    monkeypatch.setattr(claw_general_routes, "_dispatch_user_command_request", forbidden)
    from app import chat_pc_command
    monkeypatch.setattr(chat_pc_command, "dispatch_chat_pc_command", forbidden)
    response = asyncio.run(orchestration_routes.api_orchestration(request) if surface == "chat"
                           else claw_general_routes.claw_general_execute(request))
    assert response.status_code == expected
    assert not state.orchestration_bridge.calls
    if expected == 200:
        assert len(app_rig[1].staged) == 1
        assert b"pc_session" in response.body
    else:
        assert not app_rig[1].staged


def test_app_switch_is_strict_and_default_off(monkeypatch):
    assert Settings.from_values(runtime_mode="mock").chat_pc_session_enabled is False
    assert Settings.from_values(runtime_mode="mock", chat_pc_session_enabled="true").chat_pc_session_enabled is True
    with pytest.raises(ConfigError, match="PADIEM_CHAT_PC_SESSION_ENABLED"):
        Settings.from_values(runtime_mode="mock", chat_pc_session_enabled="typo")
    monkeypatch.setenv("PADIEM_CHAT_PC_SESSION_ENABLED", "1")
    assert Settings.from_env().chat_pc_session_enabled is True


@pytest.mark.parametrize("surface", ["chat", "stream"])
def test_legacy_routes_refuse_session_text_before_model_or_history(app_rig, monkeypatch, surface):
    from app import chat_routes
    async def forbidden(*args, **kwargs):
        raise AssertionError("reserved session text reached model request validation")
    monkeypatch.setattr(chat_routes, "_validate_payload_async", forbidden)
    request = Request({"type": "http", "method": "POST", "path": "/api/chat" + ("/stream" if surface == "stream" else ""),
        "headers": [(b"content-type", b"application/json")], "app": app_rig[0].app})
    request._body = json.dumps({"messages": [{"role": "user", "content": "PC 세션 secret `fixture-private`"}]}).encode()
    response = asyncio.run(chat_routes.api_chat_stream(request) if surface == "stream" else chat_routes.api_chat(request))
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "pc_session_chat_route_required"
    assert not app_rig[1].messages and not app_rig[1].staged
    assert "fixture-private" not in response.body.decode()
    app_rig[0].app.state.settings.chat_pc_session_enabled = False
    assert lane.legacy_turn_error(request, {"messages": [{"role": "user", "content": "PC 세션 시작 `python`"}]}) is None


def test_connector_fallback_cannot_route_reserved_session_text_to_model(app_rig, monkeypatch):
    from app import chat_connector_tools, orchestration_routes
    from test_7165_chat_direct_pc_command import _Bridge
    state = app_rig[0].app.state
    state.settings.runtime_mode = "mock"
    state.usage_gate_enforced = False
    state.usage_gate = None
    bridge = _Bridge()
    monkeypatch.setattr(orchestration_routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(orchestration_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(orchestration_routes, "current_user_id", lambda request: UID)
    async def granted(*args, **kwargs):
        return True
    monkeypatch.setattr(chat_connector_tools, "connector_tools_granted_for_fallback", granted)
    monkeypatch.setattr(chat_connector_tools, "google_connector_intent", lambda text: True)
    request = Request({"type": "http", "method": "POST", "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")], "app": app_rig[0].app})
    request._body = json.dumps({"messages": [{"role": "user", "content": "PC 세션 시작 `echo Google Drive`"}],
                               "conversation_id": CID, "device_id": DEVICE}).encode()
    response = asyncio.run(orchestration_routes.api_orchestration(request))
    assert response.status_code == 200
    assert json.loads(response.body)["pc_session"]["ok"] is True
    assert not bridge.calls


def test_secret_confirmation_uses_actual_300_second_memory_expiry(app_rig, monkeypatch):
    from test_7065_chat_pc_session import card, turn
    module = _queue_module("desktop_text_store")
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    memory = module.DesktopTextStore()
    async def call(method, **fields):
        return await getattr(memory, method)(**fields)
    monkeypatch.setattr(app_rig[3], "call", call)
    monkeypatch.setattr(app_rig[3], "take_desktop_text", memory.take_desktop_text)
    job = opened(app_rig)
    app_rig[2].features.append("secret_mask")
    assert card(app_rig, job, text="x" * 201, secret=True)["decision_status"] == "pc_session_confirm"
    clock[0] += 300
    result = turn(app_rig, "네")
    assert result["error"]["code"] == "pc_session_input_expired"
    assert not any(op["op"] == "input" for op in app_rig[2].operations)
    assert not memory._entries
