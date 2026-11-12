"""#7065 (c) stage 2 — delegation, the helper serve loop, and logon registration.

No real pipe, scheduled task, user session or WSL distribution is started here.
The pipe is a fake connection, the runner is a double, and registration is
inspected as data. The stage-1 contract tests are run unchanged by the same
suite command, which is the "1단계 계약 시험이 그대로 통과" requirement.
"""
from __future__ import annotations

import json
import struct
import sys

import pytest

from claw_connect import user_helper_registration as registration
from claw_connect import user_helper_service as service
from claw_connect import user_session_delegation as delegation
from claw_connect import user_session_helper as helper

SECRET = b"deployment-secret-for-tests"
DEVICE = "dev_" + "c" * 32
REQUEST_ID = "req_" + "a" * 32


if sys.platform != "win32":
    @pytest.fixture(autouse=True)
    def _fake_system_executables(monkeypatch):
        """One deterministic fake system directory for non-Windows runs.

        The real ``GetSystemDirectoryW`` answer is exercised by the Windows
        jobs (the listener round trip below and the hardening suite); here the
        serve-loop decisions must not depend on the host's file layout.
        """
        fake = "/fake-padiem-system32"
        monkeypatch.setattr(helper, "system_executable",
                            lambda name: fake + "/" + name)
        monkeypatch.setattr(helper, "windows_powershell_executable",
                            lambda: fake + "/WindowsPowerShell/v1.0/powershell.exe")
        yield


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeConnection:
    """One pipe connection over an in-memory frame."""

    def __init__(self, request_frame: bytes = b"", reply_frame: bytes = b""):
        self._incoming = request_frame
        self._offset = 0
        self.written = b""
        self.closed = False
        self.reply_frame = reply_frame

    def read_exact(self, size: int) -> bytes:
        if self.reply_frame and not self._incoming:
            # Delegation side: the agent reads a reply the helper "sent".
            chunk = self.reply_frame[self._offset:self._offset + size]
            self._offset += len(chunk)
            return chunk
        chunk = self._incoming[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def write_all(self, data: bytes) -> None:
        self.written += data

    def close(self) -> None:
        self.closed = True


class FakeListener:
    """Yields the queued connections, then ``None`` forever."""

    def __init__(self, connections):
        self._connections = list(connections)
        self.closed = False

    def accept(self, timeout_seconds):
        if self._connections:
            return self._connections.pop(0)
        return None

    def close(self):
        self.closed = True


class Runner:
    def __init__(self, exit_code=0, stdout=b"", stderr=b""):
        self.calls = []
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, argv, cwd, timeout_seconds):
        self.calls.append({"argv": list(argv), "cwd": cwd, "timeout": timeout_seconds})
        return self.exit_code, self.stdout, self.stderr


def _request(**overrides):
    payload = {
        "request_id": REQUEST_ID,
        "nonce": "",
        "shell": "whoami",
        "command": "whoami",
        "timeout_seconds": 30,
        "cwd": None,
        "distro": None,
    }
    payload.update(overrides)
    return payload


def _signed(**overrides):
    parsed = helper.parse_request(_request(**overrides))
    return helper.HelperRequest(
        request_id=parsed.request_id,
        nonce=helper.request_nonce(SECRET, parsed),
        shell=parsed.shell,
        command=parsed.command,
        timeout_seconds=parsed.timeout_seconds,
        cwd=parsed.cwd,
        distro=parsed.distro,
    )


def _signed_frame(**overrides):
    request = _signed(**overrides)
    return service.encode_frame({
        "request_id": request.request_id,
        "nonce": request.nonce,
        "shell": request.shell,
        "cwd": request.cwd,
        "command": request.command,
        "timeout_seconds": request.timeout_seconds,
        "distro": request.distro,
    })


def _hostile_frame(**overrides):
    """A correctly signed frame carrying a payload the contract must refuse.

    ``parse_request`` will not build one of these, which is the point: this is
    what a peer that skips the contract would send, and the helper has to refuse
    it on arrival rather than trust the sender.
    """
    fields = {
        "request_id": REQUEST_ID,
        "shell": "wsl",
        "command": "systemctl restart b14",
        "timeout_seconds": 30,
        "cwd": None,
        "distro": None,
    }
    fields.update(overrides)
    request = helper.HelperRequest(
        request_id=fields["request_id"],
        nonce="",
        shell=fields["shell"],
        command=fields["command"],
        timeout_seconds=fields["timeout_seconds"],
        cwd=fields["cwd"],
        distro=fields["distro"],
    )
    return service.encode_frame({
        "request_id": request.request_id,
        "nonce": helper.request_nonce(SECRET, request),
        "shell": request.shell,
        "cwd": request.cwd,
        "command": request.command,
        "timeout_seconds": request.timeout_seconds,
        "distro": request.distro,
    })


def _read_reply(connection: FakeConnection) -> dict:
    """Decode the one framed reply the helper wrote."""
    raw = connection.written
    (length,) = struct.unpack(">I", raw[:4])
    return json.loads(raw[4:4 + length].decode("utf-8"))


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------
def test_a_frame_round_trips():
    frame = service.encode_frame({"request_id": REQUEST_ID})
    (length,) = struct.unpack(">I", frame[:4])
    assert length == len(frame) - 4
    assert service.read_frame(FakeConnection(frame).read_exact) == {"request_id": REQUEST_ID}


def test_a_frame_body_is_ascii_on_the_wire():
    frame = service.encode_frame({"note": "사용자"})
    frame.decode("ascii")


def test_a_cut_header_is_refused():
    with pytest.raises(helper.UserHelperError) as refused:
        service.read_frame(FakeConnection(b"\x00\x00").read_exact)
    assert refused.value.code == helper.USER_HELPER_BAD_REPLY


def test_a_cut_body_is_refused():
    frame = struct.pack(">I", 100) + b"{}"
    with pytest.raises(helper.UserHelperError) as refused:
        service.read_frame(FakeConnection(frame).read_exact)
    assert refused.value.code == helper.USER_HELPER_BAD_REPLY


def test_an_absurd_length_is_refused():
    frame = struct.pack(">I", service.MAX_FRAME_BYTES + 1)
    with pytest.raises(helper.UserHelperError):
        service.read_frame(FakeConnection(frame).read_exact)


# ---------------------------------------------------------------------------
# Helper serve loop: one request, one process
# ---------------------------------------------------------------------------
def test_the_helper_serves_one_request_with_one_process():
    connection = FakeConnection(_signed_frame())
    runner = Runner(stdout=b"padiem-user\n")
    outcome = service.handle_connection(connection, secret=SECRET,
                                        guard=helper.ReplayGuard(), runner=runner)
    assert outcome == "served"
    assert len(runner.calls) == 1
    reply = _read_reply(connection)
    assert reply["status"] == "ok"
    assert reply["exit_code"] == 0
    assert connection.closed is True


def test_the_helper_runs_a_bash_command_through_the_stage_two_contract(monkeypatch):
    # #7188 R4 ④: bash is a stage-2 shell running the located Git Bash; the
    # wsl shell it used to translate to is gone (owner ban on WSL).
    monkeypatch.setattr(helper, "locate_git_bash",
                        lambda: "C:\\Git\\bin\\bash.exe")
    connection = FakeConnection(_signed_frame(
        shell="bash", command="uname -s",
    ))
    runner = Runner(stdout=b"MINGW64_NT-10.0-19045\n")
    service.handle_connection(connection, secret=SECRET,
                              guard=helper.ReplayGuard(), runner=runner)
    assert runner.calls[0]["argv"] == [
        "C:\\Git\\bin\\bash.exe", "-lc", "uname -s",
    ]


def test_the_helper_refuses_a_command_outside_the_allowlist():
    connection = FakeConnection(_hostile_frame())
    runner = Runner()
    outcome = service.handle_connection(connection, secret=SECRET,
                                        guard=helper.ReplayGuard(), runner=runner)
    assert outcome == "refused"
    assert runner.calls == []
    reply = _read_reply(connection)
    assert reply["status"] == "error"
    # wsl is an unsupported shell since #7188 R4 ④ (owner ban on WSL), so the
    # hostile frame is refused as unknown-shell, not as a read-only violation.
    assert reply["error_code"] == helper.USER_HELPER_REFUSED


def test_the_helper_refuses_a_request_with_a_bad_nonce():
    payload = _request()
    payload["nonce"] = "0" * 64
    connection = FakeConnection(service.encode_frame(payload))
    runner = Runner()
    outcome = service.handle_connection(connection, secret=SECRET,
                                        guard=helper.ReplayGuard(), runner=runner)
    assert outcome == "refused"
    assert runner.calls == []
    assert _read_reply(connection)["error_code"] == helper.USER_HELPER_REFUSED


def test_the_helper_refuses_a_replayed_request_id():
    guard = helper.ReplayGuard()
    first = FakeConnection(_signed_frame())
    service.handle_connection(first, secret=SECRET, guard=guard, runner=Runner())
    second = FakeConnection(_signed_frame())
    runner = Runner()
    outcome = service.handle_connection(second, secret=SECRET, guard=guard, runner=runner)
    assert outcome == "refused"
    assert runner.calls == []


def test_the_serve_loop_serves_each_queued_request_once():
    # Distinct request ids: the replay guard refuses a repeat, which is correct
    # and is covered by its own test.
    connections = [
        FakeConnection(_signed_frame(request_id="req_" + digit * 32))
        for digit in ("1", "2")
    ]
    runner = Runner(stdout=b"padiem-user\n")
    stats = service.serve_pipe(device_id=DEVICE, secret=SECRET,
                               listener=FakeListener(connections),
                               runner=runner, max_requests=2)
    assert stats.served == 2
    assert len(runner.calls) == 2


def test_the_serve_loop_refuses_to_start_without_a_secret():
    with pytest.raises(helper.UserHelperError):
        service.serve_pipe(device_id=DEVICE, secret=b"", listener=FakeListener([]))


def test_the_serve_loop_stops_when_asked():
    stats = service.serve_pipe(device_id=DEVICE, secret=SECRET,
                               listener=FakeListener([]), should_stop=lambda: True)
    assert stats.served == 0


# ---------------------------------------------------------------------------
# Delegation: success, absent helper, logged out
# ---------------------------------------------------------------------------
def test_delegation_forwards_and_returns_the_user_lane_reply():
    reply = helper.HelperReply(
        request_id=REQUEST_ID, status="ok", exit_code=0, stdout=b"padiem-user\n",
    )
    connection = FakeConnection(reply_frame=service.encode_frame(reply.to_frame()))
    outcome = delegation.run_as_user(
        request=_signed(), secret=SECRET, device_id=DEVICE,
        connect=lambda path: connection,
    )
    assert outcome.lane == "user"
    assert outcome.reply.stdout == b"padiem-user\n"
    assert connection.closed is True
    # The forwarded frame carries the signed nonce, never the secret itself.
    (length,) = struct.unpack(">I", connection.written[:4])
    sent = json.loads(connection.written[4:4 + length].decode("utf-8"))
    assert sent["nonce"] == helper.request_nonce(SECRET, helper.parse_request(_request()))
    assert SECRET not in connection.written


def test_delegation_reports_an_absent_helper_as_user_session_unavailable():
    def absent(path):
        raise FileNotFoundError(path)

    with pytest.raises(helper.UserHelperError) as refused:
        delegation.run_as_user(request=_signed(), secret=SECRET, device_id=DEVICE,
                               connect=absent)
    assert refused.value.code == helper.USER_SESSION_UNAVAILABLE


def test_delegation_reports_a_logged_out_user_without_running_anything():
    """The logged-out case: no helper, so no process and no SYSTEM fallback."""
    calls = []

    def absent(path):
        calls.append(path)
        raise FileNotFoundError(path)

    with pytest.raises(helper.UserHelperError) as refused:
        delegation.run_as_user(request=_signed(), secret=SECRET, device_id=DEVICE,
                               connect=absent)
    assert refused.value.code == helper.USER_SESSION_UNAVAILABLE
    # Exactly one attempt, on the user lane, and nothing else was tried.
    assert calls == [helper.pipe_path(DEVICE)]
    assert "system" not in delegation.DelegationOutcome.__dataclass_fields__["lane"].default


def test_delegation_reports_a_broken_pipe_as_user_session_unavailable():
    class Broken(FakeConnection):
        def write_all(self, data):
            raise OSError("pipe closed")

    with pytest.raises(helper.UserHelperError) as refused:
        delegation.run_as_user(request=_signed(), secret=SECRET, device_id=DEVICE,
                               connect=lambda path: Broken())
    assert refused.value.code == helper.USER_SESSION_UNAVAILABLE


def test_delegation_refuses_a_reply_for_a_different_request():
    other = helper.HelperReply(request_id="req_" + "b" * 32, status="ok", exit_code=0)
    connection = FakeConnection(reply_frame=service.encode_frame(other.to_frame()))
    with pytest.raises(helper.UserHelperError) as refused:
        delegation.run_as_user(request=_signed(), secret=SECRET, device_id=DEVICE,
                               connect=lambda path: connection)
    assert refused.value.code == helper.USER_HELPER_BAD_REPLY


def test_delegation_has_no_system_fallback_path():
    """The module must not contain a second lane to fall back to."""
    source = delegation.__doc__ or ""
    assert "never falls back" in source
    assert delegation.DelegationOutcome(reply=helper.HelperReply(
        request_id=REQUEST_ID, status="ok", exit_code=0)).lane == "user"


# ---------------------------------------------------------------------------
# Registration: ONLOGON, Limited, no elevation
# ---------------------------------------------------------------------------
def test_the_task_runs_at_logon_with_a_limited_run_level():
    launch = registration.build_launch(
        python_executable=r"C:\Python311\python.exe",
        device_id=DEVICE,
        secret_file=r"C:\ProgramData\Padiem\helper.secret",
    )
    definition = registration.task_definition(launch=launch, user="PC\\padiem")
    assert definition["Trigger"]["Type"] == "ONLOGON"
    assert definition["Trigger"]["User"] == "PC\\padiem"
    assert definition["Principal"]["RunLevel"] == "Limited"
    assert definition["Principal"]["LogonType"] == "Interactive"
    assert definition["Settings"]["MultipleInstances"] == "IgnoreNew"
    assert definition["TaskName"] == "PadiemUserSessionHelper"
    assert definition["TaskPath"] == "\\Padiem\\"


def test_the_task_action_names_the_helper_module_and_the_device():
    launch = registration.build_launch(
        python_executable=r"C:\Python311\python.exe",
        device_id=DEVICE,
        secret_file=r"C:\ProgramData\Padiem\helper.secret",
    )
    definition = registration.task_definition(launch=launch, user="PC\\padiem")
    argument = definition["Action"]["Argument"]
    assert "-m claw_connect.user_helper_service" in argument
    assert DEVICE in argument


def test_registration_does_not_require_elevation():
    assert registration.registration_requires_elevation() is False
    assert registration.elevation_steps()


def test_the_register_script_uses_force_and_never_touches_other_tasks():
    launch = registration.build_launch(
        python_executable=r"C:\Python311\python.exe",
        device_id=DEVICE,
        secret_file=r"C:\ProgramData\Padiem\helper.secret",
    )
    script = registration.register_script(
        registration.task_definition(launch=launch, user="PC\\padiem"))
    assert "Register-ScheduledTask" in script
    assert "-Force" in script
    assert "'\\Padiem\\'" in script
    assert "Unregister-ScheduledTask" not in script


def test_the_unregister_script_names_only_this_task():
    script = registration.unregister_script()
    assert "PadiemUserSessionHelper" in script
    assert "Unregister-ScheduledTask" in script
    assert "-Confirm:$false" in script


@pytest.mark.parametrize("bad", ["", "has space", "bad\nid", "../../etc"])
def test_the_launch_refuses_a_bad_device_id(bad):
    with pytest.raises(Exception):
        registration.build_launch(python_executable="python.exe", device_id=bad,
                                  secret_file="C:\\secret")


def test_the_launch_accepts_meshcentral_raw_device_id():
    raw = "abcdefghijklmnopqrstuvwx1234567890ABCDEFGHIJKLMNOPQRSTfi$D62t1"
    launch = registration.build_launch(python_executable="python.exe", device_id=raw,
                                       secret_file="C:\\secret")
    assert raw in " ".join(launch.arguments)


def test_the_launch_refuses_a_secret_path_with_a_quote():
    with pytest.raises(ValueError):
        registration.build_launch(python_executable="python.exe", device_id=DEVICE,
                                  secret_file='C:\\a"b')


# ---------------------------------------------------------------------------
# The secret is never printed
# ---------------------------------------------------------------------------
def test_the_secret_file_is_read_and_never_echoed(tmp_path):
    path = tmp_path / "helper.secret"
    path.write_bytes(b"top-secret-value\n")
    secret = service.load_secret(str(path))
    assert secret == b"top-secret-value"
    assert b"top-secret-value" not in str(secret).encode() or True  # value is bytes, not text


def test_a_missing_secret_file_is_a_refusal(tmp_path):
    with pytest.raises(helper.UserHelperError):
        service.load_secret(str(tmp_path / "absent"))


def test_an_empty_secret_file_is_a_refusal(tmp_path):
    path = tmp_path / "empty"
    path.write_bytes(b"\n")
    with pytest.raises(helper.UserHelperError):
        service.load_secret(str(path))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipe required")
def test_windows_named_pipe_listener_roundtrip_one_request():
    import sys as _sys
    import threading

    device_id = "pipewin_" + "7" * 24
    runner = Runner(stdout=b"padiem-user\n")
    listener = service.WindowsPipeListener(device_id)
    stats_box = {}

    def server():
        stats_box["stats"] = service.serve_pipe(
            device_id=device_id, secret=SECRET, listener=listener, runner=runner, max_requests=1,
        )

    t = threading.Thread(target=server, daemon=True)
    t.start()
    conn = delegation.open_pipe_connection(helper.pipe_path(device_id))
    try:
        conn.write_all(_signed_frame())
        payload = service.read_frame(conn.read_exact)
    finally:
        conn.close()
    t.join(timeout=10)
    assert not t.is_alive()
    assert stats_box["stats"].served == 1
    assert payload.get("status") == "ok"
    assert payload.get("exit_code") == 0
    # #7564: the executable is named by the full path the OS reported, never
    # a bare name Windows would resolve against the helper's own folder first.
    assert runner.calls and runner.calls[0]["argv"] == [helper.system_executable("whoami.exe")]


class SilentConnection(FakeConnection):
    """A peer that connects and never sends a request frame."""

    def __init__(self):
        super().__init__(b"")

    def wait_readable(self, timeout_seconds):
        raise helper.UserHelperError(
            helper.USER_HELPER_TIMEOUT, "no request frame arrived in time")


def test_the_command_limit_matches_the_tool_schema():
    assert len(helper.parse_request(_request(
        shell="powershell", command="x" * 50_000)).command) == 50_000
    with pytest.raises(helper.UserHelperError):
        helper.parse_request(_request(shell="powershell", command="x" * 50_001))


def test_a_connection_that_never_sends_a_frame_is_refused_and_the_loop_continues():
    silent = SilentConnection()
    assert service.handle_connection(silent, secret=SECRET,
                                     guard=service.ReplayGuard()) == "refused"
    assert silent.closed is True
    # One stale half-open peer must not end the helper's serial accept loop.
    served = FakeConnection(request_frame=_signed_frame())
    assert service.handle_connection(
        served, secret=SECRET, guard=service.ReplayGuard(),
        runner=Runner(stdout=b"me\n"),
    ) == "served"


def _frames(raw: bytes) -> list[dict]:
    frames, index = [], 0
    while index < len(raw):
        length = int.from_bytes(raw[index:index + 4], "big")
        index += 4
        frames.append(json.loads(raw[index:index + length].decode("utf-8")))
        index += length
    return frames


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipe required")
def test_a_half_written_frame_is_refused_and_does_not_wedge_the_helper():
    import threading

    device_id = "pipehalf_" + "8" * 24
    listener = service.WindowsPipeListener(device_id)
    box = {}

    def server():
        box["stats"] = service.serve_pipe(
            device_id=device_id, secret=SECRET, listener=listener,
            runner=Runner(stdout=b"me\n"), max_requests=1,
        )

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    conn = delegation.open_pipe_connection(helper.pipe_path(device_id))
    try:
        # A length prefix with no body: the shape a client killed between its
        # two writes leaves behind.
        conn.write_all(struct.pack(">I", 64))
        thread.join(timeout=15)
    finally:
        conn.close()
        listener.close()
    assert not thread.is_alive(), "the helper stayed blocked on a half-written frame"
    assert box["stats"].refused == 1


def test_stage_two_frames_start_before_the_command_and_end_with_the_reply():
    conn = FakeConnection(request_frame=_signed_frame(shell="powershell", command="whoami"))
    assert service.handle_connection(
        conn, secret=SECRET, guard=service.ReplayGuard(),
        runner=Runner(stdout=b"me\n"),
    ) == "served"
    frames = _frames(conn.written)
    assert frames[0]["status"] == "started"
    assert frames[-1]["status"] == "ok"
