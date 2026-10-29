"""#82 — a dispatch on its own terminal session, behind a flag that ships off.

The agent serves one `runcommand` child and drops later requests as "already busy",
so one long command holds every later one on that PC. The terminal tunnels are a
separate lane with no per-node cap. This file holds the four things the owner asked
for: a short command does not wait behind a long one, a cancel ends that session's own
PC process tree, a session that never opens falls back to the existing path, and with
the flag off nothing about today's behaviour changes.
"""
from __future__ import annotations

import base64
import io
import threading
import time
import unittest
from unittest import mock

from kagent import local_agent_meshcentral_command_port as port_module
from kagent.local_agent_meshcentral_command_port import (
    ENVELOPE_PREFIX, EXIT_SENTINEL, MeshCentralCliCommandPort,
)

NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
MESHCTRL = "/opt/meshcentral/meshctrl.js"
PASSWORD = "op3rator-meshtr0ll-secret"
OURS = "dsp_" + "a" * 32


def _frame(body: str = "ok", code: str = "0") -> bytes:
    return (ENVELOPE_PREFIX + base64.b64encode(body.encode()).decode("ascii")
            + "\n" + EXIT_SENTINEL + code + "\n").encode("ascii")


class _Handoff:
    """A terminal that yields the scripted reads, and can be held open by a test."""

    slave = 77

    def __init__(self, payload, chunks, *, hold=None):
        self.payload = payload
        self._chunks = list(chunks)
        self._hold = hold
        self.closed = False
        self.reads = 0

    def read(self, timeout):
        self.reads += 1
        if self._hold is not None and not self._hold.is_set():
            time.sleep(0.01)
            return b""
        if self._chunks:
            return self._chunks.pop(0)
        time.sleep(0.01)
        return b""

    def wait_for(self, done, seconds):  # pragma: no cover - not used by this lane
        return b""

    def wait_closed(self, seconds):  # pragma: no cover
        return None

    def release_slave(self):
        self.slaves_released = True

    def close(self):
        self.closed = True


class _Once:
    """A stdout that yields one transcript and then reports that it is done."""

    def __init__(self, transcript):
        self._transcript = transcript
        self.done = False

    def fileno(self):
        raise OSError("not an OS pipe")

    def read(self, _size):
        if self.done:
            return b""
        self.done = True
        return self._transcript


class _RunChild:
    def __init__(self, transcript):
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO()
        self.stdout = _Once(transcript)
        self.killed = False

    def poll(self):
        return 0 if self.stdout.done else None

    def kill(self):
        self.killed = True


class _Child:
    def __init__(self, *, alive=True):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.killed = False
        self._alive = alive

    def poll(self):
        return None if self._alive and not self.killed else -9 if self.killed else 0

    def kill(self):
        self.killed = True


class _Harness:
    def __init__(self, *, sessions, run_result=None, pty_error=None, holds=None,
                 shell_alive=True):
        self.sessions = list(sessions)   # one chunk list per shell session
        self.handoffs = []
        self.shell_children = []
        self.run_children = []
        self._run_result = run_result
        self._pty_error = pty_error
        self._holds = list(holds) if holds else None
        self._shell_alive = shell_alive

    def pty(self, payload):
        if self._pty_error is not None:
            raise self._pty_error
        hold = None
        if self._holds is not None:
            hold = self._holds[len(self.handoffs)] if len(self._holds) > len(self.handoffs) else None
        chunks = self.sessions[len(self.handoffs)] if len(self.sessions) > len(self.handoffs) else []
        handoff = _Handoff(payload, chunks, hold=hold)
        self.handoffs.append(handoff)
        return handoff

    def popen(self, argv, **kwargs):
        if "shell" in argv:
            child = _Child(alive=self._shell_alive)
            self.shell_children.append((list(argv), child))
            return child
        raw = getattr(self._run_result, "stdout", b"") if self._run_result is not None else b""
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        child = _RunChild(raw or b"")
        self.run_children.append((list(argv), child))
        return child

    def port(self):
        return MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: self._run_result,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=self.popen, pty_factory=self.pty,
        )


class TestTheFlagShipsOff(unittest.TestCase):
    def test_the_default_is_the_existing_queue_lane(self) -> None:
        # No environment, no argument: the shipped behaviour is unchanged, and it is
        # asserted by the lane that ran a command through `runcommand` and no session.
        harness = _Harness(sessions=[], run_result=type(
            "C", (), {"returncode": 0, "stdout": _frame("ok"), "stderr": b""})())
        outcome = harness.port().run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            dispatch_id=OURS, session_lane=False,
        )
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(len(harness.run_children), 1, "the queue lane sent it")
        # No shell session at all: the #6106 pre-flight probe is opt-in since
        # 2026-10-29 (its channel echoed input without executing it), and the command
        # itself never ran on a session.
        self.assertEqual(harness.shell_children, [], "no probe and no session")

    def test_the_environment_turns_it_on_and_nothing_else_does(self) -> None:
        self.assertFalse(port_module._session_lane_enabled(None, {}))
        self.assertFalse(port_module._session_lane_enabled(None, {
            "PADIEM_MESH_SESSION_COMMAND_LANE": "0"}))
        for on in ("1", "true", "YES", "on"):
            self.assertTrue(port_module._session_lane_enabled(None, {
                "PADIEM_MESH_SESSION_COMMAND_LANE": on}), on)


class TestASessionCarriesTheCommand(unittest.TestCase):
    def test_the_echo_is_noise_and_the_envelope_is_the_answer(self) -> None:
        echoed = ('PS C:\\\\> Write-Output ("PADIEM_" + "B64=" + ...)'
                  ' / "__PADIEM_" + "EXIT__"\r\n').encode()
        harness = _Harness(sessions=[[echoed + _frame("4 lines", "0")]])
        outcome = harness.port().run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            dispatch_id=OURS, session_lane=True,
        )
        self.assertEqual((outcome.termination, outcome.exit_code), ("exited", 0))
        self.assertEqual(outcome.output, b"4 lines", "the prompt and echo are dropped")
        self.assertEqual(len(harness.shell_children), 1)
        self.assertEqual(harness.run_children, [], "nothing was sent on the queue")
        self.assertTrue(harness.handoffs[0].closed)

    def test_an_echo_without_a_frame_is_never_a_success(self) -> None:
        echoed = b'PS C:\\\\> Write-Output ("PADIEM_" + "B64=" + ...)\r\nPS C:\\\\> '
        # The session prints the echo and then closes without ever printing a frame.
        harness = _Harness(sessions=[[echoed]], shell_alive=False)
        outcome = harness.port().run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            dispatch_id=OURS, session_lane=True,
        )
        self.assertEqual(outcome.termination, "no_reply")
        self.assertIsNone(outcome.exit_code)


class TestAShortCommandDoesNotWaitBehindALongOne(unittest.TestCase):
    def test_the_second_session_finishes_while_the_first_still_runs(self) -> None:
        """The whole point of the lane: one PC, two dispatches, no shared queue."""

        hold = threading.Event()
        long_harness = _Harness(sessions=[[_frame("slow", "0")]], holds=[hold])
        short_harness = _Harness(sessions=[[_frame("fast", "0")]])
        long_outcome = {}

        def run_long() -> None:
            long_outcome["value"] = long_harness.port().run_command(
                node_ref=NODE, command="Start-Sleep 90", timeout_seconds=None,
                dispatch_id="dsp_" + "b" * 32, session_lane=True,
            )

        worker = threading.Thread(target=run_long, daemon=True)
        worker.start()
        time.sleep(0.05)
        started = time.monotonic()
        short = short_harness.port().run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            dispatch_id=OURS, session_lane=True,
        )
        elapsed = time.monotonic() - started
        self.assertEqual(short.output, b"fast")
        self.assertLess(elapsed, 2.0, "the short command did not wait for the long one")
        self.assertFalse(worker.is_alive() and long_outcome, "the long one is still running")
        hold.set()
        worker.join(timeout=5)
        self.assertEqual(long_outcome["value"].output, b"slow")


class TestCancelAndFallback(unittest.TestCase):
    def test_a_cancel_ends_that_sessions_own_pc_tree(self) -> None:
        harness = _Harness(sessions=[[]])
        port = harness.port()
        with mock.patch.object(port, "kill_command_process") as killer:
            outcome = port.run_command(
                node_ref=NODE, command="Start-Sleep 90", timeout_seconds=None,
                dispatch_id=OURS, session_lane=True, cancel_probe=lambda: True,
            )
        self.assertEqual(outcome.termination, "cancelled")
        killer.assert_called_once_with(node_ref=NODE, dispatch_id=OURS)
        self.assertTrue(harness.shell_children[0][1].killed)

    def test_a_session_that_cannot_open_falls_back_to_the_existing_lane(self) -> None:
        for failure in ("pty", "closed"):
            with self.subTest(failure=failure):
                harness = _Harness(
                    sessions=[[]],
                    run_result=type("C", (), {
                        "returncode": 0, "stdout": _frame("via queue"), "stderr": b""})(),
                    pty_error=OSError("no terminal device") if failure == "pty" else None,
                    shell_alive=False if failure == "closed" else True,
                )
                outcome = harness.port().run_command(
                    node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
                    dispatch_id=OURS, session_lane=True,
                )
                self.assertEqual(outcome.termination, "exited")
                self.assertEqual(outcome.output, b"via queue")
                self.assertEqual(len(harness.run_children), 1, "the old lane carried it")


class TestTheMeasuredShellFailure(unittest.TestCase):
    """Qoder's live measurement, 2026-10-29, on COM1's old agent, COM2's and CGI-1.

    ``meshctrl shell`` answered with exactly the bytes it was given — 71 for the plain
    line, 73 with a newline, 77 with ``; Exit`` appended — and never executed it. No
    token, no prompt, no error word: the reply length followed the input length. A
    transport that mirrors its input must never look like a command that ran.
    """

    #: The probe line as it was typed, and the mirror it came back as.
    PROBE_LINE = "Write-Output ('PDSHELL' + 'PROBE7')"

    def test_a_mirror_is_not_an_answer_on_the_session_lane(self) -> None:
        for suffix in ("", chr(10), "; Exit"):
            line = self.PROBE_LINE + suffix
            with self.subTest(suffix=suffix):
                harness = _Harness(sessions=[[line.encode()]], shell_alive=False)
                outcome = harness.port().run_command(
                    node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
                    dispatch_id=OURS, session_lane=True,
                )
                self.assertEqual(outcome.termination, "no_reply", line)
                self.assertIsNone(outcome.exit_code)
                self.assertEqual(outcome.output, b"", "the mirror is not the output")

    def test_a_mirror_never_reaches_a_caller_as_parsed_output(self) -> None:
        # The same bytes through the reply parser the queue lane uses: there is no
        # envelope and no sentinel in a mirror, so nothing is claimed about it.
        from kagent.local_agent_meshcentral_command_port import (
            _session_payload, parse_transcript,
        )
        for suffix in ("", chr(10), "; Exit"):
            raw = (self.PROBE_LINE + suffix).encode()
            # A mirror carries no envelope, so it is silence: no output is attributed
            # to a command that never ran, and the exit code stays unobserved.
            self.assertEqual(parse_transcript(_session_payload(raw)),
                             ("no_reply", None, b""), suffix)


if __name__ == "__main__":
    unittest.main()
