"""#8140 — clock-injected tests for the connected-but-idle agent watch.

No real sleep, no real network, no imports from other test files.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from kagent.local_agent_mesh_stall_watch import (
    FAILURE_PHASES,
    NOTIFY_KEY_ENV,
    RECOVERY_PHASE,
    RESTART_HINT,
    MeshStallWatch,
    display_name,
    loopback_notify,
    set_bridge_for_test,
    source_id,
    bridge_observe,
)


class StallWatchContract(unittest.TestCase):
    def setUp(self):
        self.clock = [1_700_000_000.0]
        self.sent = []
        self.watch = MeshStallWatch(now=lambda: self.clock[0], notify=self.sent.append)

    def _advance(self, seconds):
        self.clock[0] += seconds

    def test_executor_phase_flow_three_failures_then_result_recovers(self):
        # silent_timeout + line_probe_unobserved are the two failure phases.
        for phase in ("silent_timeout", "line_probe_unobserved", "silent_timeout"):
            self._advance(30)
            self.watch.observe("COMP1$nodeid", phase)
        self.assertEqual(len(self.sent), 1)
        notice = self.sent[0]
        self.assertEqual(notice.node, "COMP1")  # display label, not the node id
        self.assertIn("PC 에이전트 응답 없음: COMP1", notice.title)
        self.assertIn(RESTART_HINT, notice.guide)
        event = notice.event()
        self.assertEqual(event["site"], "pc")
        self.assertEqual(event["kind"], "agent_stall")
        self.assertEqual(event["audience"], "real")
        self.assertEqual(event["source_id"], source_id("COMP1", notice.suspicion_start))
        # A result phase is recovery: it clears the alerted flag and last_success.
        self._advance(30)
        self.watch.observe("COMP1$nodeid", RECOVERY_PHASE)
        # Two failures after recovery are below the threshold -> no new notice.
        for _ in range(2):
            self._advance(30)
            self.watch.observe("COMP1$nodeid", "silent_timeout")
        self.assertEqual(len(self.sent), 1)
        # A full new episode after recovery alerts again, with a fresh source_id.
        self._advance(30)
        second = self.watch.observe("COMP1$nodeid", "silent_timeout")
        self.assertIsNotNone(second)
        self.assertIsNotNone(second.last_success)
        self.assertNotEqual(second.source_id, notice.source_id)
        self.assertEqual(len(self.sent), 2)

    def test_executor_bridge_reports_one_notice_and_recovery_clears(self):
        # The executor calls bridge_observe(node_ref, phase) from its single
        # phase funnel for every command phase, including silent_timeout,
        # line_probe_unobserved and result.
        set_bridge_for_test(self.watch)
        try:
            for phase in ("claimed", "silent_timeout", "line_probe_unobserved",
                          "silent_timeout"):
                self.watch  # clock shared with bridge
                self._advance(30)
                bridge_observe("COMP9$nodeid", phase)
            self.assertEqual(len(self.sent), 1)
            self.assertEqual(self.sent[0].node, "COMP9")
            bridge_observe("COMP9$nodeid", "result")
            # Below threshold again -> no second notice until a full episode.
            for _ in range(2):
                self._advance(30)
                bridge_observe("COMP9$nodeid", "silent_timeout")
            self.assertEqual(len(self.sent), 1)
        finally:
            set_bridge_for_test(None)

    def test_no_key_sends_nothing(self):
        notice = self.sent[0] if self.sent else None
        if notice is None:
            for _ in range(3):
                self.watch.observe("C$id", "silent_timeout", at=self.clock[0])
            notice = self.sent[0]
        sent = []

        def opener(request, timeout):
            sent.append((request.full_url, timeout))
            raise AssertionError("must not be called without a key")

        with mock.patch.dict(os.environ, {NOTIFY_KEY_ENV: ""}, clear=False):
            self.assertFalse(loopback_notify(notice, origin="http://127.0.0.1:8788",
                                             opener=opener))
        self.assertEqual(sent, [])

    def test_loopback_posts_with_key_and_short_timeout(self):
        for _ in range(3):
            self.watch.observe("C$id", "silent_timeout", at=self.clock[0])
        notice = self.sent[0]
        calls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout):
            calls.append((request.full_url, timeout, dict(request.header_items())))
            return Response()

        with mock.patch.dict(os.environ, {NOTIFY_KEY_ENV: "unit-key"}, clear=False):
            self.assertTrue(loopback_notify(notice, origin="http://127.0.0.1:8788/",
                                            opener=opener))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "http://127.0.0.1:8788/api/ops/notify-event")
        self.assertEqual(calls[0][1], 3.0)
        self.assertIn("unit-key", str(calls[0][2]))

    def test_loopback_failure_does_not_raise(self):
        for _ in range(3):
            self.watch.observe("C$id", "silent_timeout", at=self.clock[0])
        notice = self.sent[0]

        def opener(request, timeout):
            raise OSError("offline")

        with mock.patch.dict(os.environ, {NOTIFY_KEY_ENV: "unit-key"}, clear=False):
            self.assertFalse(loopback_notify(notice, origin="http://127.0.0.1:8788",
                                             opener=opener))

    def test_other_nodes_are_independent(self):
        for _ in range(3):
            self.watch.observe("A$id", "silent_timeout", at=self.clock[0])
        for _ in range(3):
            self.watch.observe("B$id", "silent_timeout", at=self.clock[0])
        self.assertEqual([item.node for item in self.sent], ["A", "B"])

    def test_window_gap_and_phase_vocabulary(self):
        self.watch.observe("C$id", "silent_timeout", at=1_000.0)
        self.watch.observe("C$id", "silent_timeout", at=1_030.0)
        self.watch.observe("C$id", "silent_timeout", at=1_030.0 + 700.0)
        self.assertEqual(self.sent, [])
        self.assertEqual(FAILURE_PHASES, {"silent_timeout", "line_probe_unobserved"})
        self.assertEqual(RECOVERY_PHASE, "result")
        self.assertEqual(display_name("7P4oxxx$pB"), "7P4oxxx")
        self.assertEqual(display_name("opaqueid"), display_name("opaqueid"))
        self.assertLessEqual(len(display_name("x" * 200)), 60)


if __name__ == "__main__":
    unittest.main()
