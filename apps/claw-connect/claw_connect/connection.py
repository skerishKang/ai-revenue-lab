"""Claw Connect connection state machine (#4139 S1, non-production verified).

The tray shows one of four states and never claims a state it did not
observe. Every transition is explicit and auditable:

    DISCONNECTED -> CONNECTING -> CONNECTED
    CONNECTED    -> PAUSED   (user pause)
    PAUSED       -> CONNECTING (user resume / reconnect)
    any          -> DISCONNECTED (network loss, quit, disconnect)

Network reachability is injected as a probe so the offline tests never touch a
real socket, and the tray never fakes ``CONNECTED`` on its own authority.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

#: Bound reconnect backoff (seconds). Cap keeps a dead network from spinning.
BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 15.0)
MAX_BACKOFF_SECONDS = 15.0


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    PAUSED = "paused"


#: Allowed transitions. Anything else is a programming error and refused.
_ALLOWED: dict[ConnectionState, frozenset[ConnectionState]] = {
    ConnectionState.DISCONNECTED: frozenset({ConnectionState.CONNECTING}),
    ConnectionState.CONNECTING: frozenset(
        {ConnectionState.CONNECTED, ConnectionState.DISCONNECTED}
    ),
    ConnectionState.CONNECTED: frozenset(
        {ConnectionState.PAUSED, ConnectionState.DISCONNECTED, ConnectionState.CONNECTING}
    ),
    ConnectionState.PAUSED: frozenset(
        {ConnectionState.CONNECTING, ConnectionState.DISCONNECTED}
    ),
}


class InvalidTransition(RuntimeError):
    """Raised when a transition is not part of the Connect contract."""


class ConnectionController:
    """Owns the connection state and the bounded reconnect backoff."""

    def __init__(
        self,
        probe: Callable[[], bool] | None = None,
        *,
        backoff: tuple[float, ...] = BACKOFF_SECONDS,
    ) -> None:
        self._state = ConnectionState.DISCONNECTED
        self._probe = probe or (lambda: False)
        self._backoff = backoff
        self._attempt = 0

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def reconnect_delay(self) -> float:
        """Seconds to wait before the next reconnect attempt (bounded).

        ``0.0`` while no attempt has failed yet, so a healthy or freshly
        started connection never stalls.
        """
        if self._attempt == 0:
            return 0.0
        index = min(self._attempt - 1, len(self._backoff) - 1)
        return min(float(self._backoff[index]), MAX_BACKOFF_SECONDS)

    def _transition(self, target: ConnectionState) -> ConnectionState:
        if target not in _ALLOWED[self._state]:
            raise InvalidTransition(f"{self._state.value} -> {target.value}")
        self._state = target
        return self._state

    def connect(self) -> ConnectionState:
        """Start (or restart) a connection attempt."""
        if self._state is ConnectionState.CONNECTING:
            return self._state
        return self._transition(ConnectionState.CONNECTING)

    def succeed(self) -> ConnectionState:
        """The probe confirmed an authenticated session."""
        if self._state is not ConnectionState.CONNECTING:
            raise InvalidTransition(f"{self._state.value} -> connected")
        self._attempt = 0
        return self._transition(ConnectionState.CONNECTED)

    def fail(self) -> float:
        """Attempt failed; returns the bounded backoff for the next retry."""
        if self._state is ConnectionState.CONNECTING:
            self._transition(ConnectionState.DISCONNECTED)
        self._attempt += 1
        return self.reconnect_delay

    def pause(self) -> ConnectionState:
        """User pause: no automatic reconnect until the user resumes."""
        self._attempt = 0
        return self._transition(ConnectionState.PAUSED)

    def resume(self) -> ConnectionState:
        """User resume from a pause."""
        return self._transition(ConnectionState.CONNECTING)

    def disconnect(self) -> ConnectionState:
        """User disconnect or an observed network loss."""
        self._attempt = 0
        if self._state is ConnectionState.DISCONNECTED:
            return self._state
        if self._state is ConnectionState.CONNECTING:
            return self._transition(ConnectionState.DISCONNECTED)
        if self._state is ConnectionState.PAUSED:
            return self._transition(ConnectionState.DISCONNECTED)
        return self._transition(ConnectionState.DISCONNECTED)

    def poll(self) -> ConnectionState:
        """One background poll using the injected probe (never fakes a state)."""
        if self._state is ConnectionState.CONNECTING:
            if self._probe():
                return self.succeed()
            self.fail()
            return self._state
        if self._state is ConnectionState.CONNECTED and not self._probe():
            return self._transition(ConnectionState.DISCONNECTED)
        return self._state
