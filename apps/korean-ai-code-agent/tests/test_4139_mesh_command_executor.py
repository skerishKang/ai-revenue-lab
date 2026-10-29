"""#4139 terminal lane — the Oracle command port and its exit-code contract.

The official ``meshctrl.js`` client is never actually launched here: the process
boundary is injected, so these tests pin the argv shape, the stdin credential,
and the exact transcript parsing that decides whether an exit code was observed.
"""
from __future__ import annotations

import base64
import io
import re
import subprocess
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from kagent.local_agent_meshcentral_command_port import (
    ENVELOPE_PREFIX, EXIT_SENTINEL, MeshCentralCliCommandPort,
    MeshCentralCommandRefused, cancel_kill_command, _wrap, parse_transcript,
)
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshChannelRefused, OracleMeshDispatch, OracleMeshExecutor,
)

SECRET = "deployment-channel-secret-value-261017"
PASSWORD = "op3rator-meshtr0ll-secret"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
MESHCTRL = "/opt/meshcentral/meshctrl.js"

#: The command inside the PowerShell script block the wrapper builds.
_INNER = re.compile(r"& \{ (?P<body>.*) \} 2>&1", re.S)


def _transcript(body: str, code: str = "0") -> bytes:
    """One reply transcript, exactly as the wrapped script prints it."""
    return (
        ENVELOPE_PREFIX + base64.b64encode(body.encode("utf-8")).decode("ascii")
        + "\n" + EXIT_SENTINEL + code + "\n"
    ).encode("utf-8")


def _inner(wrapped: str) -> str:
    """The caller's command as it reaches the PC."""
    return _INNER.search(wrapped).group("body")


class _Completed:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _port(completed=None, *, calls=None, password=PASSWORD, exc=None):
    def runner(argv, **kwargs):
        if calls is not None:
            calls.append((list(argv), dict(kwargs)))
        if exc is not None:
            raise exc
        return completed

    return MeshCentralCliCommandPort(
        command_runner=runner,
        meshctrl_js=MESHCTRL,
        login_user="padiemadmin",
        password_provider=lambda: password,
        url="wss://127.0.0.1:4443",
    )


class TranscriptParsingTests(unittest.TestCase):
    def test_korean_and_emoji_names_survive_the_reply_envelope(self):
        """The whole point of the envelope: cp949-era names come back intact.

        A 한국어 folder listing with an emoji file name is the exact reply that
        used to be destroyed as an invalid WebSocket frame, so the round trip is
        asserted here rather than inferred from a green transcript.
        """
        body = (
            '[{"Name":"견적서 🧾 3분기.txt","Length":4096,"PSIsContainer":false},'
            '{"Name":"보고서(최종).hwp","Length":81920,"PSIsContainer":false}]\r\n'
        )
        transcript = _transcript(body)
        # Only Base64 characters and the sentinel cross the wire on the way back.
        self.assertTrue(transcript.isascii())
        termination, exit_code, output = parse_transcript(transcript)
        self.assertEqual((termination, exit_code), ("exited", 0))
        self.assertEqual(output.decode("utf-8"), body)

    def test_crlf_output_is_preserved_and_the_sentinel_is_removed(self):
        raw = _transcript("Padiem-Command-Center\r\n")
        termination, exit_code, output = parse_transcript(raw)
        self.assertEqual(termination, "exited")
        self.assertEqual(exit_code, 0)
        # Only meshctrl's own trailing console.log newline is dropped.
        self.assertEqual(output, b"Padiem-Command-Center\r\n")

    def test_nonzero_exit_is_the_pc_value(self):
        raw = _transcript("Access is denied.\r\n", "5")
        termination, exit_code, output = parse_transcript(raw)
        self.assertEqual((termination, exit_code), ("exited", 5))
        self.assertEqual(output, b"Access is denied.\r\n")

    def test_a_reply_without_the_envelope_is_not_presented_as_pc_output(self):
        """The console answered, but in a shape this protocol never writes."""
        termination, exit_code, output = parse_transcript(
            ("plain console text\r\n" + EXIT_SENTINEL + "0\r\n\n").encode())
        self.assertEqual((termination, exit_code), ("bad_reply", 0))
        self.assertEqual(output, b"")

    def test_a_malformed_envelope_is_an_explicit_error_not_mangled_text(self):
        for broken in (
            (ENVELOPE_PREFIX + "not@@base64@@\n" + EXIT_SENTINEL + "0\n").encode(),
            (ENVELOPE_PREFIX + base64.b64encode(b"\xff\xfe").decode("ascii")
             + "\n" + EXIT_SENTINEL + "0\n").encode(),
        ):
            termination, exit_code, output = parse_transcript(broken)
            self.assertEqual((termination, exit_code, output), ("bad_reply", 0, b""))

    def test_missing_sentinel_is_no_reply_not_success(self):
        termination, exit_code, output = parse_transcript(b"partial output\n")
        self.assertEqual((termination, exit_code), ("no_reply", None))
        self.assertEqual(output, b"partial output")

    def test_marker_with_a_non_numeric_value_is_not_read_as_an_answer(self):
        """The three observations are distinct and none of them invents a code.

        No marker at all is a console that never answered; a marker whose value
        is empty is a complete answer with an unobserved code (see the parsing
        test below); a marker line that is neither is not a transcript we can
        trust, so it keeps its bytes and reports no exit code.
        """
        raw = ("x\n" + EXIT_SENTINEL + "$LASTEXITCODE\n").encode("utf-8")
        termination, exit_code, output = parse_transcript(raw)
        self.assertEqual((termination, exit_code), ("no_reply", None))
        self.assertIn(EXIT_SENTINEL.encode(), output)

    def test_empty_transcript_is_no_reply(self):
        self.assertEqual(parse_transcript(b""), ("no_reply", None, b""))


class CommandPortTests(unittest.TestCase):
    def test_command_runs_through_the_official_client_with_the_sentinel(self):
        calls = []
        port = _port(_Completed(0, _transcript("ok\r\n")), calls=calls)
        outcome = port.run_command(node_ref=NODE, command="hostname.exe", timeout_seconds=45)
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.output, b"ok\r\n")

        argv, kwargs = calls[0]
        self.assertIn("runcommand", argv)
        self.assertIn("--powershell", argv)
        self.assertIn("--reply", argv)
        self.assertEqual(argv[argv.index("--id") + 1], NODE)
        run_arg = argv[argv.index("--run") + 1]
        # The command reaches the PC as written, and the answer it is asked to
        # print is wrapped in the envelope with the exit sentinel.
        self.assertEqual(_inner(run_arg), "hostname.exe")
        self.assertIn(ENVELOPE_PREFIX, run_arg)
        self.assertIn(EXIT_SENTINEL, run_arg)
        self.assertIn("[Console]::OutputEncoding=[Text.Encoding]::UTF8", run_arg)
        # The operator credential never reaches the OS command line.
        self.assertNotIn(PASSWORD, argv)
        self.assertEqual(argv[argv.index("--loginpass") + 1],
                         "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__")
        self.assertEqual(kwargs["input"], PASSWORD + "\n")
        self.assertEqual(kwargs["timeout"], 45)

    def test_long_and_unbounded_command_deadlines_are_accepted(self):
        # #5895: the 60s default and 300s ceiling are gone. A ten-minute command
        # is accepted as written, and None carries no PADIEM client deadline (the
        # desktop-lane default), so a long-running job is never refused for time.
        for value in (600, None):
            calls = []
            port = _port(_Completed(0, _transcript("ok\r\n")), calls=calls)
            outcome = port.run_command(node_ref=NODE, command="long_running.exe", timeout_seconds=value)
            self.assertEqual(outcome.termination, "exited", value)
            self.assertEqual(calls[0][1]["timeout"], value)

    def test_timeout_claims_no_exit_code(self):
        expired = subprocess.TimeoutExpired(cmd="node", timeout=45, output=b"")
        port = _port(exc=expired)
        outcome = port.run_command(node_ref=NODE, command="hostname.exe", timeout_seconds=45)
        self.assertEqual(outcome.termination, "timed_out")
        self.assertIsNone(outcome.exit_code)

    def test_streaming_timeout_kills_the_child_and_claims_nothing(self):
        class _Proc:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.killed = False

            def poll(self):
                return None

            def kill(self):
                self.killed = True
                self.stdout = io.BytesIO(b"done")

        port = MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=lambda argv, **kw: _Proc(),
        )
        outcome = port.run_command(node_ref=NODE, command="hostname.exe", timeout_seconds=1)
        self.assertEqual(outcome.termination, "timed_out")
        self.assertIsNone(outcome.exit_code)

    def test_phase_observer_sees_spawn_and_reply_without_payload(self):
        phases = []
        port = _port(_Completed(0, ("ok\n" + EXIT_SENTINEL + "0\n\n").encode()))
        port.run_command(
            node_ref=NODE, command="hostname.exe", timeout_seconds=45,
            phase_observer=phases.append,
        )
        self.assertEqual(phases, ["spawn", "reply"])

    def test_streaming_timeout_phase_is_reported(self):
        phases = []

        class _Proc:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()

            def poll(self):
                return None

            def kill(self):
                return None

        port = MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=lambda argv, **kw: _Proc(),
        )
        outcome = port.run_command(
            node_ref=NODE, command="hostname.exe", timeout_seconds=1,
            phase_observer=phases.append,
        )
        self.assertEqual(outcome.termination, "timed_out")
        self.assertEqual(phases, ["spawn", "timeout"])

    def test_client_failure_is_no_reply(self):
        port = _port(_Completed(1, b""))
        outcome = port.run_command(node_ref=NODE, command="hostname.exe", timeout_seconds=45)
        self.assertEqual(outcome.termination, "no_reply")
        self.assertIsNone(outcome.exit_code)

    def test_non_utf8_output_is_refused_not_altered(self):
        port = _port(_Completed(0, b"\xff\xfe" + EXIT_SENTINEL.encode() + b"0\n\n"))
        with self.assertRaises(MeshCentralCommandRefused):
            port.run_command(node_ref=NODE, command="hostname.exe", timeout_seconds=45)

    def test_command_accepts_utf8_and_several_lines(self):
        calls = []
        port = _port(_Completed(0, _transcript("ok\n")), calls=calls)
        korean_path = 'type "C:\\사용자\\보고서.txt"'
        outcome = port.run_command(node_ref=NODE, command=korean_path, timeout_seconds=45)
        self.assertEqual((outcome.termination, outcome.exit_code), ("exited", 0))
        run_arg = calls[0][0][calls[0][0].index("--run") + 1]
        # Korean is ordinary command text: it reaches the PC unchanged.
        self.assertEqual(_inner(run_arg), korean_path)
        # A multi-line command keeps its newlines and still gets the envelope.
        multi = "echo one\necho two"
        port = _port(_Completed(0, _transcript("one\ntwo\n")))
        outcome = port.run_command(node_ref=NODE, command=multi, timeout_seconds=45)
        self.assertEqual((outcome.termination, outcome.exit_code), ("exited", 0))
        self.assertEqual(outcome.output, b"one\ntwo\n")

    def test_command_refuses_nul_and_carriage_return_only(self):
        port = _port(_Completed(0, b""))
        # Only what breaks the transport is refused. A long command used to be
        # rejected here by a trial character cap; ordinary text of any length is
        # input, and the OS exec boundary has its own named guard below.
        for bad in ("", "a\x00b", "a\rb"):
            with self.assertRaises(MeshCentralCommandRefused):
                port.run_command(node_ref=NODE, command=bad, timeout_seconds=45)

    def test_long_multiline_utf8_command_reaches_the_client_verbatim(self):
        calls = []
        port = _port(
            _Completed(0, _transcript("ok\n")), calls=calls,
        )
        command = "Write-Output '보고서'\n" + ("Get-Item 'C:\\temp\\a.txt'\n" * 4000)
        port.run_command(node_ref=NODE, command=command, timeout_seconds=45)
        argv = calls[0][0]
        sent = argv[argv.index("--run") + 1]
        # Only the trailing whitespace is dropped (so the appended envelope and
        # sentinel statements cannot be swallowed by an unterminated line); every
        # interior line of the script travels to the client unchanged.
        expected = command.rstrip(" \t\r\n")
        self.assertEqual(_inner(sent), expected)
        self.assertIn(EXIT_SENTINEL, sent)

    def test_command_over_the_os_argument_limit_is_refused_by_name(self):
        calls = []
        port = _port(_Completed(0, b""), calls=calls)
        # Linux caps one argv element at MAX_ARG_STRLEN = PAGE_SIZE * 32 =
        # 131,072 bytes including its NUL terminator. The wrapped command
        # (command + stream merge + exit sentinel) is what travels as one
        # argument, so the refusal names that boundary instead of letting
        # execve fail as an opaque E2BIG.
        with self.assertRaises(MeshCentralCommandRefused) as caught:
            port.run_command(node_ref=NODE, command="x" * 131_072, timeout_seconds=45)
        self.assertIn("argument", str(caught.exception))
        self.assertEqual(calls, [])

    def test_command_far_above_the_old_trial_cap_still_runs(self):
        calls = []
        port = _port(
            _Completed(0, _transcript("done\n")), calls=calls,
        )
        outcome = port.run_command(
            node_ref=NODE, command="Get-Content 'C:\\a.txt'\n" * 5_000,
            timeout_seconds=45,
        )
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(len(calls), 1)

    def test_sentinel_without_a_code_is_not_called_a_silent_console(self):
        """`$LASTEXITCODE` is only set for a native program or script.

        A cmdlet-only pipeline answers completely and reports no number, which
        is a different observation from a console that never answered, and is
        never a 0.
        """
        transcript = _transcript("line one\nline two\n", code="")
        termination, code, output = parse_transcript(transcript)
        self.assertEqual((termination, code), ("no_exit_code", None))
        self.assertEqual(output, b"line one\nline two\n")
        # The genuinely silent case still says so.
        silent = parse_transcript(b"line one\nline two\n")
        self.assertEqual((silent[0], silent[1]), ("no_reply", None))

    def test_executor_passes_the_unobserved_code_through_unchanged(self):
        """The executor neither invents a code nor calls the answer silent."""
        from kagent.local_agent_meshcentral_command_port import (
            MeshCentralCommandOutcome,
        )

        port = _FakeCommandPort(MeshCentralCommandOutcome(
            termination="no_exit_code", exit_code=None, output=b"full answer\n",
        ))
        outcome = _executor(command_port=port, read_port=_ReadPort()).execute(
            _dispatch(command="Get-Date")
        )
        self.assertEqual(
            (outcome.termination, outcome.exit_code, outcome.body),
            ("no_exit_code", None, b"full answer\n"),
        )

    def test_a_command_refused_before_the_pc_is_not_a_silent_console(self):
        from kagent.local_agent_meshcentral_command_port import (
            MeshCentralCommandOutcome,
        )

        class _RefusingPort:
            def run_command(self, *, node_ref, command, timeout_seconds, phase_observer=None,
                    cancel_probe=None, dispatch_id=None, keep_dispatch_ids=(),
                    line_guard=None):
                raise MeshCentralCommandRefused(
                    "the wrapped command exceeds the OS single-argument limit"
                )

        outcome = _executor(command_port=_RefusingPort(), read_port=_ReadPort()).execute(
            _dispatch(command="x" * 200)
        )
        self.assertEqual((outcome.termination, outcome.exit_code), ("not_executed", None))
        self.assertEqual(outcome.body, b"")

    def test_missing_credential_never_runs_the_client(self):
        calls = []
        port = _port(_Completed(0, b""), calls=calls, password="")
        with self.assertRaises(MeshCentralCommandRefused):
            port.run_command(node_ref=NODE, command="hostname.exe", timeout_seconds=45)
        self.assertEqual(calls, [])


class _FakeCommandPort:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = []

    def run_command(self, *, node_ref, command, timeout_seconds, phase_observer=None,
                    cancel_probe=None, dispatch_id=None, keep_dispatch_ids=(),
                    line_guard=None):
        self.calls.append((node_ref, command, timeout_seconds))
        return self._outcome


class _ReadPort:
    def __init__(self):
        self.calls = []

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):
        self.calls.append((node_ref, file_path, timeout_seconds))
        return b"file-bytes"


def _executor(command_port=None, read_port=None):
    return OracleMeshExecutor(
        chat_origin="https://chat.padiem.net",
        channel_secret=SECRET,
        read_port=read_port or _ReadPort(),
        command_port=command_port,
        transport=lambda path, payload: (200, {"ok": True}),
    )


def _dispatch(kind="command", command="hostname.exe", request_id="oracle_mesh_req_test"):
    return OracleMeshDispatch(
        dispatch_id="dsp-1", nonce="n" * 32, node_ref=NODE,
        file_path="command" if kind == "command" else "C:\\x.txt",
        command_id="c", run_id="run-1", request_id=request_id, kind=kind,
        command_text=command if kind == "command" else None,
    )


class ExecutorRoutingTests(unittest.TestCase):
    def test_command_dispatch_uses_the_command_port_only(self):
        from kagent.local_agent_meshcentral_command_port import MeshCentralCommandOutcome
        command_port = _FakeCommandPort(
            MeshCentralCommandOutcome(termination="exited", exit_code=0,
                                      output=b"Padiem-Command-Center\r\n"))
        read_port = _ReadPort()
        executor = _executor(command_port=command_port, read_port=read_port)
        outcome = executor.execute(_dispatch())
        self.assertEqual((outcome.termination, outcome.exit_code), ("exited", 0))
        self.assertEqual(outcome.body, b"Padiem-Command-Center\r\n")
        self.assertEqual(read_port.calls, [])
        self.assertEqual(command_port.calls[0][1], "hostname.exe")

    def test_poll_retains_the_server_request_id_for_trace_correlation(self):
        def transport(path, payload):
            return 200, {"ok": True, "dispatch": {
                "dispatch_id": "dsp-1", "nonce": "n", "node_ref": NODE,
                "file_path": "command", "command_id": "c", "run_id": "run-1",
                "request_id": "oracle_mesh_req_trace", "kind": "command",
                "command_text": "hostname.exe",
            }}

        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_ReadPort(),
            command_port=_FakeCommandPort(None),
            transport=transport,
        )
        dispatch = executor.poll_once()
        self.assertEqual(dispatch.request_id, "oracle_mesh_req_trace")

    def test_command_phase_log_has_ids_and_no_payload(self):
        from kagent.local_agent_meshcentral_command_port import MeshCentralCommandOutcome

        command = "DO_NOT_LOG_THIS_COMMAND_5015"
        port = _FakeCommandPort(MeshCentralCommandOutcome(
            termination="exited", exit_code=0, output=b"visible only in memory",
        ))
        output = io.StringIO()
        with redirect_stderr(output):
            _executor(command_port=port).execute(_dispatch(command=command))
        log = output.getvalue()
        self.assertIn("phase=start", log)
        self.assertIn("phase=result", log)
        self.assertIn("request_id=oracle_mesh_req_test", log)
        self.assertIn("command_id=c", log)
        self.assertNotIn(command, log)
        self.assertNotIn("visible only in memory", log)
    def test_timeout_phase_and_result_keep_the_same_ids(self):
        from kagent.local_agent_meshcentral_command_port import MeshCentralCommandOutcome

        port = _FakeCommandPort(MeshCentralCommandOutcome(
            termination="timed_out", exit_code=None, output=b"",
        ))
        output = io.StringIO()
        with redirect_stderr(output):
            outcome = _executor(command_port=port).execute(_dispatch())
        self.assertEqual(outcome.termination, "timed_out")
        log = output.getvalue()
        self.assertIn("phase=start", log)
        self.assertIn("phase=result", log)
        self.assertIn("termination=timed_out", log)
        self.assertIn("request_id=oracle_mesh_req_test", log)
        self.assertIn("command_id=c", log)
    def test_submit_phase_keeps_the_same_ids_without_payload(self):
        from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutionOutcome

        port = _FakeCommandPort(None)
        executor = _executor(command_port=port)
        dispatch = _dispatch()
        output = io.StringIO()
        with redirect_stderr(output):
            executor.submit(
                dispatch,
                OracleMeshExecutionOutcome(
                    termination="exited", exit_code=0,
                    body=b"secret-submit-body",
                ),
            )
        log = output.getvalue()
        self.assertIn("phase=submit", log)
        self.assertIn("phase=submit_ok", log)
        self.assertIn("request_id=oracle_mesh_req_test", log)
        self.assertIn("command_id=c", log)
        self.assertNotIn("secret-submit-body", log)

    def test_logging_failure_never_changes_the_command_outcome(self):
        from kagent.local_agent_meshcentral_command_port import MeshCentralCommandOutcome

        port = _FakeCommandPort(MeshCentralCommandOutcome(
            termination="exited", exit_code=0, output=b"result",
        ))
        executor = _executor(command_port=port)
        with patch("builtins.print", side_effect=OSError("stderr closed")):
            outcome = executor.execute(_dispatch())
        self.assertEqual((outcome.termination, outcome.exit_code, outcome.body),
                         ("exited", 0, b"result"))
    def test_read_dispatch_is_unchanged(self):
        from kagent.local_agent_meshcentral_command_port import MeshCentralCommandOutcome
        command_port = _FakeCommandPort(
            MeshCentralCommandOutcome(termination="exited", exit_code=0, output=b"x"))
        read_port = _ReadPort()
        executor = _executor(command_port=command_port, read_port=read_port)
        outcome = executor.execute(_dispatch(kind="read"))
        self.assertEqual(outcome.body, b"file-bytes")
        self.assertEqual(command_port.calls, [])

    def test_unobserved_exit_code_is_never_flipped_to_zero(self):
        from kagent.local_agent_meshcentral_command_port import MeshCentralCommandOutcome
        command_port = _FakeCommandPort(
            MeshCentralCommandOutcome(termination="exited", exit_code=None, output=b"x"))
        executor = _executor(command_port=command_port)
        outcome = executor.execute(_dispatch())
        self.assertEqual(outcome.termination, "no_reply")
        self.assertIsNone(outcome.exit_code)

    def test_command_dispatch_without_a_port_is_a_hard_refusal(self):
        executor = _executor(command_port=None)
        with self.assertRaises(OracleMeshChannelRefused):
            executor.execute(_dispatch())

    def test_poll_refuses_a_command_dispatch_without_a_command(self):
        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_ReadPort(),
            command_port=_FakeCommandPort(None),
            transport=lambda path, payload: (200, {"ok": True, "dispatch": {
                "dispatch_id": "dsp-1", "nonce": "n", "node_ref": NODE,
                "file_path": "command", "command_id": "c", "run_id": "run-1",
                "kind": "command", "command_text": None,
            }}),
        )
        with self.assertRaises(OracleMeshChannelRefused):
            executor.poll_once()

    def test_submit_carries_an_unobserved_exit_code_as_null(self):
        seen = {}

        def transport(path, payload):
            seen.update(payload or {})
            return 200, {"ok": True}

        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_ReadPort(),
            command_port=_FakeCommandPort(None),
            transport=transport,
        )
        executor.submit(_dispatch(), _outcome())
        self.assertIsNone(seen["exit_code"])
        self.assertEqual(seen["termination"], "no_reply")


def _outcome():
    from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutionOutcome
    return OracleMeshExecutionOutcome(termination="no_reply", exit_code=None, body=b"")


if __name__ == "__main__":
    unittest.main()


class TestTheOwnerStopReachesARunningCommand(unittest.TestCase):
    """#5895: the owner's 그만 has to end a command the executor already holds.

    #5995 took the client deadline away, and a PC that never answers would otherwise
    keep that command - and every operation queued behind it on a single-console agent -
    open forever. The stop is read from the server's own record, and the only effect is
    that this host stops waiting and ends its own client.
    """

    @staticmethod
    def _streaming_port(proc, **kwargs):
        return MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=lambda argv, **kw: proc,
        )

    def test_the_stop_kills_the_child_and_claims_no_console_answer(self):
        class _Proc:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(_transcript("the pc never finished\n"))
                self.stderr = io.BytesIO()
                self.killed = False

            def poll(self):
                return None

            def kill(self):
                self.killed = True

        proc = _Proc()
        phases = []
        outcome = self._streaming_port(proc).run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            phase_observer=phases.append, cancel_probe=lambda: True,
        )
        self.assertEqual(outcome.termination, "cancelled")
        self.assertIsNone(outcome.exit_code)
        self.assertEqual(outcome.output, b"")
        self.assertTrue(proc.killed)
        self.assertEqual(phases, ["spawn", "cancel"])

    def test_a_stop_that_cannot_be_read_is_never_treated_as_a_stop(self):
        class _Proc:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(_transcript("done\n", "0"))
                self.stderr = io.BytesIO()
                self.killed = False

            def poll(self):
                return 0

            def kill(self):
                self.killed = True

        proc = _Proc()
        asked = []

        def probe():
            asked.append(1)
            raise RuntimeError("the channel is down")

        outcome = self._streaming_port(proc).run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            cancel_probe=probe,
        )
        self.assertNotEqual(outcome.termination, "cancelled")
        self.assertFalse(proc.killed)
        self.assertEqual(asked, [])

    def test_a_probe_that_is_not_callable_is_refused_before_the_pc_is_asked(self):
        from kagent.contracts import ContractError

        port = _port(_Completed(0, _transcript("x\n")))
        with self.assertRaises(ContractError):
            port.run_command(node_ref=NODE, command="hostname.exe",
                             timeout_seconds=5, cancel_probe="yes")


class TestTheExecutorProbesTheChannel(unittest.TestCase):
    def test_the_executor_asks_about_the_dispatch_it_holds_and_reports_the_stop(self):
        from kagent.local_agent_meshcentral_command_port import (
            MeshCentralCommandOutcome,
        )

        class _CancellingPort:
            def __init__(self):
                self.answer = None

            def run_command(self, *, node_ref, command, timeout_seconds,
                            phase_observer=None, cancel_probe=None, dispatch_id=None,
                            keep_dispatch_ids=(), line_guard=None):
                self.answer = cancel_probe() if cancel_probe is not None else None
                return MeshCentralCommandOutcome(
                    termination="cancelled", exit_code=None, output=b"",
                )

        calls = []

        def transport(path, payload):
            calls.append((path, payload))
            return 200, {"ok": True, "cancelled": payload == {"dispatch_id": "dsp-1"}}

        port = _CancellingPort()
        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net", channel_secret=SECRET,
            read_port=_ReadPort(), command_port=port, transport=transport,
        )
        outcome = executor.execute(_dispatch(command="Get-ChildItem C:/x"))
        self.assertIs(port.answer, True)
        self.assertEqual(outcome.termination, "cancelled")
        self.assertEqual(calls[0][0], "/api/claw/connector/mesh-reads/cancel")
        self.assertEqual(calls[0][1], {"dispatch_id": "dsp-1"})

    def test_a_channel_that_does_not_answer_yes_leaves_the_command_running(self):
        from kagent.local_agent_meshcentral_command_port import (
            MeshCentralCommandOutcome,
        )

        class _ProbingPort:
            def __init__(self, transport):
                self.answer = None
                self._transport = transport

            def run_command(self, *, node_ref, command, timeout_seconds,
                            phase_observer=None, cancel_probe=None, dispatch_id=None,
                            keep_dispatch_ids=(), line_guard=None):
                self.answer = cancel_probe()
                return MeshCentralCommandOutcome(
                    termination="no_reply", exit_code=None, output=b"",
                )

        for status, body in ((503, {}), (200, {"ok": True}), (200, {"cancelled": "yes"})):
            def transport(path, payload, status=status, body=body):
                raise OracleMeshChannelRefused("down") if status == 503 else (status, body)

            port = _ProbingPort(transport)
            executor = OracleMeshExecutor(
                chat_origin="https://chat.padiem.net", channel_secret=SECRET,
                read_port=_ReadPort(), command_port=port, transport=transport,
            )
            outcome = executor.execute(_dispatch(command="Get-ChildItem C:/x"))
            self.assertIs(port.answer, False, (status, body))
            self.assertEqual(outcome.termination, "no_reply", (status, body))


class TestTheOwnerStopEndsThePcProcess(unittest.TestCase):
    """#5895: a stop has to reach the customer's machine, not just this host.

    Ending the client released the executor but left the PC's own PowerShell
    running behind a console queue that serves one task at a time - measured on
    2026-10-28, every later operation on that PC waited for the abandoned command
    until a person killed it. The agent's terminal session is the one channel that
    kept working while that queue was wedged, so the stop travels over it, aimed
    only at the pid the command itself left behind.
    """

    MARKED = "dsp_" + "a" * 32

    def test_a_running_command_leaves_its_own_marker_and_clears_it(self):
        wrapped = _wrap("Get-ChildItem C:/x", self.MARKED)
        self.assertIn("[IO.Path]::GetTempPath()+'padiem-dispatch-" + self.MARKED + ".pid'", wrapped)
        self.assertIn("Set-Content -LiteralPath $__padiem_pidfile -Value $PID", wrapped)
        self.assertIn("Remove-Item -LiteralPath $__padiem_pidfile", wrapped)
        self.assertNotIn("\n", wrapped)
        # Without a dispatch id the script is the bytes it always was.
        self.assertNotIn("padiem-dispatch", _wrap("Get-ChildItem C:/x"))

    def test_a_name_that_is_not_a_dispatch_id_is_refused_before_anyone_is_asked(self):
        for bad in ("", "not-a-dispatch", "dsp_ZZZ", "dsp_" + "a" * 32 + "';Remove-Item C:" + chr(92) + "*"):
            with self.assertRaises(MeshCentralCommandRefused):
                cancel_kill_command(bad)
            with self.assertRaises(MeshCentralCommandRefused):
                _wrap("Get-ChildItem C:/x", bad)

    def test_the_stop_targets_one_pid_and_names_no_image_or_service(self):
        script = cancel_kill_command(self.MARKED)
        self.assertIn("taskkill /T /F /PID", script)
        self.assertIn("padiem-dispatch-" + self.MARKED + ".pid", script)
        # /IM would kill every PowerShell on the PC; a service name would reach the
        # agent itself. Neither is what the owner stopped.
        for forbidden in ("/IM", "Mesh Agent", "Stop-Process", "Get-Process", "taskkill /F /IM"):
            self.assertNotIn(forbidden, script)

    def test_the_stop_travels_the_terminal_channel_and_is_bounded(self):
        class _RunChild:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.killed = False

            def poll(self):
                return None

            def kill(self):
                self.killed = True

        seen = {"run": [], "stop": []}

        def popen(argv, **kwargs):
            bucket = seen["stop"] if "shell" in argv else seen["run"]
            child = _RunChild()
            bucket.append((list(argv), dict(kwargs), child))
            return child

        handoffs = []

        def pty_factory(payload):
            class _Handoff:
                slave = 77

                def __init__(self, data):
                    self.data = data
                    self.waits = []

                def wait_closed(self, seconds):
                    self.waits.append(seconds)

                def wait_for(self, done, seconds):
                    # The probe asks; this double answers nothing, which the port
                    # reports as an unobserved console rather than a clean one.
                    self.waits.append(seconds)
                    return b""

            handoffs.append(_Handoff(payload))
            return handoffs[-1]

        port = MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=popen, pty_factory=pty_factory,
        )
        phases = []
        outcome = port.run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            phase_observer=phases.append, cancel_probe=lambda: True,
            dispatch_id=self.MARKED,
        )

        self.assertEqual(outcome.termination, "cancelled")
        self.assertIsNone(outcome.exit_code)
        self.assertTrue(seen["run"][0][2].killed, "this host stops waiting")
        # One terminal session for this command: this stop. The #6106 console look is
        # opt-in since 2026-10-29 (its channel echoed input without executing it), so a
        # default command opens none — and only the stop carries the kill.
        stops = [h for h in handoffs if b"taskkill /T /F /PID $__padiem_kill" in h.data]
        probes = [h for h in handoffs if b"Get-CimInstance" in h.data]
        self.assertEqual(len(stops), 1, "one stop session, not a queue of them")
        self.assertEqual(probes, [], "no console look unless the probe is asked for")
        stop_index = handoffs.index(stops[0])
        argv, kwargs, stop_child = seen["stop"][stop_index]
        self.assertIn("shell", argv)
        self.assertIn("--powershell", argv)
        self.assertIn(self.MARKED, stops[0].data.decode("utf-8"))
        self.assertEqual(handoffs[0].data.decode("utf-8").splitlines()[0], PASSWORD,
                         "the credential still never enters argv")
        self.assertEqual(stops[0].waits, [15], "the stop is bounded")
        self.assertIsNone(stop_child.poll())
        self.assertIn("cancel_kill", phases)

    def test_a_stop_that_cannot_reach_the_pc_is_reported_and_still_releases_the_lane(self):
        class _RefusingPty:
            slave = 77

            def __init__(self, payload):
                raise OSError("no terminal device available")

        port = MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=lambda argv, **kw: _NeverChild(), pty_factory=lambda payload: _RefusingPty(payload),
        )
        phases = []
        outcome = port.run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            phase_observer=phases.append, cancel_probe=lambda: True,
            dispatch_id=self.MARKED,
        )
        self.assertEqual(outcome.termination, "cancelled")
        self.assertIn("cancel_kill_refused", phases)


class _NeverChild:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.killed = False

    def poll(self):
        return None

    def kill(self):
        self.killed = True
