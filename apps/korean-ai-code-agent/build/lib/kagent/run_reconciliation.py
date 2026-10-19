from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .background_dispatch import DispatchState
from .contracts import ContractError
from .run_persistence import RunPersistenceSnapshot, RunRestorePlan, RestoreAction, build_restore_plan


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class WorkerObservationState(str, Enum):
    UNKNOWN = "unknown"
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"
    NOT_FOUND = "not_found"


class P01ObservationState(str, Enum):
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def active(self) -> bool:
        return self in {self.RUNNING, self.WAITING_APPROVAL}

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class ReconciliationDecisionKind(str, Enum):
    NO_ACTION_TERMINAL = "no_action_terminal"
    WAIT_FOR_WORKER = "wait_for_worker"
    FETCH_CANONICAL_EVENT_TAIL = "fetch_canonical_event_tail"
    RECONCILE_CANCELLATION = "reconcile_cancellation"
    MANUAL_REQUEUE_REVIEW = "manual_requeue_review"
    ESCALATE_INCONSISTENT_STATE = "escalate_inconsistent_state"


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TrustedWorkerLeaseObservation:
    run_id: str
    observed_at: datetime
    state: WorkerObservationState
    lease_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _id(self.run_id, "run_id"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if not isinstance(self.state, WorkerObservationState):
            raise ContractError("state must be WorkerObservationState")
        if self.state is WorkerObservationState.ACTIVE and self.lease_id is None:
            raise ContractError("active worker observation requires lease_id")
        if self.lease_id is not None:
            object.__setattr__(self, "lease_id", _id(self.lease_id, "lease_id"))


@dataclass(frozen=True, slots=True)
class TrustedP01RunObservation:
    run_id: str
    observed_at: datetime
    state: P01ObservationState
    p01_run_id: str | None = None
    latest_sequence: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _id(self.run_id, "run_id"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if not isinstance(self.state, P01ObservationState):
            raise ContractError("state must be P01ObservationState")
        if self.state in {
            P01ObservationState.RUNNING,
            P01ObservationState.WAITING_APPROVAL,
            P01ObservationState.COMPLETED,
            P01ObservationState.FAILED,
            P01ObservationState.CANCELLED,
        } and self.p01_run_id is None:
            raise ContractError("known P01 lifecycle state requires p01_run_id")
        if self.p01_run_id is not None:
            object.__setattr__(self, "p01_run_id", _id(self.p01_run_id, "p01_run_id"))
        if self.latest_sequence is not None:
            if isinstance(self.latest_sequence, bool) or not isinstance(self.latest_sequence, int) or self.latest_sequence < 1:
                raise ContractError("latest_sequence must be positive")
            if self.p01_run_id is None:
                raise ContractError("latest_sequence requires p01_run_id")


@dataclass(frozen=True, slots=True)
class RunReconciliationDecision:
    run_id: str
    snapshot_generation: int
    snapshot_digest: str
    kind: ReconciliationDecisionKind
    reason_codes: tuple[str, ...]
    p01_run_id: str | None = None
    p01_latest_sequence: int | None = None
    worker_lease_id: str | None = None
    cancellation_id: str | None = None
    automatic_resume_allowed: bool = False
    automatic_redispatch_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _id(self.run_id, "run_id"))
        if not isinstance(self.kind, ReconciliationDecisionKind):
            raise ContractError("kind must be ReconciliationDecisionKind")
        if not isinstance(self.reason_codes, tuple) or not self.reason_codes:
            raise ContractError("reason_codes must be a non-empty tuple")
        object.__setattr__(self, "reason_codes", tuple(_id(item, "reason_code") for item in self.reason_codes))
        if self.automatic_resume_allowed is not False or self.automatic_redispatch_allowed is not False:
            raise ContractError("reconciliation decision cannot authorize automatic resume or redispatch")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-run-reconciliation-decision.v1",
            "run_id": self.run_id,
            "snapshot_generation": self.snapshot_generation,
            "snapshot_digest": self.snapshot_digest,
            "kind": self.kind.value,
            "reason_codes": list(self.reason_codes),
            "p01_run_id": self.p01_run_id,
            "p01_latest_sequence": self.p01_latest_sequence,
            "worker_lease_id": self.worker_lease_id,
            "cancellation_id": self.cancellation_id,
            "automatic_resume_allowed": False,
            "automatic_redispatch_allowed": False,
            "retry_authority": "p01",
            "recovery_authority": "p01",
        }


class RunRestartReconciliationEvaluator:
    """Pure evaluator over trusted observations; performs no I/O or execution."""

    def evaluate(
        self,
        *,
        snapshot: RunPersistenceSnapshot,
        worker: TrustedWorkerLeaseObservation,
        p01: TrustedP01RunObservation,
    ) -> RunReconciliationDecision:
        if not isinstance(snapshot, RunPersistenceSnapshot):
            raise ContractError("snapshot must be RunPersistenceSnapshot")
        if not isinstance(worker, TrustedWorkerLeaseObservation):
            raise ContractError("worker must be TrustedWorkerLeaseObservation")
        if not isinstance(p01, TrustedP01RunObservation):
            raise ContractError("p01 must be TrustedP01RunObservation")
        if worker.run_id != snapshot.run_id or p01.run_id != snapshot.run_id:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.ESCALATE_INCONSISTENT_STATE,
                "run_identity_mismatch",
                worker=worker,
                p01=p01,
            )
        if worker.observed_at < snapshot.saved_at or p01.observed_at < snapshot.saved_at:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.ESCALATE_INCONSISTENT_STATE,
                "stale_observation",
                worker=worker,
                p01=p01,
            )

        restore = build_restore_plan(snapshot)
        identity_error = self._identity_error(snapshot, worker, p01)
        if identity_error is not None:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.ESCALATE_INCONSISTENT_STATE,
                identity_error,
                worker=worker,
                p01=p01,
            )

        if snapshot.run_status.terminal or restore.action is RestoreAction.NO_ACTION_TERMINAL:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.NO_ACTION_TERMINAL,
                "b54_snapshot_terminal",
                worker=worker,
                p01=p01,
            )

        if snapshot.cancellation_id is not None or restore.action is RestoreAction.RECONCILE_CANCELLATION:
            if p01.state is P01ObservationState.CANCELLED:
                return self._decision(
                    snapshot,
                    ReconciliationDecisionKind.FETCH_CANONICAL_EVENT_TAIL,
                    "cancellation_seen_fetch_canonical_event",
                    worker=worker,
                    p01=p01,
                )
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.RECONCILE_CANCELLATION,
                "cancellation_intent_pending",
                worker=worker,
                p01=p01,
            )

        if p01.state.active:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.FETCH_CANONICAL_EVENT_TAIL,
                "active_p01_blocks_redispatch",
                worker=worker,
                p01=p01,
            )

        if p01.state.terminal:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.FETCH_CANONICAL_EVENT_TAIL,
                "terminal_p01_requires_canonical_event_tail",
                worker=worker,
                p01=p01,
            )

        if worker.state is WorkerObservationState.ACTIVE:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.WAIT_FOR_WORKER,
                "worker_lease_still_active",
                worker=worker,
                p01=p01,
            )

        if snapshot.dispatch_state in {
            DispatchState.ACKNOWLEDGED,
            DispatchState.RECONCILIATION_REQUIRED,
        }:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.ESCALATE_INCONSISTENT_STATE,
                "acknowledged_dispatch_without_current_execution_fact",
                worker=worker,
                p01=p01,
            )

        if p01.state in {P01ObservationState.UNKNOWN, P01ObservationState.NOT_FOUND} and worker.state in {
            WorkerObservationState.UNKNOWN,
            WorkerObservationState.NOT_FOUND,
            WorkerObservationState.EXPIRED,
            WorkerObservationState.RELEASED,
        }:
            return self._decision(
                snapshot,
                ReconciliationDecisionKind.MANUAL_REQUEUE_REVIEW,
                "no_active_execution_fact_manual_policy_review",
                worker=worker,
                p01=p01,
            )

        return self._decision(
            snapshot,
            ReconciliationDecisionKind.ESCALATE_INCONSISTENT_STATE,
            "unclassified_reconciliation_state",
            worker=worker,
            p01=p01,
        )

    @staticmethod
    def _identity_error(
        snapshot: RunPersistenceSnapshot,
        worker: TrustedWorkerLeaseObservation,
        p01: TrustedP01RunObservation,
    ) -> str | None:
        if snapshot.worker_lease_id is not None and worker.lease_id is not None:
            if worker.lease_id != snapshot.worker_lease_id:
                return "worker_lease_identity_mismatch"
        if snapshot.p01_run_id is not None and p01.p01_run_id is not None:
            if p01.p01_run_id != snapshot.p01_run_id:
                return "p01_run_identity_mismatch"
        if snapshot.p01_last_sequence is not None and p01.latest_sequence is not None:
            if p01.latest_sequence < snapshot.p01_last_sequence:
                return "p01_sequence_regression"
        return None

    @staticmethod
    def _decision(
        snapshot: RunPersistenceSnapshot,
        kind: ReconciliationDecisionKind,
        reason: str,
        *,
        worker: TrustedWorkerLeaseObservation,
        p01: TrustedP01RunObservation,
    ) -> RunReconciliationDecision:
        return RunReconciliationDecision(
            run_id=snapshot.run_id,
            snapshot_generation=snapshot.generation,
            snapshot_digest=snapshot.snapshot_digest,
            kind=kind,
            reason_codes=(reason,),
            p01_run_id=p01.p01_run_id or snapshot.p01_run_id,
            p01_latest_sequence=p01.latest_sequence or snapshot.p01_last_sequence,
            worker_lease_id=worker.lease_id or snapshot.worker_lease_id,
            cancellation_id=snapshot.cancellation_id,
        )


REAL_RECONCILIATION_PROBES_CONFIGURED = False
AUTO_RECONCILIATION_EXECUTION_SUPPORTED = False
B54_RECOVERY_POLICY_IMPLEMENTED = False
