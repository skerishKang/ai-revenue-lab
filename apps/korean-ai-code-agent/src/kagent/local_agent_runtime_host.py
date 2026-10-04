from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar
from urllib.parse import urlsplit

from .contracts import ContractError
from .local_agent_durable_run_store import DurableRunStore
from .local_agent_restart_recovery import LocalAgentRestartRecoveryDriver
from .local_agent_control_plane_admission import (
    ControlPlaneAdmittedExecutionCoordinator,
    ControlPlanePhysicalAdmissionChannel,
)
from .local_agent_pairing import DeviceLifecycle, DeviceSession
from .local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from .local_agent_secure_transport import DeviceCredentialStore, OutboundPollRequest
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_MAX_DIAGNOSTICS = 100
_MAX_ERROR_MESSAGE = 1024


def _bounded_message(value: Any) -> str:
    return redact_secrets(str(value))[:_MAX_ERROR_MESSAGE]


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    normalized = value.strip()
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


class ResidentHostState(str, Enum):
    """Canonical resident runtime host lifecycle states."""

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    CONNECTING = "CONNECTING"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    REVOKED = "REVOKED"
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED"
    UPDATE_REQUIRED = "UPDATE_REQUIRED"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


class SingleInstanceLockPort:
    """Protocol for single-instance ownership enforcement."""

    def acquire(self, lock_key: str) -> bool:
        raise NotImplementedError

    def release(self, lock_key: str) -> None:
        raise NotImplementedError


class InMemorySingleInstanceLock(SingleInstanceLockPort):
    """Thread-safe, process-local single instance lock registry for deterministic execution."""

    _active_locks: ClassVar[set[str]] = set()
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def acquire(self, lock_key: str) -> bool:
        with self._lock:
            if lock_key in self._active_locks:
                return False
            self._active_locks.add(lock_key)
            return True

    def release(self, lock_key: str) -> None:
        with self._lock:
            self._active_locks.discard(lock_key)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._active_locks.clear()


@dataclass(frozen=True, slots=True)
class LocalAgentDiagnosticEvent:
    """Structured, secret-free diagnostic event for resident host telemetry."""

    timestamp: datetime
    state: ResidentHostState
    event_type: str
    code: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _aware(self.timestamp, "timestamp"))
        if not isinstance(self.state, ResidentHostState):
            raise ContractError("state must be ResidentHostState")
        object.__setattr__(self, "event_type", _ref(self.event_type, "event_type"))
        object.__setattr__(self, "code", _ref(self.code, "code"))
        clean_msg = _bounded_message(self.message)
        object.__setattr__(self, "message", clean_msg)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "timestamp": _iso(self.timestamp),
            "state": self.state.value,
            "event_type": self.event_type,
            "code": self.code,
            "message": self.message,
            "raw_device_credential": False,
            "authorization_header": False,
            "raw_argv": False,
            "raw_env": False,
            "raw_payload": False,
            "raw_p01_evidence": False,
        }


@dataclass(frozen=True, slots=True)
class LocalAgentResidentHostStatus:
    """Safe state projection for UI / diagnostic consumption without credential leakage."""

    device_id: str
    workspace_ref: str
    binding_ref: str
    state: ResidentHostState
    agent_version: str
    session_id: str | None
    last_heartbeat_at: datetime | None
    last_seen_at: datetime | None
    consecutive_failures: int
    reconnect_attempts: int
    active_command_id: str | None
    update_required: bool
    error_code: str | None
    error_message: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _ref(self.device_id, "device_id"))
        object.__setattr__(self, "workspace_ref", _ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(self, "binding_ref", _ref(self.binding_ref, "binding_ref"))
        if not isinstance(self.state, ResidentHostState):
            raise ContractError("state must be ResidentHostState")
        if self.session_id is not None:
            object.__setattr__(self, "session_id", _ref(self.session_id, "session_id"))
        if self.last_heartbeat_at is not None:
            object.__setattr__(self, "last_heartbeat_at", _aware(self.last_heartbeat_at, "last_heartbeat_at"))
        if self.last_seen_at is not None:
            object.__setattr__(self, "last_seen_at", _aware(self.last_seen_at, "last_seen_at"))
        if self.error_code is not None:
            object.__setattr__(self, "error_code", _ref(self.error_code, "error_code"))
        if self.error_message is not None:
            object.__setattr__(self, "error_message", _bounded_message(self.error_message))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-local-agent-resident-host-status.v1",
            "device_id": self.device_id,
            "workspace_ref": self.workspace_ref,
            "binding_ref": self.binding_ref,
            "state": self.state.value,
            "agent_version": self.agent_version,
            "session_id": self.session_id,
            "last_heartbeat_at": _iso(self.last_heartbeat_at) if self.last_heartbeat_at else None,
            "last_seen_at": _iso(self.last_seen_at) if self.last_seen_at else None,
            "consecutive_failures": self.consecutive_failures,
            "reconnect_attempts": self.reconnect_attempts,
            "active_command_id": self.active_command_id,
            "update_required": self.update_required,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "raw_device_credential": False,
            "authorization_header": False,
            "raw_argv": False,
            "raw_env": False,
            "raw_payload": False,
            "raw_p01_evidence": False,
            "public_inbound_port": False,
            "live_broker_configured": False,
            "production_ready": False,
        }


def _default_session_id_factory() -> str:
    import uuid
    return f"sess_{uuid.uuid4().hex[:16]}"


class LocalAgentResidentRuntimeHost:
    """Windows user-level resident host composing accepted Local Agent primitives.

    This host acts as a resident lifecycle manager: startup, single-instance lock,
    credential resolution, outbound session establishment, periodic heartbeat,
    bounded long-poll, command dispatch through existing canonical coordinator,
    cancellation awareness, and graceful shutdown.
    """

    def __init__(
        self,
        *,
        assembly: BoundLocalAgentRuntimeAssembly,
        channel: ControlPlanePhysicalAdmissionChannel,
        credential_store: DeviceCredentialStore,
        durable_store: DurableRunStore,
        coordinator: ControlPlaneAdmittedExecutionCoordinator | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        instance_lock: SingleInstanceLockPort | None = None,
        session_id_factory: Callable[[], str] | None = None,
        heartbeat_interval_seconds: int = 30,
        session_ttl_seconds: int = 900,
        initial_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
        backoff_multiplier: float = 2.0,
        agent_version: str = "0.2.0",
    ) -> None:
        if not isinstance(assembly, BoundLocalAgentRuntimeAssembly):
            raise ContractError("assembly must be BoundLocalAgentRuntimeAssembly")
        if not isinstance(channel, ControlPlanePhysicalAdmissionChannel):
            raise ContractError("channel must be ControlPlanePhysicalAdmissionChannel")
        if not hasattr(credential_store, "load"):
            raise ContractError("credential_store must implement load")
        # #3128: the durable run store is mandatory. It is what makes a
        # terminal result survive a crash between execution and the broker
        # acknowledgement, and it is what restart reconciliation reads.
        if not isinstance(durable_store, DurableRunStore):
            raise ContractError("durable_store must be DurableRunStore")

        # Trusted configuration verification
        authority = channel.authority
        if authority.device_id != assembly._device.device_id:
            raise ContractError("channel device does not match assembly device")
        if authority.workspace_ref != assembly._device.workspace_ref:
            raise ContractError("channel workspace does not match assembly workspace")
        if authority.binding_ref != assembly._binding.binding_ref:
            raise ContractError("channel binding does not match assembly binding")
        if authority.account_ref != assembly._binding.account_ref:
            raise ContractError("channel account does not match assembly binding")
        if authority.credential_generation != assembly._binding.credential_generation:
            raise ContractError("channel credential generation does not match assembly binding")
        if authority.credential_ref_fingerprint != assembly._broker_authority.credential_ref_fingerprint:
            raise ContractError("channel credential authority does not match assembly binding")
        if authority.config_fingerprint != assembly._broker_authority.config_fingerprint:
            raise ContractError("channel broker configuration does not match assembly authority")

        # Verify endpoint authority
        endpoint = authority.config.endpoint
        parsed = urlsplit(endpoint.url)
        if parsed.scheme.lower() not in {"https", "wss"}:
            raise ContractError("broker endpoint must use TLS (https or wss)")
        if parsed.username is not None or parsed.password is not None:
            raise ContractError("broker endpoint must not contain user credentials")
        if parsed.query or parsed.fragment:
            raise ContractError("broker endpoint must not use query or fragment")

        self._assembly = assembly
        self._channel = channel
        self._credential_store = credential_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # #3140: client-side freshness is measured on a monotonic source. The server
        # owns `last_seen_at`; this machine's wall clock never participates in the
        # heartbeat contract, and a clock jump must not fake freshness either way.
        self._monotonic = monotonic or time.monotonic
        self._coordinator = coordinator or ControlPlaneAdmittedExecutionCoordinator(
            channel=channel,
            assembly=assembly,
            clock=self._clock,
            durable_store=durable_store,
        )
        self._durable_store = durable_store
        self._recovery = LocalAgentRestartRecoveryDriver(
            store=durable_store,
            channel=channel,
            binding=assembly._binding,
        )
        self._instance_lock = instance_lock or InMemorySingleInstanceLock()
        self._session_id_factory = session_id_factory or _default_session_id_factory
        self._heartbeat_interval_seconds = max(5, min(heartbeat_interval_seconds, 300))
        self._session_ttl_seconds = max(60, min(session_ttl_seconds, 3600))
        self._initial_backoff_seconds = max(0.1, initial_backoff_seconds)
        self._max_backoff_seconds = max(self._initial_backoff_seconds, max_backoff_seconds)
        self._backoff_multiplier = max(1.1, backoff_multiplier)
        self._agent_version = agent_version

        self._lock_key = f"local_agent_host_{assembly._device.device_id}"
        self._lock_acquired = False
        self._state = ResidentHostState.STOPPED
        self._session: DeviceSession | None = None
        self._last_heartbeat_at: datetime | None = None
        self._last_heartbeat_monotonic: float | None = None
        self._last_seen_at: datetime | None = None
        # #3140 PHASE 3: the last server-owned heartbeat receipt, kept so the
        # canonical ONLINE projection can be applied from server facts alone.
        self._last_heartbeat_receipt: ControlPlaneHeartbeatReceipt | None = None
        self._last_seen_session_id: str | None = None
        self._last_sequence = 0
        self._consecutive_failures = 0
        self._reconnect_attempts = 0
        self._current_backoff = self._initial_backoff_seconds
        self._active_command_id: str | None = None
        self._active_request_id: str | None = None
        self._active_session: DeviceSession | None = None
        self._update_required = False
        self._error_code: str | None = None
        self._error_message: str | None = None
        self._diagnostics: deque[LocalAgentDiagnosticEvent] = deque(maxlen=_MAX_DIAGNOSTICS)
        self._stop_event = threading.Event()
        self._host_lock = threading.Lock()
        self._active_execution_lock = threading.Lock()

    @property
    def device_id(self) -> str:
        return self._assembly._device.device_id

    @property
    def workspace_ref(self) -> str:
        return self._assembly._device.workspace_ref

    @property
    def binding_ref(self) -> str:
        return self._assembly._binding.binding_ref

    @property
    def state(self) -> ResidentHostState:
        with self._host_lock:
            return self._state

    def _now(self) -> datetime:
        return _aware(self._clock(), "clock")

    def current_desktop_session_material(self) -> dict[str, Any]:
        """#3436 B2d — one bounded current-session projection for the trusted
        local Desktop boundary. Fail-closed on everything that is not the
        host's own current ONLINE canonical session.

        No value is minted here and no new verifier is invented: the existing
        canonical pinned authority re-validates the exact session/binding
        correlation (binding_ref, device_id, account_ref, workspace_ref) and
        currentness (`require_current_binding`, `require_session`), and the
        existing protected store re-validates the full binding context on
        load, so a rotated generation, an expired credential or a mismatched
        binding refuse here. DESKTOP_SESSION_OPEN=0: the host never opens a
        session to satisfy this projection.
        """
        from .local_agent_desktop_material import project_session_material

        with self._host_lock:
            if self._state is not ResidentHostState.ONLINE:
                raise ContractError("resident host is not online")
            session = self._session
            if session is None:
                raise ContractError("resident host has no current broker session")
            now = self._now()
            binding = self._assembly._binding
            authority = self._channel.authority
            authority.require_current_binding(binding, now=now)
            authority.require_session(session, now=now)
            credential = self._credential_store.load(binding=binding, now=now)
            return project_session_material(
                session_id=session.session_id,
                binding_ref=binding.binding_ref,
                credential=credential,
                credential_generation=binding.credential_generation,
                expires_at=session.expires_at,
            )

    def heartbeat_freshness_seconds(self) -> float | None:
        """Client-local freshness of the last acknowledged heartbeat (#3140).

        This is elapsed monotonic time since the last successful heartbeat
        response. It is deliberately not a comparison between the server clock
        and this machine's wall clock.
        """
        with self._host_lock:
            if self._last_heartbeat_monotonic is None:
                return None
            return max(0.0, self._monotonic() - self._last_heartbeat_monotonic)

    def heartbeat_is_fresh(self, *, grace_seconds: float = 0.0) -> bool:
        """True while the acknowledged heartbeat is inside the cadence (+ grace)."""
        freshness = self.heartbeat_freshness_seconds()
        if freshness is None:
            return False
        return freshness <= self._heartbeat_interval_seconds + max(0.0, grace_seconds)

    def _previous_last_seen_for(self, session: DeviceSession | None) -> datetime | None:
        """The acknowledged last-seen to compare against, or None for a new session.

        Call under the host lock. Non-regression only means anything inside one
        session, so a refreshed session starts a new comparison.
        """
        if session is None or self._last_seen_session_id != session.session_id:
            return None
        return self._last_seen_at

    def _promote_heartbeat(
        self,
        *,
        session: DeviceSession,
        receipt: ControlPlaneHeartbeatReceipt,
        at: datetime,
    ) -> None:
        """Record one acknowledged heartbeat. Call under the host lock."""
        self._last_heartbeat_at = at
        self._last_heartbeat_monotonic = self._monotonic()
        self._last_seen_at = receipt.last_seen_at
        self._last_seen_session_id = session.session_id
        self._last_heartbeat_receipt = receipt

    def _promote_binding_online(self, *, session: DeviceSession, now: datetime) -> None:
        """Apply the canonical server-backed ONLINE projection. Host lock held.

        #3140 PHASE 3: a heartbeat is not an ONLINE claim by itself, but once
        the broker has acknowledged one for this exact session the canonical
        projection promotes the redeemed binding. Until then execution stays
        refused by the assembly, which is the correct fail-closed direction.
        """

        from .local_agent_server_projection import project_server_backed_online_binding

        binding = self._assembly._binding
        if binding.state is not DeviceLifecycle.PAIRED_OFFLINE:
            return
        receipt = self._last_heartbeat_receipt
        if receipt is None or receipt.session_id != session.session_id:
            return
        try:
            projected = project_server_backed_online_binding(
                binding=binding, session=session, heartbeat=receipt, now=now
            )
        except ContractError:
            # Not-yet-current server facts are not an ONLINE claim.
            return
        self._assembly._binding = projected
        self._record_diagnostic(
            "network",
            "BINDING_ONLINE",
            "server projection promoted the redeemed binding to ONLINE",
        )

    def _record_diagnostic(self, event_type: str, code: str, message: str) -> None:
        event = LocalAgentDiagnosticEvent(
            timestamp=self._now(),
            state=self._state,
            event_type=event_type,
            code=code,
            message=message,
        )
        self._diagnostics.append(event)

    def diagnostics(self) -> tuple[LocalAgentDiagnosticEvent, ...]:
        with self._host_lock:
            return tuple(self._diagnostics)

    def status(self) -> LocalAgentResidentHostStatus:
        with self._host_lock:
            return LocalAgentResidentHostStatus(
                device_id=self.device_id,
                workspace_ref=self.workspace_ref,
                binding_ref=self.binding_ref,
                state=self._state,
                agent_version=self._agent_version,
                session_id=self._session.session_id if self._session else None,
                last_heartbeat_at=self._last_heartbeat_at,
                last_seen_at=self._last_seen_at,
                consecutive_failures=self._consecutive_failures,
                reconnect_attempts=self._reconnect_attempts,
                active_command_id=self._active_command_id,
                update_required=self._update_required,
                error_code=self._error_code,
                error_message=self._error_message,
            )

    def _set_active_request(self, request_id: str) -> None:
        if self._stop_event.is_set():
            raise ContractError("resident host stop requested")
        with self._active_execution_lock:
            self._active_session = self._session
            self._active_request_id = request_id

    def _clear_active_request(self) -> None:
        with self._active_execution_lock:
            self._active_session = None
            self._active_request_id = None

    def _acquire_instance_lock(self) -> None:
        if self._lock_acquired:
            return
        if not self._instance_lock.acquire(self._lock_key):
            self._state = ResidentHostState.FAILED
            self._error_code = "DUPLICATE_INSTANCE"
            self._error_message = f"Another instance is already running for device {self.device_id}"
            self._record_diagnostic("lifecycle", "DUPLICATE_INSTANCE", self._error_message)
            raise ContractError(f"duplicate Local Agent instance is already running for device {self.device_id}")
        self._lock_acquired = True

    def _release_instance_lock(self) -> None:
        if self._lock_acquired:
            self._instance_lock.release(self._lock_key)
            self._lock_acquired = False

    def start(self) -> None:
        """Start the resident host: acquire single-instance lock, verify credentials, connect to broker."""
        with self._host_lock:
            if self._state in {
                ResidentHostState.STARTING,
                ResidentHostState.CONNECTING,
                ResidentHostState.ONLINE,
                ResidentHostState.STOPPING,
            }:
                raise ContractError(f"cannot start host while in state {self._state.value}")

            now = self._now()
            self._acquire_instance_lock()
            self._stop_event.clear()
            self._session = None
            self._last_heartbeat_at = None
            self._last_heartbeat_monotonic = None
            self._last_seen_at = None
            self._last_seen_session_id = None
            self._active_command_id = None
            self._active_request_id = None
            self._active_session = None
            self._error_code = None
            self._error_message = None
            self._state = ResidentHostState.STARTING
            self._record_diagnostic("lifecycle", "STARTING", "Resident host starting")

            binding = self._assembly._binding
            if binding.state is DeviceLifecycle.UPDATE_REQUIRED:
                self._state = ResidentHostState.UPDATE_REQUIRED
                self._update_required = True
                self._error_code = "UPDATE_REQUIRED"
                self._error_message = "Device binding requires an update"
                self._record_diagnostic("lifecycle", "UPDATE_REQUIRED", self._error_message)
                self._release_instance_lock()
                raise ContractError("device binding requires an update")
            if binding.state is DeviceLifecycle.REVOKED:
                self._state = ResidentHostState.REVOKED
                self._error_code = "BINDING_REVOKED"
                self._error_message = "Device binding is revoked"
                self._record_diagnostic("lifecycle", "BINDING_REVOKED", self._error_message)
                self._release_instance_lock()
                raise ContractError("device binding is revoked")

            try:
                self._credential_store.load(binding=binding, now=now)
            except ContractError as exc:
                err_msg = str(exc)
                if "expired" in err_msg.lower():
                    self._state = ResidentHostState.CREDENTIAL_EXPIRED
                    self._error_code = "CREDENTIAL_EXPIRED"
                elif "revoked" in err_msg.lower():
                    self._state = ResidentHostState.REVOKED
                    self._error_code = "BINDING_REVOKED"
                else:
                    self._state = ResidentHostState.FAILED
                    self._error_code = "CREDENTIAL_INVALID"
                self._error_message = err_msg
                self._record_diagnostic("auth", self._error_code, self._error_message)
                self._release_instance_lock()
                raise

            self._state = ResidentHostState.CONNECTING
            self._record_diagnostic("network", "CONNECTING", "Opening broker session")

            try:
                session_id = self._session_id_factory()
                session = self._channel.open_session(
                    binding=binding,
                    session_id=session_id,
                    now=now,
                    ttl_seconds=self._session_ttl_seconds,
                )
                self._session = session
                hb_receipt = self._channel.heartbeat(
                    binding=binding,
                    session=session,
                    now=now,
                    previous_last_seen_at=self._previous_last_seen_for(session),
                )
                self._promote_heartbeat(session=session, receipt=hb_receipt, at=now)
                self._state = ResidentHostState.ONLINE
                self._consecutive_failures = 0
                self._reconnect_attempts = 0
                self._current_backoff = self._initial_backoff_seconds
                self._error_code = None
                self._error_message = None
                self._record_diagnostic("network", "ONLINE", "Connected to broker session successfully")
            except Exception as exc:
                self._state = ResidentHostState.OFFLINE
                self._consecutive_failures += 1
                self._error_code = "CONNECT_FAILED"
                self._error_message = str(exc)
                self._record_diagnostic("network", "CONNECT_FAILED", str(exc))
                raise

    def stop(self) -> None:
        """Gracefully stop the resident host, cancel active execution, and release instance lock."""
        self._stop_event.set()
        cancel_error: Exception | None = None
        cancelled_request_id: str | None = None
        with self._active_execution_lock:
            active_request_id = self._active_request_id
            active_session = self._active_session
        if active_session is not None and active_request_id is not None:
            try:
                self._assembly.cancel(
                    session=active_session,
                    request_id=active_request_id,
                    now=self._now(),
                )
                cancelled_request_id = active_request_id
            except Exception as exc:
                cancel_error = exc

        with self._host_lock:
            if self._state is ResidentHostState.STOPPED:
                return

            self._state = ResidentHostState.STOPPING
            self._record_diagnostic("lifecycle", "STOPPING", "Resident host stopping")
            if cancelled_request_id is not None:
                self._record_diagnostic("execution", "CANCELLED", f"Cancelled active request {cancelled_request_id}")
            elif cancel_error is not None:
                self._record_diagnostic("execution", "CANCEL_FAILED", str(cancel_error))

            self._release_instance_lock()
            self._state = ResidentHostState.STOPPED
            self._session = None
            self._last_heartbeat_at = None
            self._last_heartbeat_monotonic = None
            self._last_seen_at = None
            self._last_seen_session_id = None
            self._active_command_id = None
            self._clear_active_request()
            self._record_diagnostic("lifecycle", "STOPPED", "Resident host stopped cleanly")

    def run_once(self, *, now: datetime | None = None) -> int:
        """Execute one bounded cycle: heartbeat check, poll, and command dispatch."""
        with self._host_lock:
            if self._state is ResidentHostState.STOPPED or self._stop_event.is_set():
                return 0

            tick_now = _aware(now or self._now(), "now")

            # Check terminal states
            if self._state in {ResidentHostState.REVOKED, ResidentHostState.CREDENTIAL_EXPIRED, ResidentHostState.FAILED}:
                return 0

            # If offline, attempt reconnect
            if self._state is ResidentHostState.OFFLINE:
                reconnected = self._reconnect_locked(now=tick_now)
                if not reconnected:
                    return 0

            binding = self._assembly._binding
            session = self._session

            # Check if session needs refresh
            if session is None or tick_now >= session.expires_at:
                try:
                    session_id = self._session_id_factory()
                    session = self._channel.open_session(
                        binding=binding,
                        session_id=session_id,
                        now=tick_now,
                        ttl_seconds=self._session_ttl_seconds,
                    )
                    self._session = session
                except Exception as exc:
                    self._handle_transport_error(exc)
                    return 0

            # Send heartbeat if the monotonic interval elapsed (#3140): elapsed
            # monotonic time, not a wall-clock difference, so a clock jump cannot
            # fake freshness in either direction.
            if (
                self._last_heartbeat_monotonic is None
                or (self._monotonic() - self._last_heartbeat_monotonic) >= self._heartbeat_interval_seconds
            ):
                try:
                    hb = self._channel.heartbeat(
                        binding=binding,
                        session=session,
                        now=tick_now,
                        previous_last_seen_at=self._previous_last_seen_for(session),
                    )
                    self._promote_heartbeat(session=session, receipt=hb, at=tick_now)
                except Exception as exc:
                    self._handle_transport_error(exc)
                    return 0

            # #3140 PHASE 3: server-owned ONLINE promotion, before any polled
            # command can be dispatched.
            self._promote_binding_online(session=session, now=tick_now)

            # #3128: reconcile anything a previous process left unacknowledged
            # before dispatching new work. This never executes anything; it
            # only re-presents correlation the durable store already holds.
            self._recovery.recover_once(session=session, now=tick_now)

            # Poll for commands
            poll_request = OutboundPollRequest(
                request_ref=f"poll_{session.session_id}_{int(tick_now.timestamp())}",
                session=session,
                after_sequence=self._last_sequence,
                requested_at=tick_now,
            )

            try:
                commands = self._channel.poll(
                    binding=binding,
                    request=poll_request,
                )
            except Exception as exc:
                self._handle_transport_error(exc)
                return 0

            executed_count = 0
            for command in commands:
                if self._stop_event.is_set():
                    break
                self._active_command_id = command.command_id
                material_ref = f"mat_{command.command_id}_{command.sequence}"
                try:
                    self._coordinator.execute_polled_command(
                        binding=binding,
                        session=session,
                        command=command,
                        material_request_ref=material_ref,
                        on_execution_start=self._set_active_request,
                        on_execution_end=self._clear_active_request,
                    )
                    self._last_sequence = max(self._last_sequence, command.sequence)
                    executed_count += 1
                    self._record_diagnostic(
                        "execution",
                        "EXECUTED",
                        f"Command {command.command_id} sequence {command.sequence} executed and acknowledged",
                    )
                except Exception as exc:
                    self._record_diagnostic("execution", "EXECUTION_ERROR", str(exc))
                    if isinstance(exc, OSError):
                        self._handle_transport_error(exc)
                    raise
                finally:
                    self._active_command_id = None
                    self._clear_active_request()

            return executed_count

    def reconnect(self, *, now: datetime | None = None) -> bool:
        """Attempt one reconnect cycle."""
        with self._host_lock:
            return self._reconnect_locked(now=now)

    def _reconnect_locked(self, *, now: datetime | None = None) -> bool:
        if self._state in {
            ResidentHostState.STOPPED,
            ResidentHostState.REVOKED,
            ResidentHostState.CREDENTIAL_EXPIRED,
            ResidentHostState.FAILED,
        }:
            return False

        tick_now = _aware(now or self._now(), "now")
        self._state = ResidentHostState.CONNECTING
        self._reconnect_attempts += 1
        self._record_diagnostic("network", "RECONNECTING", f"Reconnect attempt {self._reconnect_attempts}")

        binding = self._assembly._binding
        try:
            session_id = self._session_id_factory()
            session = self._channel.open_session(
                binding=binding,
                session_id=session_id,
                now=tick_now,
                ttl_seconds=self._session_ttl_seconds,
            )
            self._session = session
            hb = self._channel.heartbeat(
                binding=binding,
                session=session,
                now=tick_now,
                previous_last_seen_at=self._previous_last_seen_for(session),
            )
            self._promote_heartbeat(session=session, receipt=hb, at=tick_now)
            self._state = ResidentHostState.ONLINE
            self._consecutive_failures = 0
            self._current_backoff = self._initial_backoff_seconds
            self._error_code = None
            self._error_message = None
            self._record_diagnostic("network", "ONLINE", "Reconnected to broker successfully")
            return True
        except Exception as exc:
            self._state = ResidentHostState.OFFLINE
            self._consecutive_failures += 1
            self._error_code = "RECONNECT_FAILED"
            self._error_message = str(exc)
            self._current_backoff = min(
                self._current_backoff * self._backoff_multiplier,
                self._max_backoff_seconds,
            )
            self._record_diagnostic("network", "RECONNECT_FAILED", str(exc))
            return False

    def _handle_transport_error(self, exc: Exception) -> None:
        if self._stop_event.is_set():
            return
        raw_message = str(exc)
        err_msg = _bounded_message(exc)
        lowered = raw_message.lower()
        if "revoked" in lowered:
            self._state = ResidentHostState.REVOKED
            self._error_code = "BINDING_REVOKED"
            self._release_instance_lock()
        elif "expired" in lowered:
            self._state = ResidentHostState.CREDENTIAL_EXPIRED
            self._error_code = "CREDENTIAL_EXPIRED"
            self._release_instance_lock()
        elif "update" in lowered or "upgrade" in lowered:
            self._state = ResidentHostState.UPDATE_REQUIRED
            self._error_code = "UPDATE_REQUIRED"
            self._update_required = True
            self._release_instance_lock()
        else:
            self._state = ResidentHostState.OFFLINE
            self._consecutive_failures += 1
            self._error_code = "TRANSPORT_ERROR"
            self._current_backoff = min(
                self._current_backoff * self._backoff_multiplier,
                self._max_backoff_seconds,
            )
        self._error_message = err_msg
        self._record_diagnostic("network", self._error_code, err_msg)

    def run_forever(self, max_iterations: int | None = None) -> None:
        """Run the resident host event loop until cancelled or terminal state reached."""
        iterations = 0
        while not self._stop_event.is_set():
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1

            with self._host_lock:
                current_state = self._state

            if current_state in {
                ResidentHostState.STOPPED,
                ResidentHostState.REVOKED,
                ResidentHostState.CREDENTIAL_EXPIRED,
                ResidentHostState.FAILED,
            }:
                break

            if current_state is ResidentHostState.OFFLINE:
                # Cancellation-aware sleep for backoff duration
                interrupted = self._stop_event.wait(self._current_backoff)
                if interrupted or self._stop_event.is_set():
                    break
                self.reconnect()
                continue

            try:
                self.run_once()
            except Exception:
                # Handled inside run_once; will transition to OFFLINE if network error
                pass

            # Idle sleep between poll cycles (cancellation-aware)
            if not self._stop_event.is_set():
                self._stop_event.wait(0.5)


WINDOWS_RESIDENT_HOST_CONTRACT = True
WINDOWS_RESIDENT_HOST_IMPLEMENTATION = True
USER_LEVEL_DEFAULT = True
SINGLE_INSTANCE = True
OUTBOUND_ONLY = True
BOUNDED_RECONNECT = True
CANCELLATION_AWARE = True
CANONICAL_SESSION_REUSED = True
CANONICAL_COMMAND_ENVELOPE_REUSED = True
CANONICAL_WINDOWS_EXECUTOR_REUSED = True
CANONICAL_P01_APPROVAL_REUSED = True
CANONICAL_PERMISSION_AUTHORITY_REUSED = True
CANONICAL_CREDENTIAL_STORE_REUSED = True
RAW_DEVICE_SECRET_IN_LOG = False
ARBITRARY_BROKER_DESTINATION = False
REAL_WINDOWS_SERVICE_INSTALL = False
REAL_USER_PAIRING_CANARY = False
PRODUCTION_REMOTE_CONTROL_CLAIM = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
