"""#7065 stage 3 — sessions on a Windows pseudo console (ConPTY).

The Windows tests start real programs on a real pseudo console through the real
session manager: a prompt that is visible before any input, a REPL answering,
Korean in and out, Ctrl+C reaching a running program, the exit code, and a
stop. They run on the ``windows-latest`` job of
``.github/workflows/claw-connect-contract-tests.yml``. The rest runs anywhere.
"""
from __future__ import annotations

import base64
import faulthandler
import sys
import time

import pytest

from claw_connect import conpty_backend
from claw_connect import user_session_manager as sessions

on_windows = pytest.mark.skipif(sys.platform != "win32",
                                reason="a pseudo console exists on Windows only")


def rid(number: int) -> str:
    return "req_%032x" % number


def sid(number: int) -> str:
    return "%032x" % number


def doc(op: str, **fields):
    return {"v": 1, "op": op, **fields}


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# Anywhere.
# ---------------------------------------------------------------------------
def test_every_session_key_has_console_bytes():
    assert set(conpty_backend.KEY_BYTES) == set(sessions.SESSION_KEYS)
    assert conpty_backend.KEY_BYTES["enter"] == b"\r"
    assert conpty_backend.KEY_BYTES["ctrl_c"] == b"\x03"
    assert conpty_backend.ConptyBackend.keys == frozenset(sessions.SESSION_KEYS)


@pytest.mark.skipif(sys.platform == "win32", reason="the non-Windows answer")
def test_without_windows_there_is_no_pseudo_console_and_sessions_use_pipes():
    assert conpty_backend.conpty_available() is False
    assert sessions.default_backends() == {"pipe": sessions.PipeBackend}
    with pytest.raises(OSError):
        conpty_backend.ConptyBackend(["x"], None, on_output=print, on_exit=print)
    manager = sessions.SessionManager(reaper_interval=None)
    try:
        assert manager.features == ["pipe"]
    finally:
        manager.shutdown()


def test_the_exit_code_is_read_as_a_signed_number():
    assert conpty_backend._signed(0) == 0
    assert conpty_backend._signed(3) == 3
    assert conpty_backend._signed(0xC000013A) == -1073741510
    assert conpty_backend._signed(0xFFFFFFFF) == -1


# ---------------------------------------------------------------------------
# Windows: real programs on a real pseudo console.
# ---------------------------------------------------------------------------
@pytest.fixture
def manager(monkeypatch):
    # The classic REPL: its prompt and echo are plain console text.
    monkeypatch.setenv("PYTHON_BASIC_REPL", "1")
    # A wedged console must fail this file with every thread's stack, not hold
    # the whole gate until the job is cancelled.
    faulthandler.dump_traceback_later(180, exit=True)
    made = []

    def make(argv_builder=None):
        built = sessions.SessionManager(
            argv_builder=argv_builder or (lambda shell, command, terminal:
                                          [sys.executable, "-q"]),
            reaper_interval=None, settle_ms=300)
        made.append(built)
        return built

    try:
        yield make
    finally:
        for built in made:
            built.shutdown()
        faulthandler.cancel_dump_traceback_later()


def everything(target, number: int) -> str:
    reply = target.handle(doc("read", session=sid(number), offset=0, length=65536),
                          request_id=rid(900))
    return reply.output.decode("utf-8")


def until(target, number: int, needle: str, timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    while True:
        seen = everything(target, number)
        if needle in seen:
            return seen
        assert time.monotonic() < deadline, seen
        time.sleep(0.1)


@on_windows
def test_windows_has_a_pseudo_console_and_it_is_the_default():
    assert conpty_backend.conpty_available() is True
    assert sessions.default_backends() == {"pipe": sessions.PipeBackend,
                                           "conpty": conpty_backend.ConptyBackend}


@on_windows
def test_a_repl_prompt_is_visible_before_any_input_and_answers(manager):
    target = manager()
    started = target.handle(doc("start", wait_ms=10000), request_id=rid(1))
    assert started.ok and started.header["backend"] == "conpty", started.header
    until(target, 1, ">>> ")
    status = target.handle(doc("read", session=sid(1), offset=0), request_id=rid(2))
    assert status.header["ends_with_newline"] is False
    assert "\x1b" not in status.output.decode("utf-8")

    answer = target.handle(doc("input", session=sid(1), text_b64=b64("6*7"), wait_ms=10000),
                           request_id=rid(3))
    assert answer.ok
    until(target, 1, "42")

    target.handle(doc("input", session=sid(1), text_b64=b64("print('한글 ' + '확인')"),
                      wait_ms=10000), request_id=rid(4))
    until(target, 1, "한글 확인")

    target.handle(doc("input", session=sid(1), text_b64=b64("import sys; sys.exit(5)"),
                      wait_ms=10000), request_id=rid(5))
    deadline = time.monotonic() + 30
    while True:
        reply = target.handle(doc("read", session=sid(1)), request_id=rid(6))
        if reply.header["alive"] is False or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    assert reply.header["ended"] == "exited" and reply.header["exit_code"] == 5, reply.header


@on_windows
def test_ctrl_c_reaches_a_running_program(manager):
    target = manager()
    assert target.handle(doc("start", wait_ms=10000), request_id=rid(1)).ok
    until(target, 1, ">>> ")
    target.handle(doc("input", session=sid(1),
                      text_b64=b64("import time; time.sleep(60)"), wait_ms=1000),
                  request_id=rid(2))
    interrupted = target.handle(doc("input", session=sid(1), key="ctrl_c", wait_ms=10000),
                                request_id=rid(3))
    assert interrupted.ok, interrupted.header
    seen = until(target, 1, "KeyboardInterrupt")
    assert seen.rstrip().endswith(">>>")  # the REPL is still there afterwards
    assert target.handle(doc("read", session=sid(1)), request_id=rid(4)).header["alive"] is True


@on_windows
def test_an_interactive_cmd_takes_commands_and_stops(manager):
    target = manager(sessions.build_session_argv)
    started = target.handle(doc("start", shell="cmd", wait_ms=10000), request_id=rid(1))
    assert started.ok and started.header["backend"] == "conpty", started.header
    target.handle(doc("input", session=sid(1), text_b64=b64("echo conpty-7065-ok"),
                      wait_ms=10000), request_id=rid(2))
    until(target, 1, "conpty-7065-ok\n")
    backend = target._sessions[sid(1)].backend
    stopped = target.handle(doc("stop", session=sid(1)), request_id=rid(3))
    assert stopped.ok and stopped.header["alive"] is False
    assert stopped.header["ended"] == "stopped"
    assert backend.poll() is not None


@on_windows
def test_a_powershell_command_reports_its_own_exit_code(manager):
    target = manager(sessions.build_session_argv)
    started = target.handle(doc("start", shell="powershell",
                                command="Write-Output 'ps-7065'; cmd /c exit 4",
                                wait_ms=15000), request_id=rid(1))
    assert started.ok, started.header
    deadline = time.monotonic() + 60
    while True:
        reply = target.handle(doc("read", session=sid(1), offset=0), request_id=rid(2))
        if reply.header["alive"] is False or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert reply.header["exit_code"] == 4, reply.header
    assert "ps-7065" in reply.output.decode("utf-8")


@on_windows
def test_a_missing_program_is_a_start_failure(manager):
    target = manager(lambda shell, command, terminal: ["padiem-no-such-program-7065.exe"])
    refused = target.handle(doc("start"), request_id=rid(1))
    assert refused.ok is False and refused.header["code"] == "pc_session_start_failed"
    assert refused.header["detail"] == "shell_unavailable"
