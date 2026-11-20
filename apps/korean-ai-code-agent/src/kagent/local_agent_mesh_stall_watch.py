"""#8140 — detect a connected-but-idle MeshAgent and alert once per node.

An executor can keep its server session alive while the local agent stops
running commands: runcommands are sent, the terminal opens, then every file
tool ends in ``silent_timeout`` with ``line_probe_unobserved``. The server and
executor are healthy; only the agent process is wedged.

This module is deliberately transport-free and clock-injected. It records a
suspicion from consecutive failure phases on the same node, emits at most one
notice until that node succeeds again, and never restarts anything. The
operator-side PowerShell hint is text only — this code cannot and does not
execute it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

#: Phase names that mean "connected but ran nothing" (from command phases).
FAILURE_PHASES = frozenset({"silent_timeout", "line_probe_unobserved"})
SUCCESS_PHASE = "success"

#: Consecutive failures within this window before an agent is called stuck.
DEFAULT_THRESHOLD = 3
DEFAULT_WINDOW_SECONDS = 600.0

#: Text-only operator guidance. No process/service control is performed here.
RESTART_HINT = '관리자 PowerShell: Restart-Service "Mesh Agent"'

_MAX_NODE_CHARS = 60


def _safe_node(name: object) -> str:
    """Bounded display label; never the full node id or a token."""
    if not isinstance(name, str):
        return "unknown-node"
    text = "".join(ch if (ch.isprintable() and ch not in "\r\n\t") else " " for ch in name)
    text = " ".join(text.split()).strip()
    if not text:
        return "unknown-node"
    # A node id/token is long and hex-like; a display name is short. Keep only a
    # short prefix so an accidental id can never be echoed in full.
    return text[:_MAX_NODE_CHARS]


@dataclass
class StallNotice:
    node: str
    last_success: str | None
    failures: int
    title: str
    guide: str = RESTART_HINT

    def as_event(self) -> dict:
        """#8105-shaped payload: only a display name and last success time."""
        return {
            "title": self.title,
            "node": self.node,
            "last_success": self.last_success or "unknown",
            "failures": self.failures,
            "guide": self.guide,
        }


@dataclass
class _NodeState:
    failures: int = 0
    first_failure_at: float = 0.0
    last_success: str | None = None
    alerted: bool = False


class MeshStallWatch:
    """Per-node consecutive-failure tracker with injected clock and notifier.

    ``now`` is a callable returning epoch seconds; ``notify`` receives one
    :class:`StallNotice` per stuck episode. Both are injected so tests never
    sleep and never touch a real alert transport.
    """

    def __init__(self, *, now: Callable[[], float], notify: Callable[[StallNotice], None],
                 threshold: int = DEFAULT_THRESHOLD,
                 window_seconds: float = DEFAULT_WINDOW_SECONDS):
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._now = now
        self._notify = notify
        self._threshold = threshold
        self._window = window_seconds
        self._nodes: dict[str, _NodeState] = {}

    def observe(self, node: object, phase: str, *, at: float | None = None) -> StallNotice | None:
        """Feed one observed phase; return the notice when an alert is emitted."""
        key = _safe_node(node)
        moment = self._now() if at is None else at
        state = self._nodes.setdefault(key, _NodeState())

        if phase == SUCCESS_PHASE:
            state.failures = 0
            state.alerted = False
            state.last_success = _stamp(moment)
            return None

        if phase not in FAILURE_PHASES:
            return None

        # A gap longer than the window breaks the run of consecutive failures.
        if state.failures == 0 or moment - state.first_failure_at > self._window:
            state.failures = 0
            state.first_failure_at = moment
        state.failures += 1

        if state.failures < self._threshold or state.alerted:
            return None

        state.alerted = True
        notice = StallNotice(
            node=key,
            last_success=state.last_success,
            failures=state.failures,
            title=f"MeshAgent 멈춤 의심: {key}",
        )
        self._notify(notice)
        return notice


def _stamp(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "FAILURE_PHASES", "SUCCESS_PHASE", "RESTART_HINT",
    "StallNotice", "MeshStallWatch",
]
