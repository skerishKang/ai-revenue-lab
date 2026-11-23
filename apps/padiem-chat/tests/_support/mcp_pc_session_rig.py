"""#8061: shared MCP PC-session rig fixtures.

Moved verbatim from ``test_7065_pc_session_tools.py`` so sibling session tests
stop importing a test file. Doubles, dispatch behavior and assertions are unchanged.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from app import mcp_gateway_session as sessions


UID = "usr_" + "a" * 32
DEVICE = "dev_" + "b" * 32
IDENTITY = {"user_id": UID, "token_id": "mcp_" + "c" * 32, "device_id": DEVICE}


class FakeHelper:
    def __init__(self):
        self.outputs = {}
        self.alive = {}
        self.operations = []
        self.features = ["pipe"]
        self.error = None

    def handle(self, op, dispatch_id):
        self.operations.append(op)
        if self.error:
            return json.dumps({"ok": False, "error_code": self.error, "detail": ""})
        kind = op["op"]
        sid = dispatch_id[4:] if kind == "start" else op.get("session")
        if kind == "status":
            return json.dumps({"v": 1, "ok": True, "code": None, "op": kind,
                "limit": 4, "features": self.features, "sessions": [
                    {"session": s, "alive": alive, "backend": "pipe", "end_offset": len(self.outputs[s])}
                    for s, alive in self.alive.items()]}) + "\n"
        if kind == "start":
            self.outputs[sid] = b"prompt> "
            self.alive[sid] = True
        if sid not in self.outputs:
            return json.dumps({"v": 1, "ok": False, "code": "pc_session_not_found",
                               "op": kind, "session": sid}) + "\n"
        before = len(self.outputs[sid])
        if kind == "input":
            text = base64.b64decode(op.get("text_b64", ""))
            self.outputs[sid] += b"[masked]" if op.get("secret") else text
            if op.get("enter", True):
                self.outputs[sid] += b"\n"
        if kind == "stop":
            self.alive[sid] = False
        offset = op.get("offset", before if kind in ("input", "stop") else 0)
        output = self.outputs[sid][offset:offset + op.get("length", 32768)]
        return json.dumps({"v": 1, "ok": True, "code": None, "op": kind, "session": sid,
            "alive": self.alive[sid], "ended": None if self.alive[sid] else "stopped",
            "exit_code": None if self.alive[sid] else 0, "offset": offset,
            "next_offset": offset + len(output), "end_offset": len(self.outputs[sid]),
            "dropped_bytes": 0, "idle_ms": 0, "ends_with_newline": output.endswith(b"\n"),
            "backend": "pipe"}) + "\n" + output.decode("utf-8")


class MemoryQueue:
    def __init__(self):
        self.values = {}
        self.takes = []

    async def call(self, name, *, ref, text):
        assert name == "deposit_desktop_text"
        self.values[ref] = text
        return True

    async def take_desktop_text(self, *, ref):
        self.takes.append(ref)
        return self.values.pop(ref, None)


class History:
    def __init__(self):
        self.rows, self.originals, self.runs = {}, {}, {}
        self.receipts = set()
        self.staged = []

    async def record_chat_pc_drive_run(self, **kwargs):
        self.runs[kwargs["run_id"]] = kwargs
        return "chat_" + "9" * 32

    async def get_pc_output_dispatch_for_owner(self, *, user_id, dispatch_id):
        row = self.rows.get(dispatch_id)
        return row if row and row["user_id"] == user_id else None

    get_oracle_mesh_dispatch_for_owner = get_pc_output_dispatch_for_owner

    async def owns_job_receipt(self, *, identity, job_id):
        return identity == IDENTITY and job_id in self.receipts

    async def read_oracle_mesh_original(self, *, user_id, dispatch_id, **kwargs):
        body = self.originals[dispatch_id]
        return body, hashlib.sha256(body).hexdigest()


@pytest.fixture
def rig(monkeypatch):
    from app import mcp_gateway_execution as execution, oracle_mesh_read_return_routes as routes
    from app import pc_work_context
    history, helper, queue = History(), FakeHelper(), MemoryQueue()
    state = SimpleNamespace(history_store=history, mcp_gateway_store=history,
        queue_client=queue, desktop_text_store=queue, settings=SimpleNamespace(
            mcp_pc_session_enabled=True, mcp_pc_shell_enabled=True, mcp_pc_shell_user_mode_enabled=True))
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    async def context(*args, **kwargs):
        return SimpleNamespace(selection_offline=False, selected_confirmed=True, tool_available=True,
            selected_device_id=DEVICE, execution_device_id=DEVICE)

    async def grant(*args, **kwargs):
        return True

    async def dispatch(_request, **kwargs):
        history.staged.append(kwargs)
        did = "dsp_" + format(len(history.staged), "032x")
        material = json.loads(kwargs["command"])
        op = json.loads(base64.b64decode(material["command"]))
        marker = material.get("session_input")
        if marker:
            text = await queue.take_desktop_text(ref=marker["ref"])
            op["text_b64"] = base64.b64encode(text.encode()).decode()
        body = helper.handle(op, did).encode()
        row = {"dispatch_id": did, "user_id": UID, "device_id": DEVICE, "kind": "command",
               "run_id": kwargs["wire"]["run_id"], "state": "done", "command_id": "cmd_fixture",
               "revision_ref": "rev_fixture", "result_sha256": hashlib.sha256(body).hexdigest(),
               "result_bytes": len(body), "job_operation": kwargs.get("job_operation")}
        history.rows[did], history.originals[did] = row, body
        return SimpleNamespace(status_code=200, body=json.dumps({"dispatch": row}).encode())

    monkeypatch.setattr(pc_work_context, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(routes, "dispatch_oracle_mesh_command_intent", dispatch)
    return request, history, helper, queue


def call(rig, tool, args, *, identity=None):
    request, history, _, _ = rig
    result = asyncio.run(sessions.execute_session_tool(request, tool_name=tool, arguments=args,
        identity=identity or IDENTITY, session=SimpleNamespace(session_id="session_fixture", tenant_id="workspace"),
        subject_id="subject_fixture", workspace_id="workspace"))
    if result and tool == "pc_shell_start" and "job_id" in result:
        history.receipts.add(result["job_id"])
    return result


def start(rig):
    return call(rig, "pc_shell_start", {"interactive": True, "command": "", "mode": "user"})


