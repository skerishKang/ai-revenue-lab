from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from .contracts import (
    SandboxLease,
    SandboxLeaseRequest,
    SandboxLeaseState,
)


class SandboxUnavailableError(RuntimeError):
    pass


class SandboxLeaseError(RuntimeError):
    pass


class SandboxLeasePort(Protocol):
    """B54 resource boundary only; P01 remains agent/tool policy authority."""

    def allocate(self, request: SandboxLeaseRequest) -> SandboxLease: ...

    def get(self, lease_id: str) -> SandboxLease: ...

    def release(self, lease_id: str, *, run_id: str) -> SandboxLease: ...


class UnconfiguredSandboxProvider:
    """Production-safe default until a real sandbox provider is explicitly wired."""

    def allocate(self, request: SandboxLeaseRequest) -> SandboxLease:
        raise SandboxUnavailableError(
            "sandbox provider is not configured; cloud execution remains unexecuted"
        )

    def get(self, lease_id: str) -> SandboxLease:
        raise SandboxUnavailableError("sandbox provider is not configured")

    def release(self, lease_id: str, *, run_id: str) -> SandboxLease:
        raise SandboxUnavailableError("sandbox provider is not configured")


class DeterministicFakeSandboxProvider:
    """Network-free fake used for contract tests and local architecture exercises only."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        prefix: str = "fake_lease",
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._prefix = prefix
        self._counter = 0
        self._leases: dict[str, SandboxLease] = {}
        self._active_by_run: dict[str, str] = {}

    def allocate(self, request: SandboxLeaseRequest) -> SandboxLease:
        active_id = self._active_by_run.get(request.run_id)
        if active_id is not None:
            active = self.get(active_id)
            if active.state is SandboxLeaseState.RESERVED:
                raise SandboxLeaseError(f"run already has an active lease: {request.run_id}")

        now = self._clock().astimezone(timezone.utc)
        self._counter += 1
        lease = SandboxLease(
            lease_id=f"{self._prefix}_{self._counter:04d}",
            run_id=request.run_id,
            execution_mode=request.execution_mode,
            resource_class=request.resource_class,
            network_policy=request.network_policy,
            writable_workspace=request.writable_workspace,
            created_at=now,
            expires_at=now + timedelta(seconds=request.ttl_seconds),
        )
        self._leases[lease.lease_id] = lease
        self._active_by_run[request.run_id] = lease.lease_id
        return lease

    def get(self, lease_id: str) -> SandboxLease:
        try:
            lease = self._leases[lease_id]
        except KeyError as exc:
            raise SandboxLeaseError(f"unknown lease: {lease_id}") from exc

        if lease.state is SandboxLeaseState.RESERVED and self._clock().astimezone(timezone.utc) >= lease.expires_at:
            lease = lease.with_state(SandboxLeaseState.EXPIRED)
            self._leases[lease_id] = lease
            self._active_by_run.pop(lease.run_id, None)
        return lease

    def release(self, lease_id: str, *, run_id: str) -> SandboxLease:
        lease = self.get(lease_id)
        if lease.run_id != run_id:
            raise SandboxLeaseError("lease belongs to a different run")
        if lease.state is not SandboxLeaseState.RESERVED:
            raise SandboxLeaseError(f"lease is not active: {lease.state.value}")
        released = lease.with_state(SandboxLeaseState.RELEASED)
        self._leases[lease_id] = released
        self._active_by_run.pop(run_id, None)
        return released
