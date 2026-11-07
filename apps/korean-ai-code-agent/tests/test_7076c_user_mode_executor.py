"""#7076c executor behavior: user_mode dispatch uses pipe-client PS, pipe absent -> user_session_unavailable, no SYSTEM fallback."""
from __future__ import annotations
import base64, json, threading, time
from dataclasses import asdict

from kagent.local_agent_oracle_mesh_executor import OracleMeshDispatch, OracleMeshExecutor, OracleMeshChannelRefused, USER_SESSION_UNAVAILABLE

DEVICE = "dev_" + "c" * 32
NODE = DEVICE + "@node"


class FakePort:
    def __init__(self, termination="exited", output=b""):
        self.calls = []
        self.termination = termination
        self.output = output
    def run_command(self, **kw):
        self.calls.append(kw)
        class O: pass
        o = O(); o.termination = self.termination; o.exit_code = 0 if self.termination=="exited" else None; o.output = self.output; o.line_blocked=0; o.line_cleared=0
        return o


def _executor(port):
    ex = object.__new__(OracleMeshExecutor)
    ex._command_port = port
    ex._desktop_port = None
    ex._poll_url = ex._submit_url = ex._busy_url = ex._cancel_url = ""
    ex._line_blocked = ex._line_cleared = 0
    ex._post = lambda *a,**k: (200, {"ok":True,"working":True})
    ex._trace_command = lambda *a,**k: None
    ex._cancel_probe = lambda d: (lambda: False)
    ex._line_guard = lambda d: (lambda: False)
    ex.active_dispatch_ids = lambda: ()
    return ex


def test_user_mode_dispatch_builds_pipe_client_and_submits_helper_reply():
    helper_reply = json.dumps({"request_id":"req_"+"0"*32,"status":"ok","exit_code":0,
                               "stdout_b64":base64.b64encode(b"limone\r\n").decode(),"stderr_b64":"","duration_ms":5}).encode()
    port = FakePort(output=helper_reply)
    ex = _executor(port)
    d = OracleMeshDispatch(dispatch_id="dsp_"+"1"*32, nonce="n", node_ref=NODE, file_path="command",
                           command_id="c", run_id="r", kind="command",
                           command_text=json.dumps({"shell":"whoami","command":"whoami","cwd":None,"timeout_seconds":30,"distro":None}),
                           user_mode=True, device_id=DEVICE)
    out = ex.execute(d)
    assert len(port.calls) == 1
    sent = port.calls[0]["command"]
    # goes through meshctrl runcommand (command port) carrying PS pipe client, not SYSTEM shell command
    assert "NamedPipeClientStream" in sent or "padiem-user-helper" in sent
    assert "user_session_unavailable" not in json.dumps(out.body.decode("utf-8", "replace"))
    assert b"limone" in out.body
    assert out.exit_code == 0
    # no direct whoami-as-system: the pipe client runs; command material is inside request JSON
    assert "Get-ScheduledTask" in sent  # secret path discovered on PC, not in dispatch


def test_user_mode_pipe_absent_maps_to_user_session_unavailable_no_fallback():
    port = FakePort(output=b"user_session_unavailable: helper pipe is not available\n")
    ex = _executor(port)
    d = OracleMeshDispatch(dispatch_id="dsp_"+"2"*32, nonce="n", node_ref=NODE, file_path="command",
                           command_id="c", run_id="r", kind="command",
                           command_text=json.dumps({"shell":"whoami","command":"whoami","cwd":None,"timeout_seconds":30,"distro":None}),
                           user_mode=True, device_id=DEVICE)
    out = ex.execute(d)
    body = json.loads(out.body.decode())
    assert body["error_code"] == USER_SESSION_UNAVAILABLE
    # only one run_command (pipe client); no SYSTEM fallback command
    assert len(port.calls) == 1
    assert "Get-ScheduledTask" in port.calls[0]["command"]


def test_user_mode_missing_dispatch_device_id_still_uses_the_task_arguments():
    port = FakePort(output=b"user_session_unavailable: helper device id is not configured\n")
    ex = _executor(port)
    # node_ref has a mesh id but dispatch.device_id is missing; the client must
    # still be sent because the PC's registered task is the only authority.
    d = OracleMeshDispatch(dispatch_id="dsp_"+"4"*32, nonce="n", node_ref="node//abcdef$X99@mesh", file_path="command",
                           command_id="c", run_id="r", kind="command",
                           command_text=json.dumps({"shell":"whoami","command":"whoami","cwd":None,"timeout_seconds":30,"distro":None}),
                           user_mode=True, device_id="")
    out = ex.execute(d)
    body = json.loads(out.body.decode())
    assert body["error_code"] == USER_SESSION_UNAVAILABLE
    assert len(port.calls) == 1
    sent = port.calls[0]["command"]
    assert "Get-ScheduledTask" in sent
    assert "--device-id" in sent
    # no SYSTEM fallback: only the pipe client ran


def test_user_mode_accepts_raw_meshcentral_device_id():
    raw = "abcdefghijklmnopqrstuvwx1234567890ABCDEFGHIJKLMNOPQRSTfi$D62t1"
    helper_reply = json.dumps({"request_id":"req_"+"0"*32,"status":"ok","exit_code":0,
                               "stdout_b64":base64.b64encode(b"limone\r\n").decode(),"stderr_b64":"","duration_ms":5}).encode()
    port = FakePort(output=helper_reply)
    ex = _executor(port)
    d = OracleMeshDispatch(dispatch_id="dsp_"+"5"*32, nonce="n", node_ref=raw+"@mesh", file_path="command",
                           command_id="c", run_id="r", kind="command",
                           command_text=json.dumps({"shell":"whoami","command":"whoami","cwd":None,"timeout_seconds":30,"distro":None}),
                           user_mode=True, device_id=raw)
    out = ex.execute(d)
    assert b"limone" in out.body
    sent = port.calls[0]["command"]
    assert raw not in sent and "$D62t1" not in sent


def test_system_mode_dispatch_uses_normal_command_path():
    port = FakePort(output=b"ok\n")
    ex = _executor(port)
    d = OracleMeshDispatch(dispatch_id="dsp_"+"3"*32, nonce="n", node_ref=NODE, file_path="command",
                           command_id="c", run_id="r", kind="command",
                           command_text="hostname.exe", user_mode=False, device_id=DEVICE)
    # _execute_command will call port.run_command with the raw command text
    out = ex.execute(d)
    assert port.calls[0]["command"] == "hostname.exe"


class SlowUserPort:
    def __init__(self):
        self.calls = []
        self.release = threading.Event()

    def run_command(self, **kw):
        self.calls.append(kw)
        class O: pass
        o = O(); o.line_blocked = 0; o.line_cleared = 0
        if "padiem-user-helper" in kw.get("command", ""):
            assert self.release.wait(10), "the user command was never released"
            o.termination = "exited"; o.exit_code = 0
            o.output = json.dumps({"status": "ok", "exit_code": 0,
                                   "stdout_b64": base64.b64encode(b"user-done").decode(),
                                   "stderr_b64": ""}).encode()
        else:
            o.termination = "exited"; o.exit_code = 0; o.output = b"system-ok\n"
        return o


def test_a_long_user_dispatch_does_not_hold_the_node_console_lock():
    port = SlowUserPort()
    ex = _executor(port)
    ex._node_execution_locks = {}
    ex._active_by_node = {}
    ex._active_background = {}
    ex._active_lock = threading.Lock()
    ex._background_jobs = None
    ex.start_lease_renewal = lambda d: None

    user = OracleMeshDispatch(
        dispatch_id="dsp_" + "8" * 32, nonce="n", node_ref=NODE, file_path="command",
        command_id="c", run_id="r", kind="command",
        command_text=json.dumps({"shell": "powershell", "command": "Start-Sleep 5",
                                 "cwd": None, "timeout_seconds": 0, "distro": None}),
        user_mode=True, device_id=DEVICE, background=True, owner_ref="u",
    )
    system = OracleMeshDispatch(
        dispatch_id="dsp_" + "9" * 32, nonce="n", node_ref=NODE, file_path="command",
        command_id="c", run_id="r", kind="command", command_text="hostname.exe",
        user_mode=False, device_id=DEVICE, background=True, owner_ref="u",
    )

    user_thread = threading.Thread(
        target=lambda: ex._run_background_dispatch(asdict(user), cancel_probe=lambda: False),
        daemon=True,
    )
    user_thread.start()
    time.sleep(0.2)
    assert user_thread.is_alive()
    assert "padiem-user-helper" in port.calls[0]["command"]

    result = {}
    system_thread = threading.Thread(
        target=lambda: result.setdefault(
            "value", ex._run_background_dispatch(asdict(system), cancel_probe=lambda: False)),
        daemon=True,
    )
    system_thread.start()
    system_thread.join(timeout=1.0)
    blocked = system_thread.is_alive()
    port.release.set()
    user_thread.join(5)
    system_thread.join(5)
    assert not blocked, "the SYSTEM dispatch waited on the user command"
    assert result["value"]["termination"] == "exited"


def test_after_a_failed_user_dispatch_the_next_system_dispatch_still_runs():
    # The client's bounded read is what ends the stuck user round; the executor
    # must be usable for the very next dispatch, including the SYSTEM lane.
    port = FakePort(output=b"user_session_unavailable: helper pipe is not available\n")
    ex = _executor(port)
    user = OracleMeshDispatch(
        dispatch_id="dsp_" + "6" * 32, nonce="n", node_ref=NODE, file_path="command",
        command_id="c", run_id="r", kind="command",
        command_text=json.dumps({"shell": "whoami", "command": "whoami", "cwd": None,
                                 "timeout_seconds": 30, "distro": None}),
        user_mode=True, device_id=DEVICE,
    )
    out = ex.execute(user)
    assert json.loads(out.body)["error_code"] == USER_SESSION_UNAVAILABLE

    system = OracleMeshDispatch(
        dispatch_id="dsp_" + "7" * 32, nonce="n", node_ref=NODE, file_path="command",
        command_id="c", run_id="r", kind="command",
        command_text="hostname.exe", user_mode=False, device_id=DEVICE,
    )
    ex.execute(system)
    assert port.calls[-1]["command"] == "hostname.exe"
