"""#4139 — the agent's own process lane, as a stop with a field for a verdict.

Every claim here is checked against the frames and the answers, not against a customer's
process table: the tables below are synthetic, and the tests are about what this lane is
allowed to send and what it is allowed to conclude.
"""
from __future__ import annotations

import io
import json
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_meshcentral_command_port import (
    MeshCentralCliCommandPort, MeshCentralStopUnconfirmed, _process_lane_enabled,
)
from kagent.local_agent_meshcentral_process_port import (
    ALLOWED_FRAME_TYPES, CONFIRMED, LANE_UNANSWERED, NO_TARGET, PSKILL_LABEL,
    STILL_RUNNING, MeshCentralProcessLane, MeshCentralProcessLaneRefused,
    dispatch_target_pids, parent_field, parse_process_table, ps_frame, psinfo_frame,
    pskill_frame, subtree_pids,
)

NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
DISPATCH = "dsp_" + "a" * 32
MARKER = "padiem-dispatch-" + DISPATCH + ".pid"
OTHER_MARKER = "padiem-dispatch-" + "b" * 32 + ".pid"


def table(*records):
    """A process table in the shape the agent answers: keys are pids, values are objects.

    The first-party parser reads `cmd` and `user` only
    (`views/default.handlebars:10844-10849`), so `cmd` here is a stand-in for whatever the
    observation finds in that field - never real customer text.
    """
    out = {}
    for pid, record in records:
        out[str(pid)] = dict(record)
    return out


OURS = {"cmd": "powershell.exe -Command " + MARKER, "user": "someone"}
THEIRS = {"cmd": "powershell.exe -Command " + OTHER_MARKER, "user": "someone"}
SHELL = {"cmd": "explorer.exe", "user": "someone"}


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

    def test_a_number_that_is_not_a_process_id_is_refused(self):
        for bad in (0, -1, "42", True, None, 4.2):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                pskill_frame(NODE, bad)

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

    def test_bytes_and_an_object_are_both_accepted(self):
        self.assertEqual(parse_process_table(b'{"9":{"cmd":"x"}}'), {9: {"cmd": "x"}})
        self.assertEqual(parse_process_table({"9": {"cmd": "x"}}), {9: {"cmd": "x"}})

    def test_an_answer_that_is_not_a_table_is_refused_without_quoting_it(self):
        for junk in ("not json", '{"a"', [], b"\xff\xfe", None, 7):
            with self.assertRaises(MeshCentralProcessLaneRefused):
                parse_process_table(junk)

    def test_the_only_thing_matched_is_our_own_marker_name(self):
        rows = parse_process_table(table((1, OURS), (2, THEIRS), (3, SHELL)))
        self.assertEqual(dispatch_target_pids(rows, DISPATCH), (1,))

    def test_a_process_that_merely_looks_like_a_shell_is_never_a_target(self):
        rows = parse_process_table(table((1, SHELL), (2, {"cmd": "powershell.exe"})))
        self.assertEqual(dispatch_target_pids(rows, DISPATCH), ())


class TestTheSubtree(unittest.TestCase):
    def test_a_parent_field_orders_the_tree_deepest_first(self):
        rows = {
            10: {"cmd": MARKER, "parentId": 0},
            11: {"cmd": "child.exe", "parentId": 10},
            12: {"cmd": "grandchild.exe", "parentId": 11},
        }
        ordered, tree = subtree_pids(rows, [10], parent_field(rows))
        self.assertTrue(tree)
        self.assertEqual(ordered, (12, 11, 10), "the leaves go first")

    def test_without_a_parent_field_only_the_matched_pid_is_addressed(self):
        rows = {10: {"cmd": MARKER}, 11: {"cmd": "child.exe"}}
        ordered, tree = subtree_pids(rows, [10], parent_field(rows))
        self.assertIsNone(parent_field(rows))
        self.assertEqual(ordered, (10,))
        self.assertFalse(tree, "the report must say a child may still be running")

    def test_a_cycle_in_the_table_cannot_loop_forever(self):
        rows = {1: {"parentId": 2}, 2: {"parentId": 1}}
        ordered, _tree = subtree_pids(rows, [1], "parentId")
        self.assertEqual(sorted(ordered), [1, 2])


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

    def test_nothing_matched_kills_nothing(self):
        lane, sent = self.lane([self.ps(table((1, SHELL), (2, THEIRS)))])
        report = lane.stop(DISPATCH)
        self.assertEqual(report.verdict, NO_TARGET)
        self.assertEqual(sent, [ps_frame(NODE, "padiem-test")],
                         "one read, no pskill, no second read")
        self.assertFalse(report.tree)

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

    def stop(self, dispatch_id):
        self.asks += 1
        return self._shape(verdict=self.verdict, dispatch_id=dispatch_id,
                           tree=self.verdict == CONFIRMED)


if __name__ == "__main__":
    unittest.main()
