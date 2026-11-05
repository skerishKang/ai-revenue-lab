"""#6923: when the Chat event loop stops running, say so, and say what it was doing.

2026-11-05 15:11:23-15:12:11 KST the com2 Chat process ran nothing for 47 s.
Every request in flight finished in the same 200 ms afterwards, the queue RPC
reported ``WriteTimeout`` at 47.5 s on an 8 s timer, and the executor's result
submits got 504 from the edge. The host, the P01 engine and the executor kept
logging, so only this process was blocked. The journal holds no line from
inside the stall, so what blocked the loop is unknown. This module makes the
next stall diagnosable:

* a heartbeat task sleeps ``tick_seconds`` and journals one line when it wakes
  more than ``lag_threshold_seconds`` late (the loop was blocked or starved);
* ``faulthandler.dump_traceback_later`` is re-armed on every heartbeat, so
  when the loop is blocked longer than ``stall_dump_seconds`` the interpreter's
  own watchdog thread writes every thread's stack to stderr (journald). That
  dump is file names, line numbers and function names only: no request data,
  no local variables.

The journal line carries durations only.
"""
from __future__ import annotations

import asyncio
import faulthandler
import os
import sys
import time
from typing import Any, Callable, Mapping

__all__ = [
    "LAG_THRESHOLD_SECONDS",
    "LoopStallWatchdog",
    "STALL_DUMP_SECONDS",
    "TICK_SECONDS",
    "WATCHDOG_ENV",
    "install",
    "watchdog_enabled",
]

#: Heartbeat period.
TICK_SECONDS = 1.0
#: A wake-up later than this is a stall worth one journal line.
LAG_THRESHOLD_SECONDS = 2.0
#: After this long without a heartbeat, every thread's stack is dumped.
STALL_DUMP_SECONDS = 10.0
#: ``off`` / ``0`` / ``false`` disables the watchdog on a host.
WATCHDOG_ENV = "PADIEM_CHAT_LOOP_STALL_WATCHDOG"


def watchdog_enabled(env: Mapping[str, str] | None = None) -> bool:
    raw = (env if env is not None else os.environ).get(WATCHDOG_ENV, "")
    return str(raw or "").strip().lower() not in {"0", "off", "false", "no"}


def _journal(line: str) -> None:
    print(line, flush=True)


class LoopStallWatchdog:
    """Heartbeat plus stack dump; see the module docstring."""

    def __init__(
        self,
        *,
        tick_seconds: float = TICK_SECONDS,
        lag_threshold_seconds: float = LAG_THRESHOLD_SECONDS,
        stall_dump_seconds: float | None = STALL_DUMP_SECONDS,
        journal: Callable[[str], None] = _journal,
        monotonic: Callable[[], float] = time.monotonic,
        arm_dump: Callable[..., Any] = faulthandler.dump_traceback_later,
        cancel_dump: Callable[[], Any] = faulthandler.cancel_dump_traceback_later,
    ) -> None:
        self._tick = max(0.001, float(tick_seconds))
        self._lag_threshold = max(0.0, float(lag_threshold_seconds))
        self._stall_dump = (
            None if stall_dump_seconds is None or float(stall_dump_seconds) <= 0
            else float(stall_dump_seconds)
        )
        self._journal = journal
        self._monotonic = monotonic
        self._arm_dump = arm_dump
        self._cancel_dump = cancel_dump
        self.stalls = 0
        self.worst_lag_ms = 0
        self.dump_armed = False

    def _arm(self) -> None:
        if self._stall_dump is None:
            return
        try:
            # ``repeat=True``: a stall longer than two dump periods leaves two
            # dumps, so a very long block is still visible as one. Never exit.
            self._arm_dump(self._stall_dump, repeat=True, file=sys.stderr, exit=False)
            self.dump_armed = True
        except (RuntimeError, ValueError, OSError, AttributeError):
            # No usable stderr (closed, replaced by a non-file object): the
            # heartbeat still runs, only the dump is skipped.
            self.dump_armed = False

    def _disarm(self) -> None:
        if not self.dump_armed:
            return
        self.dump_armed = False
        try:
            self._cancel_dump()
        except Exception:  # noqa: BLE001 - shutdown must never raise
            pass

    async def run(self) -> None:
        try:
            while True:
                self._arm()
                before = self._monotonic()
                await asyncio.sleep(self._tick)
                lag = self._monotonic() - before - self._tick
                if lag < self._lag_threshold:
                    continue
                self.stalls += 1
                lag_ms = int(lag * 1000)
                self.worst_lag_ms = max(self.worst_lag_ms, lag_ms)
                self._journal(
                    "[local] loop_stall lag_ms=%d tick_ms=%d stalls=%d worst_lag_ms=%d"
                    % (lag_ms, int(self._tick * 1000), self.stalls, self.worst_lag_ms)
                )
        finally:
            self._disarm()


def install(app: Any, *, env: Mapping[str, str] | None = None,
            watchdog_factory: Callable[[], LoopStallWatchdog] = LoopStallWatchdog) -> bool:
    """Start the watchdog with the app and stop it with the app.

    Mirrors the WAL checkpoint loop in ``local_cpython``: one task per event
    loop, bound to the Starlette app given here (the write-freeze wrapper that
    later replaces ``app`` has no ``.state``). Returns whether it was installed.
    """

    if not watchdog_enabled(env):
        print("[local] loop_stall_watchdog=off")
        return False

    tasks: dict[asyncio.AbstractEventLoop, asyncio.Task[None]] = {}

    async def _start(app=app):
        loop = asyncio.get_running_loop()
        current = tasks.get(loop)
        if current is not None and not current.done():
            app.state.loop_stall_watchdog_task = current
            return
        watchdog = watchdog_factory()
        task = loop.create_task(watchdog.run(), name="loop_stall_watchdog")
        tasks[loop] = task
        app.state.loop_stall_watchdog = watchdog
        app.state.loop_stall_watchdog_task = task
        print("[local] loop_stall_watchdog=on tick_ms=%d lag_threshold_ms=%d stall_dump_s=%s" % (
            int(watchdog._tick * 1000), int(watchdog._lag_threshold * 1000),
            "off" if watchdog._stall_dump is None else int(watchdog._stall_dump)))

    async def _stop(app=app):
        task = tasks.pop(asyncio.get_running_loop(), None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if getattr(app.state, "loop_stall_watchdog_task", None) is task:
            app.state.loop_stall_watchdog_task = None

    app.router.on_startup.append(_start)
    app.router.on_shutdown.append(_stop)
    return True
