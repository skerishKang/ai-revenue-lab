"""#7065 stage 3 — the helper's interactive session manager (pipe backend).

The real manager runs over a small echo program started with this interpreter,
so the same file proves the behaviour on the Windows gate and on a POSIX
developer machine. No named pipe, no shell and no PC-specific program is
involved: the wire side has its own test file.

The header and the codes asserted here are the ones recorded on #7065 as
"대화형 세션 연결 규약 v1".
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import time

import pytest

from claw_connect import user_session_helper as helper
from claw_connect import user_session_manager as sessions


if sys.platform != "win32":
    @pytest.fixture(autouse=True)
    def _fake_system_executables(monkeypatch):
        """One deterministic fake system directory for non-Windows runs.

        The real ``GetSystemDirectoryW`` answer is exercised by the Windows
        jobs; the session argv decisions here must not depend on the host.
        """
        fake = "/fake-padiem-system32"
        monkeypatch.setattr(sessions, "system_executable",
                            lambda name: fake + "/" + name)
        monkeypatch.setattr(sessions, "windows_powershell_executable",
                            lambda: fake + "/WindowsPowerShell/v1.0/powershell.exe")
        yield

ECHO = r'''
import sys
print("ready", flush=True)
for line in sys.stdin:
    line = line.rstrip("\r\n")
    if line == "quit":
        break
    print("got:" + line, flush=True)
print("bye", flush=True)
sys.exit(3)
'''
SLEEPER = 'import time\nprint("up", flush=True)\ntime.sleep(600)\n'
NOISY = (
    'import sys\n'
    'for i in range(400):\n'
    '    print("line%04d" % i)\n'
    'sys.stdout.flush()\n'
    'sys.stdin.readline()\n'
)
CP949 = (
    'import sys\n'
    'sys.stdout.buffer.write("한글 출력\\n".encode("cp949"))\n'
    'sys.stdout.buffer.flush()\n'
    'sys.stdin.readline()\n'
)

CONTRACT_HEADER_KEYS = {
    "v", "ok", "code", "op", "session", "alive", "ended", "exit_code", "offset",
    "next_offset", "end_offset", "dropped_bytes", "idle_ms", "ends_with_newline", "backend",
}


def rid(number: int) -> str:
    return "req_%032x" % number


def sid(number: int) -> str:
    return "%032x" % number


def doc(op: str, **fields):
    return {"v": 1, "op": op, **fields}


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def text_of(reply) -> str:
    return reply.output.decode("utf-8").replace("\r\n", "\n")


def python_argv(script: str):
    return lambda shell, command, terminal: [sys.executable, "-X", "utf8", "-u", "-c", script]


@pytest.fixture
def manager():
    made = []

    def make(script: str = ECHO, **options):
        options.setdefault("settle_ms", 60)
        options.setdefault("reaper_interval", None)
        options.setdefault("argv_builder", python_argv(script))
        # The pipe backend's own behaviour: on Windows the default would open a
        # pseudo console, whose rules have their own test file.
        options.setdefault("backends", {"pipe": sessions.PipeBackend})
        built = sessions.SessionManager(**options)
        made.append(built)
        return built

    yield make
    for built in made:
        built.shutdown()


def start(target, number: int = 1, **fields):
    fields.setdefault("wait_ms", 5000)
    reply = target.handle(doc("start", **fields), request_id=rid(number))
    assert reply.ok, reply.header
    return reply


def collect(target, number: int, until: str, timeout: float = 15.0) -> str:
    """Everything the session printed, once ``until`` has appeared."""
    deadline = time.monotonic() + timeout
    while True:
        reply = target.handle(doc("read", session=sid(number), offset=0, length=65536),
                              request_id=rid(900))
        seen = text_of(reply)
        if until in seen:
            return seen
        assert time.monotonic() < deadline, seen
        time.sleep(0.05)


def wait_ended(target, number: int, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while True:
        reply = target.handle(doc("read", session=sid(number), offset=0, length=65536),
                              request_id=rid(901))
        if reply.header["alive"] is False and reply.header["exit_code"] is not None:
            return reply
        assert time.monotonic() < deadline, reply.header
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# The real loop over a real program.
# ---------------------------------------------------------------------------
def test_start_returns_the_first_output_under_the_contract_header(manager):
    target = manager()
    reply = start(target)
    header = reply.header
    assert set(header) == CONTRACT_HEADER_KEYS
    assert header["v"] == 1 and header["op"] == "start" and header["session"] == sid(1)
    assert header["ok"] is True and header["code"] is None
    assert header["alive"] is True and header["ended"] is None and header["exit_code"] is None
    assert header["backend"] == "pipe"
    assert text_of(reply) == "ready\n"
    assert header["offset"] == 0
    assert header["next_offset"] == header["end_offset"] == len(reply.output)
    assert header["dropped_bytes"] == 0 and header["ends_with_newline"] is True
    assert reply.exit_code == 0


def test_an_input_is_answered_with_the_output_it_caused(manager):
    target = manager()
    first = start(target)
    reply = target.handle(doc("input", session=sid(1), text_b64=b64("hello"), wait_ms=5000),
                          request_id=rid(2))
    assert reply.ok and text_of(reply) == "got:hello\n"
    # Without an offset the answer starts where the output ended before the write.
    assert reply.header["offset"] == first.header["end_offset"]


def test_text_without_enter_waits_for_the_enter_key(manager):
    target = manager()
    start(target)
    held = target.handle(doc("input", session=sid(1), text_b64=b64("par"), enter=False,
                             wait_ms=300), request_id=rid(2))
    assert held.ok and text_of(held) == ""
    sent = target.handle(doc("input", session=sid(1), text_b64=b64("tial"), enter=False,
                             key="enter", wait_ms=5000), request_id=rid(3))
    assert sent.ok and text_of(sent) == "got:partial\n"


def test_several_lines_are_each_entered(manager):
    target = manager()
    start(target)
    target.handle(doc("input", session=sid(1), text_b64=b64("one\ntwo"), wait_ms=0),
                  request_id=rid(2))
    seen = collect(target, 1, "got:two")
    assert "got:one\ngot:two\n" in seen


def test_reads_page_by_offset_and_never_cut_a_character(manager):
    target = manager()
    start(target)
    target.handle(doc("input", session=sid(1), text_b64=b64("한글 입력"), wait_ms=0),
                  request_id=rid(2))
    whole = collect(target, 1, "got:한글 입력")
    offset, pages = 0, []
    while True:
        page = target.handle(doc("read", session=sid(1), offset=offset, length=1),
                             request_id=rid(3))
        if not page.output:
            break
        page.output.decode("utf-8")  # a cut character would raise here
        assert page.header["offset"] == offset
        pages.append(page.output)
        offset = page.header["next_offset"]
    assert b"".join(pages).decode("utf-8").replace("\r\n", "\n") == whole
    assert offset == page.header["end_offset"]


def test_a_read_past_the_end_waits_and_then_reports_nothing_new(manager):
    target = manager()
    first = start(target)
    began = time.monotonic()
    reply = target.handle(doc("read", session=sid(1), offset=first.header["end_offset"],
                              wait_ms=300), request_id=rid(2))
    assert reply.ok and reply.output == b"" and reply.header["alive"] is True
    assert time.monotonic() - began >= 0.25


def test_a_finished_program_reports_its_exit_code_and_refuses_input(manager):
    target = manager()
    start(target)
    target.handle(doc("input", session=sid(1), text_b64=b64("quit"), wait_ms=5000),
                  request_id=rid(2))
    ended = wait_ended(target, 1)
    assert ended.ok and ended.header["ended"] == "exited" and ended.header["exit_code"] == 3
    assert "bye\n" in text_of(ended)
    refused = target.handle(doc("input", session=sid(1), text_b64=b64("late")),
                            request_id=rid(3))
    assert refused.ok is False and refused.exit_code == 1
    assert refused.header["code"] == "pc_session_ended"
    assert refused.header["alive"] is False
    # A stop of an ended session is still an answer, and it stays "exited".
    stopped = target.handle(doc("stop", session=sid(1)), request_id=rid(4))
    assert stopped.ok and stopped.header["ended"] == "exited"


def test_ctrl_d_closes_the_input_and_the_program_ends_on_its_own(manager):
    target = manager()
    start(target)
    reply = target.handle(doc("input", session=sid(1), key="ctrl_d", wait_ms=5000),
                          request_id=rid(2))
    assert reply.ok
    ended = wait_ended(target, 1)
    assert ended.header["ended"] == "exited" and ended.header["exit_code"] == 3
    assert "bye\n" in text_of(ended)


def test_stop_ends_the_program_and_can_be_repeated(manager):
    target = manager(SLEEPER)
    start(target)
    backend = target._sessions[sid(1)].backend
    stopped = target.handle(doc("stop", session=sid(1), offset=0), request_id=rid(2))
    assert stopped.ok and stopped.header["alive"] is False
    assert stopped.header["ended"] == "stopped"
    assert text_of(stopped) == "up\n"
    assert backend.poll() is not None  # the process is really gone
    again = target.handle(doc("stop", session=sid(1)), request_id=rid(3))
    assert again.ok and again.header["ended"] == "stopped"


def test_output_in_the_pc_code_page_is_read_as_text(manager):
    target = manager(CP949)
    start(target)
    assert "한글 출력\n" in collect(target, 1, "출력")


def test_output_past_the_buffer_is_counted_as_dropped(manager):
    target = manager(NOISY, buffer_bytes=512)
    start(target)
    collect(target, 1, "line0399")
    reply = target.handle(doc("read", session=sid(1), offset=0, length=65536),
                          request_id=rid(2))
    header = reply.header
    assert header["dropped_bytes"] == header["offset"] > 0
    assert header["end_offset"] - header["offset"] <= 512
    assert "line0399" in text_of(reply) and "line0000" not in text_of(reply)


def test_the_fifth_live_session_is_refused_and_a_stop_frees_the_slot(manager):
    target = manager(SLEEPER)
    for number in range(1, 5):
        start(target, number)
    refused = target.handle(doc("start"), request_id=rid(5))
    assert refused.ok is False and refused.header["code"] == "pc_session_limit"
    assert target.handle(doc("stop", session=sid(1)), request_id=rid(6)).ok
    start(target, 7)


def test_a_program_that_cannot_start_is_a_start_failure(manager):
    target = manager(argv_builder=lambda shell, command, terminal: ["padiem-no-such-program-7065"])
    refused = target.handle(doc("start"), request_id=rid(1))
    assert refused.ok is False and refused.exit_code == 1
    assert refused.header["code"] == "pc_session_start_failed"
    assert refused.header["detail"] == "shell_unavailable"
    status = target.handle(doc("status"), request_id=rid(2))
    assert status.header["sessions"] == []


def test_shutdown_ends_every_program(manager):
    target = manager(SLEEPER)
    start(target, 1)
    start(target, 2)
    backends = [target._sessions[sid(n)].backend for n in (1, 2)]
    target.shutdown()
    assert all(backend.poll() is not None for backend in backends)
    assert target.handle(doc("status"), request_id=rid(3)).header["sessions"] == []


# ---------------------------------------------------------------------------
# The same manager over a backend double: rules that need no process.
# ---------------------------------------------------------------------------
class FakeBackend:
    name = "pipe"

    def __init__(self, argv, cwd, *, on_output, on_exit, **options):
        self.argv, self.cwd, self.options = list(argv), cwd, options
        self.on_output, self.on_exit = on_output, on_exit
        self.sent = []
        self.terminated = False
        self.closed = False
        self.block = None

    def supports_key(self, key):
        return key != "ctrl_c"

    def send_text(self, text, enter):
        if self.block is not None:
            self.block.wait(10)
        self.sent.append(("text", text, enter))

    def send_key(self, key):
        self.sent.append(("key", key))

    def poll(self):
        return -9 if self.terminated else None

    def terminate(self):
        self.terminated = True
        self.on_exit(-9)

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def fake():
    created = []

    def factory(argv, cwd, **options):
        backend = FakeBackend(argv, cwd, **options)
        created.append(backend)
        return backend

    clock = Clock()
    target = sessions.SessionManager(
        argv_builder=lambda shell, command, terminal: [shell, command, str(terminal)],
        backends={"pipe": factory}, clock=clock, settle_ms=20, reaper_interval=None,
        input_write_timeout=0.3,
    )
    target.created, target.clock = created, clock
    yield target
    for backend in created:
        if backend.block is not None:
            backend.block.set()
    target.shutdown()


def test_start_hands_the_validated_parts_to_the_backend(fake, tmp_path):
    reply = fake.handle(doc("start", shell="cmd", command="python -i", cols=120, rows=40,
                            input_encoding="cp949", wait_ms=0),
                        request_id=rid(1), cwd=str(tmp_path))
    assert reply.ok
    backend = fake.created[0]
    assert backend.argv == ["cmd", "python -i", "False"]  # no pseudo-terminal registered
    assert backend.cwd == str(tmp_path)
    assert backend.options["cols"] == 120 and backend.options["rows"] == 40
    assert backend.options["input_encoding"] == "cp949"


def test_a_pseudo_terminal_is_preferred_and_a_failed_one_falls_back_to_pipes():
    calls = []

    def conpty(argv, cwd, **options):
        calls.append(("conpty", list(argv)))
        if argv[1] == "broken":
            raise OSError("no pseudo console")
        backend = FakeBackend(argv, cwd, **options)
        backend.name = "conpty"
        return backend

    def pipe(argv, cwd, **options):
        calls.append(("pipe", list(argv)))
        return FakeBackend(argv, cwd, **options)

    target = sessions.SessionManager(
        argv_builder=lambda shell, command, terminal: [shell, command, str(terminal)],
        backends={"pipe": pipe, "conpty": conpty}, reaper_interval=None)
    try:
        assert target.features == ["pipe", "conpty", "secret_mask"]
        first = target.handle(doc("start", command="ok", wait_ms=0), request_id=rid(1))
        assert first.header["backend"] == "conpty"
        second = target.handle(doc("start", command="broken", wait_ms=0), request_id=rid(2))
        assert second.ok and second.header["backend"] == "pipe"
        third = target.handle(doc("start", command="plain", terminal=False, wait_ms=0),
                              request_id=rid(3))
        assert third.header["backend"] == "pipe"
        assert calls == [
            ("conpty", ["powershell", "ok", "True"]),
            ("conpty", ["powershell", "broken", "True"]),
            ("pipe", ["powershell", "broken", "False"]),
            ("pipe", ["powershell", "plain", "False"]),
        ]
    finally:
        target.shutdown()


def test_text_goes_first_and_the_key_second(fake):
    start(fake, wait_ms=0)
    reply = fake.handle(doc("input", session=sid(1), text_b64=b64("y"), key="tab", wait_ms=0),
                        request_id=rid(2))
    assert reply.ok
    assert fake.created[0].sent == [("text", "y", True), ("key", "tab")]


def test_a_key_the_backend_cannot_send_writes_nothing(fake):
    start(fake, wait_ms=0)
    refused = fake.handle(doc("input", session=sid(1), text_b64=b64("y"), key="ctrl_c"),
                          request_id=rid(2))
    assert refused.ok is False and refused.header["code"] == "pc_session_key_unsupported"
    assert fake.created[0].sent == []


def test_a_prompt_without_a_line_end_is_reported_as_such(fake):
    start(fake, wait_ms=0)
    backend = fake.created[0]
    threading.Timer(0.05, backend.on_output, args=(">>> ",)).start()
    reply = fake.handle(doc("input", session=sid(1), text_b64=b64("1+1"), wait_ms=5000),
                        request_id=rid(2))
    assert reply.ok and reply.output == b">>> "
    assert reply.header["ends_with_newline"] is False
    assert reply.header["idle_ms"] >= 0


def test_an_input_the_program_does_not_take_is_a_timeout_and_is_not_repeated(fake):
    start(fake, wait_ms=0)
    backend = fake.created[0]
    backend.block = threading.Event()
    refused = fake.handle(doc("input", session=sid(1), text_b64=b64("stuck")),
                          request_id=rid(2))
    assert refused.ok is False and refused.header["code"] == "pc_session_input_timeout"
    # While the first write is still waiting a second one is refused at once.
    second = fake.handle(doc("input", session=sid(1), text_b64=b64("again")),
                         request_id=rid(3))
    assert second.header["code"] == "pc_session_input_timeout"
    backend.block.set()
    deadline = time.monotonic() + 5
    while not backend.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert backend.sent == [("text", "stuck", True)]


def test_a_session_nobody_contacts_expires_and_then_is_forgotten(fake):
    start(fake, keep_minutes=1, wait_ms=0)
    fake.clock.now += 59
    fake.reap()
    assert fake.handle(doc("status"), request_id=rid(2)).header["sessions"][0]["alive"] is True
    fake.clock.now += 2
    fake.reap()
    assert fake.created[0].terminated is True
    read = fake.handle(doc("read", session=sid(1)), request_id=rid(3))
    assert read.ok and read.header["alive"] is False and read.header["ended"] == "expired"
    refused = fake.handle(doc("input", session=sid(1), text_b64=b64("x")), request_id=rid(4))
    assert refused.ok is False and refused.header["code"] == "pc_session_expired"
    fake.clock.now += sessions.ENDED_KEEP_SECONDS + 1
    fake.reap()
    gone = fake.handle(doc("read", session=sid(1)), request_id=rid(5))
    assert gone.ok is False and gone.header["code"] == "pc_session_not_found"
    assert fake.created[0].closed is True


def test_any_request_keeps_a_session_from_expiring(fake):
    start(fake, keep_minutes=1, wait_ms=0)
    for _ in range(3):
        fake.clock.now += 50
        assert fake.handle(doc("read", session=sid(1)), request_id=rid(2)).header["alive"]
    assert fake.created[0].terminated is False


def test_only_a_few_ended_sessions_are_kept(fake):
    total = sessions.MAX_ENDED_SESSIONS + 3
    for number in range(1, total + 1):
        start(fake, number, wait_ms=0)
        fake.clock.now += 1
        assert fake.handle(doc("stop", session=sid(number)), request_id=rid(500 + number)).ok
    kept = fake.handle(doc("status"), request_id=rid(999)).header["sessions"]
    assert len(kept) == sessions.MAX_ENDED_SESSIONS
    assert sid(1) not in {row["session"] for row in kept}


def test_status_lists_sessions_and_what_this_helper_can_do(fake):
    start(fake, 1, wait_ms=0)
    header = fake.handle(doc("status"), request_id=rid(2)).header
    assert header["ok"] is True and header["op"] == "status" and header["v"] == 1
    assert header["limit"] == sessions.MAX_SESSIONS and header["features"] == ["pipe", "secret_mask"]
    row = header["sessions"][0]
    assert set(row) == {"session", "alive", "ended", "exit_code", "backend", "end_offset",
                        "idle_ms"}
    assert row["session"] == sid(1) and row["alive"] is True and row["backend"] == "pipe"


def test_an_unknown_session_is_not_found(fake):
    for op in ("input", "read", "stop"):
        fields = {"text_b64": b64("x")} if op == "input" else {}
        refused = fake.handle(doc(op, session=sid(77), **fields), request_id=rid(1))
        assert refused.ok is False and refused.header["code"] == "pc_session_not_found"
        assert refused.header["session"] == sid(77) and refused.header["op"] == op


def test_a_second_start_under_the_same_request_is_refused(fake):
    start(fake, 1, wait_ms=0)
    refused = fake.handle(doc("start", wait_ms=0), request_id=rid(1))
    assert refused.ok is False and refused.header["code"] == "pc_session_bad_request"
    assert len(fake.created) == 1


@pytest.mark.parametrize("failure, detail", [
    (FileNotFoundError("missing"), "shell_unavailable"),
    (OSError("refused"), "spawn_failed"),
])
def test_a_backend_that_cannot_open_leaves_no_session_behind(failure, detail):
    def broken(argv, cwd, **options):
        raise failure

    target = sessions.SessionManager(
        argv_builder=lambda shell, command, terminal: ["x"], backends={"pipe": broken},
        reaper_interval=None)
    refused = target.handle(doc("start"), request_id=rid(1))
    assert refused.header["code"] == "pc_session_start_failed"
    assert refused.header["detail"] == detail
    assert target.handle(doc("status"), request_id=rid(2)).header["sessions"] == []


def test_a_missing_git_bash_is_a_start_failure(fake):
    def no_bash(shell, command, terminal):
        raise helper.UserHelperError(helper.USER_HELPER_BASH_MISSING, "no bash")

    fake._argv_builder = no_bash
    refused = fake.handle(doc("start", shell="bash"), request_id=rid(1))
    assert refused.header["code"] == "pc_session_start_failed"
    assert refused.header["detail"] == "shell_unavailable"


def test_a_folder_that_is_not_there_is_a_start_failure(fake, tmp_path):
    refused = fake.handle(doc("start"), request_id=rid(1), cwd=str(tmp_path / "absent"))
    assert refused.header["code"] == "pc_session_start_failed"
    assert refused.header["detail"] == "cwd_invalid"
    assert fake.created == []


BAD_DOCUMENTS = [
    {"op": "status"},                                   # no version
    {"v": 2, "op": "status"},
    {"v": True, "op": "status"},
    {"v": 1, "op": "open"},
    {"v": 1},
    {"v": 1, "op": "status", "extra": 1},
    {"v": 1, "op": "read"},
    {"v": 1, "op": "read", "session": "short"},
    {"v": 1, "op": "read", "session": sid(1), "length": 0},
    {"v": 1, "op": "read", "session": sid(1), "length": 65537},
    {"v": 1, "op": "read", "session": sid(1), "length": True},
    {"v": 1, "op": "read", "session": sid(1), "offset": -1},
    {"v": 1, "op": "read", "session": sid(1), "wait_ms": 10001},
    {"v": 1, "op": "read", "session": sid(1), "text_b64": "eA=="},
    {"v": 1, "op": "start", "shell": "fish"},
    {"v": 1, "op": "start", "command": 7},
    {"v": 1, "op": "start", "command": "a\x00b"},
    {"v": 1, "op": "start", "terminal": "yes"},
    {"v": 1, "op": "start", "cols": 5},
    {"v": 1, "op": "start", "rows": 500},
    {"v": 1, "op": "start", "keep_minutes": 0},
    {"v": 1, "op": "start", "keep_minutes": 481},
    {"v": 1, "op": "start", "input_encoding": "latin-1"},
    {"v": 1, "op": "start", "session": sid(1)},
    {"v": 1, "op": "input", "session": sid(1)},
    {"v": 1, "op": "input", "session": sid(1), "key": "f1"},
    {"v": 1, "op": "input", "session": sid(1), "text_b64": "!!!"},
    {"v": 1, "op": "input", "session": sid(1), "text_b64": b64("a\rb")},
    {"v": 1, "op": "input", "session": sid(1), "text_b64": b64("a\x00b")},
    {"v": 1, "op": "input", "session": sid(1), "text_b64": b64("x" * 4001)},
    {"v": 1, "op": "input", "session": sid(1), "text_b64": b64("x"), "enter": 1},
    {"v": 1, "op": "input", "session": sid(1), "text_b64": b64("x"), "secret": "no"},
    {"v": 1, "op": "stop", "session": sid(1), "wait_ms": 5},
]


@pytest.mark.parametrize("document", BAD_DOCUMENTS)
def test_a_document_outside_the_contract_is_a_bad_request(fake, document):
    start(fake, 1, wait_ms=0)
    refused = fake.handle(document, request_id=rid(2))
    assert refused.ok is False and refused.exit_code == 1
    assert refused.header["code"] == "pc_session_bad_request"
    assert fake.created[0].sent == [] and len(fake.created) == 1


def test_the_secret_flag_and_the_longest_text_are_accepted(fake):
    start(fake, 1, wait_ms=0)
    reply = fake.handle(doc("input", session=sid(1), text_b64=b64("x" * 4000), secret=True,
                            wait_ms=0), request_id=rid(2))
    assert reply.ok
    assert fake.created[0].sent == [("text", "x" * 4000, True)]


def test_the_frame_command_is_base64_of_the_document(fake):
    command = base64.b64encode(json.dumps(doc("status")).encode("utf-8")).decode("ascii")
    assert fake.handle_command(command, request_id=rid(1)).ok
    for broken in ("", "not base64 !!", base64.b64encode(b"[1,2]").decode("ascii"),
                   base64.b64encode(b"\xff\xfe").decode("ascii"), None):
        refused = fake.handle_command(broken, request_id=rid(1))
        assert refused.ok is False and refused.header["code"] == "pc_session_bad_request"
        assert refused.header["v"] == 1


def test_a_start_needs_a_real_request_identifier(fake):
    refused = fake.handle(doc("start"), request_id="req_nope")
    assert refused.header["code"] == "pc_session_bad_request"


def test_the_reply_body_is_a_header_line_and_then_the_output(fake):
    start(fake, 1, wait_ms=0)
    fake.created[0].on_output("가\n나")
    reply = fake.handle(doc("read", session=sid(1)), request_id=rid(2))
    head, _, rest = reply.to_body().partition(b"\n")
    assert json.loads(head.decode("ascii")) == reply.header
    assert rest.decode("utf-8") == "가\n나"
    refused = fake.handle(doc("read", session=sid(9)), request_id=rid(3))
    assert refused.to_body().endswith(b"\n") and refused.exit_code == 1


# ---------------------------------------------------------------------------
# Pieces: decoder, buffer, argv.
# ---------------------------------------------------------------------------
def test_the_decoder_joins_a_utf8_character_split_across_chunks():
    decoder = sessions.OutputDecoder()
    raw = "한글".encode("utf-8")
    assert decoder.feed(raw[:1]) + decoder.feed(raw[1:4]) + decoder.feed(raw[4:]) == "한글"
    assert decoder.fallback_used is False


def test_the_decoder_reads_the_code_page_when_a_chunk_is_not_utf8():
    decoder = sessions.OutputDecoder()
    assert decoder.feed("한글".encode("cp949")) == "한글"
    assert decoder.fallback_used is True
    # The next chunk is tried as UTF-8 again.
    assert decoder.feed("다음 줄".encode("utf-8")) == "다음 줄"


def test_the_decoder_keeps_the_valid_utf8_before_the_first_bad_byte():
    decoder = sessions.OutputDecoder()
    assert decoder.feed("앞 ".encode("utf-8") + "뒤".encode("cp949")) == "앞 뒤"


def test_the_decoder_carries_a_code_page_character_split_across_chunks():
    decoder = sessions.OutputDecoder()
    raw = "가나다".encode("cp949")
    assert decoder.feed(raw[:5]) + decoder.feed(raw[5:]) == "가나다"
    lead_only = sessions.OutputDecoder()
    assert lead_only.feed(raw[:1]) + lead_only.feed(raw[1:]) == "가나다"


def test_the_decoder_never_raises_on_a_dangling_byte_at_the_end():
    decoder = sessions.OutputDecoder()
    assert decoder.feed(b"ok\xea") == "ok"
    assert decoder.feed(b"", final=True) != ""


def test_the_buffer_addresses_output_by_absolute_offset():
    buffer = sessions.OutputBuffer(1024)
    assert buffer.end_offset == 0 and buffer.ends_with_newline is True
    assert buffer.last_append is None
    buffer.append("abc\n")
    buffer.append("def")
    assert buffer.end_offset == 7 and buffer.ends_with_newline is False
    assert buffer.last_append is not None
    piece = buffer.read(2, 3)
    assert (piece.data, piece.offset, piece.next_offset, piece.end_offset) == (b"c\nd", 2, 5, 7)
    past = buffer.read(99, 10)
    assert (past.data, past.offset, past.next_offset, past.dropped_bytes) == (b"", 7, 7, 0)


def test_the_buffer_steps_over_a_character_it_was_pointed_into():
    buffer = sessions.OutputBuffer(1024)
    buffer.append("가나")  # 3 bytes each
    inside = buffer.read(1, 10)
    assert inside.data.decode("utf-8") == "나" and inside.offset == 3
    small = buffer.read(0, 1)
    assert small.data.decode("utf-8") == "가" and small.next_offset == 3
    cut = buffer.read(0, 4)
    assert cut.data.decode("utf-8") == "가" and cut.next_offset == 3


def test_the_buffer_drops_whole_characters_from_the_front():
    buffer = sessions.OutputBuffer(16)
    buffer.append("가" * 10)  # 30 bytes into 16
    piece = buffer.read(0, 100)
    assert piece.dropped_bytes == piece.offset > 0
    assert piece.end_offset == 30 and piece.end_offset - piece.offset <= 16
    assert piece.data.decode("utf-8") == "가" * (len(piece.data) // 3)


def test_a_command_runs_through_the_chosen_shell(monkeypatch):
    def decoded(argv):
        return base64.b64decode(argv[-1]).decode("utf-16-le")

    piped = sessions.build_session_argv("powershell", "python -i", terminal=False)
    assert piped[0] == sessions.windows_powershell_executable() and piped[-2] == "-EncodedCommand"
    assert "-NonInteractive" not in piped  # a session exists to be asked questions
    assert decoded(piped) == helper.powershell_envelope("python -i")

    on_terminal = sessions.build_session_argv("powershell", "python -i", terminal=True)
    script = decoded(on_terminal)
    assert "python -i" in script and "OutputEncoding" not in script
    assert script.rstrip().endswith("exit $__padiem_exit")

    assert sessions.build_session_argv("cmd", "pip uninstall x", terminal=False) == [
        sessions.system_executable("cmd.exe"), "/d", "/s", "/c", "pip uninstall x"]
    monkeypatch.setattr(sessions, "locate_git_bash", lambda: r"C:\Git\bin\bash.exe")
    assert sessions.build_session_argv("bash", "git add -p", terminal=True) == [
        r"C:\Git\bin\bash.exe", "-lc", "git add -p"]


def test_an_empty_command_opens_the_shell_itself(monkeypatch):
    piped = sessions.build_session_argv("powershell", "", terminal=False)
    assert piped[-2:] == ["-Command", "-"]
    on_terminal = sessions.build_session_argv("powershell", "", terminal=True)
    assert "-Command" not in on_terminal and "-EncodedCommand" not in on_terminal
    assert sessions.build_session_argv("cmd", "", terminal=True) == [sessions.system_executable("cmd.exe"), "/d"]
    monkeypatch.setattr(sessions, "locate_git_bash", lambda: r"C:\Git\bin\bash.exe")
    assert sessions.build_session_argv("bash", "", terminal=False) == [
        r"C:\Git\bin\bash.exe", "--login", "-i"]


def test_bash_without_git_bash_and_an_unknown_shell_are_refused(monkeypatch):
    monkeypatch.setattr(sessions, "locate_git_bash", lambda: None)
    with pytest.raises(helper.UserHelperError) as missing:
        sessions.build_session_argv("bash", "ls", terminal=False)
    assert missing.value.code == helper.USER_HELPER_BASH_MISSING
    with pytest.raises(sessions.SessionRefusal) as refused:
        sessions.build_session_argv("fish", "ls", terminal=False)
    assert refused.value.code == "pc_session_bad_request"
