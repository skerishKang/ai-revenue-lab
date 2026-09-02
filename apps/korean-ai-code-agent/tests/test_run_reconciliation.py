from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.background_dispatch import BackgroundDispatchRequest, CancellationIntent, InMemoryBackgroundDispatchQueue
from kagent.contracts import ClawRunStatus, ExecutionMode, RunProjection
from kagent.run_persistence import RunPersistenceSnapshot
from kagent.run_reconciliation import (
    AUTO_RECONCILIATION_EXECUTION_SUPPORTED,
    B54_RECOVERY_POLICY_IMPLEMENTED,
    REAL_RECONCILIATION_PROBES_CONFIGURED,
    P01ObservationState,
    ReconciliationDecisionKind,
    RunRestartReconciliationEvaluator,
    TrustedP01RunObservation,
    TrustedWorkerLeaseObservation,
    WorkerObservationState,
)


NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
REV = "abcdef1234567890abcdef1234567890abcdef12"


def make_queue() -> InMemoryBackgroundDispatchQueue:
    queue = InMemoryBackgroundDispatchQueue()
    queue.enqueue(
        BackgroundDispatchRequest(
            dispatch_id="dispatch_1",
            run_id="run_1",
            repository_ref="skerishKang/example",
            exact_revision=REV,
            requested_at=NOW,
        )
    )
    return queue


def snapshot(
    queue: InMemoryBackgroundDispatchQueue,
    *,
    status: ClawRunStatus = ClawRunStatus.PREPARING,
) -> RunPersistenceSnapshot:
    run = RunProjection(
        run_id="run_1",
        task_id="task_1",
        status=status,
        execution_mode=ExecutionMode.CLOUD,
        summary="bounded",
        approval_required=status is ClawRunStatus.WAITING_APPROVAL,
    )
    return RunPersistenceSnapshot.capture(
        run=run,
        dispatch=queue.projection("dispatch_1"),
        generation=1,
        saved_at=NOW,
    )


def worker(
    state: WorkerObservationState,
    *,
    lease_id: str | None = None,
    run_id: str = "run_1",
    observed_at: datetime | None = None,
) -> TrustedWorkerLeaseObservation:
    return TrustedWorkerLeaseObservation(
        run_id=run_id,
        observed_at=observed_at or NOW + timedelta(seconds=10),
        state=state,
        lease_id=lease_id,
    )


def p01(
    state: P01ObservationState,
    *,
    p01_run_id: str | None = None,
    latest_sequence: int | None = None,
    run_id: str = "run_1",
    observed_at: datetime | None = None,
) -> TrustedP01RunObservation:
    return TrustedP01RunObservation(
        run_id=run_id,
        observed_at=observed_at or NOW + timedelta(seconds=10),
        state=state,
        p01_run_id=p01_run_id,
        latest_sequence=latest_sequence,
    )


class RunReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = RunRestartReconciliationEvaluator()

    def test_terminal_b54_snapshot_never_resumes(self):
        snap = snapshot(make_queue(), status=ClawRunStatus.CANCELLED)
        decision = self.evaluator.evaluate(
            snapshot=snap,
            worker=worker(WorkerObservationState.NOT_FOUND),
            p01=p01(P01ObservationState.NOT_FOUND),
        )
        self.assertEqual(decision.kind, ReconciliationDecisionKind.NO_ACTION_TERMINAL)
        self.assertFalse(decision.automatic_resume_allowed)
        self.assertFalse(decision.automatic_redispatch_allowed)

    def test_active_worker_waits_when_no_canonical_p01_run_observed(self):
        queue = make_queue()
        lease = queue.claim_next(worker_id="worker_1", now=NOW, ttl_seconds=120)
        assert lease is not None
        snap = snapshot(queue)
        decision = self.evaluator.evaluate(
            snapshot=snap,
            worker=worker(WorkerObservationState.ACTIVE, lease_id=lease.lease_id),
            p01=p01(P01ObservationState.NOT_FOUND),
        )
        self.assertEqual(decision.kind, ReconciliationDecisionKind.WAIT_FOR_WORKER)
        self.assertIn("worker_lease_still_active", decision.reason_codes)

    def test_active_p01_always_blocks_redispatch_and_fetches_event_tail(self):
        queue = make_queue()
        queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=1,
            event_id="evt_1",
        )
        snap = snapshot(queue, status=ClawRunStatus.RUNNING)
        for state in (P01ObservationState.RUNNING, P01ObservationState.WAITING_APPROVAL):
            with self.subTest(state=state):
                decision = self.evaluator.evaluate(
                    snapshot=snap,
                    worker=worker(WorkerObservationState.NOT_FOUND),
                    p01=p01(state, p01_run_id="orch_1", latest_sequence=2),
                )
                self.assertEqual(decision.kind, ReconciliationDecisionKind.FETCH_CANONICAL_EVENT_TAIL)
                self.assertIn("active_p01_blocks_redispatch", decision.reason_codes)
                self.assertFalse(decision.automatic_redispatch_allowed)

    def test_terminal_p01_status_requires_canonical_event_tail_before_b54_projection(self):
        queue = make_queue()
        queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=1,
            event_id="evt_1",
        )
        snap = snapshot(queue, status=ClawRunStatus.RUNNING)
        for state in (P01ObservationState.COMPLETED, P01ObservationState.FAILED, P01ObservationState.CANCELLED):
            with self.subTest(state=state):
                decision = self.evaluator.evaluate(
                    snapshot=snap,
                    worker=worker(WorkerObservationState.NOT_FOUND),
                    p01=p01(state, p01_run_id="orch_1", latest_sequence=3),
                )
                self.assertEqual(decision.kind, ReconciliationDecisionKind.FETCH_CANONICAL_EVENT_TAIL)

    def test_cancellation_intent_takes_precedence(self):
        queue = make_queue()
        queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=1,
            event_id="evt_1",
        )
        queue.request_cancellation(
            CancellationIntent(
                cancellation_id="cancel_1",
                dispatch_id="dispatch_1",
                run_id="run_1",
                requested_at=NOW,
                reason_ref="user-request:1",
            )
        )
        snap = snapshot(queue, status=ClawRunStatus.RUNNING)
        pending = self.evaluator.evaluate(
            snapshot=snap,
            worker=worker(WorkerObservationState.NOT_FOUND),
            p01=p01(P01ObservationState.RUNNING, p01_run_id="orch_1", latest_sequence=2),
        )
        self.assertEqual(pending.kind, ReconciliationDecisionKind.RECONCILE_CANCELLATION)
        cancelled = self.evaluator.evaluate(
            snapshot=snap,
            worker=worker(WorkerObservationState.NOT_FOUND),
            p01=p01(P01ObservationState.CANCELLED, p01_run_id="orch_1", latest_sequence=3),
        )
        self.assertEqual(cancelled.kind, ReconciliationDecisionKind.FETCH_CANONICAL_EVENT_TAIL)
        self.assertIn("cancellation_seen_fetch_canonical_event", cancelled.reason_codes)

    def test_acknowledged_dispatch_missing_worker_and_p01_escalates_not_requeues(self):
        queue = make_queue()
        lease = queue.claim_next(worker_id="worker_1", now=NOW, ttl_seconds=30)
        assert lease is not None
        queue.acknowledge(lease_id=lease.lease_id, now=NOW + timedelta(seconds=1))
        queue.expire(lease_id=lease.lease_id, now=NOW + timedelta(seconds=31))
        snap = snapshot(queue)
        self.assertEqual(snap.dispatch_state.value, "reconciliation_required")
        decision = self.evaluator.evaluate(
            snapshot=snap,
            worker=worker(WorkerObservationState.NOT_FOUND),
            p01=p01(P01ObservationState.NOT_FOUND),
        )
        self.assertEqual(decision.kind, ReconciliationDecisionKind.ESCALATE_INCONSISTENT_STATE)
        self.assertIn("acknowledged_dispatch_without_current_execution_fact", decision.reason_codes)

    def test_clean_queued_run_with_no_execution_fact_is_manual_requeue_review_only(self):
        snap = snapshot(make_queue())
        decision = self.evaluator.evaluate(
            snapshot=snap,
            worker=worker(WorkerObservationState.NOT_FOUND),
            p01=p01(P01ObservationState.NOT_FOUND),
        )
        self.assertEqual(decision.kind, ReconciliationDecisionKind.MANUAL_REQUEUE_REVIEW)
        self.assertFalse(decision.automatic_resume_allowed)
        self.assertFalse(decision.automatic_redispatch_allowed)

    def test_worker_identity_p01_identity_sequence_and_run_mismatch_escalate(self):
        queue = make_queue()
        lease = queue.claim_next(worker_id="worker_1", now=NOW, ttl_seconds=120)
        assert lease is not None
        queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=2,
            event_id="evt_2",
        ) if False else None
        # First sequence must be 1, then advance to 2.
        queue.record_p01_cursor(dispatch_id="dispatch_1", p01_run_id="orch_1", sequence=1, event_id="evt_1")
        queue.record_p01_cursor(dispatch_id="dispatch_1", p01_run_id="orch_1", sequence=2, event_id="evt_2")
        snap = snapshot(queue, status=ClawRunStatus.RUNNING)

        cases = (
            (
                worker(WorkerObservationState.ACTIVE, lease_id="other_lease"),
                p01(P01ObservationState.RUNNING, p01_run_id="orch_1", latest_sequence=2),
                "worker_lease_identity_mismatch",
            ),
            (
                worker(WorkerObservationState.ACTIVE, lease_id=lease.lease_id),
                p01(P01ObservationState.RUNNING, p01_run_id="orch_other", latest_sequence=2),
                "p01_run_identity_mismatch",
            ),
            (
                worker(WorkerObservationState.ACTIVE, lease_id=lease.lease_id),
                p01(P01ObservationState.RUNNING, p01_run_id="orch_1", latest_sequence=1),
                "p01_sequence_regression",
            ),
            (
                worker(WorkerObservationState.ACTIVE, lease_id=lease.lease_id, run_id="run_other"),
                p01(P01ObservationState.RUNNING, p01_run_id="orch_1", latest_sequence=2),
                "run_identity_mismatch",
            ),
        )
        for worker_obs, p01_obs, reason in cases:
            with self.subTest(reason=reason):
                decision = self.evaluator.evaluate(snapshot=snap, worker=worker_obs, p01=p01_obs)
                self.assertEqual(decision.kind, ReconciliationDecisionKind.ESCALATE_INCONSISTENT_STATE)
                self.assertIn(reason, decision.reason_codes)

    def test_stale_observations_escalate(self):
        snap = snapshot(make_queue())
        decision = self.evaluator.evaluate(
            snapshot=snap,
            worker=worker(
                WorkerObservationState.NOT_FOUND,
                observed_at=NOW - timedelta(seconds=1),
            ),
            p01=p01(P01ObservationState.NOT_FOUND),
        )
        self.assertEqual(decision.kind, ReconciliationDecisionKind.ESCALATE_INCONSISTENT_STATE)
        self.assertIn("stale_observation", decision.reason_codes)

    def test_product_layer_implements_no_retry_recovery_or_real_probe(self):
        decision = self.evaluator.evaluate(
            snapshot=snapshot(make_queue()),
            worker=worker(WorkerObservationState.NOT_FOUND),
            p01=p01(P01ObservationState.NOT_FOUND),
        )
        rendered = decision.safe_dict()
        self.assertEqual(rendered["retry_authority"], "p01")
        self.assertEqual(rendered["recovery_authority"], "p01")
        self.assertFalse(REAL_RECONCILIATION_PROBES_CONFIGURED)
        self.assertFalse(AUTO_RECONCILIATION_EXECUTION_SUPPORTED)
        self.assertFalse(B54_RECOVERY_POLICY_IMPLEMENTED)


if __name__ == "__main__":
    unittest.main()
