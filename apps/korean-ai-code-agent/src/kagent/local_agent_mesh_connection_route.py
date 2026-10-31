"""#5485 — the connection route that makes the DEVICE follow the claim.

The failover controller owns **which host may claim a dispatch**. That is not
the whole lane: a remote command only runs if the target PC's MeshCentral
agent is connected to a server that owns the device.

This module owns the second half: **where the agent is pointed**.

The agent reaches MeshCentral through COM1's loopback forward, and the
agent's own configuration stays untouched. Both routes use the SAME local
address and the SAME forward mechanism, and they differ only in the
destination:

    com2     ssh -L 127.0.0.1:4443:127.0.0.1:4443  user@<com2>
    oracle   ssh -L 127.0.0.1:4443:127.0.0.1:443   ubuntu@<oracle>

Oracle presents the **same** agentserver certificate that COM2 presents, so
the agent accepts either endpoint and its device identity is the same on
both. That is why the route can be switched without touching the agent, and
why the device does not have to be re-enrolled.

The rule that matters for safety: **a route is not a permission**. The
target may only take the claim once its own probe says the device is
connected there. A "COM2 is back" signal on its own is not enough, because
the agent still has to travel back to COM2 and reconnect.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .contracts import ContractError

#: The two servers the agent can be pointed at.
TARGET_COM2 = "com2"
TARGET_ORACLE = "oracle"
ROUTE_TARGETS = (TARGET_COM2, TARGET_ORACLE)

#: The route events the operations vocabulary uses.
EVENT_ROUTE_TO_ORACLE = "ROUTE_TO_ORACLE"
EVENT_ROUTE_TO_COM2 = "ROUTE_TO_COM2"

#: The local address the agent is bound to. It never changes, so the agent's
#: own configuration never has to change either.
DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_LOCAL_PORT = 4443
DEFAULT_AGENT_URL = "wss://127.0.0.1:4443/agent.ashx"


@dataclass(frozen=True)
class ConnectionRoute:
    """One way for the agent's loopback to reach a MeshCentral server."""

    target: str
    #: The host the forward connects to.
    tunnel_host: str
    #: The port on that host the forward reaches.
    tunnel_port: int
    #: The account the forward authenticates as.
    tunnel_user: str
    #: The private key the forward uses.
    tunnel_key: str
    #: The local address the agent is bound to.
    local_host: str = DEFAULT_LOCAL_HOST
    #: The local port the agent is bound to.
    local_port: int = DEFAULT_LOCAL_PORT
    #: The url the agent is configured with. It is the same on every route.
    agent_url: str = DEFAULT_AGENT_URL

    def __post_init__(self) -> None:
        if self.target not in ROUTE_TARGETS:
            raise ContractError("the route target must be a known target")
        for name, value in (
            ("tunnel_host", self.tunnel_host),
            ("tunnel_user", self.tunnel_user),
            ("tunnel_key", self.tunnel_key),
            ("local_host", self.local_host),
            ("agent_url", self.agent_url),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"{name} is required")
        for name, value in (
            ("tunnel_port", self.tunnel_port),
            ("local_port", self.local_port),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ContractError(f"{name} must be a positive integer")

    def identity(self) -> str:
        """A stable key for "is the forward already pointing here?"."""
        return (
            f"{self.target}|{self.tunnel_user}@{self.tunnel_host}:{self.tunnel_port}"
            f"|{self.local_host}:{self.local_port}"
        )

    def tunnel_arguments(self) -> list[str]:
        """The forward arguments for this route.

        The same mechanism serves both routes, so the transport side has one
        shape to reason about. The password is never an argument; the key is.
        """
        return [
            "-N",
            "-T",
            "-i",
            self.tunnel_key,
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "ExitOnForwardFailure=yes",
            "-L",
            f"{self.local_host}:{self.local_port}:127.0.0.1:{self.tunnel_port}",
            f"{self.tunnel_user}@{self.tunnel_host}",
        ]


def com2_route(
    *,
    tunnel_host: str,
    tunnel_user: str,
    tunnel_key: str,
    tunnel_port: int = 4443,
    local_host: str = DEFAULT_LOCAL_HOST,
    local_port: int = DEFAULT_LOCAL_PORT,
) -> ConnectionRoute:
    """The primary route: COM2's own MeshCentral, over the existing forward."""
    return ConnectionRoute(
        target=TARGET_COM2,
        tunnel_host=tunnel_host,
        tunnel_port=tunnel_port,
        tunnel_user=tunnel_user,
        tunnel_key=tunnel_key,
        local_host=local_host,
        local_port=local_port,
    )


def oracle_route(
    *,
    tunnel_host: str,
    tunnel_user: str,
    tunnel_key: str,
    tunnel_port: int = 443,
    local_host: str = DEFAULT_LOCAL_HOST,
    local_port: int = DEFAULT_LOCAL_PORT,
) -> ConnectionRoute:
    """The standby route: Oracle's MeshCentral, over the same forward.

    The port is the TLS endpoint that presents the same agentserver
    certificate, so the agent's session is accepted unchanged.
    """
    return ConnectionRoute(
        target=TARGET_ORACLE,
        tunnel_host=tunnel_host,
        tunnel_port=tunnel_port,
        tunnel_user=tunnel_user,
        tunnel_key=tunnel_key,
        local_host=local_host,
        local_port=local_port,
    )


def claim_owner(
    route_target: str,
    *,
    com2_device_connected: bool,
    oracle_device_connected: bool,
) -> tuple[Optional[str], str]:
    """Who may claim a dispatch, given where the device actually is.

    The claim follows the **device**, not the route. The route is the
    instruction that moves the device; until the device has arrived, the
    server that still owns it keeps the claim.

    Returns the claim owner, or ``None`` when the device is connected
    nowhere, together with the reason the claim is held.

    This is the one place the rule lives. The controller and the router both
    use it, so the two can never disagree about who may execute.
    """
    if route_target not in ROUTE_TARGETS:
        raise ContractError("the route target must be a known target")
    for name, value in (
        ("com2_device_connected", com2_device_connected),
        ("oracle_device_connected", oracle_device_connected),
    ):
        if not isinstance(value, bool):
            raise ContractError(f"{name} must be a boolean")

    at_route = (
        com2_device_connected
        if route_target == TARGET_COM2
        else oracle_device_connected
    )
    other = (
        oracle_device_connected
        if route_target == TARGET_COM2
        else com2_device_connected
    )
    if at_route:
        return route_target, ""
    if other:
        return (
            TARGET_ORACLE if route_target == TARGET_COM2 else TARGET_COM2,
            "the device is still at the other server while the route travels",
        )
    return (
        None,
        "the device is not connected anywhere yet: the claim waits instead "
        "of being lost",
    )


@dataclass(frozen=True)
class RouteDecision:
    """Where the agent should be pointed, and who may claim."""

    route_target: str
    route_changed: bool
    route_events: tuple[str, ...]
    #: The target that may claim a dispatch, or None when nobody may yet.
    claim_target: Optional[str]
    #: Why the claim is held, when it is.
    claim_blocked_reason: str

    def claim_allowed(self) -> bool:
        return self.claim_target is not None


class MeshConnectionRouter:
    """Decides where the agent is pointed, and who may claim.

    The router is pure: it takes the observed facts and returns the decision.
    It never opens a connection and never reads a file.

    The two inputs that decide the claim are the two *device* facts:

    * ``com2_device_connected`` — COM2's own probe of its MeshCentral.
    * ``oracle_device_connected`` — Oracle's own probe of its MeshCentral.

    A target only takes the claim once its device is connected there. A
    "COM2 is back" signal on its own changes the route, not the claim: the
    agent still has to travel back and reconnect.
    """

    def __init__(
        self,
        *,
        com2: ConnectionRoute,
        oracle: ConnectionRoute,
        initial_target: str = TARGET_COM2,
    ) -> None:
        if not isinstance(com2, ConnectionRoute) or not isinstance(
            oracle, ConnectionRoute
        ):
            raise ContractError("both routes are required")
        if com2.target != TARGET_COM2 or oracle.target != TARGET_ORACLE:
            raise ContractError("the routes must be the com2 and oracle routes")
        if initial_target not in ROUTE_TARGETS:
            raise ContractError("the initial route target must be a known target")
        self._routes = {TARGET_COM2: com2, TARGET_ORACLE: oracle}
        self._target = initial_target

    @property
    def route_target(self) -> str:
        """Where the agent is pointed right now."""
        return self._target

    @property
    def current_route(self) -> ConnectionRoute:
        return self._routes[self._target]

    def route_for(self, target: str) -> ConnectionRoute:
        if target not in ROUTE_TARGETS:
            raise ContractError("the route target must be a known target")
        return self._routes[target]

    def evaluate(
        self,
        *,
        com2_restored: bool,
        com2_device_connected: bool,
        oracle_device_connected: bool,
    ) -> RouteDecision:
        """Decide the route and the claim owner once.

        The three inputs are three different facts and must not be collapsed:

        * ``com2_restored`` — COM2 says it is healthy again. This is a
          **signal**, and it only moves the route. The agent still has to
          travel back and reconnect.
        * ``com2_device_connected`` — COM2's own probe says the device is
          connected to COM2 right now.
        * ``oracle_device_connected`` — Oracle's own probe says the device is
          connected to Oracle right now.

        The route follows COM2's health. The claim follows the **device**: it
        goes to a server that actually owns the device, so a dispatch is
        never claimed by a host that cannot execute it, and it is never
        handed to a host the device has not arrived at.
        """
        for name, value in (
            ("com2_restored", com2_restored),
            ("com2_device_connected", com2_device_connected),
            ("oracle_device_connected", oracle_device_connected),
        ):
            if not isinstance(value, bool):
                raise ContractError(f"{name} must be a boolean")

        # The route is the instruction that moves the device.
        desired = TARGET_COM2 if com2_restored else TARGET_ORACLE
        changed = desired != self._target
        events: tuple[str, ...] = ()
        if changed:
            events = (
                (EVENT_ROUTE_TO_COM2,)
                if desired == TARGET_COM2
                else (EVENT_ROUTE_TO_ORACLE,)
            )
            self._target = desired

        # The claim follows the device. The route's target wins when the
        # device has arrived there; until then the device is still where it
        # was, and that server keeps the claim.
        owner, reason = claim_owner(
            self._target,
            com2_device_connected=com2_device_connected,
            oracle_device_connected=oracle_device_connected,
        )
        return RouteDecision(
            route_target=self._target,
            route_changed=changed,
            route_events=events,
            claim_target=owner,
            claim_blocked_reason=reason,
        )


__all__ = [
    "DEFAULT_AGENT_URL",
    "DEFAULT_LOCAL_HOST",
    "DEFAULT_LOCAL_PORT",
    "EVENT_ROUTE_TO_COM2",
    "EVENT_ROUTE_TO_ORACLE",
    "ROUTE_TARGETS",
    "TARGET_COM2",
    "TARGET_ORACLE",
    "ConnectionRoute",
    "MeshConnectionRouter",
    "RouteDecision",
    "com2_route",
    "oracle_route",
]
