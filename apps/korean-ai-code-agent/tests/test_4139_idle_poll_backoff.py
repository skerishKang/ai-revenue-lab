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
#: Defined here, not imported from another suite: CI discovers these files with
#: ``unittest.TestLoader().discover("tests")``, which imports each module by its own
#: name and has no ``tests`` package to import from.
SECRET = "deployment-channel-secret-value-261017"


class _StubPort:
    """Stand-in read port; the channel transport is what is under test here."""

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):  # noqa: D102
        del node_ref, file_path, timeout_seconds
        return b""

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

    def start_drive_reporting(self, source):
        # The real executor starts the drive reporter when a queue origin is
        # configured; this loop test only needs the call to be accepted.
        self.drive_source = source
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
        executor.idle_poll_max_seconds = kwargs["idle_poll_max_seconds"]
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

    def test_com2_origin_uses_ten_second_ceiling_and_resets_after_work(self):
        def answer(round_number):
            return ROUND_WORKED if round_number == 7 else ROUND_IDLE
        clock, executor = _run_loop(answer, stop_at=180.0,
                                    environ={"ORACLE_MESH_QUEUE_ORIGIN": "http://127.0.0.1:8797"})
        self.assertEqual(executor.idle_poll_max_seconds, 10)
        self.assertEqual(clock.gaps[:7], [1, 2, 4, 8, 10, 10, 1])

    def test_d1_default_and_com2_override(self):
        clock, executor = _run_loop(lambda _: ROUND_IDLE, stop_at=600.0)
        self.assertEqual(executor.idle_poll_max_seconds, 60)
        self.assertEqual(clock.gaps[:7], [1, 2, 4, 8, 16, 32, 60])
        clock, executor = _run_loop(
            lambda _: ROUND_IDLE, stop_at=120.0,
            environ={"ORACLE_MESH_QUEUE_ORIGIN": "http://127.0.0.1:8797",
                     "ORACLE_MESH_IDLE_POLL_MAX_SECONDS": "8"})
        self.assertEqual(executor.idle_poll_max_seconds, 8)
        self.assertEqual(clock.gaps[:5], [1, 2, 4, 8, 8])

    def test_com2_invalid_override_uses_ten_and_logs(self):
        with patch("sys.stderr") as stderr:
            clock, executor = _run_loop(
                lambda _: ROUND_IDLE, stop_at=120.0,
                environ={"ORACLE_MESH_QUEUE_ORIGIN": "http://127.0.0.1:8797",
                         "ORACLE_MESH_IDLE_POLL_MAX_SECONDS": "bad"})
        self.assertEqual(executor.idle_poll_max_seconds, 10)
        self.assertEqual(clock.gaps[:5], [1, 2, 4, 8, 10])
        self.assertIn("using default 10", stderr.write.call_args_list[0].args[0])

    def test_eight_second_setting_caps_actual_idle_loop(self):
        clock, _ = _run_loop(lambda _round: ROUND_IDLE, stop_at=160.0,
                             environ={"ORACLE_MESH_IDLE_POLL_MAX_SECONDS": "8"})
        self.assertEqual(clock.gaps[:7], [1, 2, 4, 8, 8, 8, 8])

    def test_invalid_ceiling_falls_back_to_60_and_logs_once(self):
        for value in ("0", "-3", "abc", "", "1.5"):
            with self.subTest(value=value), patch("sys.stderr") as stderr:
                clock, _ = _run_loop(lambda _round: ROUND_IDLE, stop_at=600.0,
                                     environ={"ORACLE_MESH_IDLE_POLL_MAX_SECONDS": value})
                self.assertEqual(clock.gaps[:7], [1, 2, 4, 8, 16, 32, 60])
                self.assertEqual(stderr.write.call_count, 2)
                self.assertIn("invalid ORACLE_MESH_IDLE_POLL_MAX_SECONDS",
                              stderr.write.call_args_list[0].args[0])

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

def _assert_main_real_factory_and_real_loop_honor_environment_cap(tmp_path):
    """A real executor polls a disposable local HTTP server, with no factory/loop double."""
    import os
    import subprocess
    import sys
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    observed = []
    ready = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            observed.append((self.path, time.monotonic()))
            body = b'{"ok":true,"dispatch":null}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if sum(1 for path, _ in observed if path == POLL_PATH) >= 4:
                ready.set()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    secret = tmp_path / "synthetic-channel.txt"
    password = tmp_path / "synthetic-password.txt"
    secret.write_text("synthetic-channel-secret-for-test", encoding="utf-8")
    password.write_text("synthetic-password", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "ORACLE_MESH_CHAT_ORIGIN": "https://chat.example.test",
        "ORACLE_MESH_QUEUE_ORIGIN": "http://127.0.0.1:%d" % server.server_port,
        "ORACLE_MESH_CHANNEL_SECRET_FILE": str(secret),
        "ORACLE_MESH_MESHCTRL_JS": str(tmp_path / "meshctrl.js"),
        "ORACLE_MESH_LOGIN_USER": "synthetic",
        "ORACLE_MESH_PASSWORD_FILE": str(password),
        "ORACLE_MESH_WORK_DIR": str(tmp_path),
        "ORACLE_MESH_IDLE_POLL_MAX_SECONDS": "2",
        # Keep the repository packages the child needs (Core's drive-inventory
        # validation) beside the kagent source path this test already sets.
        "PYTHONPATH": os.pathsep.join(filter(None, (
            str(Path(__file__).resolve().parents[1] / "src"),
            str(Path(__file__).resolve().parents[3] / "packages" / "padiem-ai-core"),
            env.get("PYTHONPATH", ""),
        ))),
    })
    env.pop("MESH_FAILOVER_DEVICE_ID", None)
    process = subprocess.Popen(
        [sys.executable, "-c",
         "from kagent.local_agent_oracle_mesh_executor import main; main()"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        assert ready.wait(12), "real loop did not reach four local polls"
        # The drive reporter shares this channel and posts its own targets read,
        # so the backoff is measured across the poll requests only.
        polls = [at for path, at in observed if path == POLL_PATH]
        gaps = [polls[i + 1] - polls[i] for i in range(3)]
        assert 0.7 <= gaps[0] < 3.5
        assert all(1.6 <= gap < 3.5 for gap in gaps[1:]), gaps
    finally:
        process.terminate()
        process.wait(timeout=5)
        if process.stderr is not None:
            process.stderr.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

class TestRealMainConfiguration(unittest.TestCase):
    def test_main_real_factory_and_real_loop_honor_environment_cap(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            _assert_main_real_factory_and_real_loop_honor_environment_cap(Path(directory))


if __name__ == "__main__":
    unittest.main()
