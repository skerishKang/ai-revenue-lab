"""Engine stage times for one orchestration request (#6772).

The line carries stage names, milliseconds and the bounded correlation tokens
the Engine already logs. It never carries a question, an answer, a subject, a
credential or an upstream body.
"""

from __future__ import annotations

import logging
import re
import sys
from time import perf_counter

LOG = logging.getLogger("padiem_ai_engine.engine_timing")
LOG.setLevel(logging.INFO)

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_OUTCOMES = frozenset({"ok", "refused", "error", "cancelled"})


def ensure_host_visible() -> None:
    """Make the stage line reach the COM2 journal.

    The CPython host configures no logging, so an application INFO record is
    created and then dropped. Bind one stderr handler exactly as the Chat host
    does for its own stage line; a Worker deployment is unaffected.
    """

    if LOG.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOG.addHandler(handler)
    LOG.propagate = False


def _token(value: object) -> str:
    if isinstance(value, str) and _SAFE_TOKEN.fullmatch(value):
        return value
    return "none"


def _ms(first: float | None, second: float | None) -> float:
    if first is None or second is None:
        return -1.0
    return max(0.0, (second - first) * 1000.0)


class EngineTiming:
    """Monotonic marks for one request; arguments are stage names only."""

    __slots__ = ("_started", "_marks", "_receipt_ms")

    def __init__(self) -> None:
        self._started = perf_counter()
        self._marks: dict[str, float] = {}
        self._receipt_ms = 0.0

    def mark(self, name: str) -> None:
        self._marks[name] = perf_counter()

    def add_receipt_since(self, started_at: float) -> None:
        self._receipt_ms += max(0.0, (perf_counter() - started_at) * 1000.0)

    def line(
        self,
        *,
        run_hash: object,
        trace_id: object,
        b14_ms: int,
        outcome: str,
        combined: bool = False,
    ) -> str:
        admission = _ms(self._marks.get("admission_start"), self._marks.get("admission_end"))
        core = _ms(self._marks.get("core_start"), self._marks.get("core_end"))
        total = _ms(self._started, perf_counter())
        safe_outcome = outcome if outcome in _OUTCOMES else "error"
        combined_field = " combined=true" if combined else ""
        return (
            "engine_timing"
            f" run_hash={_token(run_hash)}"
            f" trace_id={_token(trace_id)}"
            f" admission_ms={admission:.1f}"
            f" core_ms={core:.1f}"
            f" b14_ms={b14_ms if isinstance(b14_ms, int) and b14_ms >= 0 else -1}"
            f" receipt_ms={self._receipt_ms:.1f}"
            f" total_ms={total:.1f}"
            f" outcome={safe_outcome}"
            f"{combined_field}"
        )

    def emit(
        self,
        *,
        run_hash: object,
        trace_id: object,
        b14_ms: int,
        outcome: str,
        combined: bool = False,
    ) -> None:
        LOG.info(
            self.line(
                run_hash=run_hash,
                trace_id=trace_id,
                b14_ms=b14_ms,
                outcome=outcome,
                combined=combined,
            )
        )
