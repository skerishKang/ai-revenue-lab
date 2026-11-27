"""#8727 — the PC gate leaked a ticket for every background claim, and worker 0 died.

Daily Real Usage Check run 45909981570 (2026-11-26): a COM2 ``pc_read`` sat 300.0 s
between ``claimed`` and its first PC call while the PC answered in 1.04 s. The cause
is the per-PC FIFO gate of #7994:

* every claim was stamped with a per-PC ticket in ``poll_once``, but a background
  claim (``pc_shell`` / ``pc_shell_start``) returns from ``run_once`` before the gate
  is ever taken, so its ticket was never served or released and the next ordinary
  command on that PC waited ``GATE_WAIT_SECONDS`` for it;
* worker 0 is built from the ``__main__`` copy of the executor module (the service
  runs ``python -m ...``), while the loop caught the ``kagent.`` copy's
  ``OracleMeshChannelRefused``: a different class, so the refusal killed the thread
  and the watchdog restarted the whole service 300 s later.

No real PC, MeshCentral server, queue or long wait is used: fakes and injected clocks.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

import kagent.local_agent_mesh_concurrency as concurrency
from kagent.local_agent_mesh_concurrency import (
    GATE_WAIT_LOG_SECONDS,
    _PcGate,
    _worker_round,
    install_thread_hooks,
    loop_failure_line,
    pc_gate,
)
from kagent.local_agent_mesh_unexpected_failure import unexpected_failure_outcome
from kagent.local_agent_oracle_mesh_executor import (
    PC_FILE_READ_FAILED_MARKER,
    POLL_PATH,
    RESULT_PATH,
    OracleMeshChannelRefused,
    OracleMeshExecutionOutcome,
    OracleMeshExecutor,
)

SECRET = "deployment-channel-secret-value-8727"
CHAT = "http://127.0.0.1:8798"
EDGE = "com2-edge-proof-secret-" + "e" * 32
SECRET_TEXT = "C:/Users/someone/very-private-8727.txt"


def _claim(node, ident, *, background=False):
    return types.SimpleNamespace(node_ref=node, dispatch_id=ident, background=background)


class _ScriptedPoll:
    """Just enough executor for the hooks: ``poll_once`` hands out scripted claims."""

    def __init__(self, claims):
        self._claims = list(claims)

    def poll_once(self):
        return self._claims.pop(0) if self._claims else None


class _GateRegistryCase(unittest.TestCase):
    """Node references are unique per test; the process-wide registries are cleaned."""

    def setUp(self):
        self.node = "node-8727-%s" % self.id().rsplit(".", 1)[-1]
        self.addCleanup(self._forget_node)

    def _forget_node(self):
        with concurrency._gates_guard:
            concurrency._gates.pop(self.node, None)
        with concurrency._claims_guard:
            concurrency._pc_sequences.pop(self.node, None)


class BackgroundClaimLeavesNoTicketTests(_GateRegistryCase):
    def test_a_plain_command_after_a_background_claim_does_not_wait(self):
        bg = _claim(self.node, "dsp-bg", background=True)
        plain = _claim(self.node, "dsp-plain")
        executor = _ScriptedPoll([bg, plain])
        install_thread_hooks(executor)
        # The background claim is handed to the background manager; run_once returns
        # before the gate, so the gate is never taken for it.
        self.assertIs(executor.poll_once(), bg)
        self.assertIs(executor.poll_once(), plain)

        entered = threading.Event()

        def run_plain():
            with executor._concurrency_gate(plain):
                entered.set()

        thread = threading.Thread(target=run_plain, daemon=True)
        thread.start()
        # Healthy: immediate. With the leak this blocks for GATE_WAIT_SECONDS (300 s).
        self.assertTrue(
            entered.wait(5),
            "the plain claim waited for a ticket a background claim never released",
        )
        thread.join(5)

    def test_a_background_claim_is_never_stamped(self):
        before = dict(concurrency._claim_tickets)
        executor = _ScriptedPoll([_claim(self.node, "dsp-bg-2", background=True)])
        install_thread_hooks(executor)
        executor.poll_once()
        self.assertEqual(concurrency._claim_tickets, before)
        self.assertNotIn(self.node, concurrency._pc_sequences)

    def test_plain_claims_around_a_background_claim_still_run_one_at_a_time_in_order(self):
        first = _claim(self.node, "dsp-a")
        bg = _claim(self.node, "dsp-bg", background=True)
        second = _claim(self.node, "dsp-b")
        worker_one = _ScriptedPoll([first, bg])
        worker_two = _ScriptedPoll([second])
        install_thread_hooks(worker_one)
        install_thread_hooks(worker_two)
        # Claim order: a, then the background claim, then b.
        worker_one.poll_once()
        worker_one.poll_once()
        worker_two.poll_once()

        events, lock = [], threading.Lock()

        def record(event):
            with lock:
                events.append(event)

        def run_second():
            with worker_two._concurrency_gate(second):
                record("b_start")
                time.sleep(0.05)
                record("b_end")

        thread_b = threading.Thread(target=run_second, daemon=True)
        thread_b.start()  # b asks first, but a was claimed first
        time.sleep(0.2)
        with lock:
            self.assertEqual(events, [], "b ran before a, which was claimed first")
        with worker_one._concurrency_gate(first):
            record("a_start")
            time.sleep(0.1)
            record("a_end")
        thread_b.join(5)
        self.assertFalse(thread_b.is_alive())
        self.assertEqual(events, ["a_start", "a_end", "b_start", "b_end"])


class GateWaitJournalTests(unittest.TestCase):
    @staticmethod
    def _wait(clock_values, *, ticket=1, label="dsp-wait-8727"):
        """Acquire a ticket that has to be skipped (instant: the gate wait is 50 ms)."""
        gate = _PcGate(wait_seconds=0.05)
        values = iter(clock_values)
        handle = gate.handle(ticket, label=label, clock=lambda: next(values))
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            handle.acquire()
        return journal.getvalue()

    def test_a_wait_over_ten_seconds_writes_one_line_without_secrets(self):
        line = self._wait([0.0, 300.4])
        self.assertEqual(len(line.splitlines()), 1, line)
        self.assertTrue(line.startswith("oracle-mesh-gate "), line)
        for field in ("waited_ms=300400", "skipped=1", "ticket=1", "dispatch_id=dsp-wait-8727"):
            self.assertIn(field, line)

    def test_the_line_reports_a_wait_that_ended_in_its_turn_as_not_skipped(self):
        gate = _PcGate(wait_seconds=30.0)
        values = iter([0.0, 12.0])
        handle = gate.handle(0, label="dsp-turn", clock=lambda: next(values))
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            handle.acquire()
        self.assertIn("skipped=0", journal.getvalue())
        self.assertIn("waited_ms=12000", journal.getvalue())

    def test_ten_seconds_or_less_writes_nothing(self):
        self.assertEqual(GATE_WAIT_LOG_SECONDS, 10.0)
        self.assertEqual(self._wait([0.0, 0.2]), "")
        self.assertEqual(self._wait([5.0, 15.0]), "", "exactly ten seconds is not over ten")

    def test_the_label_cannot_forge_a_journal_line(self):
        line = self._wait([0.0, 99.0], label="dsp\nFORGED line=1 " + "x" * 200)
        self.assertEqual(len(line.splitlines()), 1, line)
        # The newline and the spaces became "?": the text cannot start a second field.
        self.assertIn("dispatch_id=dsp?FORGED?line?1?", line)
        self.assertNotIn(" FORGED", line)
        self.assertLessEqual(len(line), 200)

    def test_a_broken_stderr_never_changes_the_outcome(self):
        gate = _PcGate(wait_seconds=0.05)
        values = iter([0.0, 99.0])
        handle = gate.handle(1, label="dsp-x", clock=lambda: next(values))
        with mock.patch.object(sys, "stderr", None):
            self.assertTrue(handle.acquire())


def _load_second_copy_of_the_executor_module():
    """What ``python -m kagent.local_agent_oracle_mesh_executor`` really creates:
    the service module is a second, separate copy of the canonical one."""
    name = "kagent._copy_for_8727"
    path = os.path.join(
        os.path.dirname(concurrency.__file__), "local_agent_oracle_mesh_executor.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


class _RecordingStop:
    def __init__(self, rounds):
        self.waits, self.rounds, self.count = [], rounds, 0

    def is_set(self):
        return self.count >= self.rounds

    def wait(self, seconds):
        self.waits.append(seconds)
        self.count += 1


class _RaisingExecutor:
    idle_poll_max_seconds = 60

    def __init__(self, exceptions):
        self._exceptions = list(exceptions)
        self.calls = 0
        self.last_round = "idle"

    def run_once(self):
        self.calls += 1
        if self._exceptions:
            raise self._exceptions.pop(0)
        return None


class WorkerSurvivesTests(unittest.TestCase):
    def test_the_service_module_copy_raises_a_class_the_loop_did_not_catch(self):
        copy = _load_second_copy_of_the_executor_module()
        # The cause, stated as a fact: same name, different identity.
        self.assertEqual(copy.OracleMeshChannelRefused.__name__, "OracleMeshChannelRefused")
        self.assertIsNot(copy.OracleMeshChannelRefused, OracleMeshChannelRefused)
        refusal = copy.OracleMeshChannelRefused("chat channel transport refused", leg="queue")
        self.assertNotIsInstance(refusal, OracleMeshChannelRefused)

    def test_a_worker_survives_a_refusal_from_the_service_module_copy(self):
        copy = _load_second_copy_of_the_executor_module()
        refusals = [copy.OracleMeshChannelRefused("chat channel transport refused", leg="queue")
                    for _ in range(3)]
        executor = _RaisingExecutor(refusals)
        stop = _RecordingStop(3)
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            _worker_round(executor, stop, idle=7, clock=lambda: 0.0)
        self.assertEqual(executor.calls, 3, "the worker stopped asking after a refusal")
        self.assertEqual(stop.waits, [7, 7, 7])
        self.assertEqual(
            journal.getvalue().count(
                "oracle-mesh-executor channel refusal: chat channel transport refused leg=queue"),
            3)

    def test_a_worker_keeps_polling_after_a_refusal(self):
        executor = _RaisingExecutor([OracleMeshChannelRefused("chat channel refused the poll")])
        stop = _RecordingStop(2)
        with contextlib.redirect_stderr(io.StringIO()):
            _worker_round(executor, stop, idle=5, clock=lambda: 0.0)
        self.assertEqual(executor.calls, 2)
        self.assertEqual(stop.waits, [5, 1])  # operator interval, then the idle schedule

    def test_any_other_exception_is_logged_by_class_only_and_the_worker_lives(self):
        executor = _RaisingExecutor([RuntimeError("secret " + SECRET_TEXT), KeyError(SECRET_TEXT)])
        stop = _RecordingStop(2)
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            _worker_round(executor, stop, idle=3, clock=lambda: 0.0)
        text = journal.getvalue()
        self.assertEqual(executor.calls, 2)
        self.assertIn("oracle-mesh-executor round error type=RuntimeError", text)
        self.assertIn("oracle-mesh-executor round error type=KeyError", text)
        self.assertNotIn(SECRET_TEXT, text)
        self.assertNotIn("secret", text)

    def test_the_serial_loop_also_survives_a_service_module_copy_refusal(self):
        copy = _load_second_copy_of_the_executor_module()
        executor = _RaisingExecutor([
            copy.OracleMeshChannelRefused("chat channel transport refused", leg="chat"),
            copy.OracleMeshChannelRefused("chat channel transport refused", leg="chat"),
        ])

        class _StopLoop(Exception):
            pass

        with contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(
                    concurrency.time, "sleep", side_effect=[None, _StopLoop()]):
                with self.assertRaises(_StopLoop):
                    concurrency._serial_round(executor, idle=4)
        self.assertEqual(executor.calls, 2, "the serial loop ended on the first refusal")

    def test_the_serial_loop_still_ends_on_an_unexpected_exception(self):
        # The flag-off contract the entrypoint tests rely on: only a refusal is
        # retried; anything else ends the service so systemd restarts it.
        class _Stop(Exception):
            pass

        executor = _RaisingExecutor([_Stop()])
        with contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(concurrency.time, "sleep", side_effect=AssertionError("slept")):
                with self.assertRaises(_Stop):
                    concurrency._serial_round(executor, idle=4)
        self.assertEqual(executor.calls, 1)

    def test_loop_failure_line_keeps_the_refusal_wording(self):
        line = loop_failure_line(OracleMeshChannelRefused("chat channel refused the poll", leg="chat"))
        self.assertEqual(
            line, "oracle-mesh-executor channel refusal: chat channel refused the poll leg=chat")


NODE = "node-ref-8727"


def _dispatch_dict(kind="read", ident="dsp-8727", **extra):
    base = {
        "dispatch_id": ident, "nonce": "n" * 32, "node_ref": NODE,
        "file_path": "C:/synthetic/night.txt", "command_id": "cmd-" + ident,
        "run_id": "run-" + ident, "kind": kind,
    }
    if kind == "command":
        base["command_text"] = "hostname"
    base.update(extra)
    return base


class _NeverCalledReadPort:
    def read_bytes(self, *, node_ref, file_path, timeout_seconds=60, max_bytes=1_048_576):
        raise AssertionError("execute is replaced in these tests")


def _executor():
    return OracleMeshExecutor(
        chat_origin=CHAT, channel_secret=SECRET, edge_secret=EDGE,
        read_port=_NeverCalledReadPort())


def _drive(executor, dispatch_dicts):
    """Run one ``run_once`` per scripted dispatch; return (reports, posts, journal)."""
    pending = list(dispatch_dicts)
    posts = []

    def transport(path, payload):
        posts.append((path, payload))
        if path == POLL_PATH:
            return 200, {"ok": True, "dispatch": pending.pop(0) if pending else None}
        return 200, {"ok": True, "accepted": True}

    executor._transport = transport
    journal = io.StringIO()
    reports = []
    with contextlib.redirect_stderr(journal):
        for _ in dispatch_dicts:
            reports.append(executor.run_once())
    return reports, posts, journal.getvalue()


def _raising(exc):
    def execute(dispatch):
        raise exc
    return execute


class OneFailedDispatchFailsAloneTests(unittest.TestCase):
    def test_a_read_that_raises_is_answered_read_failed_and_run_once_returns(self):
        executor = _executor()
        executor.execute = _raising(RuntimeError(SECRET_TEXT))
        reports, posts, journal = _drive(executor, [_dispatch_dict("read")])
        self.assertEqual(reports, [{"ok": True, "accepted": True}])
        results = [payload for path, payload in posts if path == RESULT_PATH]
        self.assertEqual(len(results), 1, "one answer for the one claimed dispatch")
        self.assertEqual(results[0]["termination"], "exited")
        self.assertEqual(results[0]["exit_code"], 1)
        self.assertEqual(results[0]["content_utf8"], PC_FILE_READ_FAILED_MARKER)

    def test_the_failure_is_traced_by_class_and_never_carries_the_message(self):
        executor = _executor()
        executor.execute = _raising(RuntimeError(SECRET_TEXT))
        _, posts, journal = _drive(executor, [_dispatch_dict("read")])
        line = next(l for l in journal.splitlines() if " phase=error " in l)
        self.assertIn("error_type=RuntimeError", line)
        self.assertIn("dsp-8727", line)
        self.assertNotIn(SECRET_TEXT, journal)
        self.assertNotIn(SECRET_TEXT, repr(posts))

    def test_a_command_lane_refusal_before_the_pc_is_answered_not_executed(self):
        # No command port: the real ``execute`` raises OracleMeshChannelRefused.
        executor = _executor()
        reports, posts, journal = _drive(executor, [_dispatch_dict("command")])
        result = next(payload for path, payload in posts if path == RESULT_PATH)
        self.assertEqual(result["termination"], "not_executed")
        self.assertIsNone(result["exit_code"])
        self.assertIn("error_type=OracleMeshChannelRefused", journal)
        self.assertEqual(reports, [{"ok": True, "accepted": True}])

    def test_an_unknown_command_failure_is_answered_no_reply_never_a_clean_exit(self):
        executor = _executor()
        executor.execute = _raising(ValueError("boom"))
        _, posts, _ = _drive(executor, [_dispatch_dict("command")])
        result = next(payload for path, payload in posts if path == RESULT_PATH)
        self.assertEqual(result["termination"], "no_reply")
        self.assertIsNone(result["exit_code"])

    def test_the_next_dispatch_after_a_failed_one_still_runs(self):
        executor = _executor()
        calls = []

        def execute(dispatch):
            calls.append(dispatch.dispatch_id)
            if len(calls) == 1:
                raise RuntimeError("first only")
            return OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=b"ok")

        executor.execute = execute
        reports, posts, _ = _drive(
            executor, [_dispatch_dict("read", "dsp-1"), _dispatch_dict("read", "dsp-2")])
        self.assertEqual(calls, ["dsp-1", "dsp-2"])
        results = [payload for path, payload in posts if path == RESULT_PATH]
        self.assertEqual([r["content_utf8"] for r in results], [PC_FILE_READ_FAILED_MARKER, "ok"])
        self.assertEqual(len(reports), 2)

    def test_lane_shapes_for_an_unexpected_failure(self):
        shape = lambda kind, exc: unexpected_failure_outcome(
            kind, exc, outcome_type=OracleMeshExecutionOutcome, read_failed_body=b"marker")
        self.assertEqual(
            (shape("read", RuntimeError()).termination, shape("read", RuntimeError()).exit_code,
             shape("read", RuntimeError()).body),
            ("exited", 1, b"marker"))
        self.assertEqual(shape("desktop", RuntimeError()).termination, "desktop_unavailable")
        self.assertEqual(
            shape("desktop", OracleMeshChannelRefused("x")).termination, "not_executed")
        self.assertEqual(shape("command", RuntimeError()).termination, "no_reply")
        self.assertEqual(
            shape("command", OracleMeshChannelRefused("x")).termination, "not_executed")


class RealExecutorBackgroundThenPlainTests(_GateRegistryCase):
    """The whole path with the real executor: poll_once, the hooks, run_once, the gate."""

    def test_a_read_right_after_a_background_command_on_the_same_pc_does_not_wait(self):
        node = self.node
        executor = _executor()
        install_thread_hooks(executor)
        started_background = []

        class _Manager:
            def start(self, payload, owner):
                started_background.append(payload["dispatch_id"])
                return {"job_id": payload["dispatch_id"]}

        executor._background_manager = lambda: _Manager()
        executed = []
        executor.execute = lambda dispatch: (
            executed.append(dispatch.dispatch_id)
            or OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=b"ok"))
        script = [
            _dispatch_dict("command", "dsp-bg", node_ref=node, background=True,
                           owner_ref="owner-ref-8727"),
            _dispatch_dict("read", "dsp-read", node_ref=node),
        ]
        posts = []
        pending = list(script)

        def transport(path, payload):
            posts.append(path)
            if path == POLL_PATH:
                return 200, {"ok": True, "dispatch": pending.pop(0) if pending else None}
            return 200, {"ok": True, "accepted": True}

        executor._transport = transport
        reports = []

        def two_rounds():
            with contextlib.redirect_stderr(io.StringIO()):
                reports.append(executor.run_once())  # the background claim
                reports.append(executor.run_once())  # the plain read on the same PC

        thread = threading.Thread(target=two_rounds, daemon=True)
        started = time.monotonic()
        thread.start()
        thread.join(10)
        self.assertFalse(
            thread.is_alive(),
            "the read waited on a ticket the background claim never released")
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(started_background, ["dsp-bg"])
        self.assertEqual(executed, ["dsp-read"])
        self.assertTrue(reports[0].get("background"))
        self.assertIn(RESULT_PATH, posts)


if __name__ == "__main__":
    unittest.main()
