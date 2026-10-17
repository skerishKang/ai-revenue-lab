"""#4139 terminal lane — the Oracle command port and its exit-code contract.

The official ``meshctrl.js`` client is never actually launched here: the process
boundary is injected, so these tests pin the argv shape, the stdin credential,
and the exact transcript parsing that decides whether an exit code was observed.
"""
from __future__ import annotations

import io
import subprocess
import unittest

from kagent.local_agent_meshcentral_command_port import (
    EXIT_SENTINEL, MeshCentralCliCommandPort, MeshCentralCommandRefused,
    parse_transcript,
)
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshChannelRefused, OracleMeshDispatch, OracleMeshExecutor,
)

SECRET = "deployment-channel-secret-value-261017"
PASSWORD = "op3rator-meshtr0ll-secret"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
MESHCTRL = "/opt/meshcentral/meshctrl.js"


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
    def test_crlf_output_is_preserved_and_the_sentinel_is_removed(self):
        raw = ("Padiem-Command-Center\r\n" + EXIT_SENTINEL + "0\r\n\n").encode("utf-8")
        termination, exit_code, output = parse_transcript(raw)
        self.assertEqual(termination, "exited")
        self.assertEqual(exit_code, 0)
        # Only meshctrl's own trailing console.log newline is dropped.
        self.assertEqual(output, b"Padiem-Command-Center\r\n")

    def test_nonzero_exit_is_the_pc_value(self):
        raw = ("Access is denied.\r\n" + EXIT_SENTINEL + "5\r\n\n").encode("utf-8")
        termination, exit_code, output = parse_transcript(raw)
        self.assertEqual((termination, exit_code), ("exited", 5))
        self.assertEqual(output, b"Access is denied.\r\n")

    def test_missing_sentinel_is_no_reply_not_success(self):
        termination, exit_code, output = parse_transcript(b"partial output\n")
        self.assertEqual((termination, exit_code), ("no_reply", None))
        self.assertEqual(output, b"partial output")

    def test_sentinel_without_a_number_is_not_an_exit_code(self):
        raw = ("x\n" + EXIT_SENTINEL + "\n\n").encode("utf-8")
        termination, exit_code, _ = parse_transcript(raw)
        self.assertEqual((termination, exit_code), ("no_reply", None))

    def test_empty_transcript_is_no_reply(self):
        self.assertEqual(parse_transcript(b""), ("no_reply", None, b""))


class CommandPortTests(unittest.TestCase):
    def test_command_runs_through_the_official_client_with_the_sentinel(self):
        calls = []
        port = _port(_Completed(0, ("ok\r\n" + EXIT_SENTINEL + "0\r\n\n").encode()), calls=calls)
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
        self.assertTrue(run_arg.startswith("hostname.exe"))
        self.assertIn(EXIT_SENTINEL, run_arg)
        # The operator credential never reaches the OS command line.
        self.assertNotIn(PASSWORD, argv)
        self.assertEqual(argv[argv.index("--loginpass") + 1],
                         "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__")
        self.assertEqual(kwargs["input"], PASSWORD + "\n")
        self.assertEqual(kwargs["timeout"], 45)

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
        port = _port(_Completed(0, ("ok\n" + EXIT_SENTINEL + "0\n\n").encode()), calls=calls)
        korean_path = 'type "C:\\사용자\\보고서.txt"'
        outcome = port.run_command(node_ref=NODE, command=korean_path, timeout_seconds=45)
        self.assertEqual((outcome.termination, outcome.exit_code), ("exited", 0))
        run_arg = calls[0][0][calls[0][0].index("--run") + 1]
        self.assertTrue(run_arg.startswith(korean_path))
        # A multi-line command keeps its newlines and still gets the sentinel.
        multi = "echo one\necho two"
        port = _port(_Completed(0, ("one\ntwo\n" + EXIT_SENTINEL + "\n\n").encode()))
        outcome = port.run_command(node_ref=NODE, command=multi, timeout_seconds=45)
        self.assertEqual(outcome.termination, "no_reply")
        self.assertIsNone(outcome.exit_code)

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
            _Completed(0, ("ok\n" + EXIT_SENTINEL + "0\n").encode()), calls=calls,
        )
        command = "Write-Output '보고서'\n" + ("Get-Item 'C:\\temp\\a.txt'\n" * 4000)
        port.run_command(node_ref=NODE, command=command, timeout_seconds=45)
        argv = calls[0][0]
        sent = argv[argv.index("--run") + 1]
        # Only the trailing whitespace is dropped (so the appended sentinel
        # statement cannot be swallowed by an unterminated line); every
        # interior line of the script travels to the client unchanged.
        expected = command.rstrip(" \t\r\n")
        self.assertTrue(sent.startswith(expected))
        self.assertEqual(sent.count("\n"), expected.count("\n"))
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
            _Completed(0, ("done\n" + EXIT_SENTINEL + "0\n").encode()), calls=calls,
        )
        outcome = port.run_command(
            node_ref=NODE, command="Get-Content 'C:\\a.txt'\n" * 5_000,
            timeout_seconds=45,
        )
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(len(calls), 1)

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

    def run_command(self, *, node_ref, command, timeout_seconds):
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


def _dispatch(kind="command", command="hostname.exe"):
    return OracleMeshDispatch(
        dispatch_id="dsp-1", nonce="n" * 32, node_ref=NODE,
        file_path="command" if kind == "command" else "C:\\x.txt",
        command_id="c", run_id="run-1", kind=kind,
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
