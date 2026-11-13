"""Session input uses one-shot poll material and the existing tagged helper lane."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from kagent.local_agent_meshcentral_command_port import MeshCentralCliCommandPort
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshChannelRefused, OracleMeshDispatch, OracleMeshExecutor, POLL_PATH,
)

SESSION = "1" * 32
NODE = "test-device@mesh"


def _material(op, *, text=None, secret=False, **fields):
    document = {"v": 1, "op": op, **fields}
    if op in {"input", "read", "stop"}:
        document.setdefault("session", SESSION)
    if op == "input":
        document["secret"] = secret
    material = {"shell": "session", "command": base64.b64encode(json.dumps(document).encode()).decode(),
                "cwd": None, "timeout_seconds": 0, "distro": None}
    if op == "status":
        material["session_scope"] = SESSION
    if text is not None:
        marker = {"ref": "c" * 32, "chars": len(text), "bytes": len(text.encode())}
        if not secret:
            marker["sha256_prefix"] = hashlib.sha256(text.encode()).hexdigest()[:8]
        material["session_input"] = marker
    return material


def _dispatch(op="input", *, text=None, secret=False, **fields):
    return OracleMeshDispatch(
        dispatch_id="dsp_" + SESSION, nonce="test-nonce", node_ref=NODE, file_path="command",
        command_id="command-test", run_id="run-test", kind="command", user_mode=True,
        command_text=json.dumps(_material(op, text=text, secret=secret, **fields)), session_input_text=text,
    )


class FakeHelper:
    """An in-memory helper process seam; no OS process or network is opened."""
    def __init__(self):
        self.calls = []
        self.requests = []
        self.output = ""
        self.alive = False
        self.unavailable = False
        self.status_body = None

    def build(self, **request):
        self.requests.append(request)
        return "user-helper-client"

    def run_command(self, **kwargs):
        self.calls.append(kwargs)
        if self.unavailable:
            output = b"user_session_unavailable: helper pipe is not available"
        else:
            request = self.requests[-1]
            operation = json.loads(base64.b64decode(request["command"]))
            op = operation["op"]
            if op == "start":
                self.alive = True
            elif op == "input":
                # Model a program that does not echo sensitive input.
                self.output += "accepted\n"
            elif op == "stop":
                self.alive = False
            offset = operation.get("offset", 0)
            raw = self.output.encode()
            chunk = raw[offset:offset + operation.get("length", 32768)]
            header = {"v": 1, "ok": True, "code": None, "op": op, "session": SESSION,
                      "alive": self.alive, "offset": offset, "next_offset": offset + len(chunk),
                      "end_offset": len(raw), "backend": "pipe"}
            body = json.dumps(header).encode() + b"\n" + chunk
            if op == "status":
                body = self.status_body or _status_body()
            output = json.dumps({"status": "ok", "request_id": request["request_id"], "exit_code": 0,
                                 "stdout_b64": base64.b64encode(body).decode(), "stderr_b64": ""}).encode()
        return SimpleNamespace(termination="exited", exit_code=0, output=output,
                               line_blocked=0, line_cleared=0)


def _executor(helper=None, *, pending_dir=None, enabled=True, transport=None):
    helper = helper or FakeHelper()
    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret="synthetic-channel-proof",
        read_port=SimpleNamespace(read_bytes=lambda *args, **kwargs: b""), command_port=helper,
        transport=transport or (lambda *_: (200, {"ok": True, "working": True})),
        pending_dir=str(pending_dir) if pending_dir is not None else None, session_enabled=enabled,
    )
    executor.build_user_helper_pipe_client_ps = helper.build
    executor.start_lease_renewal = lambda _: None
    return executor, helper


def _header(outcome):
    return json.loads(outcome.body.split(b"\n", 1)[0])


def _status_body():
    return json.dumps({"v": 1, "ok": True, "code": None, "op": "status", "limit": 4,
                       "features": ["pipe"], "sessions": []}).encode()


def test_start_input_read_stop_flow_uses_the_same_helper_and_offsets():
    executor, helper = _executor()
    start = _dispatch("start", shell="cmd", command="echo-program", wait_ms=10000)
    assert _header(executor.execute(start))["alive"] is True
    assert helper.requests[-1]["request_id"] == "req_" + SESSION
    assert _header(executor.execute(_dispatch(text="hello", wait_ms=0)))["next_offset"] == 9
    outcome = executor.execute(_dispatch("read", offset=3, length=4, wait_ms=10000))
    assert outcome.body.split(b"\n", 1)[1] == b"epte"
    assert _header(executor.execute(_dispatch("stop")))["alive"] is False
    assert _header(executor.execute(_dispatch("status")))["op"] == "status"
    assert all(call["dispatch_id"].startswith("dsp_") and call["deliver_as_file"] for call in helper.calls)


@pytest.mark.parametrize("secret", [False, True])
def test_poll_value_is_inserted_only_into_the_helper_frame(secret):
    text = "synthetic input 한글\nsecond line"
    dispatch = _dispatch(text=text, secret=secret)
    wire = asdict(dispatch)
    executor, helper = _executor(transport=lambda path, _: (200, {"ok": True, "dispatch": wire})
                                 if path == POLL_PATH else (200, {"ok": True}))
    claimed = executor.poll_once()
    outcome = executor.execute(claimed)
    assert _header(outcome)["ok"]
    operation = json.loads(base64.b64decode(helper.requests[0]["command"]))
    assert base64.b64decode(operation["text_b64"]).decode() == text
    assert "session_input" not in helper.requests[0]
    assert "text_b64" not in base64.b64decode(json.loads(claimed.command_text)["command"]).decode()
    assert text not in repr(claimed)
    marker = json.loads(claimed.command_text)["session_input"]
    assert ("sha256_prefix" in marker) is not secret


@pytest.mark.parametrize("fields", [{"text_b64": ""}, {"key": "enter"}])
def test_empty_text_and_named_keys_need_no_one_shot_text_value(fields):
    executor, helper = _executor()
    assert _header(executor.execute(_dispatch(**fields)))["ok"] is True
    operation = json.loads(base64.b64decode(helper.requests[0]["command"]))
    assert all(operation[key] == value for key, value in fields.items())


def test_marker_hash_and_exact_dispatch_number_are_checked():
    executor, helper = _executor()
    dispatch = _dispatch(text="valid")
    material = json.loads(dispatch.command_text)
    material["session_input"]["sha256_prefix"] = "0" * 8
    assert _header(executor.execute(replace(dispatch, command_text=json.dumps(material))))["error_code"] == "pc_session_input_uncertain"
    assert _header(executor.execute(replace(_dispatch("start"), dispatch_id="dsp_abc")))["error_code"] == "pc_session_bad_request"
    assert not helper.calls


def test_secret_input_never_enters_trace_or_failed_submission_recovery(tmp_path, capsys):
    value = "synthetic-sensitive-input-unique"
    executor, helper = _executor(pending_dir=tmp_path, transport=lambda *_: (503, {"ok": False}))
    dispatch = _dispatch(text=value, secret=True)
    outcome = executor.execute(dispatch)
    executor.submit(dispatch, outcome)
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files
    for path in files:
        stored = path.read_bytes()
        assert value.encode() not in stored
        assert base64.b64encode(value.encode()) not in stored
        assert b"session_input_text" not in stored
    assert value not in str(capsys.readouterr())
    assert json.loads(base64.b64decode(helper.requests[0]["command"]))["secret"] is True


@pytest.mark.parametrize("bad_text", ["a" * 4001, "bad\x00value", "bad\rvalue", 7, {"text": "bad"}])
def test_poll_refuses_invalid_input_without_logging_it(bad_text):
    wire = asdict(_dispatch(text="valid"))
    wire["session_input_text"] = bad_text
    executor, helper = _executor(transport=lambda *_: (200, {"ok": True, "dispatch": wire}))
    with pytest.raises(OracleMeshChannelRefused, match="invalid session input projection"):
        executor.poll_once()
    assert not helper.calls


@pytest.mark.parametrize("mutation", ["missing", "different", "background", "inline", "hash_for_secret"])
def test_uncertain_or_persisted_input_is_never_executed(mutation):
    dispatch = _dispatch(text="private-test-value", secret=True)
    material = json.loads(dispatch.command_text)
    if mutation == "missing":
        dispatch = replace(dispatch, session_input_text=None)
    elif mutation == "different":
        dispatch = replace(dispatch, session_input_text="changed")
    elif mutation == "background":
        dispatch = replace(dispatch, background=True, owner_ref="test-owner")
    elif mutation == "hash_for_secret":
        material["session_input"]["sha256_prefix"] = "f" * 8
    else:
        document = json.loads(base64.b64decode(material["command"]))
        document["text_b64"] = base64.b64encode(b"stored-value").decode()
        material["command"] = base64.b64encode(json.dumps(document).encode()).decode()
    dispatch = replace(dispatch, command_text=json.dumps(material))
    executor, helper = _executor()
    assert executor.execute(dispatch).termination == "not_executed"
    assert not helper.calls


def test_background_input_is_refused_before_any_job_receipt_is_written(tmp_path):
    dispatch = replace(_dispatch(text="sensitive-test-value", secret=True), background=True, owner_ref="owner")
    executor, helper = _executor(pending_dir=tmp_path)
    executor.poll_once = lambda: dispatch
    executor._background_manager = lambda: pytest.fail("input reached durable background storage")
    executor.run_once()
    assert not helper.calls
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("fields", [{"wait_ms": 10001}, {"wait_ms": -1}, {"wait_ms": True},
                                    {"length": 65537}, {"offset": -1}, {"session": "short"}])
def test_invalid_read_bounds_never_reach_the_helper(fields):
    executor, helper = _executor()
    assert _header(executor.execute(_dispatch("read", **fields)))["error_code"] == "pc_session_bad_request"
    assert not helper.calls


def test_missing_helper_never_falls_back_to_a_system_command():
    executor, helper = _executor()
    helper.unavailable = True
    assert _header(executor.execute(_dispatch("start")))["error_code"] == "user_session_unavailable"
    assert len(helper.calls) == 1 and helper.calls[0]["command"] == "user-helper-client"


def test_lost_input_response_is_uncertain_and_is_never_retried():
    executor, helper = _executor()
    def no_reply(**kwargs):
        helper.calls.append(kwargs)
        raise OSError("synthetic port failure")
    helper.run_command = no_reply
    outcome = executor.execute(_dispatch(text="one-shot"))
    assert _header(outcome)["error_code"] == "pc_session_input_uncertain"
    assert len(helper.calls) == 1


def test_status_is_scoped_before_submission_and_recovery_storage(tmp_path):
    foreign = "f" * 32
    submitted = []
    def transport(path, payload):
        submitted.append(payload)
        return 503, {"ok": False}
    executor, helper = _executor(pending_dir=tmp_path, transport=transport)
    own = {"session": SESSION, "alive": True, "ended": None, "exit_code": None,
           "backend": "pipe", "end_offset": 0, "idle_ms": 0, "unknown": foreign}
    other = {**own, "session": foreign}
    header = json.loads(_status_body())
    header.update(sessions=[own, other], unknown=foreign, features=["pipe", foreign, {"private": foreign}])
    helper.status_body = json.dumps(header).encode() + b"\n" + foreign.encode()
    dispatch = _dispatch("status")
    outcome = executor.execute(dispatch)
    assert _header(outcome)["sessions"] == [{key: value for key, value in own.items() if key != "unknown"}]
    assert foreign.encode() not in outcome.body
    assert "session_scope" not in helper.requests[0]
    assert json.loads(base64.b64decode(helper.requests[0]["command"])) == {"v": 1, "op": "status"}
    executor.submit(dispatch, outcome)
    assert foreign not in json.dumps(submitted)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert foreign.encode() not in path.read_bytes()


@pytest.mark.parametrize("scope", [None, "invalid", True])
def test_status_without_a_valid_authenticated_scope_does_not_reach_helper(scope):
    executor, helper = _executor()
    dispatch = _dispatch("status")
    material = json.loads(dispatch.command_text)
    material["session_scope"] = scope
    assert _header(executor.execute(replace(dispatch, command_text=json.dumps(material))))["error_code"] == "pc_session_bad_request"
    assert not helper.calls


def test_off_switch_and_system_mode_do_not_execute_a_session(monkeypatch):
    monkeypatch.delenv("PADIEM_MCP_PC_SESSION_ENABLED", raising=False)
    executor, helper = _executor(enabled=None)
    assert _header(executor.execute(_dispatch("start")))["error_code"] == "pc_session_unsupported"
    assert _header(executor.execute(replace(_dispatch("start"), user_mode=False)))["error_code"] == "pc_session_user_mode_only"
    assert not helper.calls


def test_session_start_waits_for_the_same_pc_console_lock():
    executor, helper = _executor()
    dispatch = replace(_dispatch("start"), background=True, owner_ref="owner")
    lock = executor._node_execution_lock(dispatch)
    lock.acquire()
    finished = threading.Event()
    result = []
    def run():
        result.append(executor._run_background_dispatch(asdict(dispatch), cancel_probe=lambda: False))
        finished.set()
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert not finished.wait(0.1)
        assert not helper.calls
    finally:
        lock.release()
        thread.join(3)
    assert finished.is_set() and result[0]["termination"] == "exited"


def test_session_and_ordinary_commands_select_their_own_envelopes_on_one_pc():
    own_reply = json.dumps({"status": "ok", "exit_code": 0,
                            "stdout_b64": base64.b64encode(_status_body()).decode()})
    foreign_tag = "dsp_" + "f" * 32 + ":" + "e" * 32
    def frame(tag, body, code):
        return ("PADIEM_B64=" + tag + ":" + base64.b64encode(body).decode()
                + "\n__PADIEM_EXIT__" + str(code) + "\n").encode()
    calls = []
    def runner(argv, **kwargs):
        tag = re.search(r"dsp_[0-9a-f]{32}:[0-9a-f]{32}", " ".join(argv)).group()
        body = own_reply.encode() if not calls else b"ordinary-result"
        calls.append(tag)
        stdout = frame(foreign_tag, b"foreign-result", 9) + frame(tag, body, 0) + frame(foreign_tag, b"foreign-after", 8)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")
    port = MeshCentralCliCommandPort(
        command_runner=runner, meshctrl_js="test-meshctrl.js", login_user="test-user",
        password_provider=lambda: "synthetic-password", url="wss://127.0.0.1:4443",
    )
    executor, _ = _executor()
    executor._command_port = port
    assert _header(executor.execute(_dispatch("status")))["ok"] is True
    ordinary = replace(_dispatch("status"), dispatch_id="dsp_" + "2" * 32,
                       user_mode=False, command_text="echo ordinary")
    outcome = executor.execute(ordinary)
    assert outcome.exit_code == 0 and outcome.body == b"ordinary-result"
    assert calls[0] != calls[1]
