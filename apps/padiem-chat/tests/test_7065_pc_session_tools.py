"""Session v1 crosses the existing dispatch/receipt boundaries without a PC."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from app import mcp_gateway_session as sessions
from app import mcp_gateway_shell as shell

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


def test_start_input_read_stop_use_helper_v1_and_common_receipt(rig):
    opened = start(rig)
    assert opened["status"] == "completed" and opened["alive"] is True
    job = opened["job_id"]
    assert opened["session"] == job[4:]
    typed = call(rig, "pc_shell_input", {"job_id": job, "text": "한글", "wait_ms": 10})
    assert typed["output"] == "한글\n" and typed["offset"] == opened["end_offset"]
    read = call(rig, "pc_shell_read", {"job_id": job, "offset": typed["offset"], "length": 7})
    assert read["output"] == "한글\n" and read["next_offset"] == typed["next_offset"]
    ended = call(rig, "pc_shell_stop", {"job_id": job})
    assert ended["alive"] is False and ended["ended"] == "stopped"
    staged = rig[1].staged
    assert [s["background"] for s in staged] == [True, False, False, False]
    assert staged[0]["job_operation"] == {"op": "session"}
    assert all(s["user_mode"] is True for s in staged)
    assert all(json.loads(s["command"])["shell"] == "session" for s in staged)


@pytest.mark.parametrize("identity", [
    {**IDENTITY, "token_id": "mcp_" + "d" * 32}, {**IDENTITY, "user_id": "usr_" + "e" * 32}])
@pytest.mark.parametrize("tool", ["pc_shell_input", "pc_shell_read", "pc_shell_stop"])
def test_other_account_or_token_cannot_operate_session(rig, identity, tool):
    job = start(rig)["job_id"]
    result = call(rig, tool, {"job_id": job, **({"text": "no"} if tool == "pc_shell_input" else {})}, identity=identity)
    assert result is None or result["status"] == "denied"
    assert len(rig[1].staged) == 1 and not rig[3].values


def test_status_projects_only_the_authorized_job(rig):
    job = start(rig)["job_id"]
    rig[2].outputs["f" * 32], rig[2].alive["f" * 32] = b"foreign", True
    result = call(rig, "pc_shell_read", {"job_id": job, "status_only": True})
    assert [r["session"] for r in result["sessions"]] == [job[4:]]
    assert "foreign" not in json.dumps(result) and "f" * 32 not in json.dumps(result)


@pytest.mark.parametrize("code, expected", [("user_helper_refused", "pc_session_unsupported"),
                                           ("user_session_unavailable", "user_session_unavailable")])
def test_missing_or_old_helper_fails_without_system_fallback(rig, code, expected):
    rig[2].error = code
    assert start(rig)["code"] == expected
    assert len(rig[1].staged) == 1 and rig[1].staged[0]["user_mode"] is True


def test_disabled_sessions_and_system_mode_never_dispatch(rig):
    rig[0].app.state.settings.mcp_pc_session_enabled = False
    assert start(rig)["status"] == "tool_not_enabled"
    rig[0].app.state.settings.mcp_pc_session_enabled = True
    assert call(rig, "pc_shell_start", {"interactive": True, "command": "", "mode": "system"})["code"] == "pc_session_user_mode_only"
    assert not rig[1].staged


def test_secret_requires_missing_helper_masking_before_deposit(rig):
    job = start(rig)["job_id"]
    value = "secret-never-deposited"
    result = call(rig, "pc_shell_input", {"job_id": job, "text": value, "secret": True})
    assert result["code"] == "pc_session_unsupported"
    assert not rig[3].values and not rig[3].takes
    assert [op["op"] for op in rig[2].operations] == ["start", "status"]
    assert value not in json.dumps(rig[1].staged, default=vars)


def test_capable_fake_helper_secret_never_enters_durable_input_material(rig):
    job = start(rig)["job_id"]
    rig[2].features.append("secret_mask")
    value = "one-shot-secret"
    result = call(rig, "pc_shell_input", {"job_id": job, "text": value, "secret": True})
    assert result["output"] == "[masked]\n"
    records = json.dumps(rig[1].staged, default=vars) + repr(rig[1].originals) + json.dumps(rig[1].runs)
    assert value not in records and base64.b64encode(value.encode()).decode() not in records
    assert hashlib.sha256(value.encode()).hexdigest()[:8] not in records
    marker = json.loads(rig[1].staged[-1]["command"])["session_input"]
    assert set(marker) == {"ref", "chars", "bytes"}
    assert asyncio.run(rig[3].take_desktop_text(ref=marker["ref"])) is None


def test_lost_input_reply_is_uncertain_and_not_resubmitted(rig, monkeypatch):
    job = start(rig)["job_id"]
    async def unavailable(*args, **kwargs):
        return None
    monkeypatch.setattr(shell, "_read_original", unavailable)
    result = call(rig, "pc_shell_input", {"job_id": job, "text": "once"})
    assert result["code"] == "pc_session_input_uncertain"
    assert sum(op["op"] == "input" for op in rig[2].operations) == 1


def test_bounds_and_invalid_types_are_rejected():
    job = "dsp_" + "a" * 32
    good = {"job_id": job, "text": "x" * 4000, "wait_ms": 10000, "length": 65536}
    assert sessions.validate_pc_session_input_arguments(good)
    for bad in ({"text": "x" * 4001}, {"text": "\r"}, {"text": "\x00"}, {"wait_ms": 10001},
                {"wait_ms": True}, {"length": 65537}, {"offset": -1}, {"secret": 1}, {"key": []}):
        assert not sessions.validate_pc_session_input_arguments({**good, **bad})
    assert shell.validate_pc_shell_start_arguments({"interactive": True, "command": ""})
    assert not shell.validate_pc_shell_start_arguments({"interactive": True, "command": ""}, session_enabled=False)


def test_foreign_reply_is_never_the_requested_session():
    body = json.dumps({"v": 1, "ok": True, "op": "read", "session": "b" * 32}) + "\nforeign"
    assert sessions.project_session_reply(body, op="read", session_id="a" * 32)["code"] == "pc_session_bad_reply"


@pytest.mark.parametrize("bad", [{"v": True}, {"alive": "false"}, {"ended": 123},
                                 {"exit_code": "0"}, {"backend": "unknown"}])
def test_bad_v1_metadata_is_not_success(bad):
    header = {"v": 1, "ok": True, "op": "read", "session": "a" * 32, **bad}
    assert sessions.project_session_reply(json.dumps(header), op="read", session_id="a" * 32)["code"] == "pc_session_bad_reply"


def test_status_refusal_keeps_its_error():
    header = {"v": 1, "ok": False, "op": "status", "code": "pc_session_bad_request"}
    result = sessions.project_session_reply(json.dumps(header), op="status", session_id="a" * 32)
    assert result["status"] == "failed" and result["code"] == "pc_session_bad_request"


def test_execution_adapter_routes_all_session_tools_without_normal_command_fallback(rig, monkeypatch):
    from app import mcp_gateway_execution as execution
    async def owner(*args):
        return SimpleNamespace(session_id="session_fixture", tenant_id="workspace"), "subject_fixture", "workspace"
    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    principal = {"owner_id": UID, "token_id": IDENTITY["token_id"], "device_id": DEVICE}
    def execute(tool, arguments):
        return asyncio.run(execution.execute_mcp_pc_tool(rig[0], principal, tool, arguments))
    opened = execute("pc_shell_start", {"interactive": True, "command": "", "mode": "user"})
    job = opened["job_id"]
    rig[1].receipts.add(job)
    typed = execute("pc_shell_input", {"job_id": job, "text": "one"})
    assert typed["output"] == "one\n"
    assert execute("pc_shell_read", {"job_id": job, "offset": typed["offset"]})["output"] == "one\n"
    assert execute("pc_shell_stop", {"job_id": job})["ended"] == "stopped"
    assert [op["op"] for op in rig[2].operations] == ["start", "input", "read", "stop"]


def test_disabled_ordinary_job_does_not_touch_session_receipts(rig):
    rig[0].app.state.settings.mcp_pc_session_enabled = False
    async def unexpected(**kwargs):
        raise AssertionError("ordinary off path must not inspect a session")
    rig[1].get_pc_output_dispatch_for_owner = unexpected
    assert call(rig, "pc_shell_read", {"job_id": "dsp_" + "1" * 32}) is None
