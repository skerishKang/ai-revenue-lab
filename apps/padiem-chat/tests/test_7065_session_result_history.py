"""The real result callback keeps v1 originals and projects app conversation text."""
from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from app import mcp_gateway_session as sessions, mcp_gateway_shell as shell
from app import oracle_mesh_read_return_routes as routes
from app.d1_sqlite import SqliteD1, connect
from app.history import PRODUCT_SCOPE_CHAT
from app.queue_store_proxy import QueueForwardingHistoryStore
from test_7065_chat_pc_session_integration import _queue_module
from test_7603_confirmation_card_expiry import _fixture, UID, WORKSPACE
from test_4139_mesh_command import _state, Request, SECRET, NODE, ACCOUNT, DEVICE

SESSION = "a" * 32


@pytest.mark.parametrize("action", ["pc_session", "pc_files_query"])
@pytest.mark.parametrize("kind", ["max_read", "unavailable"])
def test_real_callback_original_and_public_session_projection(tmp_path, action, kind):
    async def scenario():
        real, db = _fixture(tmp_path)
        qdb = connect(str(tmp_path / "queue.sqlite3"))
        _queue_module("schema").apply(qdb)
        async def owns(run_id, user_id):
            return await real.get_claw_run(user_id, run_id) is not None
        queue = _queue_module("background_history").QueueHistoryStore(SqliteD1(qdb), run_ownership=owns)
        class Client:
            async def call(self, method, **fields):
                return await getattr(queue, method)(**fields)
        history = QueueForwardingHistoryStore(real, Client())
        run_id = "chat_pcq_" + "c" * 32
        cid = await real.record_chat_pc_drive_run(user_id=UID, run_id=run_id, workspace_id=WORKSPACE,
            user_text="PC 세션 읽기", conversation_id=None, action=action)
        op = "read" if kind == "max_read" else "input"
        material = sessions.build_session_material({"v": 1, "op": op, "session": SESSION})
        row = await history.create_oracle_mesh_dispatch(
            user_id=UID, run_id=run_id, command_id="cmd-1", tool_request_ref="t", request_id="r",
            revision_ref="rev", evidence_ref=None, request_fingerprint="f", account_ref=ACCOUNT,
            workspace_ref=WORKSPACE, device_id=DEVICE, binding_ref=None, node_ref=NODE,
            root_ref="mesh_terminal", path_relative="command", file_path="command",
            expires_at="2099-01-01T00:00:00Z", kind="command", command_text=material, user_mode=True)
        if kind == "max_read":
            output = "x" * 65536
            header = {"v": 1, "ok": True, "code": None, "op": "read", "session": SESSION,
                      "alive": True, "offset": 0, "next_offset": 65536, "end_offset": 65536,
                      "dropped_bytes": 0, "backend": "pipe"}
            body = (json.dumps(header) + "\n" + output).encode()
            termination, exit_code = "exited", 0
        else:
            output = ""
            body = json.dumps({"ok": False, "error_code": "user_session_unavailable"}).encode()
            termination, exit_code = "not_executed", 1
        nonce = "n" * 32
        assert await queue.claim_oracle_mesh_dispatch(dispatch_id=row["dispatch_id"],
                                                       nonce_sha256=hashlib.sha256(nonce.encode()).hexdigest())
        state = _state()
        state.history_store = history
        wire = {"dispatch_id": row["dispatch_id"], "nonce": nonce, "termination": termination,
                "exit_code": exit_code, "content_utf8": body.decode(),
                "content_sha256": hashlib.sha256(body).hexdigest(), "content_bytes": len(body)}
        response = await routes.oracle_mesh_read_result(Request(wire, state, secret=SECRET))
        assert response.status_code == 200, json.loads(response.body)
        stored = await shell._dispatch_row(SimpleNamespace(app=SimpleNamespace(state=state)),
                                           uid=UID, dispatch_id=row["dispatch_id"])
        raw = await shell._read_original(SimpleNamespace(app=SimpleNamespace(state=state)),
                                        uid=UID, dispatch=stored, run_row={"conversation_id": cid})
        assert raw.encode() == body
        assert stored["result_sha256"] == hashlib.sha256(body).hexdigest()
        projected = sessions.project_session_reply(raw, op=op, session_id=SESSION)
        if kind == "max_read":
            assert projected["output"] == output and projected["next_offset"] == 65536
        else:
            assert projected["code"] == "user_session_unavailable"
        conversation = await real.get_conversation(UID, cid, product_scope=PRODUCT_SCOPE_CHAT)
        public = "\n".join(m["content"] for m in conversation["messages"] if m["role"] == "assistant")
        if action == "pc_session":
            assert '"v":' not in public and '"shell":' not in public and '"error_code":' not in public
            assert sessions._encode_operation({"v": 1, "op": op, "session": SESSION}) not in public
            if output:
                assert public.count("x") == len(output)
                assert "dsp_" + SESSION in public
        else:
            assert (json.dumps(header) if kind == "max_read" else body.decode()) in public
        qdb.close()
        db.close()
    asyncio.run(scenario())


def test_status_public_history_drops_protocol_metadata_and_other_sessions():
    from app.chat_pc_session import project_history_result
    dispatch = {"dispatch_id": "dsp_" + "b" * 32, "user_mode": True,
                "command_text": sessions.build_session_material(
                    {"v": 1, "op": "status"}, session_scope=SESSION)}
    body = json.dumps({"v": 1, "ok": True, "code": None, "op": "status",
        "features": ["secret_mask"], "sessions": [{"session": SESSION, "alive": True},
            {"session": "f" * 32, "alive": True}]}) + "\n"
    public = "\n".join(project_history_result({"action": "pc_session"}, dispatch, body))
    assert "실행 중" in public and "dsp_" + SESSION in public
    assert "secret_mask" not in public and '"v":' not in public and "f" * 32 not in public


def test_ordinary_command_keeps_its_existing_original_storage_boundary(monkeypatch):
    from test_4139_mesh_command import _dispatch, _submit, setup_auth
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state, "echo ordinary")
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    output = b"x" * 65537
    status, reply, _ = _submit(state, row, termination="exited", exit_code=0, body=output)
    assert status == 200, reply
    assert row["dispatch_id"] not in state.history_store.originals
    assert "명령:" in state.history_store.appended[0]["content"]
