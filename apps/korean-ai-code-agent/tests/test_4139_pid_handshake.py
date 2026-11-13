"""#4139 — the pid a queued PC command actually runs under.

The marker file name is not in the process command line: the agent feeds a queued
command to ``powershell -Command -`` on standard input, and ``-File`` carries only the
staged script path. These tests pin the replacement authority: the wrapper prints its
own ``$PID`` once, before the body, tagged with a per-run token; the reader keeps that
number and gives it to the stop.
"""
from __future__ import annotations

import json
import unittest

from kagent.local_agent_meshcentral_command_port import (
    ENVELOPE_PREFIX, EXIT_SENTINEL, MeshCentralCliCommandPort,
    _file_dispatch_console_script, _wrap,
)
from kagent.local_agent_meshcentral_pid_handshake import (
    PID_HANDSHAKE_PREFIX, parse_pid_handshake, pid_handshake_statement,
    strip_pid_handshake,
)
from kagent.local_agent_meshcentral_process_port import (
    BASIS_RECORDED_PID, BASIS_SCRIPT_MARKER, CONFIRMED, MeshCentralProcessLane,
)

DID = "dsp_" + "a" * 32
TOKEN = "0123456789abcdef"
NODE = "wYx8HR9Ou4C96Ys63@Dd2cdXxSOwp"


def _ps(rows):
    return {"action": "msg", "type": "ps", "nodeid": NODE, "value": json.dumps(rows)}


def _stopped(pid):
    return {"action": "msg", "type": "pskill", "nodeid": NODE, "value": str(pid) + "|x"}


class TheHandshakeLine(unittest.TestCase):
    def test_it_prints_this_wrappers_pid_and_flushes_it(self):
        line = pid_handshake_statement(TOKEN)
        self.assertIn(PID_HANDSHAKE_PREFIX + TOKEN + "=", line)
        self.assertIn("$PID", line)
        self.assertIn("[Console]::WriteLine", line)
        self.assertIn("[Console]::Out.Flush()", line)
        self.assertTrue(line.endswith(";"))

    def test_a_pid_is_read_once_and_the_line_does_not_become_output(self):
        line = PID_HANDSHAKE_PREFIX + TOKEN + "=4321"
        raw = ("terminal echo\r\n" + line + "\r\nuser output\r\n").encode("ascii")
        self.assertEqual(parse_pid_handshake(raw, TOKEN), 4321)
        stripped = strip_pid_handshake(raw, TOKEN)
        self.assertNotIn(line.encode("ascii"), stripped)
        self.assertIn(b"user output", stripped)
        self.assertIn(b"terminal echo", stripped)

    def test_the_echoed_script_is_not_an_answer(self):
        echo = ("[Console]::WriteLine('" + PID_HANDSHAKE_PREFIX + TOKEN
                + "=' + $PID); [Console]::Out.Flush();").encode("ascii")
        self.assertIsNone(parse_pid_handshake(echo, TOKEN))

    def test_a_partial_line_is_not_an_answer(self):
        line = (PID_HANDSHAKE_PREFIX + TOKEN + "=4321").encode("ascii")
        self.assertIsNone(parse_pid_handshake(line[:8], TOKEN))


class TheWrapperCarriesIt(unittest.TestCase):
    def test_the_queue_wrapper_prints_it_before_the_body(self):
        wrapped = _wrap("whoami", DID, pid_token=TOKEN)
        self.assertIn(pid_handshake_statement(TOKEN), wrapped)
        self.assertLess(wrapped.index(PID_HANDSHAKE_PREFIX), wrapped.index("whoami"))

    def test_the_file_wrapper_prints_it_before_the_marker(self):
        script = _file_dispatch_console_script(
            "whoami", DID, None, pid_token=TOKEN,
        )
        self.assertIn(pid_handshake_statement(TOKEN), script)
        self.assertLess(script.index(PID_HANDSHAKE_PREFIX), script.index("$__pp="))

    def test_a_wrapper_without_a_dispatch_has_no_handshake(self):
        self.assertNotIn(PID_HANDSHAKE_PREFIX, _wrap("whoami"))


class TheRecordedPidIsUsedWhenTheCommandLineHasNoMarker(unittest.TestCase):
    def test_a_queued_console_has_no_marker_but_its_recorded_pid_is_the_target(self):
        # The real shape: the agent's console is ``powershell -Command -`` and the
        # marker name lives only in the script on stdin, not in this command line.
        rows = {"4321": {"cmd": '"powershell.exe" -NoProfile -Command -', "pid": 4321}}
        answers = [_ps(rows), _stopped(4321), _ps({})]
        sent = []

        def ask(frame):
            sent.append(frame)
            return answers[len(sent) - 1]

        lane = MeshCentralProcessLane(node_ref=NODE, ask=ask, response_id="handshake-test")
        report = lane.stop(DID, 4321)
        self.assertEqual(report.verdict, CONFIRMED)
        self.assertEqual(report.basis, BASIS_RECORDED_PID)
        self.assertEqual(report.killed, (4321,))
        self.assertEqual(sent[1]["value"].split("|")[0], "4321")

    def test_a_staged_file_child_is_addressed_by_its_dispatch_path(self):
        # Local measurement: -File does not put the .pid name in the command line,
        # but it does carry the staged .ps1 path, which this connector wrote.
        rows = {
            "4321": {"cmd": '"powershell.exe" -NoProfile -Command -', "pid": 4321},
            "9876": {"cmd": '"powershell.exe" -File C:\\Temp\\padiem-dispatch-'
                             + DID + '.ps1', "pid": 9876},
        }
        answers = [_ps(rows), _stopped(4321), _stopped(9876), _ps({})]
        sent = []

        def ask(frame):
            sent.append(frame)
            return answers[len(sent) - 1]

        lane = MeshCentralProcessLane(node_ref=NODE, ask=ask, response_id="file-test")
        report = lane.stop(DID, 4321)
        self.assertEqual(report.verdict, CONFIRMED)
        self.assertEqual(report.basis, BASIS_RECORDED_PID)
        self.assertEqual(set(report.killed), {4321, 9876})

    def test_a_file_child_alone_is_still_a_target(self):
        rows = {
            "9876": {"cmd": '"powershell.exe" -File C:\\Temp\\padiem-dispatch-'
                             + DID + '.ps1', "pid": 9876},
        }
        answers = [_ps(rows), _stopped(9876), _ps({})]
        sent = []

        def ask(frame):
            sent.append(frame)
            return answers[len(sent) - 1]

        lane = MeshCentralProcessLane(node_ref=NODE, ask=ask, response_id="file-only")
        report = lane.stop(DID, 4321)
        self.assertEqual(report.verdict, CONFIRMED)
        self.assertEqual(report.basis, BASIS_SCRIPT_MARKER)
        self.assertEqual(report.killed, (9876,))

    def test_the_stop_plumbs_the_recorded_pid_to_the_kill(self):
        class Port(MeshCentralCliCommandPort):
            def __init__(self):
                self.seen = []

            def kill_command_process(self, **kwargs):
                self.seen.append(kwargs)

        port = Port()
        self.assertTrue(
            port._stop_on_pc(NODE, DID, lambda _name: None, recorded_pid=4321)
        )
        self.assertEqual(port.seen, [{
            "node_ref": NODE, "dispatch_id": DID, "recorded_pid": 4321,
        }])


class TheHandshakeIsStillTheSameEnvelope(unittest.TestCase):
    def test_a_handshake_does_not_change_the_tagged_envelope(self):
        # The handshake is a leading line; the result is still the tagged Base64 body
        # and its sentinel, so an old parser cannot mistake it for output.
        from kagent.local_agent_meshcentral_envelope import parse_transcript

        body = "ok\r\n"
        import base64
        raw = (
            PID_HANDSHAKE_PREFIX + TOKEN + "=4321\n"
            + ENVELOPE_PREFIX + DID + ":" + "b" * 16 + ":"
            + base64.b64encode(body.encode()).decode("ascii")
            + "\n" + EXIT_SENTINEL + "0\n"
        ).encode("ascii")
        termination, code, output = parse_transcript(raw, DID + ":" + "b" * 16)
        self.assertEqual((termination, code), ("exited", 0))
        self.assertEqual(output, body.encode())


if __name__ == "__main__":
    unittest.main()
