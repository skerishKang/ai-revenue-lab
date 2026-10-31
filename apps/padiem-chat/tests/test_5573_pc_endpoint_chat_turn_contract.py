"""Real PC endpoint contracts for a history-only pending Chat tool turn.

Real routes, migrations and D1HistoryStore; Identity/Mesh configuration is
synthetic. No provider, executor or production database call.
"""
from datetime import datetime, timedelta, timezone

import json

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app import oracle_mesh_read_return_routes as routes
from app.chat_pc_drive import CHAT_PC_DRIVE_COMMAND
from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

import test_5015_multi_tool_result_storage as db
from test_5015_pc_read_dispatch import _SignedRequest
from test_chat_pc_drive import (
    _CHAT_ACCOUNT, _CHAT_CHANNEL_SECRET, _CHAT_SECRET, _CHAT_SUBJECT,
    _CHAT_WORKSPACE, _chat_mapping,
)

DEVICE = "pc+contract@mesh"
FILES = "/internal/chat/engine-pc-files"
DRIVES = "/internal/chat/engine-pc-drive"


@pytest.mark.parametrize("endpoint,mode,op,plan", [
    pytest.param(FILES, "context", None, "files_list", id="files-context"),
    pytest.param(FILES, "dispatch", "list", "files_list", id="files-list-dispatch"),
    pytest.param(FILES, "dispatch", "read", "files", id="files-read-dispatch"),
    pytest.param(DRIVES, "dispatch", None, "query_drives", id="drives-dispatch"),
])
def test_every_pc_endpoint_accepts_a_pending_chat_tool_turn(
    monkeypatch, endpoint, mode, op, plan,
):
    sessions, owner_sessions = [], []
    now = datetime.now(timezone.utc)

    class Identity:
        async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
            assert (product_id, canonical_subject_id) == ("b62", _CHAT_SUBJECT)
            return db.OWNER

        async def resolve_current_auth_session(self, *, product_id, product_user_id):
            assert product_user_id == db.OWNER
            sessions.append(product_id)
            return AuthSessionSnapshot(
                session_id="session." + product_id, product_id=product_id,
                subject=CanonicalSubjectRef(subject_id=_CHAT_SUBJECT, subject_type=SubjectType.USER),
                issued_at=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
                tenant_id=db.WORKSPACE,
            )

        async def resolve_connector_owner_scope(self, *, session_id):
            owner_sessions.append(session_id)
            # A B62 session proves the Chat caller, never connector authority.
            assert session_id == "session.b54-padiem-claw"
            return {"account_ref": _CHAT_ACCOUNT, "workspace_ref": _CHAT_WORKSPACE}

    async def workspace(request, uid):
        assert uid == db.OWNER
        return db.WORKSPACE

    connection = db._database()
    try:
        db._stage_run(connection, status="pending", action="pc_files_query")
        assert db._run_row(connection)["status"] == "pending"
        assert connection.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0] == 0
        mapping = [{**row, "device_id": DEVICE} for row in _chat_mapping()]
        source = routes.build_oracle_mesh_return_source(
            mapping, _CHAT_CHANNEL_SECRET, routes.EXECUTION_MODE_MESH)
        assert source is not None
        app = Starlette(routes=[
            Route(FILES, routes.oracle_mesh_engine_chat_files_call, methods=["POST"]),
            Route(DRIVES, routes.oracle_chat_engine_pc_drive_call, methods=["POST"]),
        ])
        app.state.history_store = db._store(connection)
        app.state.control_plane_identity_authority = Identity()
        app.state.oracle_mesh_return_source = source
        app.state.claw_engine_desktop_secret = _CHAT_SECRET
        app.state.connector_txt_read_source = None
        monkeypatch.setattr(routes, "_resolve_memory_workspace", workspace)
        payload = {"subject_id": _CHAT_SUBJECT, "run_id": db.RUN,
                   "device_id": DEVICE, "mode": mode}
        claim = None
        if endpoint == DRIVES:
            payload["command"] = CHAT_PC_DRIVE_COMMAND
        else:
            claim = {"version": 1, "requested": plan, "admitted": plan,
                     "source": "declared", "app_id": "padiem-chat",
                     "ops": ["list"] if plan == "files_list" else ["list", "read"]}
            if mode == "dispatch":
                payload.update(op=op, path="." if op == "list" else "notes.txt",
                               tool_call_ref=db.RUN + ":" + op)
        signed = _SignedRequest(app.state, payload, secret=_CHAT_SECRET, scope=claim)
        with TestClient(app) as client:
            response = client.post(endpoint, content=signed._raw, headers=signed.headers)
        body = response.json()
        assert response.status_code == 200, {"endpoint": endpoint, "mode": mode,
                                           "response": body, "owner_sessions": owner_sessions}
        assert body["ok"] is True
        assert sessions[0] == "b62"
        assert owner_sessions and set(owner_sessions) == {"session.b54-padiem-claw"}
        assert connection.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM claw_run_history WHERE run_id=?", (db.RUN,)).fetchone()[0] == 1
        rows = connection.execute("SELECT run_id,kind,device_id,state FROM oracle_mesh_dispatch").fetchall()
        if mode == "context":
            assert body["run_id"] == db.RUN
            assert body["device"]["device_id"] == DEVICE
            # (A): a context names the owner's folders, never the real path.
            assert body["roots"] == [{"label": "padiem"}]
            assert "C:/padiem" not in json.dumps(body)
            assert not rows
        else:
            assert len(rows) == 1
            assert tuple(rows[0]) == (db.RUN, "read" if op == "read" else "command", DEVICE, "pending")
    finally:
        connection.close()
