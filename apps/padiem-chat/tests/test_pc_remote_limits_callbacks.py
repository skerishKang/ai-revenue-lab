"""Signed PC job/output callbacks use the existing owner and queue authority."""
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from app import oracle_mesh_read_return_routes as routes
from test_5015_pc_read_dispatch import (
    _History, _SignedRequest, _state, _base_payload,
    OWNER, SUBJECT, RUN, DEVICE, LIST_CALL, READ_CALL,
)


FILES_SCOPE = {"version": 1, "requested": "files", "admitted": "files",
               "source": "declared", "ops": ["list", "read"], "app_id": "padiem-chat"}


class OutputHistory(_History):
    def __init__(self):
        super().__init__()
        self.outputs = {}
        self.output_calls = []

    async def store_pc_output(self, *, user_id, subject_id, run_id, device_id,
                              dispatch_id, content, source="pc_tool"):
        owner = (user_id, subject_id, run_id, device_id)
        handle = hashlib.sha256(("test:" + dispatch_id + content).encode()).hexdigest()
        self.outputs[owner + (handle,)] = content.encode()
        self.output_calls.append(("store", owner, dispatch_id, source))
        return {"handle": handle, "size": len(content.encode()),
                "head": content[:1600], "tail": content[-2400:] if len(content) > 4096 else "",
                "truncated": len(content) > 4096}

    async def read_pc_output(self, *, user_id, subject_id, run_id, device_id, handle, offset, length):
        owner = (user_id, subject_id, run_id, device_id)
        self.output_calls.append(("read", owner, handle))
        data = self.outputs.get(owner + (handle,))
        if data is None:
            raise FileNotFoundError
        return {"content": data[offset:offset + length].decode(),
                "offset": offset, "length": length}

    async def search_pc_output(self, *, user_id, subject_id, run_id, device_id, handle, query):
        owner = (user_id, subject_id, run_id, device_id)
        data = self.outputs.get(owner + (handle,))
        if data is None:
            raise FileNotFoundError
        at = data.find(query.encode())
        return {"hits": [] if at < 0 else [{"offset": at, "line": query}]}


def call(state, mode, scope=None, **values):
    request = _SignedRequest(state, {
        "subject_id": SUBJECT, "run_id": RUN, "device_id": DEVICE,
        "mode": mode, **values,
    }, scope=scope if scope is not None else FILES_SCOPE)
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    return response.status_code, json.loads(response.body)


def finish(history, job_id, text):
    row = history.rows[job_id]
    row.update(state="done", termination="exited", exit_code=0,
               result_sha256=hashlib.sha256(text.encode()).hexdigest())
    history.originals[job_id] = text.encode()


@pytest.mark.parametrize("op,path,ref", [("list", ".", LIST_CALL), ("read", "notes.txt", READ_CALL)])
def test_job_start_immediately_returns_existing_dispatch_id(monkeypatch, op, path, ref):
    state = _state(monkeypatch, OutputHistory())
    status, body = call(state, "job_start", operation={"op": op, "path": path}, tool_call_ref=ref)
    assert status == 200, body
    job = body["result"]
    assert job["state"] == "pending"
    row = state.history_store.rows[job["job_id"]]
    assert row["background"] is True
    assert row["job_operation"] == {"op": op, "path": path}
    assert row["device_id"] == DEVICE
    assert row["kind"] == ("read" if op == "read" else "command")
    assert state.history_store.originals == {}
    row["claimed"] = True
    status, body = call(state, "job_status", job_id=job["job_id"])
    assert status == 200 and body["result"]["state"] == "running"
    assert "nonce" not in json.dumps(body)
    row["device_id"] = "other-device"
    status, body = call(state, "job_status", job_id=job["job_id"])
    assert status == 404


def test_job_cannot_smuggle_raw_shell_or_exceed_signed_scope(monkeypatch):
    state = _state(monkeypatch, OutputHistory())
    status, _ = call(state, "job_start",
        operation={"op": "list", "path": ".", "command": "arbitrary"}, tool_call_ref=LIST_CALL)
    assert status == 400 and not state.history_store.rows
    scope = {"version": 1, "requested": "files_list", "admitted": "files_list",
             "source": "declared", "ops": ["list"], "app_id": "padiem-chat"}
    status, body = call(state, "job_start", scope=scope,
        operation={"op": "write", "path": "notes.txt", "content": "x"}, tool_call_ref=LIST_CALL)
    assert status == 403 and body["error"]["code"] == "pc_scope_denied"
    assert not state.history_store.rows


def test_job_output_and_opaque_handle_keep_owner_run_device(monkeypatch):
    history = OutputHistory()
    state = _state(monkeypatch, history)
    _, body = call(state, "job_start", operation={"op": "read", "path": "notes.txt"}, tool_call_ref=READ_CALL)
    job_id = body["result"]["job_id"]
    text = "begin\n" + "middle-data\n" * 10000 + "end"
    finish(history, job_id, text)
    status, body = call(state, "job_output", job_id=job_id, offset=6, length=11)
    assert status == 200, body
    result = body["result"]
    assert result["content"] == text[6:17] and result["output_ref"]["size"] == len(text)
    assert result["operation"] == {"op": "read", "path": "notes.txt"}
    assert "middle-data\n" * 1000 not in json.dumps(body)
    handle = result["output_ref"]["handle"]
    status, body = call(state, "search_output", handle=handle, query="middle-data")
    assert status == 200 and body["result"]["hits"][0]["offset"] == 6
    assert history.output_calls[0][1] == (OWNER, SUBJECT, RUN, DEVICE)
    status, _ = call(state, "read_output", handle=handle, offset=0, length=65537)
    assert status == 422
    status, _ = call(state, "read_output", handle="f" * 64, offset=0, length=10)
    assert status == 404
    history.rows[job_id]["run_id"] = "different-run"
    status, _ = call(state, "job_output", job_id=job_id, offset=0, length=10)
    assert status == 404


def test_legacy_result_moves_large_verified_output_to_queue_store(monkeypatch):
    history = OutputHistory()
    state = _state(monkeypatch, history)
    _, body = call(state, "job_start", operation={"op": "list", "path": "."}, tool_call_ref=LIST_CALL)
    job_id = body["result"]["job_id"]
    finish(history, job_id, "x" * 15000)
    request = _SignedRequest(state, {"mode": "result", "subject_id": SUBJECT,
                                     "run_id": RUN, "dispatch_id": job_id}, scope=FILES_SCOPE)
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    result = json.loads(response.body)["dispatch"]
    assert response.status_code == 200
    assert len(result["output"]) < 4096
    assert result["output_ref"]["size"] == 15000
    assert result["content_sha256"] == hashlib.sha256(b"x" * 15000).hexdigest()


def test_large_batch_summary_requires_engine_proof_and_stays_scoped(monkeypatch):
    history = OutputHistory()
    state = _state(monkeypatch, history)
    summary = "result " * 2000
    status, body = call(state, "store_output", output=summary, source="pc_batch", tool_call_ref=LIST_CALL)
    assert status == 200, body
    assert body["result"]["size"] == len(summary)
    assert history.output_calls[-1] == ("store", (OWNER, SUBJECT, RUN, DEVICE), "", "pc_batch:" + LIST_CALL)
    request = _SignedRequest(state, {"mode": "store_output", "subject_id": SUBJECT, "run_id": RUN,
        "device_id": DEVICE, "source": "pc_batch", "tool_call_ref": LIST_CALL, "output": summary})
    request.headers["X-Claw-Engine-Proof"] = "0" * 64
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    assert response.status_code == 401

def test_new_modes_require_independent_scope_proof(monkeypatch):
    state = _state(monkeypatch, OutputHistory())
    payload = {"mode": "job_start", "subject_id": SUBJECT, "run_id": RUN,
               "device_id": DEVICE, "operation": {"op": "list", "path": "."},
               "tool_call_ref": LIST_CALL}
    missing = _SignedRequest(state, payload)
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(missing))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "pc_scope_required"
    forged = _SignedRequest(state, payload, scope=FILES_SCOPE)
    forged.headers["X-Claw-PC-Scope-Proof"] = "0" * 64
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(forged))
    assert response.status_code == 401 and not state.history_store.rows


@pytest.mark.parametrize("endpoint", ["files", "chat_drive", "claw_drive"])
def test_callback_queue_rpc_disk_reference_roundtrip(monkeypatch, tmp_path, endpoint):
    """A real queued dispatch + real RPC + disk OutputStore, only PC execution is simulated."""
    import importlib.util
    from pathlib import Path
    from app.queue_store_proxy import QueueForwardingHistoryStore

    helper_path = Path(__file__).resolve().parents[2] / "padiem-mesh-queue/tests/test_queue_internal_store_rpc.py"
    spec = importlib.util.spec_from_file_location("chat_limits_queue_test_door", helper_path)
    queue_fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(queue_fixture)
    queue = queue_fixture._app(output_directory=str(tmp_path))
    inner = _History()
    parts = []

    class RpcClient:
        async def call(self, method, **arguments):
            request = queue_fixture._Request(queue.state, {"method": method, "arguments": arguments})
            parts.append((method, len(request._body)))
            response = await queue_fixture._handler(queue)(request)
            assert response.status_code == 200, (method, response.body)
            return queue_fixture._body(response)["result"]

    state = _state(monkeypatch, inner)
    state.history_store = QueueForwardingHistoryStore(inner, RpcClient())
    if endpoint == "files":
        entry = routes.oracle_mesh_engine_chat_files_call
        status, body = call(state, "job_start",
            operation={"op": "read", "path": "notes.txt"}, tool_call_ref=READ_CALL)
        assert status == 200, body
        job_id = body["result"]["job_id"]
    else:
        from app.chat_pc_drive import CHAT_PC_DRIVE_COMMAND
        entry = (routes.oracle_chat_engine_pc_drive_call if endpoint == "chat_drive"
                 else routes.oracle_mesh_engine_desktop_call)
        staged = asyncio.run(entry(_SignedRequest(state, {
            "mode": "dispatch", "subject_id": SUBJECT, "run_id": RUN,
            "device_id": DEVICE, "command": CHAT_PC_DRIVE_COMMAND})))
        assert staged.status_code == 200, staged.body
        job_id = json.loads(staged.body)["dispatch"]["dispatch_id"]
    connection = queue.state.queue_database.connection
    original = "START\n" + "line\n" * 220000 + "END"
    digest = hashlib.sha256(original.encode()).hexdigest()
    # The existing executor result lane normally pins this terminal row and private original.
    connection.execute(
        "UPDATE oracle_mesh_dispatch SET state='done', result_sha256=?, termination='exited', exit_code=0 "
        "WHERE dispatch_id=?", (digest, job_id))
    row = dict(connection.execute("SELECT * FROM oracle_mesh_dispatch WHERE dispatch_id=?", (job_id,)).fetchone())
    assert row["user_id"] == OWNER and row["device_id"] == DEVICE
    inner.rows[job_id] = row
    inner.originals[job_id] = original.encode()

    response = asyncio.run(entry(_SignedRequest(
        state, {"mode": "result", "subject_id": SUBJECT, "run_id": RUN, "dispatch_id": job_id},
        scope=FILES_SCOPE)))
    assert response.status_code == 200, response.body
    result = json.loads(response.body)["dispatch"]
    ref = result["output_ref"]
    assert result["content_sha256"] == result["result_sha256"] == digest
    assert ref["size"] == len(original) and ref["truncated"] is True
    assert len(result["output"]) <= 4101 and original not in result["output"]
    assert any(method == "append_pc_output" for method, _ in parts)
    assert max(size for _, size in parts) < 1_000_000

    recovered = []
    for offset in range(0, ref["size"], 65536):
        status, page = call(state, "read_output", handle=ref["handle"], offset=offset, length=65536)
        assert status == 200, page
        recovered.append(page["result"]["content"])
    assert "".join(recovered) == original
    status, found = call(state, "search_output", handle=ref["handle"], query="END")
    assert status == 200 and found["result"]["hits"][0]["offset"] == original.index("END")
    if endpoint == "files":
        status, page = call(state, "job_output", job_id=job_id, offset=len(original)-3, length=3)
        assert status == 200 and page["result"]["content"] == "END"
        assert page["result"]["output_ref"]["handle"] == ref["handle"]

    foreign_run = RUN + "-other"
    inner.run_rows[foreign_run] = {**inner.run_rows[RUN], "run_id": foreign_run}
    foreign = _SignedRequest(state, {"mode": "read_output", "subject_id": SUBJECT,
        "run_id": foreign_run, "device_id": DEVICE, "handle": ref["handle"],
        "offset": 0, "length": 100}, scope=FILES_SCOPE)
    denied = asyncio.run(routes.oracle_mesh_engine_chat_files_call(foreign))
    assert denied.status_code != 200 and "START" not in denied.body.decode()

def test_job_keeps_write_expectation_without_content_and_exposes_failed_log(monkeypatch):
    history = OutputHistory()
    state = _state(monkeypatch, history)
    scope = {"version": 1, "requested": "files_write", "admitted": "files_write",
             "source": "declared", "ops": ["write", "move", "delete"], "app_id": "padiem-chat"}
    content = "한글 원문"
    status, body = call(state, "job_start", scope=scope, operation={
        "op": "write", "path": "notes.txt", "content": content}, tool_call_ref=LIST_CALL)
    assert status == 200, body
    job_id = body["result"]["job_id"]
    operation = history.rows[job_id]["job_operation"]
    assert operation == {"op": "write", "path": "notes.txt",
        "expected_bytes": len(content.encode()), "expected_sha256": hashlib.sha256(content.encode()).hexdigest()}
    assert "content" not in operation
    finish(history, job_id, "verified diagnostic: access denied")
    history.rows[job_id].update(state="failed", termination="exited", exit_code=1)
    status, body = call(state, "job_status", scope=scope, job_id=job_id)
    assert status == 200 and body["result"]["operation"] == operation
    assert body["result"]["state"] == "failed"
    status, body = call(state, "job_output", scope=scope, job_id=job_id, offset=0, length=100)
    assert status == 200, body
    assert body["result"]["state"] == "failed" and body["result"]["exit_code"] == 1
    assert body["result"]["content"] == "verified diagnostic: access denied"
    assert body["result"]["operation"] == operation