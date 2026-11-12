"""#7065 stage 3 — session operations on the helper's wire.

A session request is the stage-1 frame with ``shell=session`` and the operation
document in ``command``. This file proves three things about that wiring:

* the frame's authentication is the stage-1 one — a forged or repeated request
  never reaches the session manager;
* the answer is one final frame the SYSTEM client already relays unchanged
  (header line + output in ``stdout_b64``, 0/1 in ``exit_code``);
* the serve loop answers a session operation while a long command is still
  running, and commands themselves stay serial.

The last test is a real Windows round trip: the real named pipe, the real
PowerShell client the executor sends, the real serve loop and a real program.
"""
from __future__ import annotations

import base64
import json
import struct
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
KAGENT_SRC = ROOT / "apps" / "korean-ai-code-agent" / "src"
SHARED_PACKAGES = [ROOT / "packages" / "padiem-ai-core", ROOT / "packages" / "padiem-control-plane"]
for path in (str(ROOT / "apps" / "claw-connect"), str(KAGENT_SRC),
             *[str(item) for item in SHARED_PACKAGES]):
    if path not in sys.path:
        sys.path.insert(0, path)

from claw_connect import user_helper_service as service  # noqa: E402
from claw_connect import user_session_helper as helper  # noqa: E402
from claw_connect import user_session_manager as sessions  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_system_executables(monkeypatch):
    """Keep this file independent of the PC it runs on (#7564).

    The helper now names system executables by the path the OS reports and
    refuses when it cannot. These tests are about the wire and the serve loop,
    not about that lookup, so off Windows the lookup answers one fixed fake
    host; on Windows the real answer is used.
    """
    if sys.platform != "win32":
        import os

        monkeypatch.setattr(
            helper, "system_executable",
            lambda name: os.path.join("/fake-padiem-system32", name))
        monkeypatch.setattr(
            helper, "windows_powershell_executable",
            lambda: os.path.join("/fake-padiem-system32", "WindowsPowerShell", "v1.0", "powershell.exe"))
    yield

SECRET = b"deployment-secret-for-session-wire-tests"
DEVICE = "dev_" + "e" * 32

ECHO = r'''
import sys
print("ready", flush=True)
for line in sys.stdin:
    line = line.rstrip("\r\n")
    if line == "quit":
        break
    print("got:" + line, flush=True)
'''

REPLY_FRAME_KEYS = {"request_id", "status", "exit_code", "stdout_b64", "stderr_b64",
                    "truncated", "error_code", "duration_ms"}


def rid(number: int) -> str:
    return "req_%032x" % number


def sid(number: int) -> str:
    return "%032x" % number


def doc(op: str, **fields):
    return {"v": 1, "op": op, **fields}


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def op_command(document) -> str:
    return base64.b64encode(json.dumps(document).encode("utf-8")).decode("ascii")


def frame_for(number: int, *, shell: str = "session", command: str, cwd=None,
              secret: bytes = SECRET, timeout_seconds: int = 0) -> bytes:
    request = helper.parse_request({
        "request_id": rid(number), "nonce": "", "shell": shell, "command": command,
        "timeout_seconds": timeout_seconds, "cwd": cwd, "distro": None,
    })
    return service.encode_frame({
        "request_id": request.request_id, "nonce": helper.request_nonce(secret, request),
        "shell": request.shell, "cwd": request.cwd, "command": request.command,
        "timeout_seconds": request.timeout_seconds, "distro": request.distro,
    })


def session_frame(number: int, document, **options) -> bytes:
    return frame_for(number, command=op_command(document), **options)


class FakeConnection:
    def __init__(self, request_frame: bytes):
        self._incoming = request_frame
        self._offset = 0
        self.written = b""
        self.closed = False

    def read_exact(self, size: int) -> bytes:
        chunk = self._incoming[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def write_all(self, data: bytes) -> None:
        self.written += data

    def close(self) -> None:
        self.closed = True

    def frames(self) -> list[dict]:
        found, view = [], self.written
        while view:
            (length,) = struct.unpack(">I", view[:4])
            found.append(json.loads(view[4:4 + length].decode("utf-8")))
            view = view[4 + length:]
        return found

    def final(self) -> dict:
        return self.frames()[-1]


class FakeListener:
    def __init__(self, connections):
        self._connections = list(connections)

    def accept(self, timeout_seconds):
        if self._connections:
            return self._connections.pop(0)
        time.sleep(0.01)
        return None

    def close(self):
        pass


def body_of(reply: dict):
    body = base64.b64decode(reply["stdout_b64"])
    head, _, rest = body.partition(b"\n")
    return json.loads(head.decode("ascii")), rest.decode("utf-8").replace("\r\n", "\n")


class FakeBackend:
    name = "pipe"

    def __init__(self, argv, cwd, *, on_output, on_exit, **options):
        self.argv, self.cwd = list(argv), cwd
        self.on_exit = on_exit
        self.terminated = False

    def supports_key(self, key):
        return True

    def send_text(self, text, enter):
        pass

    def send_key(self, key):
        pass

    def poll(self):
        return -9 if self.terminated else None

    def terminate(self):
        self.terminated = True
        self.on_exit(-9)

    def close(self):
        pass


def fake_manager(created: list):
    def factory(argv, cwd, **options):
        backend = FakeBackend(argv, cwd, **options)
        created.append(backend)
        return backend

    return sessions.SessionManager(
        argv_builder=lambda shell, command, terminal: [shell, command],
        backends={"pipe": factory}, reaper_interval=None, settle_ms=20)


class SpyManager:
    """Counts what reaches the session manager, and can be told to raise."""

    def __init__(self, raises: bool = False):
        self.calls = []
        self.raises = raises

    def handle_command(self, command, *, request_id, cwd=None):
        self.calls.append((command, request_id, cwd))
        if self.raises:
            raise RuntimeError("boom")
        return sessions.SessionReply(header={"v": 1, "ok": True, "code": None, "op": "status"})


def handle(frame: bytes, **options):
    connection = FakeConnection(frame)
    options.setdefault("guard", helper.ReplayGuard())
    # This suite exercises the session wire after peer admission.
    options.setdefault("peer_verifier", lambda connection: None)
    outcome = service.handle_connection(connection, secret=SECRET, **options)
    return outcome, connection


# ---------------------------------------------------------------------------
# The shell value and the frame.
# ---------------------------------------------------------------------------
def test_session_is_one_shared_word_outside_the_command_vocabulary():
    from padiem_ai_core.pc_shell_selection import PC_SHELL_NAMES

    assert helper.SHELL_SESSION == sessions.SESSION_SHELL == "session"
    assert helper.SHELL_SESSION not in helper.SUPPORTED_SHELLS
    assert helper.SHELL_SESSION not in PC_SHELL_NAMES


def test_a_session_frame_parses_and_never_becomes_a_process():
    command = op_command(doc("status"))
    request = helper.parse_request({
        "request_id": rid(1), "nonce": "", "shell": "session", "command": command,
        "timeout_seconds": 0, "cwd": None, "distro": None,
    })
    assert request.shell == "session" and request.command == command
    with pytest.raises(helper.UserHelperError) as refused:
        helper.build_argv(request)
    assert refused.value.code == helper.USER_HELPER_REFUSED
    ran = []
    signed = helper.HelperRequest(
        request_id=request.request_id, nonce=helper.request_nonce(SECRET, request),
        shell=request.shell, command=request.command, timeout_seconds=0)
    reply = helper.serve_one(signed, secret=SECRET,
                             runner=lambda argv, cwd, timeout: ran.append(argv) or (0, b"", b""))
    assert reply.status == "error" and ran == []


@pytest.mark.parametrize("command", ["two words", "line\nbreak", "한글", "tab\there"])
def test_a_session_command_is_one_line_of_printable_ascii(command):
    with pytest.raises(helper.UserHelperError) as refused:
        helper.parse_request({
            "request_id": rid(1), "nonce": "", "shell": "session", "command": command,
            "timeout_seconds": 0, "cwd": None, "distro": None,
        })
    assert refused.value.code == helper.USER_HELPER_BAD_REQUEST


# ---------------------------------------------------------------------------
# One connection.
# ---------------------------------------------------------------------------
def test_a_session_operation_is_answered_in_one_stage_1_shaped_frame(tmp_path):
    created = []
    manager = fake_manager(created)
    try:
        outcome, connection = handle(
            session_frame(1, doc("start", shell="cmd", command="python -i", wait_ms=0),
                          cwd=str(tmp_path)),
            sessions=manager)
        assert outcome == "served" and connection.closed is True
        frames = connection.frames()
        assert len(frames) == 1  # no started/heartbeat frames: the answer is immediate
        reply = frames[0]
        assert set(reply) == REPLY_FRAME_KEYS
        assert reply["request_id"] == rid(1) and reply["status"] == "ok"
        assert reply["exit_code"] == 0 and reply["error_code"] is None
        assert reply["stderr_b64"] == "" and reply["truncated"] is False
        header, output = body_of(reply)
        assert header["ok"] is True and header["op"] == "start" and header["session"] == sid(1)
        assert output == ""
        assert created[0].argv == ["cmd", "python -i"] and created[0].cwd == str(tmp_path)
    finally:
        manager.shutdown()


def test_a_session_level_refusal_is_an_ok_frame_with_exit_code_1():
    manager = fake_manager([])
    try:
        outcome, connection = handle(session_frame(1, doc("read", session=sid(9))),
                                     sessions=manager)
        reply = connection.final()
        assert outcome == "served" and reply["status"] == "ok" and reply["exit_code"] == 1
        header, _ = body_of(reply)
        assert header["ok"] is False and header["code"] == "pc_session_not_found"
    finally:
        manager.shutdown()


def test_a_document_that_cannot_be_read_is_answered_in_the_header():
    manager = fake_manager([])
    try:
        outcome, connection = handle(frame_for(1, command=b64("not json")), sessions=manager)
        reply = connection.final()
        assert outcome == "served" and reply["status"] == "ok" and reply["exit_code"] == 1
        header, _ = body_of(reply)
        assert header == {"v": 1, "ok": False, "code": "pc_session_bad_request", "op": None,
                          "session": None, "detail": header["detail"]}
    finally:
        manager.shutdown()


def test_a_forged_session_frame_reaches_no_manager():
    spy = SpyManager()
    outcome, connection = handle(session_frame(1, doc("status"), secret=b"another-secret"),
                                 sessions=spy)
    reply = connection.final()
    assert outcome == "refused" and spy.calls == []
    assert reply["status"] == "error" and reply["error_code"] == helper.USER_HELPER_REFUSED


def test_a_repeated_session_request_is_refused_before_the_manager():
    spy = SpyManager()
    guard = helper.ReplayGuard()
    frame = session_frame(1, doc("status"))
    first, _ = handle(frame, sessions=spy, guard=guard)
    second, connection = handle(frame, sessions=spy, guard=guard)
    assert (first, second) == ("served", "refused") and len(spy.calls) == 1
    assert connection.final()["error_code"] == helper.USER_HELPER_REFUSED


def test_without_a_session_manager_the_frame_is_refused():
    outcome, connection = handle(session_frame(1, doc("status")))
    reply = connection.final()
    assert outcome == "refused" and reply["status"] == "error"
    assert reply["error_code"] == helper.USER_HELPER_REFUSED


def test_a_manager_that_raises_becomes_a_frame_refusal_and_the_helper_lives():
    spy = SpyManager(raises=True)
    outcome, connection = handle(session_frame(1, doc("status")), sessions=spy)
    reply = connection.final()
    assert outcome == "refused" and connection.closed is True
    assert reply["status"] == "error" and reply["error_code"] == helper.USER_HELPER_REFUSED
    assert "boom" not in json.dumps(reply)


def test_a_whole_session_runs_over_frames():
    manager = sessions.SessionManager(
        argv_builder=lambda shell, command, terminal: [sys.executable, "-X", "utf8", "-u",
                                                       "-c", ECHO],
        backends={"pipe": sessions.PipeBackend}, reaper_interval=None, settle_ms=60)
    guard = helper.ReplayGuard()
    try:
        _, started = handle(session_frame(1, doc("start", wait_ms=5000)),
                            sessions=manager, guard=guard)
        header, output = body_of(started.final())
        assert header["alive"] is True and output == "ready\n"

        _, typed = handle(session_frame(2, doc("input", session=sid(1),
                                               text_b64=b64("한글 y"), wait_ms=5000)),
                          sessions=manager, guard=guard)
        header, output = body_of(typed.final())
        assert header["ok"] is True and output == "got:한글 y\n"

        _, read = handle(session_frame(3, doc("read", session=sid(1), offset=0)),
                         sessions=manager, guard=guard)
        assert body_of(read.final())[1] == "ready\ngot:한글 y\n"

        _, stopped = handle(session_frame(4, doc("stop", session=sid(1))),
                            sessions=manager, guard=guard)
        header, _ = body_of(stopped.final())
        assert header["alive"] is False and header["ended"] == "stopped"
    finally:
        manager.shutdown()


# ---------------------------------------------------------------------------
# The serve loop.
# ---------------------------------------------------------------------------
class BlockingRunner:
    """A command that runs until released, and records how many ran at once."""

    def __init__(self, hold: float | None = None):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.hold = hold
        self.active = 0
        self.most = 0
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, argv, cwd, timeout_seconds):
        with self._lock:
            self.active += 1
            self.calls += 1
            self.most = max(self.most, self.active)
        self.entered.set()
        if self.hold is None:
            self.release.wait(20)
        else:
            time.sleep(self.hold)
        with self._lock:
            self.active -= 1
        return 0, b"done\n", b""


def command_frame(number: int) -> bytes:
    return frame_for(number, shell="powershell", command="Start-Sleep 600", timeout_seconds=0)


def serve_in_thread(**options):
    options.setdefault("peer_verifier", lambda connection: None)
    box = {}

    def run():
        box["stats"] = service.serve_pipe(device_id=DEVICE, secret=SECRET, **options)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def wait_until(predicate, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_a_session_operation_is_answered_while_a_long_command_runs():
    runner = BlockingRunner()
    long_command = FakeConnection(command_frame(1))
    status = FakeConnection(session_frame(2, doc("status")))
    thread, box = serve_in_thread(listener=FakeListener([long_command, status]),
                                  runner=runner, max_requests=2, sessions=fake_manager([]))
    try:
        wait_until(runner.entered.is_set)
        wait_until(lambda: status.closed)
        # The command is still running and the session question is already answered.
        assert runner.active == 1 and thread.is_alive()
        header, _ = body_of(status.final())
        assert header["ok"] is True and header["op"] == "status"
    finally:
        runner.release.set()
        thread.join(20)
    assert box["stats"].served == 2 and box["stats"].refused == 0
    assert long_command.final()["status"] == "ok"


def test_commands_stay_serial_across_connections():
    runner = BlockingRunner(hold=0.15)
    connections = [FakeConnection(command_frame(number)) for number in (1, 2, 3)]
    stats = service.serve_pipe(device_id=DEVICE, secret=SECRET,
                               listener=FakeListener(connections), runner=runner,
                               max_requests=3, sessions=fake_manager([]),
                               peer_verifier=lambda connection: None)
    assert stats.served == 3 and runner.calls == 3
    assert runner.most == 1  # never two commands at once


def test_a_command_whose_client_left_while_it_waited_is_never_started():
    class Abandoned(FakeConnection):
        def peer_closed(self):
            return True

    runner = BlockingRunner()
    long_command = FakeConnection(command_frame(1))
    abandoned = Abandoned(command_frame(2))
    thread, box = serve_in_thread(listener=FakeListener([long_command, abandoned]),
                                  runner=runner, max_requests=2, sessions=fake_manager([]))
    try:
        wait_until(runner.entered.is_set)
    finally:
        runner.release.set()
        thread.join(20)
    assert runner.calls == 1 and abandoned.written == b"" and abandoned.closed is True
    assert box["stats"].served == 1 and box["stats"].refused == 1


def test_past_the_thread_cap_the_loop_serves_the_connection_itself(monkeypatch):
    monkeypatch.setattr(service, "MAX_CONNECTION_THREADS", 1)
    runner = BlockingRunner()
    long_command = FakeConnection(command_frame(1))
    first, second = (FakeConnection(session_frame(n, doc("status"))) for n in (2, 3))
    thread, box = serve_in_thread(listener=FakeListener([long_command, first, second]),
                                  runner=runner, max_requests=3, sessions=fake_manager([]))
    try:
        wait_until(runner.entered.is_set)
        wait_until(lambda: first.closed and second.closed)
        assert runner.active == 1
    finally:
        runner.release.set()
        thread.join(20)
    assert box["stats"].served == 3


def test_the_loop_ends_the_sessions_it_kept_when_it_ends(monkeypatch):
    created = []
    monkeypatch.setattr(service, "SessionManager", lambda: fake_manager(created))
    stats = service.serve_pipe(
        device_id=DEVICE, secret=SECRET, max_requests=1,
        peer_verifier=lambda connection: None,
        listener=FakeListener([FakeConnection(session_frame(1, doc("start", wait_ms=0)))]))
    assert stats.served == 1
    assert len(created) == 1 and created[0].terminated is True


def test_a_manager_handed_to_the_loop_is_left_running():
    created = []
    manager = fake_manager(created)
    try:
        service.serve_pipe(
            device_id=DEVICE, secret=SECRET, max_requests=1, sessions=manager,
            peer_verifier=lambda connection: None,
            listener=FakeListener([FakeConnection(session_frame(1, doc("start", wait_ms=0)))]))
        assert created[0].terminated is False
    finally:
        manager.shutdown()
    assert created[0].terminated is True


def test_the_replay_guard_accepts_a_request_once_under_threads():
    guard = helper.ReplayGuard()
    accepted = []
    barrier = threading.Barrier(8)

    def race():
        barrier.wait()
        for number in range(200):
            if guard.accept(rid(number)):
                accepted.append(number)

    threads = [threading.Thread(target=race) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(accepted) == list(range(200))


# ---------------------------------------------------------------------------
# What the server sees after the SYSTEM client's relay.
# ---------------------------------------------------------------------------
def _executor():
    module = pytest.importorskip("kagent.local_agent_oracle_mesh_executor")
    return module.OracleMeshExecutor


def test_the_relay_hands_the_server_the_body_and_the_frame_exit_code():
    manager = fake_manager([])
    try:
        _, connection = handle(session_frame(1, doc("read", session=sid(9))), sessions=manager)
    finally:
        manager.shutdown()
    reply = connection.final()
    # The PowerShell client re-emits the final frame's fields as one JSON object.
    outcome = _executor()._parse_user_helper_outcome(json.dumps(reply).encode("utf-8"))
    assert outcome.termination == "exited" and outcome.exit_code == 1
    assert outcome.body == base64.b64decode(reply["stdout_b64"])
    assert json.loads(outcome.body.split(b"\n", 1)[0])["code"] == "pc_session_not_found"


def test_an_older_helper_reaches_the_server_as_user_helper_refused(monkeypatch):
    # An older helper is this one without the session value.
    monkeypatch.setattr(helper, "SHELL_SESSION", "not-known-to-this-helper")
    frame = service.encode_frame({
        "request_id": rid(1), "nonce": "0" * 64, "shell": "session",
        "command": op_command(doc("status")), "timeout_seconds": 0, "cwd": None,
        "distro": None,
    })
    outcome, connection = handle(frame, sessions=SpyManager())
    reply = connection.final()
    assert outcome == "refused" and reply["status"] == "error"
    assert reply["error_code"] == helper.USER_HELPER_REFUSED
    assert base64.b64decode(reply["stderr_b64"]) == b"shell is not one this helper runs"
    relayed = _executor()._parse_user_helper_outcome(json.dumps(reply).encode("utf-8"))
    assert relayed.exit_code == 1
    body = json.loads(relayed.body)
    assert body == {"ok": False, "error_code": "user_helper_refused", "detail": ""}
    assert "v" not in body


# ---------------------------------------------------------------------------
# One real Windows round trip.
# ---------------------------------------------------------------------------
WINDOWS_DEVICE = "session7065_" + uuid.uuid4().hex
WINDOWS_SECRET = b"deployment-secret-for-the-7065-session-round-trip"


def _client(number: int, document, secret_file: Path):
    """One session operation through the shipped PowerShell client."""
    import subprocess
    import tempfile

    executor = _executor()
    script = executor.build_user_helper_pipe_client_ps(
        request_id=rid(number), shell="session", command=op_command(document),
        cwd=None, timeout_seconds=0, distro=None,
        task_arguments=f'--device-id "{WINDOWS_DEVICE}" --secret-file "{secret_file}"',
    )
    # The production executor also delivers this client as a file. Long test
    # paths must not inflate an encoded command beyond CreateProcess's limit.
    with tempfile.TemporaryDirectory(prefix="claw-session7065-") as directory:
        client_file = Path(directory) / "client.ps1"
        client_file.write_text(script, encoding="utf-8-sig")
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(client_file)],
            capture_output=True, timeout=90, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    raw = completed.stdout.strip()
    assert raw, completed.stderr.decode("utf-8", "replace")
    outcome = executor._parse_user_helper_outcome(raw)
    head, _, rest = outcome.body.partition(b"\n")
    return outcome.exit_code, json.loads(head), rest.decode("utf-8").replace("\r\n", "\n")


@pytest.mark.skipif(sys.platform != "win32",
                    reason="the helper pipe and its PowerShell client exist on Windows only")
def test_real_pipe_round_trip_keeps_a_program_between_requests(tmp_path):
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(WINDOWS_SECRET + b"\n")
    # No quoting inside the command: the program is a file, run unbuffered so
    # its prompt reaches the pipe before it waits.
    asker_script = tmp_path / "asker.py"
    asker_script.write_text("print('got-' + input('name? '))\n", encoding="utf-8")
    listener = service.WindowsPipeListener(WINDOWS_DEVICE)
    failures: list[BaseException] = []
    stop = threading.Event()

    def serve() -> None:
        try:
            service.serve_pipe(device_id=WINDOWS_DEVICE, secret=WINDOWS_SECRET,
                               listener=listener, max_requests=7, should_stop=stop.is_set,
                               peer_verifier=lambda connection: None)
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    try:
        # 1. A program that asks a question: the prompt is visible, the answer
        #    is taken, and the session ends with the program's own exit code.
        asker = f"{sys.executable} -u {asker_script}"
        code, header, output = _client(1, doc("start", shell="cmd", command=asker,
                                              terminal=False, wait_ms=8000), secret_file)
        assert code == 0 and header["ok"] is True and header["backend"] == "pipe", header
        assert header["alive"] is True and output.endswith("name? "), (header, output)
        assert header["ends_with_newline"] is False

        code, header, output = _client(2, doc("input", session=sid(1), text_b64=b64("padiem"),
                                              wait_ms=8000), secret_file)
        assert code == 0 and "got-padiem" in output, (header, output)

        deadline = time.monotonic() + 30
        while True:
            code, header, _ = _client(3, doc("read", session=sid(1), offset=0), secret_file)
            if header["alive"] is False or time.monotonic() > deadline:
                break
            time.sleep(0.5)
        assert header["ended"] == "exited" and header["exit_code"] == 0, header

        # 2. The shell itself, kept open: a command typed into it is answered,
        #    and a stop ends it.
        code, header, _ = _client(4, doc("start", shell="cmd", terminal=False, wait_ms=3000),
                                  secret_file)
        assert code == 0 and header["alive"] is True, header
        code, header, output = _client(5, doc("input", session=sid(4),
                                              text_b64=b64("echo session-7065-ok"),
                                              wait_ms=8000), secret_file)
        assert code == 0 and "session-7065-ok" in output, (header, output)
        code, header, _ = _client(6, doc("stop", session=sid(4)), secret_file)
        assert code == 0 and header["alive"] is False and header["ended"] == "stopped", header

        # 3. A session nobody started is a refusal the relay carries as exit 1.
        code, header, _ = _client(7, doc("read", session=sid(99)), secret_file)
        assert code == 1 and header["code"] == "pc_session_not_found", header
    finally:
        # The loop may be waiting in a blocking accept (a failed assertion
        # above leaves requests unsent). One empty connection wakes it so it
        # sees the stop; closing the pipe under a pending accept would hang.
        stop.set()
        if server.is_alive():
            from claw_connect import user_session_delegation as delegation

            try:
                delegation.open_pipe_connection(helper.pipe_path(WINDOWS_DEVICE)).close()
            except OSError:
                pass
        server.join(timeout=30)
        listener.close()
    assert not failures, failures
