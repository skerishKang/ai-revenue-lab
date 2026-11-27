"""#7994 — feature-flagged concurrent execution for the Oracle mesh executor.

The serial service loop is the default. ``ORACLE_MESH_CONCURRENCY`` (default 0)
turns on N workers (default 3, ceiling 16). With the flag on:

* each worker owns its own executor, and therefore its own ``urllib`` opener,
  pending result and background directory — nothing mutable is shared between
  threads except the two registries below;
* a process-wide, per-PC FIFO gate lets one command run on a PC at a time, in
  claim order, while different PCs run in parallel;
* each worker keeps the original idle/refusal cadence, so a silent queue backs
  off exactly as the serial loop did.

The flag is read once at startup. Zero, a negative value or a non-integer keeps
the serial loop byte-for-byte, so an existing deployment sees no change until
an operator opts in.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from typing import Any, Callable, Optional

from .local_agent_oracle_mesh_executor import (
    IDLE_HEARTBEAT_SECONDS,
    IDLE_POLL_BASE_SECONDS,
    ROUND_IDLE,
    OracleMeshChannelRefused,
    channel_refusal_line,
)

#: Opt-in switch. 0 (the default) is the serial loop every deployment runs today.
CONCURRENCY_ENV = "ORACLE_MESH_CONCURRENCY"
#: Workers when the switch is on but no count is named.
DEFAULT_MAX_WORKERS = 3
#: A typo must not start hundreds of clients against one host.
MAX_WORKERS_CEILING = 16
#: A gate ticket whose owner never advances is skipped after this long, so one
#: dead worker cannot wedge every later command aimed at the same PC.
GATE_WAIT_SECONDS = 300.0
#: A claim that waited longer than this for its PC's turn writes one journal line
#: (#8727): a healthy gate is nearly instant, so a long wait is a leaked ticket.
GATE_WAIT_LOG_SECONDS = 10.0


def concurrency_config(env: Any = None) -> tuple[bool, int]:
    """Return ``(enabled, max_workers)``; anything not a positive int is serial."""

    source = os.environ if env is None else env
    raw = str(source.get(CONCURRENCY_ENV, "") or "").strip()
    if not raw:
        return False, DEFAULT_MAX_WORKERS
    try:
        count = int(raw)
    except (TypeError, ValueError):
        if raw.lower() in {"on", "true", "yes"}:
            return True, DEFAULT_MAX_WORKERS
        return False, DEFAULT_MAX_WORKERS
    if count <= 0:
        return False, DEFAULT_MAX_WORKERS
    return True, min(count, MAX_WORKERS_CEILING)


def _log_gate_wait(waited: float, skipped: bool, label: str, ticket: int) -> None:
    """One journal line for a claim that waited long for its PC's turn (#8727).

    Counts and a dispatch id only: no PC reference, path, command or secret.
    Logging is observational, so a broken stderr never changes the outcome.
    """

    try:
        safe = re.sub(r"[^A-Za-z0-9_.:-]", "?", str(label or ""))[:64] or "-"
        print(
            "oracle-mesh-gate waited_ms=%d skipped=%d ticket=%d dispatch_id=%s"
            % (int(waited * 1000), 1 if skipped else 0, ticket, safe),
            file=sys.stderr, flush=True,
        )
    except Exception:
        pass


class _GateHandle:
    """A re-entrant-safe handle on a per-PC gate, acquired in claim order."""

    def __init__(
        self, gate: "_PcGate", ticket: int, label: str = "",
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._gate = gate
        self._ticket = ticket
        self._label = label
        self._clock = clock or time.monotonic
        self._held = False

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        del blocking, timeout
        started = self._clock()
        skipped = self._gate._await_turn(self._ticket)
        self._held = True
        waited = self._clock() - started
        if waited > GATE_WAIT_LOG_SECONDS:
            _log_gate_wait(waited, skipped, self._label, self._ticket)
        return True

    def release(self) -> None:
        if self._held:
            self._gate._advance(self._ticket)
            self._held = False

    def __enter__(self) -> "_GateHandle":
        self.acquire()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()


class _PcGate:
    """One command at a time per PC, served in the order claims were stamped."""

    def __init__(self, *, wait_seconds: float = GATE_WAIT_SECONDS) -> None:
        self._cond = threading.Condition()
        self._serving = 0  # per-PC tickets start at zero and are served in order
        self._wait = wait_seconds

    def handle(
        self, ticket: int, label: str = "",
        clock: Optional[Callable[[], float]] = None,
    ) -> _GateHandle:
        return _GateHandle(self, ticket, label, clock)

    def _await_turn(self, ticket: int) -> bool:
        """Wait for this ticket's turn; True when a dead ticket had to be skipped."""

        skipped = False
        with self._cond:
            while ticket > self._serving:
                if not self._cond.wait(timeout=self._wait):
                    # The owner never advanced. Skip its ticket rather than
                    # wedge every later command for this PC.
                    if ticket > self._serving:
                        self._serving = ticket
                        self._cond.notify_all()
                        skipped = True
        return skipped

    def _advance(self, ticket: int) -> None:
        with self._cond:
            if ticket >= self._serving:
                self._serving = ticket + 1
            self._cond.notify_all()


_gates_guard = threading.Lock()
_gates: dict[str, _PcGate] = {}


def pc_gate(node_ref: str) -> _PcGate:
    with _gates_guard:
        return _gates.setdefault(node_ref, _PcGate())


_claims_guard = threading.Lock()
_pc_sequences: dict[str, int] = {}
_claim_tickets: dict[int, int] = {}


def _stamp_claim(dispatch: Any) -> None:
    if dispatch is None:
        return
    node = getattr(dispatch, "node_ref", "")
    with _claims_guard:
        ticket = _pc_sequences.get(node, 0)
        _pc_sequences[node] = ticket + 1
        _claim_tickets[id(dispatch)] = ticket


def _claimed_ticket(dispatch: Any) -> int:
    """The per-PC ticket stamped when this dispatch was claimed."""

    with _claims_guard:
        return _claim_tickets.pop(id(dispatch), 0)


def install_thread_hooks(executor: Any) -> None:
    """Give one worker executor its own claim stamps and per-PC gate.

    ``poll_once`` is wrapped so a claim is stamped while the global claim lock
    is still held: a dispatch claimed first is always served first on its PC.
    ``run_once`` is expected to consult ``_concurrency_gate`` around execution.

    A background claim (``pc_shell`` and friends) is never stamped (#8727):
    ``run_once`` hands it to the background manager and returns before the gate,
    so its ticket would never be served or released and the next ordinary
    command on that PC would wait out the whole ``GATE_WAIT_SECONDS`` for it.
    Background work keeps running outside this gate exactly as before.
    """

    original_poll = executor.poll_once

    def stamped_poll_once():
        dispatch = original_poll()
        if not getattr(dispatch, "background", False):
            _stamp_claim(dispatch)
        return dispatch

    executor.poll_once = stamped_poll_once
    executor._concurrency_gate = lambda dispatch: pc_gate(
        dispatch.node_ref).handle(
            _claimed_ticket(dispatch), label=getattr(dispatch, "dispatch_id", ""))


def _is_channel_refusal(exc: BaseException) -> bool:
    """True for an ``OracleMeshChannelRefused`` from either copy of its module.

    The service runs as ``python -m kagent.local_agent_oracle_mesh_executor``,
    so worker 0 is built from the ``__main__`` copy of that module while this
    module imports the ``kagent.`` copy: the two classes share a name but not
    an identity, and ``isinstance`` misses the refusal worker 0 raises (#8727).
    The executor already tells its own refusals apart by class name elsewhere.
    """

    return isinstance(exc, OracleMeshChannelRefused) or any(
        cls.__name__ == "OracleMeshChannelRefused" for cls in type(exc).__mro__)


def loop_failure_line(exc: BaseException) -> str:
    """The journal line for a round that raised: the refusal line, or a class name.

    A refusal keeps its established wording. Any other exception prints its
    class only, never the message, which may carry a path or a value.
    """

    if _is_channel_refusal(exc):
        return channel_refusal_line(exc)
    return "oracle-mesh-executor round error type=%s" % type(exc).__name__


def _serial_round(executor: Any, idle: float) -> None:
    """The original service loop for the flag-off path.

    Its cadence is unchanged, and so is its contract: an unexpected exception
    ends the service so systemd restarts it (the entrypoint tests stop this loop
    that way). Only a channel refusal is retried after ``idle`` — from either
    copy of the executor module (#8727: the ``__main__`` copy's class was not
    the one caught here, so every refused poll ended the service).
    """

    gap = IDLE_POLL_BASE_SECONDS
    idle_reported_at = None
    while True:
        try:
            result = executor.run_once()
        except Exception as exc:
            if not _is_channel_refusal(exc):
                raise
            print(loop_failure_line(exc), file=sys.stderr)
            gap = IDLE_POLL_BASE_SECONDS
            time.sleep(idle)
            continue
        if result is None:
            if (executor.last_round == ROUND_IDLE
                    and (idle_reported_at is None
                         or time.monotonic() - idle_reported_at >= IDLE_HEARTBEAT_SECONDS)):
                print("oracle-mesh-executor poll idle", flush=True)
                idle_reported_at = time.monotonic()
            time.sleep(gap)
            gap = (IDLE_POLL_BASE_SECONDS if executor.last_round != ROUND_IDLE
                   else min(gap * 2, executor.idle_poll_max_seconds))
            continue
        gap = IDLE_POLL_BASE_SECONDS
        observations = executor.line_observations()
        print(
            f"oracle-mesh-executor result ok={result.get('ok')} "
            f"retryable={result.get('retryable', False)} "
            f"quarantined={result.get('quarantined', False)} "
            f"line_blocked_total={observations['line_blocked_total']} "
            f"line_cleared_total={observations['line_cleared_total']}",
            flush=True,
        )
        if result.get("ok") is True:
            continue
        wait = result.get("wait_seconds") if isinstance(result, dict) else None
        if not isinstance(wait, int) or isinstance(wait, bool):
            wait = idle
        time.sleep(max(1, min(wait, 300)))


def _worker_round(
    executor: Any, stop: threading.Event, idle: float, clock: Callable[[], float],
) -> None:
    """One worker's poll/execute loop; cadence matches the serial loop.

    ``stop.wait`` replaces ``time.sleep`` so a stopped worker need not finish a
    backoff before exiting. The registered clock drives the idle heartbeat so
    a test can advance time without sleeping.

    A round that raises never ends the worker (#8727): a channel refusal from
    either copy of the executor module, or any other exception, is logged and
    the worker retries after ``idle``. A dead worker thread left its watchdog
    to restart the whole service 300 s later, cutting every PC's running work.
    """

    gap = IDLE_POLL_BASE_SECONDS
    idle_reported_at = None
    while not stop.is_set():
        try:
            result = executor.run_once()
        except Exception as exc:
            print(loop_failure_line(exc), file=sys.stderr)
            gap = IDLE_POLL_BASE_SECONDS
            stop.wait(idle)
            continue
        if result is None:
            if (executor.last_round == ROUND_IDLE
                    and (idle_reported_at is None
                         or clock() - idle_reported_at >= IDLE_HEARTBEAT_SECONDS)):
                print("oracle-mesh-executor poll idle", flush=True)
                idle_reported_at = clock()
            stop.wait(gap)
            gap = (IDLE_POLL_BASE_SECONDS if executor.last_round != ROUND_IDLE
                   else min(gap * 2, executor.idle_poll_max_seconds))
            continue
        gap = IDLE_POLL_BASE_SECONDS
        observations = executor.line_observations()
        print(
            f"oracle-mesh-executor result ok={result.get('ok')} "
            f"retryable={result.get('retryable', False)} "
            f"quarantined={result.get('quarantined', False)} "
            f"line_blocked_total={observations['line_blocked_total']} "
            f"line_cleared_total={observations['line_cleared_total']}",
            flush=True,
        )
        if result.get("ok") is True:
            continue
        wait = result.get("wait_seconds") if isinstance(result, dict) else None
        if not isinstance(wait, int) or isinstance(wait, bool):
            wait = idle
        stop.wait(max(1, min(wait, 300)))


def _worker_kwargs(base: dict[str, Any], index: int) -> dict[str, Any]:
    """Worker 0 keeps the configured work dir; others get a private one.

    Background receipts are not claimed atomically, so two workers reading the
    same directory could submit one result twice. A private directory per
    additional worker keeps that state isolated. Worker 0 keeps the original
    directory so a pending result from a serial restart is still delivered.
    """

    if index == 0:
        return dict(base)
    kwargs = dict(base)
    work_dir = base.get("work_dir")
    if work_dir:
        kwargs["work_dir"] = os.path.join(str(work_dir), "worker-%d" % index)
    return kwargs


def run_concurrent(
    *,
    executor: Any,
    executor_kwargs: dict[str, Any],
    max_workers: int,
    idle: float,
    stop_event: Optional[threading.Event] = None,
    clock: Optional[Callable[[], float]] = None,
    worker_factory: Optional[Callable[[int], Any]] = None,
) -> threading.Event:
    """Start N workers and join them. ``executor`` is worker 0.

    Tests inject ``worker_factory``, ``clock`` and ``stop_event`` so no real PC
    or wall-clock wait is involved. Production builds additional workers from
    ``executor_kwargs`` and lets each own its watchdog.
    """

    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    clock = clock or time.monotonic
    stop = stop_event or threading.Event()
    workers = [executor]
    if worker_factory is None:
        from .local_agent_oracle_mesh_executor import make_oracle_mesh_executor

        def worker_factory(index):  # noqa: F811 - production default
            built = make_oracle_mesh_executor(**_worker_kwargs(executor_kwargs, index))
            built.start_channel_watchdog()
            return built

    workers.extend(worker_factory(i) for i in range(1, max_workers))
    for worker in workers:
        install_thread_hooks(worker)
    threads = [
        threading.Thread(
            target=_worker_round, args=(worker, stop, idle, clock),
            name="oracle-mesh-worker-%d" % index, daemon=True,
        )
        for index, worker in enumerate(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return stop


def run_service_loop(
    executor: Any, executor_kwargs: dict[str, Any], *, idle: float, environ: Any = None,
) -> None:
    """Dispatch to the serial loop (flag off) or the worker pool (flag on)."""

    enabled, max_workers = concurrency_config(environ)
    if not enabled:
        return _serial_round(executor, idle)
    return run_concurrent(
        executor=executor, executor_kwargs=executor_kwargs,
        max_workers=max_workers, idle=idle,
    )


__all__ = [
    "CONCURRENCY_ENV",
    "DEFAULT_MAX_WORKERS",
    "MAX_WORKERS_CEILING",
    "concurrency_config",
    "install_thread_hooks",
    "loop_failure_line",
    "pc_gate",
    "run_concurrent",
    "run_service_loop",
    "_worker_kwargs",
]
