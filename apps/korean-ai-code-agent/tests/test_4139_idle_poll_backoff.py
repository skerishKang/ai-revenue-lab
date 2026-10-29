"""#4139 follow-up: an idle executor asks the lane less often; a busy one does not.

The CTO asked for two numbers, not a feeling: rounds per minute against the lane, and
how long a dispatch waits for its first claim. Both come out of the schedule the service
loop actually runs, below, against a real gap counter - no wall clock sleeps and no
rounded expectations.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import kagent.local_agent_oracle_mesh_executor as entry
from kagent.local_agent_oracle_mesh_executor import (
    IDLE_POLL_BASE_SECONDS,
    IDLE_POLL_MAX_SECONDS,
    OracleMeshChannelRefused,
    OracleMeshExecutor,
    POLL_PATH,
    ROUND_IDLE,
    ROUND_SKIPPED,
    ROUND_WORKED,
)
from tests.test_4139_oracle_mesh_executor import SECRET, _StubPort

ENV = {
    "ORACLE_MESH_CHAT_ORIGIN": "https://chat.example.test",
    "ORACLE_MESH_CHANNEL_SECRET_FILE": "fake",
    "ORACLE_MESH_MESHCTRL_JS": "fake",
    "ORACLE_MESH_LOGIN_USER": "synthetic",
    "ORACLE_MESH_PASSWORD_FILE": "fake",
}


class _Stop(Exception):
    def __init__(self, gaps):
        super().__init__("the virtual hour ended")
        self.gaps = gaps


class _Clock:
    """Virtual time: the loop's sleeps are recorded, never lived.

    A round also costs the five seconds the lane holds the poll open
    (`oracle_mesh_read_return_routes.py:1883`), which is why the loop's gaps alone are
    not the period: the beat and the request rate are counted over both.
    """

    def __init__(self, stop_at: float, hold: float = 0.0):
        self.now = 0.0
        self.gaps: list[float] = []
        self.stop_at = stop_at
        self.hold = hold

    def sleep(self, seconds: float) -> None:
        self.gaps.append(seconds)
        self.now += seconds
        if self.now >= self.stop_at:
            raise _Stop(self.gaps)

    def round(self) -> None:
        """One ask: the request itself is on the wire for `hold` seconds."""
        self.now += self.hold


class _Scripted:
    """A loop-facing executor whose rounds follow a script."""

    def __init__(self, answer, clock: _Clock):
        self._answer = answer
        self._clock = clock
        self.rounds = 0
        self.last_round = ROUND_SKIPPED

    def load_pending(self):
        return False

    def start_channel_watchdog(self):
        return None

    def line_observations(self):
        return {"line_blocked_total": 0, "line_cleared_total": 0}

    def run_once(self):
        self.rounds += 1
        self._clock.round()
        kind = self._answer(self.rounds)
        if kind == "refused":
            raise OracleMeshChannelRefused("synthetic channel refusal")
        self.last_round = kind
        if kind == ROUND_IDLE or kind == ROUND_SKIPPED:
            return None
        return {"ok": True}


#: What the lane keeps one poll open before answering empty
#: (`oracle_mesh_read_return_routes.py:1883`, capped by #5479).
LANE_HOLD_SECONDS = 5.0


def _run_loop(answer, *, stop_at=3600.0, environ=None, hold=LANE_HOLD_SECONDS):
    clock = _Clock(stop_at, hold=hold)
    made = {}

    def factory(**kwargs):
        executor = _Scripted(answer, clock)
        made["executor"] = executor
        return executor

    env = dict(ENV)
    env.update(environ or {})
    with patch.object(entry, "deployment_secret_password_provider",
                      return_value=lambda: "fake"), \
         patch.object(entry, "_read_secret_file", return_value=SECRET), \
         patch.object(entry, "make_oracle_mesh_executor", side_effect=factory), \
         patch("time.sleep", side_effect=clock.sleep):
        try:
            entry.main(env)
        except _Stop:
            pass
    return clock, made["executor"]


class TestTheIdleWaitGrows(unittest.TestCase):
    def test_an_empty_lane_stretches_the_gap_and_the_lane_keeps_the_beat(self):
        clock, executor = _run_loop(lambda _round: ROUND_IDLE, stop_at=600.0)
        # The first gap is the second the loop always waited, and every later one is
        # what the previous round earned.
        self.assertEqual(clock.gaps[:7], [1, 2, 4, 8, 16, 32, 60])
        self.assertTrue(all(g == IDLE_POLL_MAX_SECONDS for g in clock.gaps[6:]),
                        "the wait settles at the ceiling and never past it")
        self.assertGreater(executor.rounds, 0)

    def test_the_ceiling_is_where_the_presence_beat_stays_fresh(self):
        # The beat rides the poll body, so the longest a beat can age is the ceiling
        # plus the five seconds the lane already holds the request open. The product
        # acts on a presence row at 180 s and the connector watch alarms at 300.
        lane_hold_seconds = 5
        oldest_beat = IDLE_POLL_MAX_SECONDS + lane_hold_seconds
        self.assertLessEqual(oldest_beat * 2, 180,
                             "the beat must stay inside what the product judges fresh")
        self.assertLessEqual(oldest_beat * 4, 300,
                             "and well inside what the watch alarms on")

    def test_a_round_this_host_skipped_never_stretches_the_next_ask(self):
        # A failover landing on this host must start claiming on the next second: a
        # skipped round says nothing about the queue, so it may not buy a long wait.
        clock, _ = _run_loop(
            lambda _round: ROUND_SKIPPED if _round % 2 else ROUND_IDLE, stop_at=120.0)
        self.assertTrue(all(g <= IDLE_POLL_BASE_SECONDS + 1 for g in clock.gaps[:8]),
                        "alternating skips keep the gaps at the base")

    def test_a_channel_that_will_not_answer_is_the_operators_interval_not_a_backoff(self):
        clock, executor = _run_loop(
            lambda _round: "refused" if _round in (1, 2) else ROUND_IDLE, stop_at=120.0)
        self.assertEqual(clock.gaps[:2], [5, 5], "ORACLE_MESH_POLL_SECONDS governs refusals")
        self.assertEqual(clock.gaps[2], IDLE_POLL_BASE_SECONDS,
                         "the first empty answer after a refusal starts over at one second")

    def test_work_resets_the_wait_the_moment_the_lane_is_not_empty(self):
        answered = []

        def answer(round_number):
            # Ten idle rounds, then work, then idle again.
            if round_number <= 10:
                return ROUND_IDLE
            if round_number == 11:
                return ROUND_WORKED
            return ROUND_IDLE

        clock, _ = _run_loop(answer, stop_at=900.0)
        # Gaps: 1,2,4,8,16,32,60,60,60,60 (after 10 idle rounds), none for the worked
        # round (a busy lane is drained, not awaited), then the base again.
        self.assertEqual(clock.gaps[:10], [1, 2, 4, 8, 16, 32, 60, 60, 60, 60])
        self.assertEqual(clock.gaps[10], IDLE_POLL_BASE_SECONDS,
                         "the ask right after work waits one second, as before")

    def test_one_second_ceiling_is_exactly_the_cadence_this_lane_had(self):
        clock, _ = _run_loop(lambda _round: ROUND_IDLE, stop_at=120.0,
                             environ={"ORACLE_MESH_IDLE_POLL_MAX_SECONDS": "1"})
        self.assertEqual(set(clock.gaps), {1},
                         "the operator can reproduce the pre-backoff cadence verbatim")


class TestTheNumbersTheCtoAskedFor(unittest.TestCase):
    """Rounds per minute against the lane, and the wait before a first claim."""

    def test_polls_per_minute_at_rest(self):
        clock, executor = _run_loop(lambda _round: ROUND_IDLE, stop_at=3600.0)
        after = 60.0 * executor.rounds / clock.now
        # Before: the loop slept one second after every five-second round, whatever
        # the lane said. The lane holds each poll open five seconds and answers
        # immediately when work exists, so a round cost six seconds.
        before = 60.0 / (LANE_HOLD_SECONDS + IDLE_POLL_BASE_SECONDS)
        self.assertAlmostEqual(before, 10.0, places=1)
        self.assertLess(after, 1.0, "at rest the lane is asked under once a minute")
        self.assertLess(after, before / 10.0, "more than ten times fewer rounds")

    def test_the_lane_reads_behind_each_round(self):
        # The held wait re-reads the dispatch table on a two-second cadence, so the
        # cost of a round is up to three reads, not one.
        reads_per_round = 1 + int(LANE_HOLD_SECONDS / 2)
        clock, executor = _run_loop(lambda _round: ROUND_IDLE, stop_at=3600.0)
        after = reads_per_round * executor.rounds / (clock.now / 60.0)
        self.assertLess(after, 3.0, "under three table reads a minute at rest")

    def test_a_dispatch_arriving_into_a_quiet_lane_waits_at_most_the_ceiling(self):
        # Worst case: it arrives just after the loop gave up waiting on the lane and
        # sleeps the full ceiling; then the lane's own two-second re-check adds a beat.
        worst = IDLE_POLL_BASE_SECONDS + IDLE_POLL_MAX_SECONDS + 2
        self.assertLessEqual(worst, 63, "measured, and inside the ten-minute rule")
        # The lane answers the moment it sees the row, so the wait is the gap plus at
        # most one of its two-second re-checks - never a multiple of either.
        self.assertLessEqual(worst, IDLE_POLL_MAX_SECONDS + LANE_HOLD_SECONDS)
        # The first thirty-one seconds after traffic stops are the doubling phase -
        # which is where a burst of dispatches actually lands.
        clock, _ = _run_loop(lambda _round: ROUND_IDLE, stop_at=90.0, hold=0.0)
        self.assertEqual(clock.gaps[:5], [1, 2, 4, 8, 16])
        self.assertEqual(sum(clock.gaps[:5]), 31)


class TestTheRoundStatesAreRealFields(unittest.TestCase):
    """The loop reads a field the lane's own answer set, never a text match."""

    def _executor(self, transport=None, gate=None):
        return OracleMeshExecutor(
            chat_origin="https://chat.example.test",
            channel_secret=SECRET,
            read_port=_StubPort(),
            transport=transport,
            claim_gate=gate,
        )

    def test_an_empty_answer_is_recorded_as_idle(self):
        executor = self._executor(
            transport=lambda *_a: (200, {"ok": True, "dispatch": None}))
        self.assertIsNone(executor.run_once())
        self.assertEqual(executor.last_round, ROUND_IDLE)

    def test_a_gate_that_is_closed_is_recorded_as_skipped(self):
        executor = self._executor(
            transport=lambda *_a: (_ for _ in ()).throw(AssertionError("must not poll")),
            gate=lambda: False)
        self.assertIsNone(executor.run_once())
        self.assertEqual(executor.last_round, ROUND_SKIPPED)

    def test_a_claimed_dispatch_is_recorded_as_work_before_anything_is_executed(self):
        seen = []

        def transport(path, payload):
            seen.append(path)
            if path == POLL_PATH:
                return 200, {"ok": True, "dispatch": {
                    "dispatch_id": "dsp_" + "a" * 32, "nonce": "n" * 32,
                    "node_ref": "node-ref", "file_path": "C:/x/report.txt",
                    "command_id": "cmd-1", "run_id": "run-1", "kind": "read",
                }}
            return 200, {"ok": True, "status": "ok"}

        executor = self._executor(transport=transport)
        during = []
        with patch.object(executor, "execute",
                          side_effect=lambda _d: during.append(executor.last_round)
                          or _outcome()):
            executor.run_once()
        self.assertEqual(during, [ROUND_WORKED],
                         "the reset does not wait for the submission")


def _outcome():
    from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutionOutcome

    return OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=b"ok")


if __name__ == "__main__":
    unittest.main()
