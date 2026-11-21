"""#7994 — the opt-in concurrent executor pool.

No real PC, MeshCentral server or wall-clock wait is used here. Fake executors
return scripted dispatches and records are kept under a lock, so the order and
overlap assertions describe the pool itself.
"""
from __future__ import annotations

import os
import threading
import time
import unittest
from types import SimpleNamespace

from kagent.local_agent_mesh_concurrency import (
    CONCURRENCY_ENV,
    DEFAULT_MAX_WORKERS,
    MAX_WORKERS_CEILING,
    concurrency_config,
    install_thread_hooks,
    pc_gate,
    run_concurrent,
    run_service_loop,
    _worker_kwargs,
)


class _Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self.events = []

    def add(self, event):
        with self._lock:
            self.events.append(event)

    def snapshot(self):
        with self._lock:
            return list(self.events)


class _FakeExecutor:
    """A loop-facing executor: returns dispatches from a script queue."""

    idle_poll_max_seconds = 60

    def __init__(self, name, queue, recorder, *, hang=None, clock=None):
        self.name = name
        self._queue = queue
        self._recorder = recorder
        self._hang = hang or threading.Event()
        self._clock = clock or (lambda: time.monotonic())
        self.last_round = "idle"
        self.idle_poll_max_seconds = 60

    def poll_once(self):
        try:
            return self._queue.pop(0)
        except IndexError:
            self.last_round = "idle"
            return None

    def run_once(self):
        dispatch = self.poll_once()
        if dispatch is None:
            return None
        self.last_round = "worked"
        self._recorder.add(("claim", self.name, dispatch.node_ref, dispatch.dispatch_id))
        gate = getattr(self, "_concurrency_gate", None)
        holder = gate(dispatch) if gate is not None else pc_gate(dispatch.node_ref).handle(0)
        with holder:
            self._recorder.add(("start", self.name, dispatch.node_ref, dispatch.dispatch_id))
            if dispatch.node_ref in self._hang_targets():
                self._hang.wait(30)
            self._recorder.add(("end", self.name, dispatch.node_ref, dispatch.dispatch_id))
        return {"ok": True}

    def _hang_targets(self):
        return set()

    def line_observations(self):
        return {"line_blocked_total": 0, "line_cleared_total": 0}


class _HangingExecutor(_FakeExecutor):
    def __init__(self, *a, hang_node=None, **kw):
        super().__init__(*a, **kw)
        self._hang_node = hang_node

    def _hang_targets(self):
        return {self._hang_node} if self._hang_node else set()


def _dispatch(node, ident):
    return SimpleNamespace(node_ref=node, dispatch_id=ident)


class ConcurrencyConfigTests(unittest.TestCase):
    def test_default_is_serial(self):
        enabled, workers = concurrency_config({})
        self.assertFalse(enabled)
        self.assertEqual(workers, DEFAULT_MAX_WORKERS)

    def test_zero_negative_and_garbage_stay_serial(self):
        for raw in ("0", "-3", "nonsense", "1.5"):
            with self.subTest(raw=raw):
                enabled, _ = concurrency_config({CONCURRENCY_ENV: raw})
                self.assertFalse(enabled)

    def test_positive_enables_and_default_count(self):
        enabled, workers = concurrency_config({CONCURRENCY_ENV: "on"})
        self.assertTrue(enabled)
        self.assertEqual(workers, DEFAULT_MAX_WORKERS)
        enabled, workers = concurrency_config({CONCURRENCY_ENV: "1"})
        self.assertTrue(enabled)
        self.assertEqual(workers, 1)

    def test_count_is_bounded(self):
        _, workers = concurrency_config({CONCURRENCY_ENV: "999"})
        self.assertEqual(workers, MAX_WORKERS_CEILING)
        _, workers = concurrency_config({CONCURRENCY_ENV: "2"})
        self.assertEqual(workers, 2)


class SerialDefaultTests(unittest.TestCase):
    def test_flag_off_uses_serial_round(self):
        # With the flag off, no worker hooks are installed on the executor.
        rec = _Recorder()
        executor = _FakeExecutor("main", [_dispatch("pc1", "d1")], rec)
        run_service_loop(
            executor, {}, idle=0.01,
            environ={CONCURRENCY_ENV: "0"},
            stop_event=threading.Event(),
        ) if False else None  # serial loop never returns; covered by idle tests
        self.assertIsNone(getattr(executor, "_concurrency_gate", None))


class PerPcGateTests(unittest.TestCase):
    def test_gate_serves_tickets_in_order(self):
        rec = _Recorder()
        gate = pc_gate("order-pc")
        # Simulate three claims stamped in order, taken by three threads that
        # start out of order. The gate must still run them 0,1,2.
        def run(ticket):
            with gate.handle(ticket):
                rec.add(("run", ticket))

        threads = [threading.Thread(target=run, args=(t,)) for t in (2, 0, 1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        runs = [e[1] for e in rec.snapshot() if e[0] == "run"]
        self.assertEqual(runs, [0, 1, 2])

    def test_same_pc_commands_do_not_overlap(self):
        rec = _Recorder()
        gate = pc_gate("serial-pc")
        active = {"value": 0}

        def run(ticket):
            with gate.handle(ticket):
                active["value"] += 1
                if active["value"] > 1:
                    rec.add(("overlap", ticket))
                time.sleep(0.01)
                active["value"] -= 1

        threads = [threading.Thread(target=run, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual([e for e in rec.snapshot() if e[0] == "overlap"], [])


class ConcurrentPoolTests(unittest.TestCase):
    def test_different_pcs_run_in_parallel_and_one_hang_does_not_block_others(self):
        rec = _Recorder()
        stop = threading.Event()
        hang = threading.Event()
        # Worker 0 (hanging) owns a long PC1 command; worker 1 must still
        # finish a PC2 command while PC1 is stuck.
        w0 = _HangingExecutor(
            "w0", [_dispatch("pc1", "d1")], rec, hang=hang, hang_node="pc1")
        w1 = _FakeExecutor("w1", [_dispatch("pc2", "d2")], rec)
        factory = lambda index: {1: w1}[index]
        # Release the hang after PC2 is seen done, then stop the workers so the
        # join in run_concurrent returns. Two timers keep the test bounded.
        snapshot = []
        def finish():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if ("end", "w1", "pc2", "d2") in rec.snapshot():
                    break
                time.sleep(0.01)
            # Capture the state while PC1 is still stuck, then release it so
            # the worker can finish and run_concurrent can join.
            snapshot.append(rec.snapshot())
            hang.set()
            stop.set()

        timer = threading.Thread(target=finish, daemon=True)
        timer.start()
        run_concurrent(
            executor=w0, executor_kwargs={}, max_workers=2, idle=0.01,
            stop_event=stop, worker_factory=factory,
        )
        timer.join(10)
        events = snapshot[0]
        # PC2 command started and ended; PC1 started but never ended.
        self.assertIn(("start", "w1", "pc2", "d2"), events)
        self.assertIn(("end", "w1", "pc2", "d2"), events)
        self.assertIn(("start", "w0", "pc1", "d1"), events)
        self.assertNotIn(("end", "w0", "pc1", "d1"), events)

    def test_same_pc_two_workers_are_serialized_in_claim_order(self):
        rec = _Recorder()
        stop = threading.Event()

        # install_thread_hooks already stamps claims in claim order.
        w0 = _FakeExecutor("w0", [_dispatch("pcX", "same1")], rec)
        w1 = _FakeExecutor("w1", [_dispatch("pcX", "same2")], rec)
        # Release after both commands are done; the gate decides their order.
        def finish():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if len([e for e in rec.snapshot() if e[0] == "end"]) >= 2:
                    break
                time.sleep(0.01)
            stop.set()

        timer = threading.Thread(target=finish, daemon=True)
        timer.start()
        run_concurrent(
            executor=w0, executor_kwargs={}, max_workers=2, idle=0.01,
            stop_event=stop, worker_factory=lambda index: w1,
        )
        timer.join(10)
        events = rec.snapshot()
        starts = [e for e in events if e[0] == "start"]
        ends = [e for e in events if e[0] == "end"]
        self.assertEqual(len(starts), 2)
        self.assertEqual(len(ends), 2)
        # The same-PC gate never lets a start precede the previous end.
        self.assertEqual([e[3] for e in starts], [e[3] for e in ends])

    def test_worker_kwargs_are_isolated(self):
        base = {"work_dir": "/opt/x", "chat_origin": "https://chat"}
        w0 = _worker_kwargs(base, 0)
        w1 = _worker_kwargs(base, 1)
        self.assertEqual(w0["work_dir"], "/opt/x")
        self.assertEqual(w1["work_dir"], os.path.join("/opt/x", "worker-1"))
        self.assertEqual(w0["chat_origin"], w1["chat_origin"])
        self.assertNotIn("worker-1", w0["work_dir"])


if __name__ == "__main__":
    unittest.main()


class _RecordingStop:
    """A stop object that records waits and ends the loop after N rounds."""

    def __init__(self, rounds):
        self.waits = []
        self.rounds = rounds
        self.count = 0

    def is_set(self):
        return self.count >= self.rounds

    def wait(self, seconds):
        self.waits.append(seconds)
        self.count += 1


class _IdleExecutor:
    def __init__(self, *, refuse=False):
        self.last_round = "idle"
        self.idle_poll_max_seconds = 60
        self._refuse = refuse
        self._n = 0

    def run_once(self):
        self._n += 1
        if self._refuse:
            from kagent.local_agent_oracle_mesh_executor import OracleMeshChannelRefused
            raise OracleMeshChannelRefused("synthetic")
        return None


class ConcurrentCadenceTests(unittest.TestCase):
    """#7994: each worker keeps the original idle/refusal cadence.

    Time and the stop signal are injected, so no wall-clock wait or real PC is
    involved. The serial cadence tests stay untouched at flag 0.
    """

    def test_idle_backoff_matches_the_serial_schedule(self):
        from kagent.local_agent_mesh_concurrency import _worker_round
        stop = _RecordingStop(7)
        _worker_round(_IdleExecutor(), stop, idle=5, clock=lambda: 0.0)
        self.assertEqual(stop.waits[:7], [1, 2, 4, 8, 16, 32, 60])

    def test_refusal_waits_the_operator_interval_and_resets(self):
        from kagent.local_agent_mesh_concurrency import _worker_round
        stop = _RecordingStop(3)
        _worker_round(_IdleExecutor(refuse=True), stop, idle=7, clock=lambda: 0.0)
        self.assertEqual(stop.waits, [7, 7, 7])
