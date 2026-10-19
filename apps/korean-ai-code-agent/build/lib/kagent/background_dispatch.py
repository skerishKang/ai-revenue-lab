from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError, ExecutionMode
from .security import redact_secrets


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_EXACT_REVISION_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


class DispatchState(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    ACKNOWLEDGED = "acknowledged"
    CANCELLATION_REQUESTED = "cancellation_requested"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class WorkerLeaseState(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


def _safe_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _safe_ref(value: str, field_name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise ContractError(f"{field_name} must be a bounded non-empty reference")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain raw credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _exact_revision(value: str) -> str:
    value = _safe_ref(value, "exact_revision", limit=64)
    if not _EXACT_REVISION_RE.fullmatch(value):
        raise ContractError("exact_revision must be an immutable hexadecimal revision")
    return value.lower()


@dataclass(frozen=True, slots=True)
class BackgroundDispatchRequest:
    dispatch_id: str
    run_id: str
    repository_ref: str
    exact_revision: str
    requested_at: datetime
    execution_mode: ExecutionMode = ExecutionMode.CLOUD

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispatch_id", _safe_id(self.dispatch_id, "dispatch_id"))
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(self, "repository_ref", _safe_ref(self.repository_ref, "repository_ref", limit=1024))
        object.__setattr__(self, "exact_revision", _exact_revision(self.exact_revision))
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if self.execution_mode is not ExecutionMode.CLOUD:
            raise ContractError("background dispatch accepts cloud runs only")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-background-dispatch.v1",
            "dispatch_id": self.dispatch_id,
            "run_id": self.run_id,
            "repository_ref": self.repository_ref,
            "exact_revision": self.exact_revision,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "execution_mode": self.execution_mode.value,
        }


@dataclass(frozen=True, slots=True)
class WorkerLease:
    lease_id: str
    dispatch_id: str
    run_id: str
    worker_id: str
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    state: WorkerLeaseState = WorkerLeaseState.ACTIVE
    acknowledged_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("lease_id", "dispatch_id", "run_id", "worker_id"):
            object.__setattr__(self, field_name, _safe_id(getattr(self, field_name), field_name))
        acquired = _aware(self.acquired_at, "acquired_at")
        heartbeat = _aware(self.heartbeat_at, "heartbeat_at")
        expires = _aware(self.expires_at, "expires_at")
        if heartbeat < acquired or expires <= heartbeat:
            raise ContractError("worker lease timestamps are out of order")
        if expires - heartbeat > timedelta(minutes=5):
            raise ContractError("worker lease heartbeat extension exceeds five minutes")
        object.__setattr__(self, "acquired_at", acquired)
        object.__setattr__(self, "heartbeat_at", heartbeat)
        object.__setattr__(self, "expires_at", expires)
        if not isinstance(self.state, WorkerLeaseState):
            raise ContractError("state must be WorkerLeaseState")
        if self.acknowledged_at is not None:
            acknowledged = _aware(self.acknowledged_at, "acknowledged_at")
            if acknowledged < acquired:
                raise ContractError("acknowledged_at cannot precede acquisition")
            object.__setattr__(self, "acknowledged_at", acknowledged)

    def active_at(self, now: datetime) -> bool:
        current = _aware(now, "now")
        return self.state is WorkerLeaseState.ACTIVE and current < self.expires_at

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-worker-lease.v1",
            "lease_id": self.lease_id,
            "dispatch_id": self.dispatch_id,
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "acquired_at": self.acquired_at.isoformat().replace("+00:00", "Z"),
            "heartbeat_at": self.heartbeat_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "state": self.state.value,
            "acknowledged_at": self.acknowledged_at.isoformat().replace("+00:00", "Z") if self.acknowledged_at else None,
        }


@dataclass(frozen=True, slots=True)
class CancellationIntent:
    cancellation_id: str
    dispatch_id: str
    run_id: str
    requested_at: datetime
    reason_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "cancellation_id", _safe_id(self.cancellation_id, "cancellation_id"))
        object.__setattr__(self, "dispatch_id", _safe_id(self.dispatch_id, "dispatch_id"))
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        object.__setattr__(self, "reason_ref", _safe_ref(self.reason_ref, "reason_ref"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cancellation-intent.v1",
            "cancellation_id": self.cancellation_id,
            "dispatch_id": self.dispatch_id,
            "run_id": self.run_id,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "reason_ref": self.reason_ref,
            "canonical_cancellation_confirmed": False,
        }


@dataclass(frozen=True, slots=True)
class P01EventCursor:
    dispatch_id: str
    run_id: str
    p01_run_id: str
    last_sequence: int
    last_event_id: str

    def __post_init__(self) -> None:
        for field_name in ("dispatch_id", "run_id", "p01_run_id", "last_event_id"):
            object.__setattr__(self, field_name, _safe_id(getattr(self, field_name), field_name))
        if isinstance(self.last_sequence, bool) or not isinstance(self.last_sequence, int) or self.last_sequence < 1:
            raise ContractError("last_sequence must be a positive integer")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-p01-event-cursor.v1",
            "dispatch_id": self.dispatch_id,
            "run_id": self.run_id,
            "p01_run_id": self.p01_run_id,
            "last_sequence": self.last_sequence,
            "last_event_id": self.last_event_id,
        }


@dataclass(frozen=True, slots=True)
class DispatchProjection:
    request: BackgroundDispatchRequest
    state: DispatchState
    active_lease: WorkerLease | None
    cancellation: CancellationIntent | None
    cursor: P01EventCursor | None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.safe_dict(),
            "state": self.state.value,
            "active_lease": self.active_lease.safe_dict() if self.active_lease else None,
            "cancellation": self.cancellation.safe_dict() if self.cancellation else None,
            "cursor": self.cursor.safe_dict() if self.cursor else None,
            "claw_running_claimed": False,
            "retry_authority": "p01",
            "recovery_authority": "p01",
        }


class InMemoryBackgroundDispatchQueue:
    """Deterministic queue/lease fake for B54 product conformance.

    This is not a scheduler deployment and never executes P01. A dispatch
    acknowledgement only proves a worker accepted infrastructure ownership; it
    does not project the Claw run to RUNNING.
    """

    def __init__(self) -> None:
        self._requests: dict[str, BackgroundDispatchRequest] = {}
        self._run_to_dispatch: dict[str, str] = {}
        self._states: dict[str, DispatchState] = {}
        self._leases: dict[str, WorkerLease] = {}
        self._dispatch_lease: dict[str, str] = {}
        self._cancellations: dict[str, CancellationIntent] = {}
        self._cursors: dict[str, P01EventCursor] = {}
        self._lease_counter = 0

    def enqueue(self, request: BackgroundDispatchRequest) -> None:
        if not isinstance(request, BackgroundDispatchRequest):
            raise ContractError("request must be BackgroundDispatchRequest")
        if request.dispatch_id in self._requests:
            raise ContractError("dispatch_id already exists")
        if request.run_id in self._run_to_dispatch:
            raise ContractError("run already has a background dispatch")
        self._requests[request.dispatch_id] = request
        self._run_to_dispatch[request.run_id] = request.dispatch_id
        self._states[request.dispatch_id] = DispatchState.QUEUED

    def _lease(self, lease_id: str) -> WorkerLease:
        try:
            return self._leases[lease_id]
        except KeyError as exc:
            raise ContractError("unknown worker lease") from exc

    def _request(self, dispatch_id: str) -> BackgroundDispatchRequest:
        try:
            return self._requests[dispatch_id]
        except KeyError as exc:
            raise ContractError("unknown dispatch") from exc

    def claim_next(self, *, worker_id: str, now: datetime, ttl_seconds: int = 120) -> WorkerLease | None:
        worker_id = _safe_id(worker_id, "worker_id")
        current = _aware(now, "now")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 30 <= ttl_seconds <= 300:
            raise ContractError("ttl_seconds must be between 30 and 300")
        candidates = sorted(
            (request for request in self._requests.values() if self._states[request.dispatch_id] is DispatchState.QUEUED),
            key=lambda request: (request.requested_at, request.dispatch_id),
        )
        if not candidates:
            return None
        request = candidates[0]
        self._lease_counter += 1
        lease = WorkerLease(
            lease_id=f"worker_lease_{self._lease_counter:08d}",
            dispatch_id=request.dispatch_id,
            run_id=request.run_id,
            worker_id=worker_id,
            acquired_at=current,
            heartbeat_at=current,
            expires_at=current + timedelta(seconds=ttl_seconds),
        )
        self._leases[lease.lease_id] = lease
        self._dispatch_lease[request.dispatch_id] = lease.lease_id
        self._states[request.dispatch_id] = DispatchState.LEASED
        return lease

    def heartbeat(self, *, lease_id: str, now: datetime, ttl_seconds: int = 120) -> WorkerLease:
        current = _aware(now, "now")
        lease = self._lease(lease_id)
        if not lease.active_at(current):
            raise ContractError("expired or released worker lease cannot heartbeat")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 30 <= ttl_seconds <= 300:
            raise ContractError("ttl_seconds must be between 30 and 300")
        updated = replace(
            lease,
            heartbeat_at=current,
            expires_at=current + timedelta(seconds=ttl_seconds),
        )
        self._leases[lease_id] = updated
        return updated

    def acknowledge(self, *, lease_id: str, now: datetime) -> WorkerLease:
        current = _aware(now, "now")
        lease = self._lease(lease_id)
        if not lease.active_at(current):
            raise ContractError("expired or released worker lease cannot acknowledge")
        dispatch_state = self._states[lease.dispatch_id]
        if dispatch_state is not DispatchState.LEASED:
            raise ContractError("dispatch is not in leasable acknowledgement state")
        updated = replace(lease, acknowledged_at=current)
        self._leases[lease_id] = updated
        self._states[lease.dispatch_id] = DispatchState.ACKNOWLEDGED
        return updated

    def release(self, *, lease_id: str, now: datetime) -> WorkerLease:
        current = _aware(now, "now")
        lease = self._lease(lease_id)
        if lease.state is not WorkerLeaseState.ACTIVE:
            raise ContractError("only active worker lease may release")
        if current < lease.acquired_at:
            raise ContractError("release cannot predate acquisition")
        released = replace(lease, state=WorkerLeaseState.RELEASED)
        self._leases[lease_id] = released
        self._dispatch_lease.pop(lease.dispatch_id, None)
        state = self._states[lease.dispatch_id]
        if state is DispatchState.LEASED:
            self._states[lease.dispatch_id] = DispatchState.QUEUED
        elif state is DispatchState.ACKNOWLEDGED:
            self._states[lease.dispatch_id] = DispatchState.RECONCILIATION_REQUIRED
        return released

    def expire(self, *, lease_id: str, now: datetime) -> WorkerLease:
        current = _aware(now, "now")
        lease = self._lease(lease_id)
        if lease.state is not WorkerLeaseState.ACTIVE:
            raise ContractError("only active worker lease may expire")
        if current < lease.expires_at:
            raise ContractError("worker lease has not expired yet")
        expired = replace(lease, state=WorkerLeaseState.EXPIRED)
        self._leases[lease_id] = expired
        self._dispatch_lease.pop(lease.dispatch_id, None)
        state = self._states[lease.dispatch_id]
        if state is DispatchState.LEASED:
            self._states[lease.dispatch_id] = DispatchState.QUEUED
        elif state in {DispatchState.ACKNOWLEDGED, DispatchState.CANCELLATION_REQUESTED}:
            self._states[lease.dispatch_id] = DispatchState.RECONCILIATION_REQUIRED
        return expired

    def request_cancellation(self, intent: CancellationIntent) -> CancellationIntent:
        if not isinstance(intent, CancellationIntent):
            raise ContractError("intent must be CancellationIntent")
        request = self._request(intent.dispatch_id)
        if request.run_id != intent.run_id:
            raise ContractError("cancellation run does not match dispatch")
        existing = self._cancellations.get(intent.dispatch_id)
        if existing is not None:
            if existing == intent:
                return existing
            raise ContractError("dispatch already has a different cancellation intent")
        self._cancellations[intent.dispatch_id] = intent
        self._states[intent.dispatch_id] = DispatchState.CANCELLATION_REQUESTED
        return intent

    def record_p01_cursor(
        self,
        *,
        dispatch_id: str,
        p01_run_id: str,
        sequence: int,
        event_id: str,
    ) -> P01EventCursor:
        request = self._request(dispatch_id)
        p01_run_id = _safe_id(p01_run_id, "p01_run_id")
        event_id = _safe_id(event_id, "event_id")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ContractError("sequence must be a positive integer")
        previous = self._cursors.get(dispatch_id)
        if previous is None:
            if sequence != 1:
                raise ContractError("first P01 cursor sequence must be 1")
        else:
            if previous.p01_run_id != p01_run_id:
                raise ContractError("dispatch cursor cannot switch P01 run identity")
            if sequence == previous.last_sequence and event_id == previous.last_event_id:
                return previous
            if sequence != previous.last_sequence + 1:
                raise ContractError("P01 cursor sequence must be contiguous")
        cursor = P01EventCursor(
            dispatch_id=dispatch_id,
            run_id=request.run_id,
            p01_run_id=p01_run_id,
            last_sequence=sequence,
            last_event_id=event_id,
        )
        self._cursors[dispatch_id] = cursor
        return cursor

    def projection(self, dispatch_id: str) -> DispatchProjection:
        request = self._request(dispatch_id)
        lease_id = self._dispatch_lease.get(dispatch_id)
        active_lease = self._leases.get(lease_id) if lease_id is not None else None
        return DispatchProjection(
            request=request,
            state=self._states[dispatch_id],
            active_lease=active_lease,
            cancellation=self._cancellations.get(dispatch_id),
            cursor=self._cursors.get(dispatch_id),
        )


REAL_QUEUE_DEPLOYMENT_SUPPORTED = False
B54_RETRY_ENGINE_SUPPORTED = False
B54_RECOVERY_ENGINE_SUPPORTED = False
B54_AGENT_STATE_CHECKPOINT_SUPPORTED = False
