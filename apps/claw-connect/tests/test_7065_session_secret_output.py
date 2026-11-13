"""Secret echoes never enter the helper's readable output, including split VT."""
from __future__ import annotations

import base64
import sys
import threading
import time

import pytest

from claw_connect import user_session_manager as sessions
from claw_connect.session_output_text import TerminalTextFilter
from claw_connect.session_secret_output import MASK, MAX_PENDING_CHARS, SecretOutputFilter, prompt_hints


def registered(value, *, terminal=False, encoding="utf-8"):
    filtered = SecretOutputFilter()
    filtered.register(value, terminal=terminal, encoding=encoding)
    return filtered


def test_every_split_keeps_the_unfinished_value_out_of_output():
    value = "테스트-unique-passphrase"
    for split in range(1, len(value)):
        filtered = registered(value)
        assert filtered.feed("echo:" + value[:split]) == "echo:"
        assert filtered.feed(value[split:] + "\nordinary output\n") == MASK + "\nordinary output\n"
        assert filtered.feed("", final=True) == ""


def test_repeated_values_and_longer_overlapping_values_stay_hidden():
    filtered = registered("abcdef")
    filtered.register("abc", terminal=False, encoding="utf-8")
    assert filtered.feed("abc") == ""
    assert filtered.feed("def abc! abcdef\n") == f"{MASK} {MASK}! {MASK}\n"


def test_an_unfinished_final_echo_is_masked_and_memory_is_released():
    filtered = registered("unique-value")
    assert filtered.feed("uni") == ""
    assert filtered.feed("", final=True) == MASK
    assert filtered._patterns == {} and filtered._pending == ""
    assert filtered.feed("unique-value") == ""
    assert "unique-value" not in repr(filtered)


def test_multiline_values_are_masked_when_each_line_is_echoed_separately():
    filtered = registered("first-secret\n한글비밀\n")
    assert filtered.feed("first-secret\r\n") == MASK + "\r\n"
    assert filtered.feed("한글") == ""
    assert filtered.feed("비밀\n") == MASK + "\n"


def test_the_pipe_code_page_replacement_is_masked_too():
    filtered = registered("한글🔒value", encoding="cp949")
    assert filtered.feed("한글?value\n") == MASK + "\n"


def test_conpty_wraps_and_cursor_spaces_after_vt_reduction_are_masked():
    value = "abcdefghijklmnopqrstuvwxyz0123456789-long-secret"
    filtered = registered(value, terminal=True)
    terminal = TerminalTextFilter()
    # A 20-column console wraps to another row; cursor-forward supplies a
    # rendering space. Neither the control sequences nor these chunk borders
    # are the boundaries of the input value.
    chunks = ["\x1b[1;1H" + value[:20], "\x1b[2;1H" + value[20:26],
              "\x1b[3", "C" + value[26:40], "\x1b[3;1H" + value[40:] + "\r\n"]
    rendered = [filtered.feed(terminal.feed(chunk)) for chunk in chunks]
    assert rendered[:-1] == ["", "", "", ""]
    assert "".join(rendered) == MASK + "\n"


def test_control_characters_in_conpty_input_register_the_visible_value():
    filtered = registered("sec\x1b[31mret", terminal=True)
    assert filtered.feed("secret\n") == MASK + "\n"


def test_conpty_repainted_prefixes_never_leave_the_filter():
    filtered = registered("unique-value", terminal=True)
    terminal = TerminalTextFilter(preserve_redraws=True)
    chunks = ["u", "\runi", "\runiqu", "\runique-value\r\n"]
    output = "".join(filtered.feed(terminal.feed(chunk)) for chunk in chunks)
    assert output == MASK + "\n"


@pytest.mark.parametrize("move", ["\x1b[1;1H", "\x1b[1G", "\x1b[D"])
def test_cursor_repaint_markers_hide_the_previous_partial_echo(move):
    filtered = registered("unique-value", terminal=True)
    terminal = TerminalTextFilter(preserve_redraws=True)
    assert filtered.feed(terminal.feed("u")) == ""
    assert filtered.feed(terminal.feed(move + "unique-value\r\n")) == MASK + "\n"


@pytest.mark.parametrize("move", ["\x1b[1;1H", "\x1b[1G", "\x1b[D"])
def test_cursor_movement_can_resume_the_masked_values_suffix(move):
    filtered = registered("abcdef", terminal=True)
    terminal = TerminalTextFilter(preserve_redraws=True)
    assert filtered.feed(terminal.feed("abc")) == ""
    assert filtered.feed(terminal.feed(move + "def\r\n")) == MASK + "\n"


def test_a_repeated_value_can_resume_or_repaint_after_cursor_movement():
    filtered = registered("abab", terminal=True)
    terminal = TerminalTextFilter(preserve_redraws=True)
    assert filtered.feed(terminal.feed("ab")) == ""
    assert filtered.feed(terminal.feed("\x1b[1Gabab\r\n")) == MASK + "\n"


def test_an_unknown_forward_row_is_a_wrap_not_a_repaint():
    filtered = registered("unique-value", terminal=True)
    terminal = TerminalTextFilter(preserve_redraws=True)
    assert filtered.feed(terminal.feed("uni")) == ""
    assert filtered.feed(terminal.feed("\x1b[2;1Hque-value\r\n")) == MASK + "\n"


def test_default_text_reduction_keeps_a_later_row_break_after_same_row_moves():
    terminal = TerminalTextFilter()
    assert terminal.feed("\x1b[1;1Hplain\x1b[1;1H\x1b[2;1Hnext") == "plain\nnext"


@pytest.mark.parametrize("terminal", [False, True])
def test_an_echo_aborted_with_a_newline_does_not_release_its_prefix(terminal):
    filtered = registered("unique-value", terminal=terminal)
    assert filtered.feed("uni") == ""
    expected = MASK + ("" if terminal else "\n") + "failed\n"
    assert filtered.feed("\nfailed\n") == expected


def test_unbounded_render_spaces_keep_only_masked_match_positions():
    filtered = registered("unique-value", terminal=True)
    assert filtered.feed("uni" + " " * MAX_PENDING_CHARS) == MASK
    for _ in range(50):
        assert filtered.feed(" \n" * MAX_PENDING_CHARS) == ""
        assert filtered._pending == ""
        assert filtered._masked_prefix == [("unique-value", 3)]
    assert filtered.feed("que-value\nordinary\n") == "\nordinary\n"
    assert filtered._masked_prefix == []


def test_after_a_bounded_masked_match_diverges_other_output_is_preserved():
    filtered = registered("unique-value", terminal=True)
    assert filtered.feed("uni" + " " * MAX_PENDING_CHARS) == MASK
    assert filtered.feed("different output\n") == "different output\n"


def test_nonsecret_text_and_a_nonmatching_prefix_keep_their_contents():
    filtered = registered("unique-value")
    assert filtered.feed("other output\nuni") == "other output\n"
    assert filtered.feed("versal\n") == "universal\n"


@pytest.mark.parametrize("prompt", ["Password: ", "passphrase:", "암호: ", "비밀번호:", "PIN: "])
def test_secret_prompt_hints_are_advisory(prompt):
    assert prompt_hints("earlier\n" + prompt, alive=True, ends_with_newline=False) == {
        "waiting_hint": "input", "prompt_kind": "secret"}


def test_hints_use_the_current_unterminated_line_and_running_state_only():
    assert prompt_hints("Password:\nnormal prompt> ", alive=True, ends_with_newline=False) == {
        "waiting_hint": "input"}
    assert prompt_hints("Password:\n", alive=True, ends_with_newline=True) == {}
    assert prompt_hints("Password:", alive=False, ends_with_newline=False) == {}
    assert prompt_hints("", alive=True, ends_with_newline=True) == {}


class EchoBackend:
    name = "pipe"

    def __init__(self, _argv, _cwd, *, on_output, on_exit, **_options):
        self.output, self.exit = on_output, on_exit
        self.sent = 0
        self.on_send = None

    def supports_key(self, key):
        return True

    def send_text(self, text, enter):
        self.sent += 1
        if self.on_send:
            self.on_send(text)
        else:
            for char in text:
                self.output(char)
            self.output("\n" if enter else "")

    def send_key(self, key):
        pass

    def terminate(self):
        self.exit(0)


@pytest.fixture
def running(tmp_path):
    manager = sessions.SessionManager(backends={"pipe": EchoBackend},
                                      argv_builder=lambda *args, **kwargs: ["fake"],
                                      reaper_interval=None)
    reply = manager.handle({"v": 1, "op": "start", "wait_ms": 0},
                           request_id="req_" + "1" * 32, cwd=str(tmp_path))
    assert reply.ok
    session = manager._sessions["1" * 32]
    yield manager, session
    manager.shutdown()


def input_reply(manager, value, **options):
    return manager.handle({"v": 1, "op": "input", "session": "1" * 32,
                           "text_b64": base64.b64encode(value.encode()).decode(),
                           "secret": True, "wait_ms": 0, **options},
                          request_id="req_" + "2" * 32)


def read_reply(manager, **options):
    return manager.handle({"v": 1, "op": "read", "session": "1" * 32, **options},
                          request_id="req_" + "3" * 32)


def test_registration_precedes_synchronous_echo_and_ring_offsets_use_masked_bytes(running):
    manager, session = running
    value = "unique-input-value"
    reply = input_reply(manager, value)
    expected = (MASK + "\n").encode()
    assert reply.output == expected
    assert bytes(session.buffer._data) == expected
    assert reply.header["next_offset"] == reply.header["end_offset"] == len(expected)
    assert value not in repr(session) and value not in repr(reply)
    session.backend.output("after\n")
    assert read_reply(manager, offset=len(expected)).output == b"after\n"
    assert "secret_mask" in manager.features


def test_concurrent_read_never_sees_a_pending_secret_prefix(running):
    manager, session = running
    midpoint, finish = threading.Event(), threading.Event()
    value = "unique-input-value"

    def write(text):
        session.backend.output(text[:7])
        midpoint.set()
        assert finish.wait(2)
        session.backend.output(text[7:] + "\n")

    session.backend.on_send = write
    result = []
    worker = threading.Thread(target=lambda: result.append(input_reply(manager, value)))
    worker.start()
    try:
        assert midpoint.wait(2)
        assert read_reply(manager).output == b""
        assert bytes(session.buffer._data) == b""
    finally:
        finish.set()
        worker.join(2)
    assert result[0].output == (MASK + "\n").encode()


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, OSError])
def test_input_exception_details_never_escape_into_replies_or_logs(running, caplog, error_type):
    manager, session = running
    value = "unique-exception-value"

    def fail(text):
        raise error_type(text)

    session.backend.on_send = fail
    reply = input_reply(manager, value)
    assert reply.ok is False
    assert reply.header["code"] in ("pc_session_input_timeout", "pc_session_ended")
    assert value not in repr(reply) and value not in caplog.text
    assert value.encode() not in reply.to_body()


def test_hints_follow_current_output_even_when_reading_an_old_slice(running):
    manager, session = running
    session.backend.output("earlier\nPassword: ")
    reply = read_reply(manager, offset=0, length=2)
    assert reply.output == b"ea"
    assert reply.header["prompt_kind"] == "secret"
    assert reply.header["waiting_hint"] == "input"
    session.backend.output("\nready\n")
    reply = read_reply(manager)
    assert "prompt_kind" not in reply.header and "waiting_hint" not in reply.header


def test_stop_masks_incomplete_echo_and_releases_secrets(running):
    manager, session = running
    session.backend.on_send = lambda text: session.backend.output(text[:7])
    assert input_reply(manager, "unique-input-value").output == b""
    reply = manager.handle({"v": 1, "op": "stop", "session": "1" * 32, "offset": 0},
                           request_id="req_" + "4" * 32)
    assert reply.output == MASK.encode()
    assert session.secret_output._patterns == {}
    session.backend.output("unique-input-value")
    assert read_reply(manager).output == MASK.encode()


def test_real_pipe_drains_normal_final_output_before_closing_the_filter(tmp_path):
    unit = "normal final output 한글\n"
    expected = unit * 1000
    script = "import sys; sys.stdout.buffer.write(" + repr(unit.encode()) + " * 1000); sys.stdout.flush()"
    manager = sessions.SessionManager(
        backends={"pipe": sessions.PipeBackend}, reaper_interval=None,
        argv_builder=lambda *args, **kwargs: [sys.executable, "-u", "-c", script])
    try:
        started = manager.handle({"v": 1, "op": "start", "wait_ms": 10000},
                                 request_id="req_" + "1" * 32, cwd=str(tmp_path))
        assert started.ok
        deadline = time.monotonic() + 10
        while True:
            reply = read_reply(manager, length=65536)
            if not reply.header["alive"]:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert reply.output.decode().replace("\r\n", "\n") == expected
    finally:
        manager.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="ConPTY requires Windows")
@pytest.mark.parametrize("value", ["stage7-abcdefghijklmnopqrstuvwxyz-0123456789",
                                  "단계칠비밀입력-한글abcdefghijklmnopqrstuvwxyz-0123456789"])
def test_real_conpty_secret_echo_in_a_twenty_column_console(tmp_path, value):
    from claw_connect.conpty_backend import ConptyBackend

    script = 'value = input("Password: "); print("echo:" + value); print("finished-session")'
    manager = sessions.SessionManager(
        backends={"conpty": ConptyBackend}, reaper_interval=None,
        argv_builder=lambda *args, **kwargs: [sys.executable, "-X", "utf8", "-u", "-c", script])
    try:
        started = manager.handle({"v": 1, "op": "start", "cols": 20, "rows": 10,
                                  "wait_ms": 10000}, request_id="req_" + "1" * 32,
                                 cwd=str(tmp_path))
        assert started.ok and started.header["backend"] == "conpty"
        assert started.header["prompt_kind"] == "secret"
        reply = input_reply(manager, value, wait_ms=10000)
        assert reply.ok
        deadline = time.monotonic() + 15
        while True:
            reply = read_reply(manager, length=65536)
            if not reply.header["alive"]:
                break
            assert time.monotonic() < deadline
            time.sleep(0.05)
        rendered = reply.output.decode()
        assert MASK in rendered
        assert value not in rendered and value[:10] not in rendered
        assert "finished-session" in rendered.replace("\n", "")
    finally:
        manager.shutdown()
