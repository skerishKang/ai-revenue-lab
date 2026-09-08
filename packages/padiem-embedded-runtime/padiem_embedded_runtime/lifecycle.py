"""Minimal embedded shell lifecycle contract for IP-SIDECAR.

Valid journey: ``closed -> opening -> open -> closing -> closed``.
A ``disabled`` fail-safe state is reachable from any state; a disabled shell
performs no embedded work and every operation returns a host-safe result so
the host primary journey never breaks because of a sidecar failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .bootstrap import BootstrapConfig
from .errors import SidecarContractError

CLOSED = "closed"
OPENING = "opening"
OPEN = "open"
CLOSING = "closing"
DISABLED = "disabled"

STATES = frozenset({CLOSED, OPENING, OPEN, CLOSING, DISABLED})

_TRANSITIONS = {
    (CLOSED, "open"): OPENING,
    (OPENING, "opened"): OPEN,
    (OPEN, "close"): CLOSING,
    (CLOSING, "closed_event"): CLOSED,
}

_HOST_SAFE_FALLBACK = "host-primary-continue"


@dataclass
class HostSafeResult:
    """Outcome returned to the host; never raises, never leaks internals."""

    ok: bool
    state: str
    fallback: str = _HOST_SAFE_FALLBACK
    detail: str = ""

    def to_public_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "state": self.state,
            "fallback": self.fallback,
            "detail": self.detail,
        }


class EmbeddedShell:
    """One host-bound shell instance. No cross-instance (cross-tenant) state."""

    def __init__(self, config: BootstrapConfig) -> None:
        if not isinstance(config, BootstrapConfig):
            raise SidecarContractError("shell requires a validated BootstrapConfig")
        self._config = config
        self._state = CLOSED
        self._disable_reason = ""

    @property
    def host_id(self) -> str:
        return self._config.host_id

    @property
    def state(self) -> str:
        return self._state

    @property
    def disable_reason(self) -> str:
        return self._disable_reason

    def _move(self, action: str) -> str:
        if self._state == DISABLED:
            raise SidecarContractError(f"shell is disabled; action {action!r} refused")
        try:
            nxt = _TRANSITIONS[(self._state, action)]
        except KeyError:
            raise SidecarContractError(
                f"illegal shell transition: {self._state!r} + {action!r}"
            ) from None
        self._state = nxt
        return nxt

    def open(self) -> str:
        """closed -> opening."""
        return self._move("open")

    def opened(self) -> str:
        """opening -> open."""
        return self._move("opened")

    def close(self) -> str:
        """open -> closing."""
        return self._move("close")

    def closed_event(self) -> str:
        """closing -> closed."""
        return self._move("closed_event")

    def disable(self, reason: str = "") -> HostSafeResult:
        """Enter fail-safe disabled state from any state."""
        if not isinstance(reason, str):
            raise SidecarContractError("disable reason must be text")
        self._disable_reason = reason[:160]
        self._state = DISABLED
        return HostSafeResult(ok=True, state=self._state, detail="shell disabled")

    def enable(self) -> str:
        """Re-arm a disabled shell back to closed (never directly to open)."""
        if self._state != DISABLED:
            raise SidecarContractError("enable is only valid from disabled")
        self._state = CLOSED
        self._disable_reason = ""
        return self._state

    def fail(self, summary: str = "") -> HostSafeResult:
        """Record a bounded failure summary and fail over to disabled.

        The host primary journey must continue; only a bounded,
        non-internal summary is retained.
        """
        if not isinstance(summary, str):
            summary = ""
        self._disable_reason = summary[:160]
        self._state = DISABLED
        return HostSafeResult(ok=False, state=self._state, detail=self._disable_reason)

    def guard_open_interaction(self) -> Optional[HostSafeResult]:
        """Return None when interaction is allowed, else a host-safe result."""
        if self._state == OPEN:
            return None
        if self._state == DISABLED:
            return HostSafeResult(ok=False, state=self._state, detail="shell disabled")
        return HostSafeResult(ok=False, state=self._state, detail="shell not open")
