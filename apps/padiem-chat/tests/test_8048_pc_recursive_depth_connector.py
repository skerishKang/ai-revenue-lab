"""#8048 — recursive search and depth listing from the external MCP connector.

The same two calls are staged through the connector path (``execute_mcp_pc_tool``)
and the Chat drive plan path (``chat_pc_drive``). Each scenario runs on both
store shapes: the local database store and the queue-backed history proxy.
Korean folder/query examples are synthetic; no owner folder name is published.
The helpers are local on purpose: test modules must not import other tests.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from app import mcp_gateway_execution as execution
from app.chat_pc_drive import _tool_arguments_for_plan, chat_pc_plan_for_tool
from app.d1_sqlite import SqliteD1, connect
from app.history import D1HistoryStore
from _support.migrated_db_template import apply_copied_migrations as apply_migrations
from app.mcp_gateway_transport import _TOOLS as MCP_TOOLS
from app.mcp_gateway_transport import validate_tool_arguments
from app.oracle_mesh_read_return_routes import _pc_files_command
from app.queue_store_proxy import QueueForwardingHistoryStore
from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient

DEVICE = "dev_" + "c" * 32
UID = "usr_" + "8" * 32
WORKSPACE = "ws-8048"
PRINCIPAL = {"owner_id": UID, "device_id": DEVICE, "token_id": "mcp_token_fixture"}
KOREAN_FOLDER = "한글 폴더"
KOREAN_QUERY = "보고서"


class _Bucket:
    def __init__(self):
        self.objects = {}

    def put(self, key, body, httpMetadata=None):
        self.objects[key] = bytes(body)

    def delete(self, key):
        self.objects.pop(key, None)

    def get(self, key):
        return self.objects.get(key)


class RecordingTransport:
    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        answer = json.dumps({"status": "completed", "answer": "확인했습니다."})
        return EngineTransportResponse(status=200, headers={}, body=json.dumps({
            "ok": True,
            "orchestration": {
                "events": [{"event_id": "event_fixture", "run_id": "run_fixture",
                            "trace_id": "trace_fixture", "app_id": "padiem-chat",
                            "kind": "run_completed", "sequence": 1}],
                "execution": {"answer": answer},
            },
        }).encode())


def _local_store(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "chat.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
        "picture_url, created_at, updated_at) VALUES (?, 'google', 'sub_8048', "
        "'owner@example.test', '', '', '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z')",
        (UID,),
    )
    return D1HistoryStore(SqliteD1(connection), full_context_bucket=_Bucket()), connection


def _queue_module(name):
    path = Path(__file__).resolve().parents[2] / "padiem-mesh-queue" / (name + ".py")
    spec = importlib.util.spec_from_file_location("pc_8048_queue_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["local", "queue"])
def store(request, tmp_path):
    real, db = _local_store(tmp_path)
    if request.param == "local":
        yield real, request.param
        db.close()
        return
    schema = _queue_module("schema")
    queue_class = _queue_module("background_history").QueueHistoryStore
    qdb = connect(str(tmp_path / "queue.sqlite3"))
    schema.apply(qdb)

    async def owns(run_id, user_id):
        return await real.get_claw_run(user_id, run_id) is not None

    queue = queue_class(SqliteD1(qdb), run_ownership=owns)

    class Client:
        async def call(self, method, **fields):
            return await getattr(queue, method)(**fields)

    yield QueueForwardingHistoryStore(real, Client()), request.param
    qdb.close()
    db.close()


def connector_harness(monkeypatch, history):
    async def owner(request, uid):
        return SimpleNamespace(session_id="session_fixture"), "sub_" + "a" * 32, WORKSPACE

    async def context(request, **kwargs):
        return SimpleNamespace(selected_confirmed=True, tool_available=True, selection_offline=False,
                               selected_device_id=DEVICE, execution_device_id=DEVICE)

    async def grant(request, session, **kwargs):
        return True

    async def delegation(request, uid):
        return {"version": 1, "rules": []}

    async def notice(*args, **kwargs):
        return True

    async def folders(request, **kwargs):
        return [{"name": "work", "path": r"E:\work"},
                {"name": KOREAN_FOLDER, "path": "D:/" + KOREAN_FOLDER}]

    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution, "load_pc_delegation", delegation)
    monkeypatch.setattr(execution, "_append_lane_notice", notice)
    monkeypatch.setattr(execution, "_registered_pc_folders", folders)
    transport = RecordingTransport()
    bridge = execution.B62EngineOrchestrationBridge(
        client=PadiemAiEngineClient(transport=transport, app_id="padiem-chat",
                                    caller_id="padiem-chat", credential="fixture" * 8),
        store=object())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge, history_store=history)))
    return request, transport


def staged(monkeypatch, history, tool, arguments):
    request, transport = connector_harness(monkeypatch, history)
    result = asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, tool, arguments))
    assert result["status"] == "completed"
    body = json.loads(transport.calls[0]["body"])
    return body["pc_gateway"], [step["tool_id"] for step in body["agent_plan"]["steps"]]


def test_connector_advertises_and_admits_both_optional_arguments():
    search = MCP_TOOLS["pc_search"]["inputSchema"]["properties"]
    listing = MCP_TOOLS["pc_list"]["inputSchema"]["properties"]
    assert search["recursive"]["type"] == "boolean"
    assert listing["depth"]["type"] == "integer"
    assert validate_tool_arguments("pc_search", {
        "path": ".", "query": KOREAN_QUERY, "recursive": True}) is True
    assert validate_tool_arguments("pc_list", {
        "path": ".", "depth": 2}) is True


@pytest.mark.parametrize("depth", [2, 3])
def test_connector_depth_reaches_the_engine_on_both_stores(monkeypatch, store, depth):
    gateway, plan = staged(monkeypatch, store[0], "pc_list", {
        "path": "work", "depth": depth})
    assert gateway["tool_id"] == "claw.pc.list_files"
    assert plan == ["claw.pc.list_files"]
    assert gateway["arguments"]["depth"] == depth


def test_connector_recursive_korean_query_reaches_the_search_tool(monkeypatch, store):
    gateway, plan = staged(monkeypatch, store[0], "pc_search", {
        "path": KOREAN_FOLDER, "query": KOREAN_QUERY, "recursive": True})
    assert gateway["tool_id"] == "claw.pc.search_files"
    assert plan == ["claw.pc.search_files"]
    assert gateway["search_query"] == KOREAN_QUERY
    assert "recursive" not in gateway["arguments"]
    assert "query" not in gateway["arguments"]


def test_recursive_and_depth_plans_keep_both_argument_keys():
    # The Chat drive lane must stage the same plan and target hint as the
    # connector. The Engine accepts this exact closed key (see engine test).
    recursive_plan = chat_pc_plan_for_tool("files_search")
    assert [step["tool_id"] for step in recursive_plan["steps"]] == ["claw.pc.search_files"]
    assert _tool_arguments_for_plan(recursive_plan, DEVICE) == {
        "files_search": {"device_id": DEVICE}}
    depth_plan = chat_pc_plan_for_tool("files_list")
    assert [step["tool_id"] for step in depth_plan["steps"]] == ["claw.pc.list_files"]
    assert _tool_arguments_for_plan(depth_plan, DEVICE) == {
        "files_list": {"device_id": DEVICE}}


def test_pc_command_caps_and_link_rules_are_unchanged():
    recursive = _pc_files_command(op="list", root="D:/work", relative="",
                                  recursive=True, filter_term=KOREAN_QUERY)
    assert "$scan=2000" in recursive
    assert "$cap=50" in recursive
    assert "$skip=2 -bor 4 -bor 1024" in recursive
    assert "IndexOf($needle," in recursive
    deep = _pc_files_command(op="list", root="D:/work", relative="", depth=3)
    assert "$maxDepth=3" in deep
    assert "$cap=200" in deep
    assert "Add-DepthRow" in deep
    assert "$skip=2 -bor 4 -bor 1024" in deep
