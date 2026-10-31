"""#5462 — MeshCentral execution failover/failback controller for COM2 <-> Oracle.

The remote-execution lane has two possible homes for its executor: COM2
(primary) and Oracle (secondary). Both run the same MeshCentral server
identity, and the target PC is registered on both with the same node id,
so a server that owns the device can execute and a server that does not
cannot. The controller owns exactly one question: **which of the two is
allowed to claim a dispatch right now**.

Design constraints that come from the measured production state, not from
preference:

* The Chat channel hands the oldest claimable dispatch to exactly one
  poller, with a fresh single-use nonce. The server owns the claim, so
  the controller does not have to re-implement a queue.
* A server that answers HTTP 200 but has no connected device cannot
  execute. Liveness is therefore "the device is connected", never "the
  server answered".
* COM2 sits behind NAT and has no usable inbound path from Oracle, so
  the health signal travels COM2 -> Oracle as a heartbeat. Oracle never
  has to reach into COM2 to learn whether COM2 is usable.
* Every switch bumps a monotonically increasing **epoch**. A poller may
  only claim while it holds the current epoch, so a slow or restarted
  consumer that still believes it is active is fenced out instead of
  racing the new one. This is what makes "the same work is never
  executed twice" hold across a switch.
* Failover is confirmed faster than failback, so a flapping COM2 does
  not oscillate the active target. The asymmetry is deliberate and
  matches the existing COM1 recovery engine, which also acts on a fault
  at once and recovers only on a clean observation.

The controller core performs no I/O, so the state machine is testable
without a MeshCentral, a network or a clock.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from .contracts import ContractError
from .local_agent_mesh_connection_route import (
    EVENT_ROUTE_TO_COM2,
    EVENT_ROUTE_TO_ORACLE,
    TARGET_COM2,
    TARGET_ORACLE,
    claim_owner,
    com2_route,
    oracle_route,
)
from .local_agent_meshcentral_private_reader import (
    _MESHCTRL_STDIN_BOOTSTRAP,
    _PASSWORD_MARKER,
)
from .local_agent_oracle_mesh_executor import deployment_secret_password_provider

#: The two homes for the executor.
ACTIVE_COM2 = "com2"
ACTIVE_ORACLE = "oracle"
#: Every target this controller may select.
ACTIVE_TARGETS = (ACTIVE_COM2, ACTIVE_ORACLE)

#: The four event names the operations vocabulary uses. They are emitted
#: only on a real transition, never on every poll.
EVENT_COM2_FAULT = "COM2_FAULT"
EVENT_ORACLE_ACTIVE = "ORACLE_ACTIVE"
EVENT_COM2_RESTORED = "COM2_RESTORED"
EVENT_FAILBACK_COMPLETE = "FAILBACK_COMPLETE"
#: Sentinel for "the caller did not say", so that "nobody may claim" stays a
#: real, carryable state instead of looking like a missing value.
_UNSPECIFIED = object()

FAILOVER_EVENTS = (
    EVENT_COM2_FAULT,
    EVENT_ORACLE_ACTIVE,
    EVENT_COM2_RESTORED,
    EVENT_FAILBACK_COMPLETE,
)

#: A heartbeat older than this means COM2 stopped proving it is usable.
DEFAULT_HEARTBEAT_STALE_SECONDS = 180
#: Consecutive unusable observations before the switch. Two keeps a single
#: missed heartbeat from moving the target, and is still fast.
DEFAULT_FAULT_CONFIRMATIONS = 2
#: Consecutive usable observations before the failback. Three is slower
#: than the failover on purpose.
DEFAULT_RESTORE_CONFIRMATIONS = 3


@dataclass(frozen=True)
class MeshFailoverDecision:
    """One evaluation of the failover state machine.

    ``active_target`` is who may claim a dispatch, and it is ``None`` while
    the device is connected nowhere: the claim waits rather than being
    taken by a host that cannot execute it.

    ``route_target`` is where the agent is being pointed. The route is the
    instruction that moves the device, so it moves **before** the claim.

    ``epoch`` is the fencing token. A consumer that presents an older
    epoch is not allowed to claim a dispatch.
    """

    active_target: Optional[str]
    route_target: str
    epoch: int
    changed: bool
    events: tuple[str, ...]
    reason: str

    def may_claim(self, presented_epoch: int) -> bool:
        """Only the consumer holding the current epoch may claim."""
        if isinstance(presented_epoch, bool) or not isinstance(presented_epoch, int):
            raise ContractError("the presented epoch must be an integer")
        return presented_epoch == self.epoch


class MeshFailoverController:
    """The active-target state machine. No I/O, no clock, no network.

    The caller supplies the truth it observed (``com2_usable``) and the
    controller decides whether the active target changes. The controller
    never decides that COM2 is unusable by itself: an unreachable or
    missing heartbeat is a *reason to doubt*, and doubt is resolved by
    the caller's own probe.
    """

    def __init__(
        self,
        *,
        heartbeat_stale_seconds: int = DEFAULT_HEARTBEAT_STALE_SECONDS,
        fault_confirmations: int = DEFAULT_FAULT_CONFIRMATIONS,
        restore_confirmations: int = DEFAULT_RESTORE_CONFIRMATIONS,
        initial_target: str = ACTIVE_COM2,
        fault_streak: int = 0,
        restore_streak: int = 0,
        initial_epoch: int = 1,
        initial_route: Optional[str] = None,
        initial_claim: Any = _UNSPECIFIED,
    ) -> None:
        for name, value in (
            ("heartbeat_stale_seconds", heartbeat_stale_seconds),
            ("fault_confirmations", fault_confirmations),
            ("restore_confirmations", restore_confirmations),
            ("fault_streak", fault_streak),
            ("restore_streak", restore_streak),
            ("initial_epoch", initial_epoch),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractError(f"{name} must be a non-negative integer")
        if fault_confirmations < 1 or restore_confirmations < 1:
            raise ContractError("the confirmation windows must be positive")
        if initial_epoch < 1:
            raise ContractError("the initial epoch must be at least 1")
        if initial_target not in ACTIVE_TARGETS:
            raise ContractError("the initial target must be a known target")
        self._heartbeat_stale_seconds = heartbeat_stale_seconds
        self._fault_confirmations = fault_confirmations
        self._restore_confirmations = restore_confirmations
        # The route is where the agent is pointed; the claim is who may
        # execute. They are separate because the route has to move first
        # and the device has to travel.
        self._route = initial_route or initial_target
        # The claim starts where the route points, so the first pass does not
        # look like a transition. "Nobody may claim" is a real state and is
        # carried explicitly, which is why the default is a sentinel.
        self._claim = (
            self._route if initial_claim is _UNSPECIFIED else initial_claim
        )
        # The epoch is the fencing token, so it is carried across processes
        # and never restarts from a lower value: a consumer that still holds
        # an older epoch must stay refused.
        self._epoch = initial_epoch
        self._fault_streak = fault_streak
        self._restore_streak = restore_streak

    @property
    def active_target(self) -> Optional[str]:
        """Who may claim a dispatch right now."""
        return self._claim

    @property
    def route_target(self) -> str:
        """Where the agent is being pointed right now."""
        return self._route

    @property
    def epoch(self) -> int:
        """The current fencing token."""
        return self._epoch

    @property
    def fault_streak(self) -> int:
        """Consecutive unusable observations seen so far."""
        return self._fault_streak

    @property
    def restore_streak(self) -> int:
        """Consecutive usable observations seen so far."""
        return self._restore_streak

    def heartbeat_is_stale(self, age_seconds: Optional[float]) -> bool:
        """A missing or old heartbeat means COM2 stopped proving liveness."""
        if age_seconds is None:
            return True
        if isinstance(age_seconds, bool) or not isinstance(age_seconds, (int, float)):
            raise ContractError("the heartbeat age must be a number or None")
        return float(age_seconds) > self._heartbeat_stale_seconds

    def evaluate(
        self,
        *,
        com2_restored: bool,
        com2_device_connected: bool,
        oracle_device_connected: bool,
        com2_heartbeat_age_seconds: Optional[float] = None,
    ) -> MeshFailoverDecision:
        """Evaluate the state machine once and return the decision.

        Three facts are kept apart on purpose:

        * ``com2_restored`` — COM2 says it is healthy again. This is a
          **signal**. It moves the route, and the route is what sends the
          device.
        * ``com2_device_connected`` — COM2's own probe says the device is
          connected to COM2 **now**. The agent has to travel back before
          this becomes true, so it is the fact the claim waits for.
        * ``oracle_device_connected`` — Oracle's own probe says the device
          is connected to Oracle now.

        The claim follows the **device**. A target that owns no device
        would lose the dispatch, so the claim never moves to a target
        before the device is there, and a "COM2 is back" signal on its own
        does not hand the claim back to a COM2 the device has not returned
        to.
        """
        for name, value in (
            ("com2_restored", com2_restored),
            ("com2_device_connected", com2_device_connected),
            ("oracle_device_connected", oracle_device_connected),
        ):
            if not isinstance(value, bool):
                raise ContractError(f"{name} must be a boolean")
        stale = self.heartbeat_is_stale(com2_heartbeat_age_seconds)
        # COM2 is only trusted when it says it is restored AND its
        # heartbeat is fresh. A stale heartbeat alone does not fail COM2
        # over; it only means the caller must not claim COM2 is restored
        # without its own probe.
        restored = com2_restored and not stale

        previous_route = self._route
        previous_claim = self._claim

        if self._route == ACTIVE_COM2:
            if restored:
                self._fault_streak = 0
                self._restore_streak = 0
            else:
                self._restore_streak = 0
                self._fault_streak = min(
                    self._fault_streak + 1, self._fault_confirmations
                )
                if self._fault_streak >= self._fault_confirmations:
                    self._route = ACTIVE_ORACLE
                    self._epoch += 1
        else:
            # The route is on Oracle. COM2 comes back only after it has
            # claimed it is restored for the whole restore window.
            if restored:
                self._fault_streak = 0
                self._restore_streak = min(
                    self._restore_streak + 1, self._restore_confirmations
                )
                if self._restore_streak >= self._restore_confirmations:
                    self._route = ACTIVE_COM2
                    self._epoch += 1
            else:
                self._restore_streak = 0
                self._fault_streak = min(
                    self._fault_streak + 1, self._fault_confirmations
                )

        owner, blocked = claim_owner(
            self._route,
            com2_device_connected=com2_device_connected,
            oracle_device_connected=oracle_device_connected,
        )
        self._claim = owner

        events: list[str] = []
        if self._route != previous_route:
            if self._route == ACTIVE_ORACLE:
                events.append(EVENT_ROUTE_TO_ORACLE)
                events.append(EVENT_COM2_FAULT)
            else:
                events.append(EVENT_ROUTE_TO_COM2)
                events.append(EVENT_COM2_RESTORED)
        if owner != previous_claim:
            # ORACLE_ACTIVE says Oracle owns the claim now, which is true
            # whatever the route is doing.
            #
            # FAILBACK_COMPLETE describes a **finished** failback, so it
            # only fires when the route is back on COM2 as well: while the
            # device is travelling, the claim may already name COM2 and the
            # failback is still not complete.
            if owner == ACTIVE_ORACLE:
                events.append(EVENT_ORACLE_ACTIVE)
            elif owner == ACTIVE_COM2 and self._route == ACTIVE_COM2:
                events.append(EVENT_FAILBACK_COMPLETE)

        reason = self._reason(
            restored=restored,
            owner=owner,
            blocked=blocked,
            route_changed=self._route != previous_route,
        )
        return MeshFailoverDecision(
            active_target=owner,
            route_target=self._route,
            epoch=self._epoch,
            changed=bool(events),
            events=tuple(events),
            reason=reason,
        )

    def _reason(
        self,
        *,
        restored: bool,
        owner: Optional[str],
        blocked: str,
        route_changed: bool,
    ) -> str:
        if route_changed:
            return (
                f"the route moved to {self._route}; the device follows it"
            )
        if owner is None:
            return blocked or "the claim is held"
        if owner == ACTIVE_COM2:
            return (
                "com2 is restored, its heartbeat is fresh and the device is "
                "connected there"
            )
        return (
            "com2 is not restored, so oracle keeps the claim and the device "
            "stays with it"
        )



def heartbeat_age_seconds(
    path: str, *, now: Optional[float] = None
) -> Optional[float]:
    """Age of a heartbeat file, or ``None`` when it is absent.

    A heartbeat is a small JSON document written by the COM2 side. The
    age is measured from the file's own modification time so a clock
    skew between the two hosts cannot make a fresh heartbeat look old.
    """
    if not isinstance(path, str) or not path.strip():
        raise ContractError("the heartbeat path is required")
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    current = time.time() if now is None else now
    return max(0.0, current - stamp)


def read_heartbeat(path: str) -> dict[str, Any]:
    """Read a heartbeat document. A corrupt heartbeat reads as empty."""
    if not isinstance(path, str) or not path.strip():
        raise ContractError("the heartbeat path is required")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


class MeshCentralDevicePresence:
    """Which devices the LOCAL MeshCentral currently has connected.

    This is the "remote execution is actually possible" probe. It uses the
    OFFICIAL ``meshctrl.js`` client that the product already ships, with
    the operator credential injected on stdin, so neither the OS command
    line nor a log ever contains it.
    """

    def __init__(
        self,
        *,
        meshctrl_js: str,
        mesh_url: str,
        login_user: str,
        password_provider: Callable[[], str],
        command_runner: Optional[Callable[..., Any]] = None,
        node_executable: str = "node",
        timeout_seconds: int = 30,
    ) -> None:
        if not isinstance(meshctrl_js, str) or not meshctrl_js.strip():
            raise ContractError("the official meshctrl client path is required")
        if not isinstance(mesh_url, str) or not mesh_url.strip():
            raise ContractError("the MeshCentral url is required")
        if not isinstance(login_user, str) or not login_user.strip():
            raise ContractError("the MeshCentral operator account is required")
        if not callable(password_provider):
            raise ContractError("the password provider must be callable")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise ContractError("timeout_seconds must be an integer")
        self._meshctrl_js = meshctrl_js
        self._mesh_url = mesh_url
        self._login_user = login_user
        self._password_provider = password_provider
        self._command_runner = command_runner
        self._node_executable = node_executable
        self._timeout_seconds = timeout_seconds

    def _run_listdevices(self) -> str:
        if self._command_runner is not None:
            runner = self._command_runner
        else:
            import subprocess

            def runner(argv, input=None, timeout=None):  # type: ignore[misc]
                return subprocess.run(
                    argv,
                    input=input,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

        argv = [
            self._node_executable,
            "-e",
            _MESHCTRL_STDIN_BOOTSTRAP,
            self._meshctrl_js,
            "listdevices",
            "--url",
            self._mesh_url,
            "--loginuser",
            self._login_user,
            "--loginpass",
            _PASSWORD_MARKER,
        ]
        password = self._password_provider()
        if (
            not isinstance(password, str)
            or not password
            or "\n" in password
            or "\r" in password
        ):
            raise ContractError(
                "the protected MeshCentral operator credential is invalid"
            )
        completed = runner(
            argv, input=password + "\n", timeout=self._timeout_seconds
        )
        stdout = getattr(completed, "stdout", "") or ""
        stderr = getattr(completed, "stderr", "") or ""
        return stdout if isinstance(stdout, str) else str(stdout) + (
            stderr if isinstance(stderr, str) else str(stderr)
        )

    @staticmethod
    def _parse_listdevices(text: str) -> list[dict[str, Any]]:
        """Parse the official client's ``listdevices`` table.

        The client prints a CSV-ish table:

            id, name, icon, conn, pwr
            "nodeid@domain", "name", 1, 1, 1
        """
        rows: list[dict[str, Any]] = []
        header: list[str] | None = None
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("---"):
                continue
            if line.lower().startswith("id, name"):
                header = [
                    part.strip().lower()
                    for part in line.split(",")
                ]
                continue
            if header is None:
                continue
            if line.startswith("Device group:"):
                header = None
                continue
            fields = [part.strip() for part in line.split(",")]
            if len(fields) != len(header):
                continue
            row: dict[str, Any] = {}
            for key, value in zip(header, fields):
                value = value.strip('"')
                if key in ("conn", "pwr", "icon"):
                    try:
                        row[key] = int(value)
                    except ValueError:
                        row[key] = 0
                else:
                    row[key] = value
            rows.append(row)
        return rows

    def listing(self) -> list[dict[str, Any]]:
        """The local server's whole device table, from ONE run of the official client.

        Every reader below used to start its own enumeration, so a caller that wanted
        both "is this device connected" and "what is its name" paid twice per device.
        Nothing is cached here: a caller that wants the same answer twice in one round
        asks for it once.
        """
        return self._parse_listdevices(self._run_listdevices())

    def connected_device_ids(self) -> frozenset[str]:
        """Node ids the local MeshCentral currently has connected."""
        rows = self.listing()
        connected = set()
        for row in rows:
            node_id = row.get("id")
            if not isinstance(node_id, str) or not node_id:
                continue
            if int(row.get("conn", 0) or 0) == 1:
                connected.add(node_id)
        return frozenset(connected)

    def pairing_candidates(self) -> list[dict[str, Any]]:
        """Connected devices whose name carries a pairing tag, from ONE parse.

        #5573 PR-4c: this is how a PC that cannot name its own node identity
        reaches its owner. The enumeration already happens; only names holding
        exactly one `pd-` tag token are returned, and each candidate carries the
        id the Mesh lane can address plus the name that proves the pairing.
        """
        rows = self.listing()
        found: list[dict[str, Any]] = []
        for row in rows:
            node_id = row.get("id")
            name = row.get("name")
            if not isinstance(node_id, str) or not node_id:
                continue
            if not isinstance(name, str) or not name.strip():
                continue
            if int(row.get("conn", 0) or 0) != 1:
                # A candidate that is not connected cannot be claimed yet, and a
                # stale row would waste the beat's budget.
                continue
            found.append({"device_id": node_id, "connected": True, "agent_name": name.strip()[:256]})
        return found

    def name_of(self, device_id: str) -> str | None:
        """The name the local server reports for one device, or ``None``.

        #5573: the pairing tag an installer stamps into the agent name is how a
        PC that cannot name its own node identity still gets claimed. The name
        is observation only — it is handed to the server and never kept here.
        """
        if not isinstance(device_id, str) or not device_id.strip():
            raise ContractError("the device id is required")
        for row in self.listing():
            if row.get("id") == device_id:
                name = row.get("name")
                return name if isinstance(name, str) and name.strip() else None
        return None

    def is_connected(self, device_id: str) -> bool:
        """Whether the named device is connected to the local server."""
        if not isinstance(device_id, str) or not device_id.strip():
            raise ContractError("the device id is required")
        return device_id in self.connected_device_ids()


@dataclass
class MeshFailoverSupervisor:
    """Wire the controller to the host's real signals.

    The supervisor reads the COM2 heartbeat, asks the local presence
    probe whether the target device is connected here, evaluates the
    controller, persists the decision and emits the event vocabulary.

    The supervisor never claims anything itself. It only decides which
    target may claim, and it hands out the epoch that fences the others.
    """

    controller: MeshFailoverController
    heartbeat_path: str
    presence: MeshCentralDevicePresence
    device_id: str
    state_path: str
    notifier: Optional[Callable[[str, str], None]] = None
    local_target: str = ACTIVE_ORACLE
    #: The two routes the transport can apply. When they are configured the
    #: decision file carries the forward arguments, so the transport side
    #: does not have to know how a route is built.
    routes: Optional[dict[str, Any]] = None
    now: Callable[[], float] = time.time
    _last_events: tuple[str, ...] = field(default=(), init=False, repr=False)

    def _local_can_execute(self) -> bool:
        """Whether THIS host can actually execute the dispatch."""
        try:
            return self.presence.is_connected(self.device_id)
        except (ContractError, OSError, ValueError):
            return False

    def _com2_device_connected(self) -> bool:
        """Whether the device is connected to COM2 **right now**.

        COM2 publishes that truth in its own heartbeat, because COM2 has
        no inbound path from Oracle. A heartbeat that is missing, stale or
        does not claim the device is not a proof of execution.
        """
        age = heartbeat_age_seconds(self.heartbeat_path, now=self.now())
        if age is None or self.controller.heartbeat_is_stale(age):
            return False
        payload = read_heartbeat(self.heartbeat_path)
        if not payload:
            return False
        if payload.get("device_connected") is not True:
            return False
        if payload.get("target") != ACTIVE_COM2:
            return False
        return True

    def _com2_restored(self) -> bool:
        """Whether COM2 says it is healthy again.

        This is the **signal**, and it is deliberately weaker than the
        device being connected there: COM2's MeshCentral and its executor
        can be up while the agent is still travelling back from the
        standby. The route follows this signal; the claim does not.
        """
        age = heartbeat_age_seconds(self.heartbeat_path, now=self.now())
        if age is None or self.controller.heartbeat_is_stale(age):
            return False
        payload = read_heartbeat(self.heartbeat_path)
        if not payload:
            return False
        if payload.get("target") != ACTIVE_COM2:
            return False
        if payload.get("executor_alive") is not True:
            return False
        return True

    def run_once(self) -> MeshFailoverDecision:
        """Evaluate once, persist the decision and emit any event.

        The confirmation windows span several passes, and each pass is a fresh
        process, so the streaks are carried in the state file. A window that
        lived only in memory would never confirm anything.
        """
        com2_restored = self._com2_restored()
        com2_device_connected = self._com2_device_connected()
        oracle_device_connected = self._local_can_execute()
        age = heartbeat_age_seconds(self.heartbeat_path, now=self.now())
        decision = self.controller.evaluate(
            com2_restored=com2_restored,
            com2_device_connected=com2_device_connected,
            oracle_device_connected=oracle_device_connected,
            com2_heartbeat_age_seconds=age,
        )
        self._persist(
            decision,
            com2_restored=com2_restored,
            com2_device_connected=com2_device_connected,
            heartbeat_age=age,
        )
        if decision.events:
            for event in decision.events:
                self._emit(event, decision)
            self._last_events = decision.events
        return decision

    def _persist(
        self,
        decision: MeshFailoverDecision,
        *,
        com2_restored: bool,
        com2_device_connected: bool,
        heartbeat_age: Optional[float],
    ) -> None:
        payload = {
            "schema": "padiem_mesh_failover/v1",
            # Who may claim. None means the device is connected nowhere yet,
            # so the claim waits instead of being taken and lost.
            "active_target": decision.active_target,
            # Where the agent is being pointed. This is the instruction the
            # transport applies, and it moves BEFORE the claim.
            "route_target": decision.route_target,
            "epoch": decision.epoch,
            "local_target": self.local_target,
            "local_can_execute": self._local_can_execute(),
            "com2_restored": com2_restored,
            "com2_device_connected": com2_device_connected,
            "com2_heartbeat_age_seconds": heartbeat_age,
            "changed": decision.changed,
            "events": list(decision.events),
            "reason": decision.reason,
            # The confirmation windows have to survive the process, so the
            # streaks are part of the persisted decision.
            "fault_streak": self.controller.fault_streak,
            "restore_streak": self.controller.restore_streak,
            "ts": self.now(),
        }
        route = None
        if self.routes:
            chosen = self.routes.get(decision.route_target)
            if chosen is not None:
                route = {
                    "target": chosen.target,
                    "identity": chosen.identity(),
                    "agent_url": chosen.agent_url,
                    "tunnel_arguments": list(chosen.tunnel_arguments()),
                }
        payload["connection_route"] = route
        directory = os.path.dirname(self.state_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = self.state_path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, self.state_path)

    def _emit(self, event: str, decision: MeshFailoverDecision) -> None:
        if self.notifier is None:
            return
        message = (
            f"{event}\n"
            f"active_target: {decision.active_target}\n"
            f"epoch: {decision.epoch}\n"
            f"reason: {decision.reason}"
        )
        self.notifier(event, message)


def build_heartbeat(
    *,
    mesh_url: str,
    device_id: str,
    device_connected: bool,
    executor_alive: bool,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Build the COM2 heartbeat document.

    The heartbeat carries the truth COM2 knows about itself, because
    Oracle cannot reach into COM2 to check. A heartbeat that only says
    "I am alive" is not enough: the controller needs to know that the
    device is actually connected, otherwise a server that answers HTTP
    200 while owning no device would be treated as usable.
    """
    if not isinstance(mesh_url, str) or not mesh_url.strip():
        raise ContractError("the MeshCentral url is required")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ContractError("the device id is required")
    if not isinstance(device_connected, bool):
        raise ContractError("device_connected must be a boolean")
    if not isinstance(executor_alive, bool):
        raise ContractError("executor_alive must be a boolean")
    return {
        "schema": "padiem_mesh_heartbeat/v1",
        "target": ACTIVE_COM2,
        "mesh_url": mesh_url,
        "device_id": device_id,
        "device_connected": device_connected,
        "executor_alive": executor_alive,
        "ts": time.time() if now is None else now,
    }


def write_heartbeat(path: str, payload: dict[str, Any]) -> None:
    """Write the heartbeat atomically so a reader never sees a torn file."""
    if not isinstance(path, str) or not path.strip():
        raise ContractError("the heartbeat path is required")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def decision_file_claim_gate(
    state_path: str, local_target: str
) -> Callable[[], bool]:
    """A gate that only lets THIS host claim while it is the active target.

    The state file is the controller's own decision, written by the
    supervisor on the same host. A host that is not the active target
    stops claiming new dispatches. The held-result resend is not gated:
    bytes the PC already produced still have to reach the server once.
    """
    if not isinstance(state_path, str) or not state_path.strip():
        raise ContractError("the decision state path is required")
    if local_target not in ACTIVE_TARGETS:
        raise ContractError("the local target must be a known target")

    def gate() -> bool:
        try:
            with open(state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            # No decision yet: this host must not claim on its own.
            return False
        if not isinstance(state, dict):
            return False
        return state.get("active_target") == local_target

    return gate


def highest_issued_epoch(path: str) -> int:
    """The highest epoch this host has ever issued, from the event log.

    The decision file holds the current epoch, but the event log is the
    durable record of every epoch that was handed out. The epoch is the
    fencing token, so it has to be strictly greater than every epoch a
    consumer may still be holding; taking the highest issued one keeps
    that true even if the decision file was ever rewritten.
    """
    if not isinstance(path, str) or not path.strip():
        return 0
    highest = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = re.search(r"^epoch:\s*(\d+)\s*$", line.strip())
                if match:
                    value = int(match.group(1))
                    if value > highest:
                        highest = value
    except OSError:
        return 0
    return highest


def events_file_notifier(path: str) -> Callable[[str, str], None]:
    """Append every event to a durable local log.

    The log is the auditable record of what the controller decided. The
    delivery of that record to a human is a separate concern and stays
    pluggable, so a host that cannot reach the operator's channel still
    keeps the evidence.
    """
    if not isinstance(path, str) or not path.strip():
        raise ContractError("the events log path is required")

    def notifier(event: str, message: str) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"=== {stamp} {event} ===\n{message}\n")

    return notifier


def command_notifier(
    command: Sequence[str], timeout_seconds: int = 60
) -> Callable[[str, str], None]:
    """Deliver an event by running a reviewed command.

    The command receives the event name and the message as two
    arguments, so no shell is involved and no secret reaches an
    argument list. A delivery failure is recorded, never raised into the
    decision loop: a failed notification must not move the active
    target.
    """
    argv = list(command or ())
    if not argv:
        raise ContractError("the delivery command is required")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ContractError("timeout_seconds must be an integer")

    def notifier(event: str, message: str) -> None:
        import subprocess

        try:
            completed = subprocess.run(
                argv + [event, message],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if completed.returncode != 0:
                print(
                    f"mesh-failover delivery failed event={event} "
                    f"exit={completed.returncode}",
                    file=sys.stderr,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            print(
                f"mesh-failover delivery errored event={event} {exc}",
                file=sys.stderr,
            )

    return notifier


def _both_notifiers(
    first: Callable[[str, str], None], second: Callable[[str, str], None]
) -> Callable[[str, str], None]:
    """Run both notifiers, and never let one of them stop the other.

    The local log is the evidence; the delivery is the notification. A
    failed delivery must not cost the evidence, and a failed log write must
    not cost the notification.
    """

    def notifier(event: str, message: str) -> None:
        for one in (first, second):
            try:
                one(event, message)
            except Exception as exc:  # a notifier must never break the loop
                print(
                    f"mesh-failover notifier failed event={event} "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

    return notifier


def main(environ: Optional[dict[str, str]] = None) -> int:
    """One supervisor pass. Configured by environment only.

      MESH_FAILOVER_HEARTBEAT_PATH  where COM2 publishes its heartbeat
      MESH_FAILOVER_STATE_PATH      where this host's decision is written
      MESH_FAILOVER_EVENTS_PATH     where every event is appended
      MESH_FAILOVER_DEVICE_ID       the target device the lane executes on
      MESH_FAILOVER_LOCAL_TARGET    com2 | oracle — which host this is
      MESH_FAILOVER_HEARTBEAT_STALE_SECONDS
      MESH_FAILOVER_FAULT_CONFIRMATIONS
      MESH_FAILOVER_RESTORE_CONFIRMATIONS
      MESH_FAILOVER_NOTIFY_COMMAND  optional delivery command (argv)
      ORACLE_MESH_MESHCTRL_JS       the OFFICIAL meshctrl client path
      ORACLE_MESH_URL               this host's MeshCentral url
      ORACLE_MESH_LOGIN_USER        the MeshCentral operator account
      ORACLE_MESH_PASSWORD_FILE     mode-0600 file with the operator password
    """
    import os
    import sys

    env = dict(os.environ if environ is None else environ)

    def need(key: str) -> str:
        value = env.get(key, "").strip()
        if not value:
            raise ContractError(f"{key} is required")
        return value

    def optional_int(key: str, default: int) -> int:
        raw = env.get(key, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ContractError(f"{key} must be an integer") from exc

    try:
        # The confirmation windows span several passes and each pass is a
        # fresh process, so the previous decision is restored before the next
        # evaluation. Without this the window could never be reached.
        state_path = need("MESH_FAILOVER_STATE_PATH")
        events_path = need("MESH_FAILOVER_EVENTS_PATH")
        previous = read_heartbeat(state_path)
        controller = MeshFailoverController(
            heartbeat_stale_seconds=optional_int(
                "MESH_FAILOVER_HEARTBEAT_STALE_SECONDS",
                DEFAULT_HEARTBEAT_STALE_SECONDS,
            ),
            fault_confirmations=optional_int(
                "MESH_FAILOVER_FAULT_CONFIRMATIONS", DEFAULT_FAULT_CONFIRMATIONS
            ),
            restore_confirmations=optional_int(
                "MESH_FAILOVER_RESTORE_CONFIRMATIONS", DEFAULT_RESTORE_CONFIRMATIONS
            ),
            initial_target=previous.get("route_target", ACTIVE_COM2),
            initial_route=previous.get("route_target", ACTIVE_COM2),
            initial_claim=previous.get("active_target"),
            fault_streak=int(previous.get("fault_streak", 0) or 0),
            restore_streak=int(previous.get("restore_streak", 0) or 0),
            # The epoch is the fencing token and it must never go back, so it
            # is carried across processes with the rest of the decision, and
            # it is also lifted above every epoch the event log shows.
            initial_epoch=max(
                1,
                int(previous.get("epoch", 1) or 1),
                highest_issued_epoch(events_path),
            ),
        )
        presence = MeshCentralDevicePresence(
            meshctrl_js=need("ORACLE_MESH_MESHCTRL_JS"),
            mesh_url=need("ORACLE_MESH_URL"),
            login_user=need("ORACLE_MESH_LOGIN_USER"),
            password_provider=deployment_secret_password_provider(
                need("ORACLE_MESH_PASSWORD_FILE")
            ),
        )
        notifier = events_file_notifier(need("MESH_FAILOVER_EVENTS_PATH"))
        # The delivery of the event is pluggable, so a host that can reach
        # the operator's channel delivers it and a host that cannot still
        # keeps the durable local log.
        delivery = env.get("MESH_FAILOVER_NOTIFY_COMMAND", "").strip()
        if delivery:
            command = shlex.split(delivery)
            if not command:
                raise ContractError("the delivery command is required")
            notifier = _both_notifiers(
                notifier, command_notifier(command)
            )
        # The routes are optional: without them the decision still names the
        # route target, and the transport side resolves the forward itself.
        routes = None
        com2_host = env.get("MESH_FAILOVER_COM2_TUNNEL_HOST", "").strip()
        oracle_host = env.get("MESH_FAILOVER_ORACLE_TUNNEL_HOST", "").strip()
        if com2_host and oracle_host:
            routes = {
                TARGET_COM2: com2_route(
                    tunnel_host=com2_host,
                    tunnel_user=env.get(
                        "MESH_FAILOVER_COM2_TUNNEL_USER", ""
                    ).strip(),
                    tunnel_key=env.get(
                        "MESH_FAILOVER_COM2_TUNNEL_KEY", ""
                    ).strip(),
                    tunnel_port=optional_int(
                        "MESH_FAILOVER_COM2_TUNNEL_PORT", 4443
                    ),
                ),
                TARGET_ORACLE: oracle_route(
                    tunnel_host=oracle_host,
                    tunnel_user=env.get(
                        "MESH_FAILOVER_ORACLE_TUNNEL_USER", ""
                    ).strip(),
                    tunnel_key=env.get(
                        "MESH_FAILOVER_ORACLE_TUNNEL_KEY", ""
                    ).strip(),
                    tunnel_port=optional_int(
                        "MESH_FAILOVER_ORACLE_TUNNEL_PORT", 443
                    ),
                ),
            }
        supervisor = MeshFailoverSupervisor(
            controller=controller,
            heartbeat_path=need("MESH_FAILOVER_HEARTBEAT_PATH"),
            presence=presence,
            device_id=need("MESH_FAILOVER_DEVICE_ID"),
            state_path=state_path,
            notifier=notifier,
            local_target=need("MESH_FAILOVER_LOCAL_TARGET"),
            routes=routes,
        )
    except (ContractError, ValueError) as exc:
        print(f"mesh-failover refused to start: {exc}", file=sys.stderr)
        return 2

    try:
        decision = supervisor.run_once()
    except Exception as exc:  # the decision loop never dies on one bad pass
        print(f"mesh-failover pass failed: {exc}", file=sys.stderr)
        return 1
    print(
        "MESH_FAILOVER_DECISION "
        f"active={decision.active_target} epoch={decision.epoch} "
        f"changed={decision.changed} events={','.join(decision.events) or '-'} "
        f"reason={decision.reason}"
    )
    return 0


__all__ = [
    "ACTIVE_COM2",
    "ACTIVE_ORACLE",
    "ACTIVE_TARGETS",
    "DEFAULT_FAULT_CONFIRMATIONS",
    "DEFAULT_HEARTBEAT_STALE_SECONDS",
    "DEFAULT_RESTORE_CONFIRMATIONS",
    "EVENT_COM2_FAULT",
    "EVENT_COM2_RESTORED",
    "EVENT_FAILBACK_COMPLETE",
    "EVENT_ORACLE_ACTIVE",
    "FAILOVER_EVENTS",
    "MeshCentralDevicePresence",
    "MeshFailoverController",
    "MeshFailoverDecision",
    "MeshFailoverSupervisor",
    "build_heartbeat",
    "command_notifier",
    "decision_file_claim_gate",
    "events_file_notifier",
    "heartbeat_age_seconds",
    "highest_issued_epoch",
    "main",
    "read_heartbeat",
    "write_heartbeat",
]


if __name__ == "__main__":
    raise SystemExit(main())
