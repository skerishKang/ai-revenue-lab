from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from .contracts import (
    SANDBOX_LEASE_MAX_TTL_SECONDS,
    SANDBOX_LEASE_MIN_TTL_SECONDS,
    ContractError,
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

    def renew(self, lease_id: str, *, run_id: str, ttl_seconds: int) -> SandboxLease: ...

    def release(self, lease_id: str, *, run_id: str) -> SandboxLease: ...


class SandboxWorkloadCancellationPort(Protocol):
    """Explicit cancellation capability, deliberately kept off ``SandboxLeasePort``.

    Cancellation is a provider capability, not a lease necessity. Holding it in a
    separate protocol means a provider that cannot cancel still satisfies
    ``SandboxLeasePort`` and simply does not satisfy this one, so a caller has to
    ask for the capability instead of assuming it, and Cloud M1 conformance can
    fail closed on its absence (#1405).

    ``cancel`` ends the lease. It is not proof that a guest process tree died:
    ``process_tree_killed`` still has no producer, and real teardown evidence
    remains gated behind provider selection.
    """

    def cancel(self, lease_id: str, *, run_id: str) -> SandboxLease: ...


def supports_workload_cancellation(provider: object) -> bool:
    """Whether ``provider`` exposes a cancel operation, as opposed to a declared boolean.

    Presence of the callable is not proof the operation works — conformance has to
    exercise it (#2790). This only answers "is there anything to call", so a caller
    never reaches for ``cancel`` on a provider that has none.

    Duck-typed because ``SandboxLeasePort`` and this protocol are both structural:
    an ``isinstance`` check against a bare ``Protocol`` raises ``TypeError``, and
    copying that failure into a boolean would silently report "no capability" for
    every provider, including one that supports it.
    """
    return callable(getattr(provider, "cancel", None))


class UnconfiguredSandboxProvider:
    """Production-safe default until a real sandbox provider is explicitly wired."""

    def allocate(self, request: SandboxLeaseRequest) -> SandboxLease:
        raise SandboxUnavailableError(
            "sandbox provider is not configured; cloud execution remains unexecuted"
        )

    def get(self, lease_id: str) -> SandboxLease:
        raise SandboxUnavailableError("sandbox provider is not configured")

    def renew(self, lease_id: str, *, run_id: str, ttl_seconds: int) -> SandboxLease:
        raise SandboxUnavailableError(
            "sandbox provider is not configured; sandbox lifetime remains unextended"
        )

    def release(self, lease_id: str, *, run_id: str) -> SandboxLease:
        raise SandboxUnavailableError("sandbox provider is not configured")

    def cancel(self, lease_id: str, *, run_id: str) -> SandboxLease:
        # An unconfigured provider reports no cancellation at all: it has no
        # workload to stop, and returning anything here would read as evidence
        # that a cancel succeeded.
        raise SandboxUnavailableError(
            "sandbox provider is not configured; no workload cancellation was performed"
        )


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

    def renew(self, lease_id: str, *, run_id: str, ttl_seconds: int) -> SandboxLease:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not SANDBOX_LEASE_MIN_TTL_SECONDS <= ttl_seconds <= SANDBOX_LEASE_MAX_TTL_SECONDS
        ):
            raise SandboxLeaseError(
                "ttl_seconds must be between "
                f"{SANDBOX_LEASE_MIN_TTL_SECONDS} and {SANDBOX_LEASE_MAX_TTL_SECONDS}"
            )
        lease = self.get(lease_id)
        if lease.run_id != run_id:
            raise SandboxLeaseError("lease belongs to a different run")
        # get() is what flips a lapsed lease to EXPIRED, so this RESERVED check is
        # the guard that keeps renewal from resurrecting a released sandbox.
        if lease.state is not SandboxLeaseState.RESERVED:
            raise SandboxLeaseError(f"lease is not active: {lease.state.value}")
        now = self._clock().astimezone(timezone.utc)
        try:
            renewed = lease.with_expiry(now + timedelta(seconds=ttl_seconds))
        except ContractError as exc:
            # Keeps the port boundary uniform with release(): a rejected renewal is
            # always a SandboxLeaseError, while the contract still owns the reason.
            raise SandboxLeaseError(f"lease cannot be renewed: {exc}") from exc
        self._leases[lease_id] = renewed
        return renewed

    def release(self, lease_id: str, *, run_id: str) -> SandboxLease:
        return self._terminate(lease_id, run_id)

    def cancel(self, lease_id: str, *, run_id: str) -> SandboxLease:
        """End the lease for ``run_id`` as a cancellation.

        Shares one termination rule with ``release`` on purpose: both drive
        ``RESERVED -> RELEASED`` and a terminal lease refuses every later
        operation. The two verbs stay separate because the *reason* differs; they
        must not diverge in what "ended" means, and no distinct ``CANCELLED``
        state is invented to make cancellation look stronger than it is.

        Cancelling releases the run's active slot, so the run may allocate again
        under ``allocate``'s one-active-lease rule.
        """
        return self._terminate(lease_id, run_id)

    def _terminate(self, lease_id: str, run_id: str) -> SandboxLease:
        lease = self.get(lease_id)
        if lease.run_id != run_id:
            raise SandboxLeaseError("lease belongs to a different run")
        if lease.state is not SandboxLeaseState.RESERVED:
            raise SandboxLeaseError(f"lease is not active: {lease.state.value}")
        released = lease.with_state(SandboxLeaseState.RELEASED)
        self._leases[lease_id] = released
        self._active_by_run.pop(run_id, None)
        return released


REAL_SANDBOX_LEASE_RENEWAL_PROVIDER_CONFIGURED = False
SANDBOX_LEASE_RENEWAL_PERFORMS_NO_CLOUD_CALL = True
SANDBOX_LEASE_RENEWAL_MINTS_NO_ADDITIONAL_LEASE = True
SANDBOX_LEASE_LIFETIME_CAP_ENFORCED_BY_CONTRACT = True
