"""#8140 — detect a connected-but-idle MeshAgent and alert once per node.

An executor can keep its server session alive while the local agent stops
running commands: runcommands are sent, the terminal opens, then every file
tool ends in ``silent_timeout`` with ``line_probe_unobserved``. The server and
executor are healthy; only the agent process is wedged.

This module owns the detection, the one-per-episode dedup, and the loopback
notice to the local Chat service. It is clock-injected and transport-injected
so tests never sleep and never touch a real service. It never restarts anything.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

#: Command phase names (from local_agent_mesh_command_phases) that mean
#: "connected but ran nothing", and the result phase that means the agent
#: answered again (recovery).
FAILURE_PHASES = frozenset({"silent_timeout", "line_probe_unobserved"})
RECOVERY_PHASE = "result"

DEFAULT_THRESHOLD = 3
DEFAULT_WINDOW_SECONDS = 600.0
NOTIFY_PATH = "/api/ops/notify-event"
NOTIFY_KEY_ENV = "PADIEM_OPS_NOTIFY_KEY_PC"
NOTIFY_TIMEOUT_SECONDS = 3.0
NOTIFY_SITE = "pc"
NOTIFY_KIND = "agent_stall"

#: Text-only operator guidance. This code never executes it.
RESTART_HINT = '관리자 PowerShell: Restart-Service "Mesh Agent"'

_MAX_LABEL_CHARS = 60


def display_name(node_ref: object) -> str:
    """A bounded label from the node ref; never the full node id or a token.

    A MeshCentral node id looks like ``NAME$suffix``. Use only the part before
    ``$``, capped; when there is no separator use a short digest prefix so an
    opaque id is never echoed whole.
    """
    if not isinstance(node_ref, str) or not node_ref.strip():
        return "unknown-node"
    ref = node_ref.strip()
    label = ref.split("$", 1)[0].strip() if "$" in ref else hashlib.sha256(
        ref.encode("utf-8")).hexdigest()[:12]
    label = " ".join(label.split())
    return (label or "unknown-node")[:_MAX_LABEL_CHARS]


def _stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def source_id(label: str, suspicion_start: float) -> str:
    """Stable id for one suspicion episode: label + when it began."""
    identity = json.dumps([label, round(suspicion_start, 3)], separators=(",", ":"))
    return "stall_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


@dataclass
class StallNotice:
    node: str
    last_success: str | None
    failures: int
    suspicion_start: float
    title: str
    source_id: str = ""
    guide: str = RESTART_HINT

    def event(self) -> dict:
        """The #8130 ingress payload: label + last success time only."""
        return {
            "site": NOTIFY_SITE,
            "kind": NOTIFY_KIND,
            "audience": "real",
            "title": self.title,
            "source_id": self.source_id or source_id(self.node, self.suspicion_start),
        }


@dataclass
class _NodeState:
    failures: int = 0
    first_failure_at: float = 0.0
    last_success: str | None = None
    alerted: bool = False


class MeshStallWatch:
    """Per-node consecutive-failure tracker with injected clock and notifier."""

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
        key = display_name(node)
        moment = self._now() if at is None else at
        state = self._nodes.setdefault(key, _NodeState())

        if phase == RECOVERY_PHASE:
            state.failures = 0
            state.alerted = False
            state.last_success = _stamp(moment)
            return None
        if phase not in FAILURE_PHASES:
            return None

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
            suspicion_start=state.first_failure_at,
            title=f"PC 에이전트 응답 없음: {key}",
            source_id=source_id(key, state.first_failure_at),
        )
        self._notify(notice)
        return notice


def loopback_notify(notice: StallNotice, *, origin: str, opener=None,
                    timeout: float = NOTIFY_TIMEOUT_SECONDS) -> bool:
    """POST one notice to the local Chat ingress. No key => no send.

    Never raises: a notification failure must not touch executor behavior.
    ``opener`` is injected for tests (no real network, no sleep).
    """
    key = os.environ.get(NOTIFY_KEY_ENV, "")
    if not key:
        return False
    url = origin.rstrip("/") + NOTIFY_PATH
    body = json.dumps(notice.event(), ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"content-type": "application/json", "X-Padiem-Ops-Notify-Key": key},
    )
    try:
        opener = opener or urllib.request.urlopen
        with opener(request, timeout=timeout):
            return True
    except Exception:
        return False


#: One bridge per process, created lazily so importing the executor has zero
#: side effects and no environment is read at import time.
_BRIDGE: MeshStallWatch | None = None


def get_bridge() -> MeshStallWatch:
    """Process-wide watcher wired to the loopback notifier.

    Origin/key are resolved at send time (loopback_notify), never at import,
    so a machine with no key sends nothing and nothing fails at startup.
    """
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = MeshStallWatch(now=lambda: __import__("time").time(),
                                 notify=lambda notice: loopback_notify(
                                     notice, origin=_loopback_origin()))
    return _BRIDGE


def _loopback_origin() -> str:
    import os
    return os.environ.get("PADIEM_MESH_CHAT_ORIGIN", "http://127.0.0.1:8788")


def bridge_observe(node_ref: object, phase: str) -> None:
    """Best-effort hook called from the executor's single phase funnel.

    Never raises: detection/notification must not affect command execution.
    """
    try:
        (_BRIDGE or get_bridge()).observe(node_ref, phase)
    except Exception:
        pass


def set_bridge_for_test(watch: MeshStallWatch | None) -> None:
    """Inject a clock/notifier-bound watcher; tests never touch a real service."""
    global _BRIDGE
    _BRIDGE = watch


__all__ = [
    "FAILURE_PHASES", "RECOVERY_PHASE", "RESTART_HINT", "NOTIFY_KEY_ENV",
    "StallNotice", "MeshStallWatch", "display_name", "source_id", "loopback_notify",
    "bridge_observe", "get_bridge", "set_bridge_for_test",
]
