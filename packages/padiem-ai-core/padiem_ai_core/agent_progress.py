"""Progress-based liveness for long-running Agent/Task execution (#4194).

ZCode-parity contract: an Agent/Task run has **no fixed total wall clock**. It is
bounded instead by an *inactivity watchdog* that only fires when the run stops
making locally observed progress, plus the existing step/tool budgets, durable
lease fencing, approval expiry, quota/cost limits and user cancellation.

This module is deliberately metadata-only. A progress touch is *not* an
authorization, an approval, or proof of a side effect. It exists so a healthy
run that keeps working for hours (long model generations, many Tool steps) is
never force-failed merely because a fixed timer elapsed, while a genuinely
stalled run still fails closed inside the configured window.

The tracker never stores prompts, tool arguments, model output, credentials or
user identifiers; :meth:`AgentProgressTracker.snapshot` is safe to log.
"""

from __future__ import annotations

from collections.abc import Awaitable
import asyncio
import math
import re
import time
from typing import Any, Callable

_PHASE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")

#: Poll cadence for the progress-aware wait. This is a check interval, NOT a
#: deadline: it must never be used to shorten a healthy run.
DEFAULT_PROGRESS_POLL_SECONDS = 1.0


class AgentProgressError(ValueError):
    """Raised when a progress contract is violated."""


class AgentIdleTimeoutError(TimeoutError):
    """The run made no locally observed progress inside the idle window.

    Inherits :class:`TimeoutError`/:class:`asyncio.TimeoutError` so existing
    fail-closed timeout handling keeps working. This is an inactivity stall,
    never a fixed wall clock: a run that keeps progressing cannot raise it.
    """


class AgentProgressTracker:
    """Monotonic, non-sensitive liveness signal for one Agent/Task run."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        started_at: float | None = None,
    ) -> None:
        if not callable(clock):
            raise AgentProgressError("clock must be callable")
        self._clock = clock
        now = float(clock()) if started_at is None else float(started_at)
        self._started_at = now
        self._last_progress_at = now
        self._progress_count = 0
        self._last_phase = "run_start"

    def _now(self) -> float:
        return float(self._clock())

    def touch(self, phase: str) -> None:
        """Record verified local progress (a real step/tool/checkpoint event)."""
        if type(phase) is not str or not _PHASE_RE.fullmatch(phase):
            raise AgentProgressError("invalid progress phase")
        self._progress_count += 1
        self._last_phase = phase
        self._last_progress_at = self._now()

    @property
    def progress_count(self) -> int:
        return self._progress_count

    @property
    def last_phase(self) -> str:
        return self._last_phase

    def seconds_since_progress(self) -> float:
        return max(0.0, self._now() - self._last_progress_at)

    def elapsed_seconds(self) -> float:
        return max(0.0, self._now() - self._started_at)

    def remaining_idle_seconds(self, idle_seconds: float) -> float:
        window = _idle_window(idle_seconds)
        return max(0.0, window - self.seconds_since_progress())

    def idle_exceeded(self, idle_seconds: float) -> bool:
        return self.remaining_idle_seconds(idle_seconds) <= 0.0

    def snapshot(self) -> dict[str, Any]:
        """Non-sensitive observability payload; no prompt/output/identity."""
        return {
            "progress_count": self._progress_count,
            "last_phase": self._last_phase,
            "seconds_since_progress": self.seconds_since_progress(),
            "elapsed_seconds": self.elapsed_seconds(),
        }


def _idle_window(idle_seconds: float) -> float:
    if isinstance(idle_seconds, bool) or not isinstance(idle_seconds, (int, float)):
        raise AgentProgressError("idle_seconds must be a number")
    value = float(idle_seconds)
    if not math.isfinite(value) or value <= 0.0:
        raise AgentProgressError("idle_seconds must be a finite positive number")
    return value


async def await_with_agent_progress(
    awaitable: Awaitable[Any],
    *,
    tracker: AgentProgressTracker,
    idle_seconds: float,
    poll_interval: float = DEFAULT_PROGRESS_POLL_SECONDS,
) -> Any:
    """Await work under an inactivity watchdog instead of a fixed wall clock.

    The deadline is reset every time ``tracker`` observes verified progress, so
    a run that keeps working is never cut off by total elapsed time. Only a
    genuine no-progress stall raises :class:`AgentIdleTimeoutError`.

    Cancellation from the caller (user cancel, request abort, lease loss) is
    propagated to the inner awaitable, and the inner awaitable's own transport
    idle/connect timeouts remain authoritative for its network calls.
    """
    if not isinstance(tracker, AgentProgressTracker):
        raise AgentProgressError("tracker must be AgentProgressTracker")
    window = _idle_window(idle_seconds)
    cadence = _idle_window(poll_interval)
    task: asyncio.Future[Any] = asyncio.ensure_future(awaitable)
    try:
        while True:
            if task.done():
                return task.result()
            remaining = tracker.remaining_idle_seconds(window)
            if remaining <= 0.0:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise AgentIdleTimeoutError(
                    "Agent run made no verified progress inside the idle window"
                )
            await asyncio.wait({task}, timeout=min(remaining, cadence))
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise


AGENT_PROGRESS_IS_NOT_AUTHORIZATION = True
AGENT_PROGRESS_REPLACES_FIXED_WALL_CLOCK = True
