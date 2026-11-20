"""#8140 — clock-injected tests for the connected-but-idle agent watch."""
from __future__ import annotations

import unittest

from kagent.local_agent_mesh_stall_watch import (
    FAILURE_PHASES,
    RESTART_HINT,
    SUCCESS_PHASE,
    MeshStallWatch,
)


class StallWatchContract(unittest.TestCase):
    def setUp(self):
        self.clock = [1_700_000_000.0]
        self.sent = []
        self.watch = MeshStallWatch(now=lambda: self.clock[0], notify=self.sent.append)

    def _advance(self, seconds):
        self.clock[0] += seconds

    def test_three_consecutive_failures_notify_once_then_silent(self):
        phases = ["silent_timeout", "line_probe_unobserved", "silent_timeout"]
        notices = []
        for phase in phases:
            self._advance(30)
            got = self.watch.observe("Comp-1", phase)
            if got:
                notices.append(got)
            self.watch.observe("Comp-1", "result")  # a neutral phase does not count
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].node, "Comp-1")
        self.assertEqual(notices[0].failures, 3)
        self.assertIn(RESTART_HINT, notices[0].guide)
        # Further failures without recovery stay silent.
        for _ in range(5):
            self._advance(30)
            self.assertIsNone(self.watch.observe("Comp-1", "silent_timeout"))
        self.assertEqual(len(self.sent), 1)

    def test_recovery_clears_and_a_new_episode_alerts_again(self):
        for phase in ["silent_timeout"] * 3:
            self._advance(30)
            self.watch.observe("Comp-1", phase)
        self.assertEqual(len(self.sent), 1)
        self._advance(30)
        self.watch.observe("Comp-1", SUCCESS_PHASE, at=self.clock[0])
        # A success records a last-success timestamp and resets the run.
        self._advance(30)
        self.watch.observe("Comp-1", "silent_timeout")
        self.watch.observe("Comp-1", "silent_timeout")
        self.assertEqual(len(self.sent), 1)  # only 2 new failures, under threshold
        self._advance(30)
        second = self.watch.observe("Comp-1", "line_probe_unobserved")
        self.assertIsNotNone(second)
        self.assertEqual(len(self.sent), 2)
        self.assertIsNotNone(second.last_success)

    def test_other_nodes_are_independent(self):
        for phase in ["silent_timeout"] * 3:
            self._advance(30)
            self.watch.observe("Comp-A", phase)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0].node, "Comp-A")
        for phase in ["silent_timeout"] * 3:
            self._advance(30)
            self.watch.observe("Comp-B", phase)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[1].node, "Comp-B")

    def test_window_gap_breaks_the_run(self):
        self.watch.observe("Comp-1", "silent_timeout", at=1_000.0)
        self.watch.observe("Comp-1", "silent_timeout", at=1_030.0)
        self.watch.observe("Comp-1", "silent_timeout", at=1_030.0 + 700.0)
        self.assertEqual(len(self.sent), 0)

    def test_event_never_carries_a_full_node_id_or_token(self):
        long_id = "node_" + "a" * 80 + "_tok_secret"
        for _ in range(3):
            self.watch.observe(long_id, "silent_timeout", at=self.clock[0])
        event = self.sent[0].as_event()
        self.assertLessEqual(len(event["node"]), 60)
        self.assertNotIn("secret", event["node"])
        self.assertNotIn("tok", event["node"])
        self.assertEqual(set(event) - {"title", "node", "last_success", "failures", "guide"}, set())
        self.assertEqual(event["guide"], RESTART_HINT)

    def test_success_phase_is_the_only_recovery(self):
        self.assertEqual(SUCCESS_PHASE, "success")
        self.assertEqual(FAILURE_PHASES, {"silent_timeout", "line_probe_unobserved"})


if __name__ == "__main__":
    unittest.main()
