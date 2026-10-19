"""Provider-neutral sandbox lease TTL reclamation and reconciliation (#1405 / #2803).

A reservation lapses by clock, but nothing on ``SandboxLeasePort`` can drive that
transition. ``get`` only notices a lapse when somebody happens to read that lease,
and ``release`` refuses anything that is not active — so an unread lapsed lease stays
reserved, keeps holding its run's active slot, and no caller can finish it.

This module owns the *decision*, and it performs no I/O: it reads no clock, opens no
connection, constructs no provider and schedules nothing. A caller that can observe
time passes that observation in, and the report says exactly what one bounded pass
did — including what it could not settle.

Reclamation ends a reservation. It is not evidence that a guest workload stopped:
``process_tree_killed`` still has no producer, and no field here may be read as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .contracts import (
    ContractError,
    SandboxLease,
    SandboxLeaseState,
    _aware_utc,
    _safe_id,
)
from .sandbox import (
    SandboxLeaseError,
    SandboxUnavailableError,
    supports_lease_reclamation,
)
from .security import redact_secrets


_MAX_REASON_CHARS = 512

# One pass is bounded so a sweep cannot be turned into an unbounded scan of a
# provider's inventory. Callers re-invoke until a report stops saying it truncated.
DEFAULT_RECLAMATION_SCAN = 50
MAX_RECLAMATION_SCAN = 500


class LeaseReclamationOutcome(str, Enum):
    """What one examined lease ended up as. Only ``RECLAIMED`` counts as reclaimed."""

    RECLAIMED = "reclaimed"
    NOT_YET_LAPSED = "not_yet_lapsed"
    ALREADY_TERMINAL = "already_terminal"
    RECONCILIATION_REQUIRED = "reconciliation_required"


def _reason(value: object) -> str:
    """Bound and redact a provider-supplied explanation before it is recorded.

    A provider's own error text is not trusted to be short or credential-free, and a
    reclamation report is projected into evidence.
    """
    text = "unspecified reclamation failure" if value is None else str(value).strip()
    if not text:
        text = "unspecified reclamation failure"
    return redact_secrets(text)[:_MAX_REASON_CHARS]


@dataclass(frozen=True, slots=True)
class LeaseReclamationRecord:
    """The disposition of exactly one lease examined by one sweep."""

    lease_id: str
    run_id: str
    outcome: LeaseReclamationOutcome
    expires_at: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        # One identifier contract with the lease itself: no second grammar here.
        object.__setattr__(self, "lease_id", _safe_id(self.lease_id, "lease_id"))
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        if not isinstance(self.outcome, LeaseReclamationOutcome):
            try:
                object.__setattr__(self, "outcome", LeaseReclamationOutcome(self.outcome))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid reclamation outcome") from exc
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _aware_utc(self.expires_at, "expires_at"))
        if self.reason is not None:
            object.__setattr__(self, "reason", _reason(self.reason))
        # An unresolved lease has to say why, or "reconciliation required" would be a
        # label a caller could not act on.
        if self.outcome is LeaseReclamationOutcome.RECONCILIATION_REQUIRED and not self.reason:
            raise ContractError("an unresolved lease requires a reconciliation reason")

    @property
    def reclaimed(self) -> bool:
        return self.outcome is LeaseReclamationOutcome.RECLAIMED

    @property
    def unresolved(self) -> bool:
        return self.outcome is LeaseReclamationOutcome.RECONCILIATION_REQUIRED

    def safe_dict(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "run_id": self.run_id,
            "outcome": self.outcome.value,
            "expires_at": self.expires_at.isoformat() if self.expires_at else "NONE",
            "reason": self.reason or "NONE",
        }


@dataclass(frozen=True, slots=True)
class LeaseReclamationReport:
    """What one bounded pass did. Every count is derived from the records it holds.

    Counts are deliberately not constructor arguments: a report that could be handed
    a ``reclaimed_count`` would let a caller claim reclamation it never observed,
    which is the failure mode #1405 keeps closing.
    """

    observed_at: datetime
    limit: int
    inventory_size: int
    records: tuple[LeaseReclamationRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit < 1:
            raise ContractError("reclamation limit must be a positive integer")
        if self.limit > MAX_RECLAMATION_SCAN:
            raise ContractError(f"reclamation limit must not exceed {MAX_RECLAMATION_SCAN}")
        if (
            isinstance(self.inventory_size, bool)
            or not isinstance(self.inventory_size, int)
            or self.inventory_size < 0
        ):
            raise ContractError("reclamation inventory size must be a non-negative integer")
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, LeaseReclamationRecord) for record in self.records
        ):
            raise ContractError("reclamation records must be a tuple of records")
        if len(self.records) > self.limit:
            raise ContractError("a sweep may not examine more leases than its limit")
        if len(self.records) > self.inventory_size:
            raise ContractError("a sweep may not examine more leases than the inventory holds")
        seen: set[str] = set()
        for record in self.records:
            if record.lease_id in seen:
                raise ContractError("one sweep may not record the same lease twice")
            seen.add(record.lease_id)

    @property
    def examined(self) -> int:
        return len(self.records)

    @property
    def truncated(self) -> bool:
        """Whether the inventory held more leases than this pass was allowed to reach."""
        return self.inventory_size > self.examined

    @property
    def reclaimed_count(self) -> int:
        return sum(1 for record in self.records if record.reclaimed)

    @property
    def unresolved_count(self) -> int:
        return sum(1 for record in self.records if record.unresolved)

    @property
    def outcome_counts(self) -> dict[str, int]:
        return {
            outcome.value: sum(1 for record in self.records if record.outcome is outcome)
            for outcome in LeaseReclamationOutcome
        }

    @property
    def fully_reclaimed(self) -> bool:
        """True only when this pass reached the whole inventory and reclaimed all of it.

        A pass that met a live lease, an already-terminal one, or an unresolved one did
        not fully reclaim anything, even though it left nothing needing reconciliation:
        ``not_yet_lapsed`` in particular is a lease still held right now. An empty
        inventory is the one trivially true case.
        """
        return not self.truncated and all(record.reclaimed for record in self.records)

    def safe_dict(self) -> dict[str, object]:
        return {
            "observed_at": self.observed_at.isoformat(),
            "limit": self.limit,
            "inventory_size": self.inventory_size,
            "examined": self.examined,
            "truncated": self.truncated,
            "reclaimed_count": self.reclaimed_count,
            "unresolved_count": self.unresolved_count,
            "fully_reclaimed": self.fully_reclaimed,
            "outcome_counts": dict(self.outcome_counts),
            "records": [record.safe_dict() for record in self.records],
            # Bookkeeping about reservations, never about processes.
            "workload_stop_observed": False,
            "real_provider_calls": 0,
            "production_claim": False,
        }


def _scan_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError("reclamation limit must be a positive integer")
    if value > MAX_RECLAMATION_SCAN:
        raise ContractError(f"reclamation limit must not exceed {MAX_RECLAMATION_SCAN}")
    return value


def _record(
    lease: SandboxLease,
    outcome: LeaseReclamationOutcome,
    reason: str | None = None,
) -> LeaseReclamationRecord:
    return LeaseReclamationRecord(
        lease_id=lease.lease_id,
        run_id=lease.run_id,
        outcome=outcome,
        expires_at=lease.expires_at,
        reason=reason,
    )


def _reap_one(provider: object, lease: SandboxLease, observed: datetime) -> LeaseReclamationRecord:
    if lease.state is not SandboxLeaseState.RESERVED:
        # Something else already ended it. Reclamation never re-terminates a lease,
        # and an already-terminal one is not evidence of a reclamation.
        return _record(lease, LeaseReclamationOutcome.ALREADY_TERMINAL)
    if observed < lease.expires_at:
        return _record(lease, LeaseReclamationOutcome.NOT_YET_LAPSED)
    try:
        reclaimed = provider.expire(  # type: ignore[attr-defined]
            lease.lease_id, run_id=lease.run_id, now=observed
        )
    except (SandboxLeaseError, SandboxUnavailableError, ContractError) as exc:
        # A provider that stops answering mid-pass — including one that becomes
        # unconfigured partway — leaves the sweep reporting the lease as unsettled.
        # Losing the report would hide the leases that WERE reclaimed.
        return _record(lease, LeaseReclamationOutcome.RECONCILIATION_REQUIRED, str(exc))
    if not isinstance(reclaimed, SandboxLease) or reclaimed.state is not SandboxLeaseState.EXPIRED:
        # The provider accepted the call without performing the transition, so the
        # lease is still held. Reported unresolved rather than counted as reclaimed.
        return _record(
            lease,
            LeaseReclamationOutcome.RECONCILIATION_REQUIRED,
            "provider did not drive the lease to EXPIRED",
        )
    return _record(lease, LeaseReclamationOutcome.RECLAIMED)


def reap_expired_leases(
    provider: object,
    *,
    now: datetime,
    limit: int = DEFAULT_RECLAMATION_SCAN,
) -> LeaseReclamationReport:
    """Sweep a provider's reserved leases and reclaim the ones that have lapsed.

    ``now`` is the caller's clock reading, validated by the contract layer's one
    timezone rule and passed unchanged to the provider, so the two can never
    disagree about the same sweep. Leases are examined in ``lease_id`` order and at
    most ``limit`` of them per pass; a report that says it truncated means exactly
    that more inventory existed.

    Three vocabularies, deliberately distinct. A malformed clock or scan limit is a
    ``ContractError``: the caller asked a nonsense question. A provider that does not
    expose the reclamation operations raises ``SandboxLeaseError`` here rather than
    being swept into an empty report, because "nothing left to reclaim" is a claim it
    never earned. A provider that does expose them and refuses — the unconfigured
    production default — raises ``SandboxUnavailableError`` from its own boundary,
    which is a different fact: it was asked and said no. A provider that becomes
    unavailable *mid-pass* instead yields a complete report whose unsettled leases are
    marked for reconciliation, because the leases that were reclaimed still have to
    be reported.
    """
    observed = _aware_utc(now, "now")
    scan = _scan_limit(limit)
    if not supports_lease_reclamation(provider):
        raise SandboxLeaseError(
            "provider does not support sandbox lease reclamation; nothing was reclaimed"
        )
    inventory = tuple(provider.active_leases())  # type: ignore[attr-defined]
    examined = sorted(inventory, key=lambda lease: lease.lease_id)[:scan]
    records = tuple(_reap_one(provider, lease, observed) for lease in examined)
    return LeaseReclamationReport(
        observed_at=observed,
        limit=scan,
        inventory_size=len(inventory),
        records=records,
    )


def unresolved_leases(report: LeaseReclamationReport) -> tuple[LeaseReclamationRecord, ...]:
    """The leases this pass could not settle, in the order the sweep met them.

    Separate from the report so a caller cannot mistake "no records here" for "no
    leases left": the report still says whether it truncated.
    """
    return tuple(record for record in report.records if record.unresolved)


SANDBOX_LEASE_RECLAMATION_PERFORMS_NO_IO = True
SANDBOX_LEASE_RECLAMATION_COUNTS_DERIVED_FROM_RECORDS = True
SANDBOX_LEASE_RECLAMATION_SCHEDULING_DRIVER_CONFIGURED = False
SANDBOX_LEASE_RECLAMATION_ENDS_A_RESERVATION_NOT_A_PROCESS = True
