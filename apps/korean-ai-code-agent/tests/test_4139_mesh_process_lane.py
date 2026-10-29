"""#4139 — the agent's own process lane, as a stop with a field for a verdict.

Every claim here is checked against the frames and the answers, not against a customer's
process table: the tables below are synthetic, and the tests are about what this lane is
allowed to send and what it is allowed to conclude. The shapes are the ones the read-only
capture on CGI-1 reported on 2026-10-30 - `ps` records with `cmd` and `pid` only, no parent
field, `psinfo` answering the .NET process object - so the rules below are pinned to what
the agent actually carries, not to what a shell could be made to say.
"""
from __future__ import annotations

import io
import json
import unittest

from kagent import local_agent_meshcentral_process_port as lane_module
from kagent.contracts import ContractError
from kagent.local_agent_meshcentral_command_port import (
    MeshCentralCliCommandPort, MeshCentralStopUnconfirmed, _process_lane_enabled,
)
from kagent.local_agent_meshcentral_process_port import (
    ALLOWED_FRAME_TYPES, BASIS_CMD_MARKER, BASIS_NONE, BASIS_RECORDED_PID, CONFIRMED,
    LANE_UNANSWERED, NO_TARGET, NO_TREE_NOTE, PS_WAIT_FLOOR_SECONDS, PS_WAIT_SECONDS,
    PSKILL_LABEL, STILL_RUNNING, MeshCentralProcessLane, MeshCentralProcessLaneRefused,
    marker_matched_pids, parse_process_table, ps_frame, psinfo_frame, pskill_frame,
    selected_details,
)

NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
DISPATCH = "dsp_" + "a" * 32
MARKER = "padiem-dispatch-" + DISPATCH + ".pid"
OTHER_MARKER = "padiem-dispatch-" + "b" * 32 + ".pid"


def table(*records):
    """A process table in the shape the agent answers: keys are pids, values are objects.

    Observed on CGI-1: one object keyed by pid, every record carrying `cmd` and `pid` and
    nothing else. `cmd` here is a stand-in for whatever that field holds on a real PC -
    never real customer text.
    """
    out = {}
    for pid, record in records:
        out[str(pid)] = dict(record)
    return out


OURS = {"cmd": "powershell.exe -Command " + MARKER, "pid": 1}
THEIRS = {"cmd": "powershell.exe -Command " + OTHER_MARKER, "pid": 2}
SHELL = {"cmd": "explorer.exe", "pid": 3}


class LaneCase(unittest.TestCase):
    def lane(self, answers):
        """A lane whose socket replays scripted answers, frame by frame."""
        sent = []

        def ask(frame):
            sent.append(frame)
            return answers[len(sent) - 1] if len(sent) <= len(answers) else None

        lane = MeshCentralProcessLane(node_ref=NODE, ask=ask, response_id="padiem-test")
        return lane, sent

    def ps(self, rows):
        return {"action": "msg", "type": "ps", "nodeid": NODE, "value": json.dumps(rows)}


class TestTheFrames(unittest.TestCase):
    def test_the_three_verbs_are_the_shapes_the_agent_answers(self):
        self.assertEqual(ps_frame(NODE, "r1"), {
            "action": "msg", "type": "ps", "nodeid": NODE, "responseid": "r1"})
        self.assertEqual(pskill_frame(NODE, 4021), {
            "action": "msg", "type": "pskill", "nodeid": NODE,
            "value": "4021|" + PSKILL_LABEL})
        self.assertEqual(psinfo_frame(NODE, 4, "r2"), {
            "action": "msg", "type": "psinfo", "nodeid": NODE, "pid": 4, "responseid": "r2"})

    def test_the_label_is_ours_so_a_command_line_never_reaches_the_server_log(self):
        # The web UI passes the process command line here; the agent writes that part into
        # its own log line (agents/meshcore.js:1544-1547). This lane sends a fixed word.
        value = pskill_frame(NODE, 7)["value"]
        self.assertTrue(value.startswith("7|"))
        self.assertEqual(value.split("|", 1)[1], PSKILL_LABEL)
        self.assertNotIn(MARKER, value)

    def test_zero_and_a_negative_are_not_process_ids_and_are_refused(self):
        # 0 is the idle process: the agent's own handler skips a falsy pid, so asking about
        # it is asking for a reply that cannot come. A negative is not a pid here at all.
        for bad in (0, -1, -4021, "42", True, None, 4.2):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                pskill_frame(NODE, bad)
        for bad in (0, -1):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                psinfo_frame(NODE, bad, "r2")

    def test_a_device_that_is_not_an_identifier_is_refused(self):
        for bad in ("", " ", None, 7, "has space", "line" + chr(10) + "break"):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                ps_frame(bad, "r1")

    def test_a_response_id_that_is_not_bounded_text_is_refused(self):
        for bad in ("", None, 7, "x" * 129):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                ps_frame(NODE, bad)


class TestTheTable(unittest.TestCase):
    def test_the_table_is_read_on_the_first_party_shape(self):
        rows = parse_process_table(json.dumps(
            {"4": {"cmd": "a", "user": "u"}, "5": None, "notapid": {"cmd": "b"}}))
        self.assertEqual(sorted(rows), [4])
        self.assertEqual(rows[4]["cmd"], "a")

    def test_the_idle_process_is_never_a_row_this_lane_can_address(self):
        # Observed shape, observed refusal: a `0` key stays out of the table, so it cannot
        # reach pskill_frame even by way of a matching record.
        rows = parse_process_table({"0": {"cmd": MARKER, "pid": 0}, "7": {"cmd": "x"}})
        self.assertEqual(sorted(rows), [7])

    def test_bytes_and_an_object_are_both_accepted(self):
        self.assertEqual(parse_process_table(b'{"9":{"cmd":"x"}}'), {9: {"cmd": "x"}})
        self.assertEqual(parse_process_table({"9": {"cmd": "x"}}), {9: {"cmd": "x"}})

    def test_an_answer_that_is_not_a_table_is_refused_without_quoting_it(self):
        for junk in ("not json", '{"a"', [], b"\xff\xfe", None, 7):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                parse_process_table(junk)

    def test_the_only_thing_matched_is_our_own_marker_name(self):
        rows = parse_process_table(table((1, OURS), (2, THEIRS), (3, SHELL)))
        self.assertEqual(marker_matched_pids(rows, DISPATCH), (1,))

    def test_a_process_that_merely_looks_like_a_shell_is_never_a_target(self):
        rows = parse_process_table(table((1, SHELL), (2, {"cmd": "powershell.exe"})))
        self.assertEqual(marker_matched_pids(rows, DISPATCH), ())


class TestThereIsNoFamilyWalk(LaneCase):
    """CGI-1 answered `cmd|pid` and 42 .NET fields with no parent in either.

    A path that climbed or descended a process tree cannot be built on this agent, so it is
    not built at all - and this test is what keeps nobody re-adding a guess later.
    """

    def test_the_lane_exports_no_parent_or_subtree_machinery(self):
        for name in ("parent_field", "subtree_pids", "kill_tree", "children_of"):
            self.assertNotIn(name, dir(lane_module), name + " would need a field that is not there")

    def test_a_stop_that_touched_a_process_says_a_child_may_survive(self):
        lane, _sent = self.lane([
            self.ps(table((1, OURS))), {"action": "msg", "type": "pskill"},
            self.ps(table((3, SHELL))),
        ])
        report = lane.stop(DISPATCH)
        self.assertEqual(report.verdict, CONFIRMED)
        self.assertIn(NO_TREE_NOTE, report.notes)

    def test_only_the_addressed_pid_is_ever_sent(self):
        rows = table((1, OURS), (2, THEIRS), (3, SHELL), (4, {"cmd": "child.exe"}))
        lane, sent = self.lane([
            self.ps(rows), {"action": "msg", "type": "pskill"}, self.ps(table((3, SHELL))),
        ])
        report = lane.stop(DISPATCH)
        self.assertEqual([frame["value"].split("|")[0] for frame in sent
                          if frame["type"] == "pskill"], ["1"])
        self.assertEqual(report.killed, (1,))


class TestTheRecordedPidIsTheAuthority(LaneCase):
    def test_a_recorded_pid_is_addressed_even_when_its_cmd_names_another_dispatch(self):
        # The dispatch's own record outranks a text match: pid 2's record names a different
        # dispatch, and this one still ends pid 2 because that is the number it wrote down.
        lane, sent = self.lane([
            self.ps(table((1, OURS), (2, THEIRS))),
            {"action": "msg", "type": "pskill"},
            self.ps(table((1, OURS))),
        ])
        report = lane.stop(DISPATCH, 2)
        self.assertEqual(report.targets, (2,))
        self.assertEqual(report.basis, BASIS_RECORDED_PID)
        self.assertEqual(sent[1]["value"], "2|" + PSKILL_LABEL)

    def test_a_recorded_pid_that_is_not_in_the_table_is_already_finished_with(self):
        lane, sent = self.lane([self.ps(table((3, SHELL)))])
        report = lane.stop(DISPATCH, 4021)
        self.assertEqual(report.verdict, CONFIRMED)
        self.assertEqual(report.killed, ())
        self.assertEqual([frame["type"] for frame in sent], ["ps"],
                         "nothing was sent to kill what is already gone")

    def test_the_marker_match_is_the_auxiliary_and_says_so(self):
        lane, _sent = self.lane([
            self.ps(table((1, OURS))), {"action": "msg", "type": "pskill"},
            self.ps(table((3, SHELL))),
        ])
        report = lane.stop(DISPATCH)
        self.assertEqual(report.basis, BASIS_CMD_MARKER)
        self.assertEqual(report.targets, (1,))

    def test_a_stop_that_matched_nothing_addresses_nothing(self):
        lane, sent = self.lane([self.ps(table((1, SHELL), (2, THEIRS)))])
        report = lane.stop(DISPATCH)
        self.assertEqual(report.verdict, NO_TARGET)
        self.assertEqual(report.basis, BASIS_NONE)
        self.assertEqual(sent, [ps_frame(NODE, "padiem-test")],
                         "one read, no pskill, no second read")

    def test_a_recorded_number_that_is_not_a_pid_is_refused_before_anything_is_read(self):
        lane, sent = self.lane([self.ps(table((1, OURS)))])
        for bad in (0, -1, "4021"):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                lane.stop(DISPATCH, bad)
        self.assertEqual(sent, [], "a refusal does not spend a request")


class TestTheStopVerdicts(LaneCase):
    def test_a_pid_that_is_gone_after_the_read_is_the_only_confirmed_stop(self):
        lane, sent = self.lane([
            self.ps(table((1, OURS), (2, SHELL))),
            {"action": "msg", "type": "pskill", "result": "OK"},
            self.ps(table((2, SHELL))),
        ])
        report = lane.stop(DISPATCH)
        self.assertEqual(report.verdict, CONFIRMED)
        self.assertTrue(report.confirmed)
        self.assertEqual(report.targets, (1,))
        self.assertEqual(report.killed, (1,))
        self.assertEqual(report.remaining, ())
        self.assertEqual(lane.sent_types, ["ps", "pskill", "ps"],
                         "the second read is the verdict")

    def test_a_pid_still_in_the_second_table_is_still_running_not_done(self):
        lane, _sent = self.lane([
            self.ps(table((1, OURS))), {"action": "msg", "type": "pskill"},
            self.ps(table((1, OURS))),
        ])
        report = lane.stop(DISPATCH)
        self.assertEqual(report.verdict, STILL_RUNNING)
        self.assertEqual(report.remaining, (1,))
        self.assertFalse(report.confirmed)

    def test_a_lane_that_answers_nothing_is_reported_as_nothing(self):
        lane, _sent = self.lane([])
        self.assertEqual(lane.stop(DISPATCH).verdict, LANE_UNANSWERED)

    def test_a_stop_that_killed_but_cannot_confirm_is_not_a_stop(self):
        lane, _sent = self.lane([
            self.ps(table((1, OURS))), {"action": "msg", "type": "pskill"}, None,
        ])
        report = lane.stop(DISPATCH)
        self.assertEqual(report.verdict, LANE_UNANSWERED)
        self.assertEqual(report.killed, (1,), "what was sent is recorded")
        self.assertFalse(report.confirmed)

    def test_only_the_three_verbs_ever_leave_the_lane(self):
        lane, sent = self.lane([
            self.ps(table((1, OURS))), {"action": "msg", "type": "pskill"},
            self.ps({}),
        ])
        lane.stop(DISPATCH)
        self.assertTrue({frame["type"] for frame in sent} <= set(ALLOWED_FRAME_TYPES))
        self.assertNotIn("console", [frame["type"] for frame in sent])

    def test_the_lane_needs_a_socket_and_refuses_to_invent_one(self):
        with self.assertRaises(ContractError):
            MeshCentralProcessLane(node_ref=NODE, ask=None, response_id="r")


class TestTheWaitBudget(LaneCase):
    """One observed `ps` took 15,283 ms; a shorter bound invents a silent PC."""

    def _ask(self, frame):
        return None

    def test_the_default_wait_clears_the_observed_answer_time(self):
        self.assertGreaterEqual(PS_WAIT_FLOOR_SECONDS, 15.0)
        self.assertGreaterEqual(PS_WAIT_SECONDS, PS_WAIT_FLOOR_SECONDS)
        lane = MeshCentralProcessLane(node_ref=NODE, ask=self._ask, response_id="r")
        self.assertGreaterEqual(lane.ps_wait_seconds, PS_WAIT_FLOOR_SECONDS)

    def test_a_socket_bound_shorter_than_the_observed_answer_is_refused(self):
        for short in (0.5, 1, 5, 14.9):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                MeshCentralProcessLane(node_ref=NODE, ask=self._ask, response_id="r",
                                       ps_wait_seconds=short)

    def test_a_wait_that_would_reach_the_execution_ceiling_is_not_a_communication_bound(self):
        # #5895 removed ceilings on the work itself; this wait is on an ANSWER, so it is
        # bounded and bounded generously - and never allowed to be the hidden way to give up
        # on a PC that is merely slow to list its processes.
        self.assertGreaterEqual(PS_WAIT_FLOOR_SECONDS, 15.0)


class TestTheDetailRecord(LaneCase):
    """`psinfo` answers 42 .NET fields; this lane keeps the handful that are numbers."""

    DETAIL = {
        "Id": 4021, "SessionId": 1, "CPU": 12.5, "Responding": True,
        "HandleCount": 300, "WorkingSet64": 4096, "PeakWorkingSet64": 8192,
        "PrivateMemorySize64": 1024, "StartTime": "2026-10-30T04:00:00Z",
        # Fields the observation found and this lane must not carry onward.
        "StartInfo": {"FileName": "powershell.exe", "Arguments": "-Command " + MARKER},
        "MachineName": "CGI-1", "Name": "powershell", "ProcessName": "powershell",
        "Threads": [{"Id": 1}], "EnableRaisingEvents": False, "__NounName": "Process",
    }

    def test_only_the_listed_scalars_survive_a_detail_record(self):
        kept = selected_details(self.DETAIL)
        self.assertEqual(sorted(kept), sorted(
            "Id SessionId CPU Responding HandleCount WorkingSet64 PeakWorkingSet64 "
            "PrivateMemorySize64 StartTime".split()))
        for smuggled in ("StartInfo", "MachineName", "Name", "ProcessName", "Threads"):
            self.assertNotIn(smuggled, kept)

    def test_the_lane_hands_back_no_field_it_did_not_ask_for(self):
        lane, _sent = self.lane([
            {"action": "msg", "type": "psinfo", "nodeid": NODE, "pid": 4021,
             "value": self.DETAIL},
        ])
        details = lane.details(4021)
        self.assertNotIn("StartInfo", details)
        self.assertEqual(details["Id"], 4021)
        text = json.dumps(details, default=str)
        self.assertNotIn(MARKER, text, "a command line cannot ride out of a detail record")
        self.assertNotIn("CGI-1", text)

    def test_an_empty_detail_answer_is_a_possible_truth_not_a_transport_fault(self):
        lane, _sent = self.lane([{"action": "msg", "type": "psinfo", "value": {}}])
        self.assertEqual(lane.details(4021), {})

    def test_a_detail_answer_that_is_not_an_object_is_read_as_empty(self):
        for junk in ("text", None, 7, [1, 2]):
            lane, _sent = self.lane([{"action": "msg", "type": "psinfo", "value": junk}])
            self.assertEqual(lane.details(4021), {})

    def test_a_stop_never_buys_a_detail_read(self):
        lane, sent = self.lane([
            self.ps(table((1, OURS))), {"action": "msg", "type": "pskill"},
            self.ps(table((3, SHELL))),
        ])
        lane.stop(DISPATCH)
        self.assertEqual([frame["type"] for frame in sent], ["ps", "pskill", "ps"])


class TestTheSwitchIsOptIn(unittest.TestCase):
    """The terminal stop is what runs while this lane is off - which is shipped default."""

    MARK = DISPATCH

    def _port(self, lane=None, enabled=None, answers=(b"",)):
        created = []

        class _Child:
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()

            def poll(self):
                return None

            def kill(self):
                return None

        class _Handoff:
            slave = 77

            def __init__(self, payload):
                created.append(payload)

            def wait_for(self, done, seconds):
                return answers[0]

            def wait_closed(self, seconds):
                return None

            def release_slave(self):
                return None

        return MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js="/opt/meshcentral/meshctrl.js", login_user="operator",
            password_provider=lambda: "op3rator-secret", url="wss://127.0.0.1:4443",
            popen_factory=lambda argv, **kw: _Child(), pty_factory=_Handoff,
            process_lane=lane, process_lane_enabled=enabled,
        ), created

    def test_off_is_default_and_explicit_yes_is_the_only_way_on(self):
        self.assertFalse(_process_lane_enabled(None, {}))
        self.assertFalse(_process_lane_enabled(None, {"PADIEM_MESH_PROCESS_LANE": "0"}))
        for value in ("1", "true", "YES", "on"):
            self.assertTrue(_process_lane_enabled(None, {"PADIEM_MESH_PROCESS_LANE": value}))
        self.assertFalse(_process_lane_enabled(False, {"PADIEM_MESH_PROCESS_LANE": "1"}),
                         "an explicit no beats an environment")

    def test_the_terminal_stop_is_what_runs_when_the_lane_is_off(self):
        port, created = self._port(lane=_CountingLane(CONFIRMED), enabled=False)
        with self.assertRaises(MeshCentralStopUnconfirmed):
            port.kill_command_process(node_ref=NODE, dispatch_id=self.MARK)
        self.assertEqual(len(created), 1, "the terminal session opened, the lane did not")

    def test_a_confirmed_stop_by_the_lane_needs_no_terminal(self):
        lane = _CountingLane(CONFIRMED)
        port, created = self._port(lane=lane, enabled=True)
        port.kill_command_process(node_ref=NODE, dispatch_id=self.MARK)
        self.assertEqual(lane.asks, 1)
        self.assertEqual(created, [], "no session is opened when the lane has the answer")

    def test_the_recorded_pid_travels_to_the_lane_and_nowhere_else(self):
        lane = _CountingLane(CONFIRMED)
        port, created = self._port(lane=lane, enabled=True)
        port.kill_command_process(node_ref=NODE, dispatch_id=self.MARK, recorded_pid=4021)
        self.assertEqual(lane.recorded, [4021])
        self.assertEqual(created, [])

    def test_an_unconfirmed_verdict_travels_the_same_exception_as_the_terminal(self):
        lane = _CountingLane(NO_TARGET)
        port, created = self._port(lane=lane, enabled=True)
        with self.assertRaises(MeshCentralStopUnconfirmed) as caught:
            port.kill_command_process(node_ref=NODE, dispatch_id=self.MARK)
        self.assertEqual(caught.exception.verdict, NO_TARGET)
        self.assertNotIn(self.MARK, str(caught.exception),
                         "the message carries our word, not the dispatch")
        self.assertEqual(created, [])

    def test_the_journal_names_the_verdict_as_a_phase_and_never_as_done(self):
        lane = _CountingLane(STILL_RUNNING)
        port, _created = self._port(lane=lane, enabled=True)
        phases = []
        self.assertFalse(port._stop_on_pc(NODE, self.MARK, phases.append))
        self.assertEqual(phases, ["cancel_kill_still_running", "cancel_kill_unverified"])


class _CountingLane:
    """A lane that answers one verdict, and counts being asked."""

    def __init__(self, verdict):
        from kagent.local_agent_meshcentral_process_port import ProcessStopReport

        self.verdict = verdict
        self._shape = ProcessStopReport
        self.asks = 0
        self.recorded: list = []

    def stop(self, dispatch_id, recorded_pid=None):
        self.asks += 1
        self.recorded.append(recorded_pid)
        return self._shape(verdict=self.verdict, dispatch_id=dispatch_id,
                           basis=BASIS_RECORDED_PID if recorded_pid else BASIS_CMD_MARKER)


if __name__ == "__main__":
    unittest.main()
