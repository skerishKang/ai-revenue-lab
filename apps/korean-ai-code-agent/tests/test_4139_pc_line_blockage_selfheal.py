r"""#4139 — a held PC console line clears itself, without anyone being asked.

The MeshCentral agent serves one console per PC, so a command that never finished
holds every later operation on that machine. Measured twice on the same device:
2026-10-28, a cancelled sweep whose PowerShell stayed behind; 2026-10-29, a
diagnostic shell a person opened that lived eleven hours. Both times a human ended
the process and restarted the agent service.

These tests pin the two rules the owner decision keeps apart:

* the wait for an ANSWER carries a deadline;
* the WORK on the PC never does.

They also pin the safety that makes the first rule survivable: a sweep that finds
the PC running real work ends nothing at all.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
import unittest
from unittest.mock import patch

from kagent import local_agent_meshcentral_command_port as port_module
from kagent.local_agent_meshcentral_command_port import (
    ENVELOPE_PREFIX, EXIT_SENTINEL, SWEEP_MODE_ABANDONED, SWEEP_MODE_HELD,
    SWEEP_SENTINEL, MeshCentralCliCommandPort, MeshCentralCommandRefused,
    MeshCentralCommandOutcome, _wrap, parse_sweep_reply, sweep_script,
)

NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
MESHCTRL = "/opt/meshcentral/meshctrl.js"
PASSWORD = "op3rator-meshtr0ll-secret"
OURS = "dsp_" + "a" * 32
OTHER = "dsp_" + "b" * 32

#: One read slice of the silent console, and the window these tests wait in. A
#: real slice is a second; shrinking both keeps the branch and costs no minutes.
SLICE_SECONDS = 0.005
STALL_SECONDS = 0.05

_TRANSCRIPT = (
    ENVELOPE_PREFIX + base64.b64encode(b"ok").decode("ascii")
    + "\n" + EXIT_SENTINEL + "0\n"
).encode("ascii")


def _frame(**fields) -> bytes:
    """One sweep answer, exactly as the PC prints it."""
    body = base64.b64encode(json.dumps(fields).encode("utf-8")).decode("ascii")
    return (SWEEP_SENTINEL + body + "\n").encode("ascii")


class _ConsoleChild:
    """The meshctrl client on this host: a console that answers at a stated time.

    ``answers_at`` is seconds from the child's birth, ``None`` never. A silent
    console is the case these tests are about, so the default is silence.
    """

    def __init__(self, answers_at=None):
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO()
        self.stdout = _ConsoleStream(self)
        self.answers_at = answers_at
        self.killed = False
        self.answered = False
        self.exit_code = None
        self._born = time.monotonic()

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed = True
        self.exit_code = -9


class _ConsoleStream:
    def __init__(self, child):
        self._child = child

    def fileno(self):
        raise OSError("not an OS pipe: a test double")

    def read(self, _size):
        child = self._child
        if child.answered:
            return b""
        time.sleep(SLICE_SECONDS)
        if child.answers_at is None:
            return b""
        if (time.monotonic() - child._born) < child.answers_at:
            return b""
        child.answered = True
        child.exit_code = 0
        return _TRANSCRIPT


class _Harness:
    """Every process boundary of one command, counted, with scripted console answers.

    ``sweep_answers`` and ``run_answers`` are consumed one session at a time and
    the last entry holds, so a test names what the PC reports about its own console
    without counting the read slices the port happens to need.
    """

    def __init__(self, sweep_answers=(), run_answers=(None,)):
        self._sweep_answers = list(sweep_answers) or [b""]
        self._run_answers = list(run_answers) or [None]
        self.sweeps = []
        self.runs = []

    def _next(self, scripted, index):
        return scripted[min(index, len(scripted) - 1)]

    def popen(self, argv, **kwargs):
        if "shell" in argv:
            session = self.sweeps[-1]
            session["argv"] = list(argv)
            session["child"] = _ConsoleChild()
            return session["child"]
        child = _ConsoleChild(self._next(self._run_answers, len(self.runs)))
        self.runs.append({"argv": list(argv), "kwargs": dict(kwargs), "child": child})
        return child

    def pty(self, payload_bytes):
        session = {
            "payload": payload_bytes, "argv": None, "kwargs": None, "child": None,
            "bound": None,
            "answer": self._next(self._sweep_answers, len(self.sweeps)),
        }
        self.sweeps.append(session)

        class _Handoff:
            slave = 77

            def wait_for(self, done, seconds):
                session["bound"] = seconds
                return session["answer"]

            def wait_closed(self, seconds):
                session["bound"] = seconds

        return _Handoff()

    def port(self):
        return MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=self.popen, pty_factory=self.pty,
        )

    def run(self, **call):
        call.setdefault("command", "Get-ChildItem C:/x")
        call.setdefault("timeout_seconds", None)
        call.setdefault("dispatch_id", OURS)
        phases = []
        outcome = self.port().run_command(
            node_ref=NODE, phase_observer=phases.append, **call,
        )
        return outcome, phases

    @property
    def sweep_scripts(self):
        return [session["payload"].decode("utf-8") for session in self.sweeps]


class TestALeaveBehindProcessIsClearedBeforeTheCommand(unittest.TestCase):
    """The owner's stop ends the client; this ends what the client left on the PC."""

    def test_the_scope_reads_the_console_the_agent_owns_and_names_no_image(self):
        script = sweep_script(dispatch_id=OURS, keep_dispatch_ids=(OTHER,))
        # /IM would end every PowerShell on the customer's machine, a service name
        # would reach the agent itself, and neither is what was abandoned.
        for forbidden in ("/IM", "Stop-Process", "Get-Process", "Restart-Service",
                          "Stop-Service", "meshcentral"):
            self.assertNotIn(forbidden, script)
        # Only a marker nobody owns is a target, and the marker goes with the tree
        # so the next sweep can never aim a recycled process id at a stranger.
        self.assertIn("$__padiem_orphan", script)
        self.assertIn("Remove-Item -LiteralPath $__padiem_o.file", script)
        self.assertNotIn("\n", script)
        self.assertLess(len(script), 8_192, "one console line, not a script file")
        # The wider scope is the one taken only after the answer window, and it is
        # still built from the parent this session is a child of - never a name.
        held = sweep_script(dispatch_id=OURS, mode=SWEEP_MODE_HELD)
        self.assertIn("ParentProcessId=$__padiem_agent", held)
        self.assertNotIn("ParentProcessId=$__padiem_agent", script)

    def test_the_in_progress_dispatches_are_protected_by_id(self):
        script = sweep_script(dispatch_id=OURS, keep_dispatch_ids=(OTHER,))
        self.assertIn("'" + OURS + "'", script)
        self.assertIn("'" + OTHER + "'", script)
        self.assertIn("$__padiem_safe", script)

    def test_the_command_is_sent_after_one_look_at_the_console(self):
        harness = _Harness(
            sweep_answers=(_frame(running=False, found=[], killed=[]),),
            run_answers=(0.0,),
        )
        outcome, phases = harness.run()
        self.assertEqual(len(harness.sweeps), 1, "one look at the console line")
        self.assertEqual(len(harness.runs), 1, "and one command")
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual((outcome.line_blocked, outcome.line_cleared), (0, 0))
        self.assertEqual(phases[0], "line_probe")

    def test_an_orphan_the_sweep_ended_is_counted_without_retrying_the_command(self):
        harness = _Harness(
            sweep_answers=(_frame(
                running=False,
                found=[{"pid": 4012, "name": "powershell.exe", "dispatch": OTHER}],
                killed=[4012],
            ),),
            run_answers=(0.0,),
        )
        outcome, phases = harness.run()
        self.assertEqual(outcome.line_blocked, 1)
        self.assertEqual(outcome.line_cleared, 1)
        self.assertEqual(outcome.termination, "exited", "the command ran once")
        self.assertEqual(len(harness.runs), 1, "clearing the line is not a retry")
        self.assertIn("line_cleared", phases)


class TestAWorkingPcIsNeverInterrupted(unittest.TestCase):
    """Standard rule 1: no ceiling on the work itself, ever."""

    def test_a_command_the_pc_reports_as_running_outruns_the_answer_window(self):
        harness = _Harness(
            sweep_answers=(_frame(running=True, found=[], killed=[]),),
            run_answers=(0.6,),
        )
        with patch.object(port_module, "LINE_STALL_WAIT_SECONDS", STALL_SECONDS):
            outcome, phases = harness.run()
        self.assertEqual(outcome.termination, "exited", "the wait outlasted the window")
        self.assertEqual(len(harness.runs), 1, "a running command is never re-sent")
        self.assertEqual(outcome.line_blocked, 0)
        self.assertEqual(outcome.line_cleared, 0)
        self.assertFalse(harness.runs[0]["child"].killed,
                         "and its client is never killed here")
        self.assertNotIn("line_stalled", phases)
        self.assertGreaterEqual(
            len(harness.sweeps), 2,
            "the PC was asked again after each window, and answered running every time",
        )


class TestASilentLineIsClearedAndTriedOnce(unittest.TestCase):
    """The communication deadline: nothing answered, and the PC says nothing was running."""

    def test_silence_past_the_window_clears_the_line_and_retries_once(self):
        harness = _Harness(
            sweep_answers=(
                _frame(running=False, found=[], killed=[]),
                _frame(running=False, found=[{"pid": 701, "name": "powershell.exe"}],
                       killed=[701]),
                _frame(running=False, found=[], killed=[]),
            ),
            run_answers=(None, 0.0),
        )
        with patch.object(port_module, "LINE_STALL_WAIT_SECONDS", STALL_SECONDS):
            outcome, phases = harness.run()
        self.assertEqual(len(harness.runs), 2, "one retry, not a queue of guesses")
        self.assertEqual(outcome.line_blocked, 1)
        self.assertEqual(outcome.line_cleared, 1)
        self.assertEqual(outcome.termination, "exited", "the retry got its answer")
        self.assertIn("line_stalled", phases)
        self.assertIn("line_retry", phases)

    def test_a_line_still_held_after_the_retry_is_reported_as_no_answer(self):
        harness = _Harness(
            sweep_answers=(_frame(running=False, found=[{"pid": 7}], killed=[7]),),
            run_answers=(None, None),
        )
        with patch.object(port_module, "LINE_STALL_WAIT_SECONDS", STALL_SECONDS):
            outcome, phases = harness.run()
        self.assertEqual(len(harness.runs), 2, "never a third attempt")
        self.assertEqual(outcome.termination, "no_reply", "and never a fake success")
        self.assertIsNone(outcome.exit_code)
        self.assertGreaterEqual(outcome.line_blocked, 1)

    def test_the_stall_sweep_uses_the_held_scope_and_the_first_uses_the_marker_scope(self):
        harness = _Harness(
            sweep_answers=(_frame(running=False), _frame(running=False, killed=[9])),
            run_answers=(None, None),
        )
        with patch.object(port_module, "LINE_STALL_WAIT_SECONDS", STALL_SECONDS):
            harness.run()
        self.assertIn(SWEEP_MODE_ABANDONED, harness.sweep_scripts[0])
        self.assertIn(SWEEP_MODE_HELD, harness.sweep_scripts[1])
        # The held scope is the wider one, and it is reached only after the window.
        self.assertIn("ParentProcessId=$__padiem_agent", harness.sweep_scripts[1])

    def test_a_sweep_that_cannot_be_read_reports_itself_instead_of_a_clean_console(self):
        harness = _Harness(
            sweep_answers=(b"",),
            run_answers=(0.0,),
        )
        outcome, phases = harness.run()
        self.assertEqual(outcome.line_blocked, 0, "an unreadable line is not a clear one")
        self.assertEqual(outcome.line_cleared, 0)
        self.assertIn("line_probe_unobserved", phases)
        self.assertEqual(len(harness.runs), 1, "and it never blocks the command")

    def test_a_terminal_channel_that_refuses_the_sweep_still_runs_the_command(self):
        refusing = MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=lambda argv, **kw: _ConsoleChild(
                0.0 if "runcommand" in argv else None
            ),
            pty_factory=lambda payload: (_ for _ in ()).throw(
                OSError("no terminal device available")
            ),
        )
        phases = []
        outcome = refusing.run_command(
            node_ref=NODE, command="Get-ChildItem C:/x", timeout_seconds=None,
            dispatch_id=OURS, phase_observer=phases.append,
        )
        self.assertIn("line_probe_refused", phases)
        self.assertEqual(outcome.termination, "exited", "the command was still sent")

    def test_an_explicit_caller_deadline_is_the_only_wait_that_still_ends_the_client(self):
        # A caller that names a deadline keeps its own behaviour: that is a
        # transport bound it chose, not the line watch, and the sweep is not
        # doubled onto it.
        harness = _Harness(
            sweep_answers=(_frame(running=False),),
            run_answers=(None,),
        )
        outcome, phases = harness.run(timeout_seconds=1)
        self.assertEqual(outcome.termination, "timed_out")
        self.assertTrue(harness.runs[0]["child"].killed)
        self.assertNotIn("line_stalled", phases)

    def test_a_command_with_no_dispatch_marker_is_never_swept(self):
        # Without a marker the PC cannot say whose process is whose, so nothing
        # here is allowed to end a process for it.
        harness = _Harness(run_answers=(0.0,))
        outcome, phases = harness.run(dispatch_id=None)
        self.assertEqual(harness.sweeps, [])
        self.assertNotIn("line_probe", phases)
        self.assertEqual(outcome.termination, "exited")


class TestTheSweepAnswerIsReadFromThePcAlone(unittest.TestCase):
    """Standard rule 4: the verdict is the PC's own process state, not text."""

    def test_a_verdict_frame_is_read_and_a_stray_token_is_not(self):
        verdict = parse_sweep_reply(_frame(running=True, killed=[9]))
        self.assertIs(verdict["running"], True)
        self.assertEqual(verdict["killed"], [9])
        # The terminal echoes the script that asks for the frame. The script splits
        # the token, so its own echo cannot be mistaken for an answer.
        echoed = ('Write-Output ("__PADIEM_" + "SWEEP__"'
                  " + [Convert]::ToBase64String(...))\r\n").encode("ascii")
        self.assertIsNone(parse_sweep_reply(echoed))
        self.assertIsNone(parse_sweep_reply(b""))
        self.assertIsNone(parse_sweep_reply(SWEEP_SENTINEL.encode("ascii") + b"@@@"))
        self.assertIsNone(parse_sweep_reply(None))

    def test_a_scope_this_module_does_not_know_is_refused_before_the_pc_is_asked(self):
        with self.assertRaises(MeshCentralCommandRefused):
            sweep_script(dispatch_id=OURS, mode="everything")

    def test_every_scope_is_one_line_the_pcs_own_parser_accepts(self):
        # The held scope once closed its second loop with one brace too many, and
        # the PC reported nothing at all: the answer frame never arrived, so the
        # only proof was the machine's own parser. These counts are the closest
        # thing to that proof on a host without PowerShell.
        scripts = (
            sweep_script(),
            sweep_script(dispatch_id=OURS),
            sweep_script(dispatch_id=OURS, keep_dispatch_ids=(OTHER,)),
            sweep_script(dispatch_id=OURS, mode=SWEEP_MODE_HELD),
            sweep_script(mode=SWEEP_MODE_HELD),
        )
        for script in scripts:
            with self.subTest(length=len(script)):
                self.assertNotIn("\n", script)
                self.assertEqual(script.count("{"), script.count("}"), "balanced blocks")
                self.assertEqual(script.count("("), script.count(")"), "balanced calls")
                # A switch and its value need their space: -Filter"x" is a parse
                # error on the PC, and a sweep that dies there reports a healthy line.
                self.assertIsNone(
                    re.search(r"-[A-Za-z]+\"", script),
                    "a parameter glued to its value",
                )
                self.assertLess(len(script), 8_192)

    def test_a_name_that_is_not_a_dispatch_id_is_refused_before_the_pc_is_asked(self):
        for bad in ("", "not-a-dispatch", "dsp_ZZZ"):
            with self.assertRaises(MeshCentralCommandRefused):
                sweep_script(dispatch_id=OURS, keep_dispatch_ids=(bad,))
            with self.assertRaises(MeshCentralCommandRefused):
                sweep_script(dispatch_id=bad)

    def test_the_marker_names_the_host_that_wrote_it_and_the_stop_still_reads_the_pid(self):
        wrapped = _wrap("Get-ChildItem C:/x", OURS, "oci-manage-01")
        # The pid stays the first line: that is all #6059's stop has ever read, and
        # a stop must keep working against a marker written by the older revision.
        self.assertRegex(wrapped, r"Set-Content -LiteralPath \$__padiem_pidfile -Value \$PID")
        self.assertIn("Add-Content -LiteralPath $__padiem_pidfile -Value 'oci-manage-01'",
                      wrapped)
        self.assertIn("$__padiem_v[0]", sweep_script(host_tag="oci-manage-01"))
        self.assertIn("$__padiem_v[1]", sweep_script(host_tag="oci-manage-01"))

    def test_a_command_still_leaves_the_marker_the_stop_needs_when_unhosted(self):
        self.assertIn("Set-Content -LiteralPath $__padiem_pidfile -Value $PID",
                      _wrap("Get-ChildItem C:/x", OURS))
        self.assertNotIn("Add-Content", _wrap("Get-ChildItem C:/x", OURS))

    def test_the_pre_flight_scope_only_reaches_this_hosts_own_leftovers(self):
        script = sweep_script(dispatch_id=OURS, host_tag="oci-manage-01")
        self.assertIn("$__padiem_o.host -ne 'oci-manage-01'", script)
        # The recovery scope is taken only after a line is provably dead, and it
        # clears the console whatever the marker says - a partner host that died
        # mid-command would otherwise hold this PC forever.
        held = sweep_script(dispatch_id=OURS, mode=SWEEP_MODE_HELD,
                            host_tag="oci-manage-01")
        self.assertNotIn("$__padiem_o.host", held)

    def test_a_scope_that_cannot_tell_its_own_host_ends_nothing(self):
        # No tag means "ours" is undefined, so the pre-flight scope has no target.
        self.assertIn(" continue;", sweep_script(dispatch_id=OURS))

    def test_a_host_name_that_is_not_a_host_name_is_stripped_not_escaped(self):
        script = sweep_script(dispatch_id=OURS, host_tag="a');Restart-Service Mesh(;")
        self.assertIn("o.host -ne 'aRestart-ServiceMesh'", script)
        # Only the two characters the comparison needs sit around the tag, so a
        # hostname can never open a new statement on a customer machine.
        clause = script[script.index("o.host -ne"):script.index("{ continue }")]
        self.assertEqual(clause.count("'"), 2, clause)


class TestTheJournalAndTheReportCarryTheCount(unittest.TestCase):
    """Standard rule 3: whoever watches must see the events without being told."""

    def _executor(self, command_port):
        from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor

        def transport(path, payload):
            if path.endswith("/poll"):
                return 200, {"ok": True, "dispatch": {
                    "dispatch_id": OURS, "nonce": "n" * 32, "node_ref": NODE,
                    "file_path": "C:/x/a.txt", "command_id": "cmd-1",
                    "run_id": "run-1", "kind": "command",
                    "command_text": "Get-ChildItem C:/x",
                }}
            return 200, {"ok": True}

        return OracleMeshExecutor(
            chat_origin="https://chat.example", channel_secret="x" * 32,
            read_port=_ReadPort(), command_port=command_port, transport=transport,
        )

    def test_line_counts_reach_the_round_report_and_the_process_total(self):
        class _SweepingPort:
            def run_command(self, **call):
                call["phase_observer"]("line_cleared")
                return MeshCentralCommandOutcome(
                    termination="exited", exit_code=0, output=b"ok",
                    line_blocked=1, line_cleared=1,
                )

        executor = self._executor(_SweepingPort())
        result = executor.run_once()
        self.assertEqual(
            executor.line_observations(),
            {"line_blocked_total": 1, "line_cleared_total": 1},
        )
        self.assertEqual(result.get("line_blocked_total"), 1, "the round says what it fixed")
        self.assertEqual(result.get("line_cleared_total"), 1)

    def test_a_quiet_round_reports_no_line_numbers_at_all(self):
        class _QuietPort:
            def run_command(self, **call):
                return MeshCentralCommandOutcome(
                    termination="exited", exit_code=0, output=b"ok",
                )

        result = self._executor(_QuietPort()).run_once()
        self.assertNotIn("line_blocked_total", result, "a healthy PC adds no noise")

    def test_the_sweep_is_told_which_dispatch_is_actually_running(self):
        seen = {}

        class _AskingPort:
            def __init__(self, executor_box):
                self._box = executor_box

            def run_command(self, **call):
                self._box["keep"] = call["keep_dispatch_ids"]
                self._box["during"] = None
                return MeshCentralCommandOutcome(
                    termination="exited", exit_code=0, output=b"ok",
                )

        box = {}
        executor = self._executor(_AskingPort(box))
        executor.run_once()
        self.assertEqual(box["keep"], (OURS,), "the busy PC names its own dispatch")
        self.assertIsNone(executor.active_dispatch_id(NODE),
                          "and lets go the moment the console answered")

    def test_a_finished_result_does_not_keep_the_pc_marked_busy(self):
        # A held result is bytes this host already has. The PC's console is free,
        # so the next claim must not be told that PC is busy.
        box = {}

        class _HoldingPort:
            def run_command(self, **call):
                box["keep"] = call["keep_dispatch_ids"]
                return MeshCentralCommandOutcome(
                    termination="exited", exit_code=0, output=b"ok",
                )

        executor = self._executor(_HoldingPort())
        executor.run_once()
        self.assertEqual(box["keep"], (OURS,))
        self.assertIsNone(executor._pending)
        self.assertEqual(executor.active_dispatch_ids(), ())


class _ReadPort:
    def read_bytes(self, **call):
        raise AssertionError("the command lane never reads a file")


if __name__ == "__main__":
    unittest.main()
