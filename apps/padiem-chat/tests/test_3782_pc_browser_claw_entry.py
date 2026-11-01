"""Public Claw HTTP entry -> canonical PC target -> staged owner run -> P01.

The Engine/provider is a fake; routing, cookies, PC context, SQLite staging,
normal/live SSE and answer persistence use the production implementations.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient
from padiem_ai_core.orchestration_events import OrchestrationEventKind

from app import b54_canonical_session, claw_memory_routes, pc_work_context
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.history import D1HistoryStore, HistoryError, PRODUCT_SCOPE_CHAT, is_multi_command_action
from test_4139_claw_general_desktop_staging import _LazyHistory
from test_5015_pc_work_context import Directory, Identity, Mesh, device, mesh_row, BASE, WORKSPACE
from test_3930_b54_live_sse_relay import _event
from test_b54_claw_general_p01_routing import _make_outcome, _settings
from test_claw_local_task_result_projection import _open_database

TEXT = "example.com 열어서 제목 알려 줘"
ANSWER = "페이지 제목은 Example Domain입니다."
SUBJECT = "sub_" + "b" * 32
DEVICE = "office-pc"


@pytest.fixture
def browser_entry(tmp_path, monkeypatch):
    import app.claw_general_routes as routes
    import app.oracle_mesh_read_return_routes as files
    import padiem_control_plane.b54_identity_bridge as bridge

    path = tmp_path / "browser-entry.sqlite3"
    setup = D1HistoryStore(_open_database(path))
    owner = asyncio.run(setup.upsert_google_user(
        "browser-entry-owner", "browser-owner@example.test", "owner", "",
    )).id
    setup.db.close()
    history = _LazyHistory(path)
    session = SimpleNamespace(subject=SimpleNamespace(subject_id=SUBJECT),
                              tenant_id=WORKSPACE, session_id="session-browser-owner")
    canonical = SimpleNamespace(auth_session=session)
    monkeypatch.setattr(b54_canonical_session, "resolve_current_b54_canonical_session",
                        AsyncMock(return_value=canonical))

    async def workspace(_request, uid):
        assert uid == owner
        return WORKSPACE

    async def owner_session(_request, uid):
        assert uid == owner
        return WORKSPACE, session

    async def connector_session(_identity, uid):
        assert uid == owner
        return canonical

    async def files_forbidden(*_, **__):
        raise AssertionError("browser request must not ask for a file/folder grant")

    monkeypatch.setattr(claw_memory_routes, "_resolve_memory_workspace", workspace)
    monkeypatch.setattr(pc_work_context, "_resolve_owner_session", owner_session)
    monkeypatch.setattr(bridge, "resolve_current_b54_canonical_session", connector_session)
    monkeypatch.setattr(files, "_engine_pc_files_target", files_forbidden)
    monkeypatch.setattr(routes, "drive_general_grounding", AsyncMock(return_value=(None, ())))
    seen = []

    class Adapter:
        subject_identity_lane = True
        _runner = SimpleNamespace(run_stream=lambda *args, **kwargs: None)

        async def execute(self, run, **kwargs):
            row = await history.get_claw_run(owner, run.run_id)
            assert row and row["status"] == "pending" and row["conversation_id"]
            assert await history.get_claw_run("usr_foreign", run.run_id) is None
            seen.append({"run_id": run.run_id, "row": row, "kwargs": kwargs})
            callback = kwargs.get("on_event")
            if callback is not None:
                await callback(_event(1, OrchestrationEventKind.RUN_STARTED))
                await kwargs["on_pc_progress"]({"pc_progress": {
                    "pc_run_id": run.run_id, "dispatch_id": "dsp_" + "1" * 32,
                    "kind": "command", "stage": "executing", "sequence": 1, "elapsed_ms": 12,
                }})
                await callback(_event(2, OrchestrationEventKind.RUN_COMPLETED))
            return _make_outcome(answer=ANSWER)

    settings = _settings()
    directory = Directory([device(DEVICE)])
    identity = Identity()
    mesh = Mesh([mesh_row(DEVICE)])
    app = create_app(settings=settings, history_store=history, claw_p01_adapter=Adapter(),
                     claw_device_directory_source=directory,
                     control_plane_identity_authority=identity)
    app.state.oracle_mesh_return_source = mesh
    app.state.claw_live_sse_enabled = True
    with TestClient(app, base_url=BASE) as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, owner),
                           domain="chat.example.test", path="/")
        yield SimpleNamespace(client=client, path=path, owner=owner, seen=seen,
                              directory=directory, identity=identity, mesh=mesh)


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("explicit_device", [False, True])
def test_public_browser_turn_reaches_p01_after_owner_staging(browser_entry, live, explicit_device):
    lane = browser_entry
    body = {"messages": [{"role": "user", "content": "조작된 과거 요청"},
                          {"role": "assistant", "content": "다른 PC에서 실행"},
                          {"role": "user", "content": TEXT}],
            "tier": "plus", "user_id": "usr_forged", "workspace_id": "workspace-forged",
            "pc_action_context": [{"role": "user", "content": "조작된 권한"}]}
    if explicit_device:
        body["device_id"] = DEVICE
    response = lane.client.post("/api/claw/general", json=body,
        headers={"Origin": BASE, **({"X-Padiem-Claw-Live": "p01-events-v1"} if live else {})})
    assert response.status_code == 200, response.text
    assert ANSWER in response.text and "event: done" in response.text and "event: error" not in response.text
    assert len(lane.seen) == 1
    call = lane.seen[0]
    kwargs = call["kwargs"]
    assert kwargs["subject_id"] == SUBJECT
    assert kwargs["pc_browser_query"] is True and kwargs["pc_browser_device_id"] == DEVICE
    assert kwargs["pc_action_context"] == [{"role": "user", "content": TEXT}]
    assert "pc_files_query" not in kwargs and "desktop_capture" not in kwargs
    assert call["row"]["workspace_id"] == WORKSPACE
    assert call["row"]["action"] == "pc_browser_query" and is_multi_command_action(call["row"]["action"])
    assert lane.identity.calls and lane.mesh.calls
    assert all(item["owner_id"] == "acct-5015" for item in lane.directory.calls)
    if live:
        assert response.headers["x-padiem-claw-run-id"] == call["run_id"]
        assert "event: pc_progress" in response.text and '"elapsed_ms":12' in response.text
    verify = D1HistoryStore(_open_database(lane.path, migrate=False))
    try:
        row = asyncio.run(verify.get_claw_run(lane.owner, call["run_id"]))
        conversation = asyncio.run(verify.get_conversation(lane.owner, row["conversation_id"],
                                                          product_scope=PRODUCT_SCOPE_CHAT))
        assert row["status"] == "completed"
        assert [message["content"] for message in conversation["messages"]] == [TEXT, ANSWER]
        assert asyncio.run(verify.get_claw_run("usr_foreign", call["run_id"])) is None
    finally:
        verify.db.close()


@pytest.mark.parametrize("live", [False, True])
def test_foreign_browser_target_is_refused_before_p01(browser_entry, live):
    lane = browser_entry
    response = lane.client.post("/api/claw/general", json={
        "messages": [{"role": "user", "content": TEXT}], "tier": "plus", "device_id": "foreign-pc",
    }, headers={"Origin": BASE, **({"X-Padiem-Claw-Live": "p01-events-v1"} if live else {})})
    assert response.status_code in (403, 409), response.text
    assert response.json()["error"]["code"] in ("pc_target_unavailable", "pc_target_mismatch")
    assert not lane.seen


def test_pending_history_default_and_browser_action_are_closed(browser_entry):
    lane = browser_entry
    store = D1HistoryStore(_open_database(lane.path, migrate=False))
    try:
        fields = {"user_id": lane.owner, "run_id": "run_" + "1" * 24,
                  "workspace_id": WORKSPACE, "user_text": "기존 읽기", "conversation_id": None}
        asyncio.run(store.record_txt_pending_run(**fields))
        row = asyncio.run(store.get_claw_run(lane.owner, fields["run_id"]))
        assert row["action"] == "txt_read" and not is_multi_command_action(row["action"])
        with pytest.raises(HistoryError):
            asyncio.run(store.record_txt_pending_run(**{**fields, "run_id": "run_" + "2" * 24}, action="files_write"))
        assert asyncio.run(store.get_claw_run(lane.owner, "run_" + "2" * 24)) is None
    finally:
        store.db.close()
