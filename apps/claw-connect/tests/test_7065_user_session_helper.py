"""#7065 (c) stage 1 — the logged-in user helper protocol.

No real WSL distribution, pipe, scheduled task or user session is started here.
The runner seam is a double, so the one-request-one-process rule is proven
without a process, and the pipe is a fake handle.
"""
from __future__ import annotations

import base64
import json

import pytest

from claw_connect import user_session_helper as helper

SECRET = b"deployment-secret-for-tests"
DEVICE = "dev_" + "c" * 32
REQUEST_ID = "req_" + "a" * 32


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
    """A request carrying the nonce the agent would send."""
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


class Runner:
    """Records every process the helper asked for."""

    def __init__(self, exit_code=0, stdout=b"", stderr=b""):
        self.calls = []
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, argv, cwd, timeout_seconds):
        self.calls.append({"argv": list(argv), "cwd": cwd, "timeout": timeout_seconds})
        return self.exit_code, self.stdout, self.stderr


# ---------------------------------------------------------------------------
# Pipe naming
# ---------------------------------------------------------------------------
def test_pipe_name_is_stable_hash_of_raw_device_id():
    expected = helper.pipe_name(DEVICE)
    assert expected == helper.PIPE_PREFIX + helper.device_id_pipe_suffix(DEVICE)
    assert expected == helper.pipe_name(DEVICE)
    assert helper.pipe_path(DEVICE) == "\\\\.\\pipe\\" + expected
    assert expected.startswith(helper.PIPE_PREFIX + "dev_")
    suffix = expected[len(helper.PIPE_PREFIX):]
    assert len(suffix) == 36 and suffix.startswith("dev_")
    assert all(c in "0123456789abcdef" for c in suffix[4:])


def test_pipe_name_accepts_meshcentral_raw_device_id_and_is_safe():
    raw = "abcdefghijklmnopqrstuvwx1234567890ABCDEFGHIJKLMNOPQRSTfi$D62t1"
    # raw includes '$' and is MeshCentral-like; must not raise and must derive stable hash
    name = helper.pipe_name(raw)
    assert name == helper.pipe_name(raw)
    assert "$" not in name
    assert name.startswith(helper.PIPE_PREFIX + "dev_")


@pytest.mark.parametrize("bad", ["", "has space", "bad\nid", "bad\rid", "../../etc", "node//abc", None])
def test_pipe_name_refuses_unsafe_device_id(bad):
    with pytest.raises(helper.UserHelperError) as refused:
        helper.pipe_name(bad)
    assert refused.value.code == helper.USER_HELPER_BAD_REQUEST


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------
def test_whoami_request_parses_and_signs():
    request = helper.parse_request(_request())
    assert request.shell == "whoami"
    assert helper.verify_nonce(SECRET, _signed()) is True


def test_unknown_field_is_refused():
    with pytest.raises(helper.UserHelperError) as refused:
        helper.parse_request(_request(extra="x"))
    assert refused.value.code == helper.USER_HELPER_BAD_REQUEST


def test_request_id_must_be_a_request_identifier():
    with pytest.raises(helper.UserHelperError):
        helper.parse_request(_request(request_id="req_short"))


def test_timeout_is_signed_but_not_an_execution_deadline():
    # #7107: the field stays on the wire for the nonce contract; it no longer
    # ends a command. The runner receives None and the child runs to completion.
    seen = {}

    def runner(argv, cwd, timeout_seconds):
        seen["timeout"] = timeout_seconds
        return 0, b"ok\n", b""

    reply = helper.serve_one(_signed(timeout_seconds=999_999), secret=SECRET, runner=runner)
    assert seen["timeout"] is None
    assert reply.status == "ok"
    with pytest.raises(helper.UserHelperError):
        helper.parse_request(_request(timeout_seconds=-1))
    with pytest.raises(helper.UserHelperError):
        helper.parse_request(_request(timeout_seconds=True))


def test_whoami_shell_runs_whoami_only():
    with pytest.raises(helper.UserHelperError) as refused:
        helper.parse_request(_request(shell="whoami", command="whoami /all"))
    assert refused.value.code == helper.USER_HELPER_REFUSED


@pytest.mark.parametrize("shell", ["wsl", "fish", "pwsh", "Powershell"])
def test_a_shell_the_helper_does_not_run_is_refused(shell):
    with pytest.raises(helper.UserHelperError) as refused:
        helper.parse_request(_request(shell=shell, command="whoami"))
    assert refused.value.code == helper.USER_HELPER_REFUSED


@pytest.mark.parametrize("shell", ["whoami", "bash", "powershell", "cmd"])
def test_distro_belongs_to_no_shell_any_more(shell):
    """#7188 R4 ④: the wsl shell is gone, so any distro value is a bad request.

    The field itself stays in the wire contract — the executor's pipe client
    always sends it, as ``null`` — and ``null`` stays valid.
    """
    command = "whoami" if shell == "whoami" else "echo ok"
    with pytest.raises(helper.UserHelperError) as refused:
        helper.parse_request(_request(shell=shell, command=command, distro="Ubuntu"))
    assert refused.value.code == helper.USER_HELPER_BAD_REQUEST


def test_distro_null_stays_valid_for_every_shell():
    for shell in ("whoami", "bash", "powershell", "cmd"):
        command = "whoami" if shell == "whoami" else "echo ok"
        request = helper.parse_request(_request(shell=shell, command=command, distro=None))
        assert request.distro is None


# ---------------------------------------------------------------------------
# bash is a stage-2 shell now (#7188 R4 ④) — the read-only gate is gone with
# the wsl shell it guarded, so `echo $BASH_VERSION; uname -s` runs instead of
# the user_helper_not_read_only refusal the CTO measured on COM1.
# ---------------------------------------------------------------------------
def test_bash_takes_the_stage_two_gate_not_the_read_only_gate():
    request = helper.parse_request(
        _request(shell="bash", command="echo $BASH_VERSION; uname -s"))
    assert request.shell == "bash"
    assert request.command == "echo $BASH_VERSION; uname -s"


@pytest.mark.parametrize("command", ["", "   ", "a\x00b", "a\x07b"])
def test_bash_stage_two_command_must_be_a_bounded_line(command):
    assert helper.is_windows_shell_command(command) is False



# ---------------------------------------------------------------------------
# argv: the command is one element, never a shell string
# ---------------------------------------------------------------------------
def test_bash_argv_runs_the_located_git_bash(monkeypatch):
    monkeypatch.setattr(helper, "locate_git_bash",
                        lambda: "C:\Git\bin\bash.exe")
    request = _signed(shell="bash", command="uname -s")
    argv = helper.build_argv(request)
    assert argv == ["C:\Git\bin\bash.exe", "-lc", "uname -s"]


def test_bash_argv_without_a_located_git_bash_is_a_bounded_refusal(monkeypatch):
    monkeypatch.setattr(helper, "locate_git_bash", lambda: None)
    request = _signed(shell="bash", command="uname -s")
    with pytest.raises(helper.UserHelperError) as missing:
        helper.build_argv(request)
    assert missing.value.code == helper.USER_HELPER_BASH_MISSING


def test_whoami_argv_is_one_executable():
    assert helper.build_argv(_signed()) == ["whoami.exe"]


# ---------------------------------------------------------------------------
# #7104 stage 2: powershell and cmd run as the logged-in user
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("shell,command", [
    ("powershell", "Write-Output 'ok'"),
    ("cmd", "echo ok"),
])
def test_stage_two_shells_parse_and_sign(shell, command):
    request = _signed(shell=shell, command=command)
    assert request.shell == shell
    assert helper.verify_nonce(SECRET, request) is True


def test_powershell_argv_is_one_encoded_command():
    request = _signed(shell="powershell", command="Get-Location")
    argv = helper.build_argv(request)
    assert argv[:6] == ["powershell.exe", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-EncodedCommand"]
    assert len(argv) == 7
    script = base64.b64decode(argv[6]).decode("utf-16-le")
    assert "Get-Location" in script
    # The exit code is the child's own, the same rule the SYSTEM lane applies.
    assert "$LASTEXITCODE" in script


def test_cmd_argv_passes_the_command_as_one_element():
    request = _signed(shell="cmd", command='echo "a b" & whoami')
    assert helper.build_argv(request) == ["cmd.exe", "/d", "/s", "/c", 'echo "a b" & whoami']


@pytest.mark.parametrize("command", ["", "   ", "a\x00b", "a\x07b"])
def test_stage_two_command_must_be_a_bounded_line(command):
    assert helper.is_windows_shell_command(command) is False


def test_stage_two_command_keeps_newlines_for_a_real_script():
    assert helper.is_windows_shell_command("Get-Location\nWrite-Output 'x'") is True


def test_stage_two_shells_do_not_get_a_read_only_gate():
    # `systemctl restart` used to be refused on the wsl shell; on the stage-2
    # shells (bash included) it is just text the approved dispatch authorizes.
    for shell_name in ("bash", "cmd"):
        request = helper.parse_request(_request(shell=shell_name, command="systemctl restart x"))
        assert request.command == "systemctl restart x"


# ---------------------------------------------------------------------------
# One request = one process
# ---------------------------------------------------------------------------
def test_one_request_runs_exactly_one_process():
    runner = Runner(exit_code=0, stdout=b"padiem-user\n")
    reply = helper.serve_one(_signed(), secret=SECRET, runner=runner)
    assert len(runner.calls) == 1
    assert reply.status == "ok"
    assert reply.exit_code == 0
    assert reply.stdout == b"padiem-user\n"


def test_a_refused_request_starts_no_process():
    runner = Runner()
    bad = _signed()
    bad = helper.HelperRequest(
        request_id=bad.request_id, nonce="0" * 64, shell=bad.shell,
        command=bad.command, timeout_seconds=bad.timeout_seconds,
    )
    reply = helper.serve_one(bad, secret=SECRET, runner=runner)
    assert runner.calls == []
    assert reply.status == "error"
    assert reply.error_code == helper.USER_HELPER_REFUSED


def test_exit_code_is_the_childs_own():
    runner = Runner(exit_code=3, stdout=b"inactive\n")
    reply = helper.serve_one(_signed(), secret=SECRET, runner=runner)
    assert reply.exit_code == 3
    assert reply.stdout == b"inactive\n"


def test_a_timeout_is_reported_as_a_timeout():
    def slow(argv, cwd, timeout_seconds):
        raise helper.UserHelperError(helper.USER_HELPER_TIMEOUT, "the process did not finish in time")

    reply = helper.serve_one(_signed(), secret=SECRET, runner=slow)
    assert reply.status == "error"
    assert reply.error_code == helper.USER_HELPER_TIMEOUT


def test_a_large_body_is_returned_whole():
    # #7107: the 256 KiB per-stream cut is gone. The caller pages the whole body.
    body = b"x" * (helper.MAX_STREAM_BYTES + 10)
    reply = helper.serve_one(_signed(), secret=SECRET, runner=Runner(stdout=body))
    assert reply.truncated is False
    assert reply.stdout == body


# ---------------------------------------------------------------------------
# Reply frame: ASCII only, UTF-8 bodies
# ---------------------------------------------------------------------------
def test_reply_frame_round_trips_korean_text():
    runner = Runner(stdout="사용자\n".encode("utf-8"))
    reply = helper.serve_one(_signed(), secret=SECRET, runner=runner)
    frame = json.dumps(reply.to_frame(), ensure_ascii=True).encode("utf-8")
    frame.decode("ascii")
    decoded = helper.decode_reply(frame)
    assert decoded.stdout.decode("utf-8") == "사용자\n"
    assert decoded.request_id == REQUEST_ID


def test_a_non_utf8_body_is_refused_not_shown():
    frame = json.dumps({
        "request_id": REQUEST_ID, "status": "ok", "exit_code": 0,
        "stdout_b64": base64.b64encode(b"\xff\xfe\x00").decode("ascii"),
        "stderr_b64": "", "truncated": False, "error_code": None, "duration_ms": 1,
    }).encode("utf-8")
    with pytest.raises(helper.UserHelperError) as refused:
        helper.decode_reply(frame)
    assert refused.value.code == helper.USER_HELPER_BAD_REPLY


@pytest.mark.parametrize("raw", [b"not json", b"[]", b'{"status":"ok"}'])
def test_an_unreadable_reply_is_refused(raw):
    with pytest.raises(helper.UserHelperError) as refused:
        helper.decode_reply(raw)
    assert refused.value.code == helper.USER_HELPER_BAD_REPLY


# ---------------------------------------------------------------------------
# Replay guard
# ---------------------------------------------------------------------------
def test_a_request_id_is_accepted_once():
    guard = helper.ReplayGuard()
    assert guard.accept(REQUEST_ID) is True
    assert guard.accept(REQUEST_ID) is False


def test_the_replay_window_is_bounded():
    guard = helper.ReplayGuard(window=4)
    for index in range(10):
        guard.accept(f"req_{index:032x}")
    assert len(guard.seen) == 4


# ---------------------------------------------------------------------------
# Logged out is reported as logged out, never run as SYSTEM
# ---------------------------------------------------------------------------
def test_a_logged_out_user_is_user_session_unavailable():
    def absent(path):
        raise FileNotFoundError(path)

    with pytest.raises(helper.UserHelperError) as refused:
        helper.forward_to_helper(_signed(), secret=SECRET, device_id=DEVICE, connect=absent)
    assert refused.value.code == helper.USER_SESSION_UNAVAILABLE


def test_an_unopenable_pipe_is_user_session_unavailable():
    def broken(path):
        raise OSError("pipe busy")

    with pytest.raises(helper.UserHelperError) as refused:
        helper.forward_to_helper(_signed(), secret=SECRET, device_id=DEVICE, connect=broken)
    assert refused.value.code == helper.USER_SESSION_UNAVAILABLE


class FakePipe:
    def __init__(self, reply_frame):
        self.reply_frame = reply_frame
        self.written = b""
        self.closed = False

    def write(self, data):
        self.written += data

    def flush(self):
        pass

    def read(self, size):
        return self.reply_frame

    def close(self):
        self.closed = True


def test_forwarding_sends_a_signed_frame_and_reads_the_reply():
    reply = helper.HelperReply(
        request_id=REQUEST_ID, status="ok", exit_code=0, stdout=b"padiem-user\n",
    )
    pipe = FakePipe(json.dumps(reply.to_frame(), ensure_ascii=True).encode("utf-8"))
    result = helper.forward_to_helper(
        _signed(), secret=SECRET, device_id=DEVICE, connect=lambda path: pipe,
    )
    assert result.stdout == b"padiem-user\n"
    assert pipe.closed is True
    sent = json.loads(pipe.written.decode("utf-8"))
    assert sent["request_id"] == REQUEST_ID
    assert sent["nonce"] == helper.request_nonce(SECRET, helper.parse_request(_request()))
    assert set(sent) == {
        "request_id", "nonce", "shell", "cwd", "command", "timeout_seconds", "distro",
    }


def test_the_forwarded_frame_carries_no_secret():
    reply = helper.HelperReply(request_id=REQUEST_ID, status="ok", exit_code=0)
    pipe = FakePipe(json.dumps(reply.to_frame(), ensure_ascii=True).encode("utf-8"))
    helper.forward_to_helper(_signed(), secret=SECRET, device_id=DEVICE,
                             connect=lambda path: pipe)
    assert SECRET not in pipe.written
