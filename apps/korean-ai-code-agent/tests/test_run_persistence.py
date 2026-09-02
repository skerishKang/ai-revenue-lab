from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.background_dispatch import (
    BackgroundDispatchRequest,
    CancellationIntent,
    InMemoryBackgroundDispatchQueue,
)
from kagent.contracts import ClawRunStatus, ContractError, ExecutionMode, RunProjection
from kagent.run_persistence import (
    AUTO_RESUME_FROM_B54_SNAPSHOT_SUPPORTED,
    B54_P01_INTERNAL_STATE_PERSISTENCE_SUPPORTED,
    REAL_DURABLE_RUN_STORE_CONFIGURED,
    InMemoryRunSnapshotStore,
    RestoreAction,
    RunPersistenceSnapshot,
    build_restore_plan,
)


NOW = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)
REV = "abcdef1234567890abcdef1234567890abcdef12"


def run_projection(status: ClawRunStatus = ClawRunStatus.PREPARING, *, summary: str = "준비 중") -> RunProjection:
    return RunProjection(
        run_id="run_1",
        task_id="task_1",
        status=status,
        execution_mode=ExecutionMode.CLOUD,
        summary=summary,
        changed_files=("src/app.py",) if status in {ClawRunStatus.RUNNING, ClawRunStatus.COMPLETED} else (),
        approval_required=status is ClawRunStatus.WAITING_APPROVAL,
    )


def queue_with_dispatch() -> InMemoryBackgroundDispatchQueue:
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


def capture(
    queue: InMemoryBackgroundDispatchQueue,
    *,
    generation: int,
    status: ClawRunStatus = ClawRunStatus.PREPARING,
    saved_at: datetime | None = None,
    summary: str = "준비 중",
) -> RunPersistenceSnapshot:
    return RunPersistenceSnapshot.capture(
        run=run_projection(status, summary=summary),
        dispatch=queue.projection("dispatch_1"),
        generation=generation,
        saved_at=saved_at or NOW,
    )


class RunPersistenceSnapshotTests(unittest.TestCase):
    def test_snapshot_contains_only_bounded_product_projection(self):
        queue = queue_with_dispatch()
        snapshot = capture(queue, generation=1, summary="준비 token=fixturevalue")
        rendered = snapshot.safe_dict()
        self.assertNotIn("fixturevalue", rendered["summary"])
        self.assertFalse(rendered["task_prompt_stored"])
        self.assertFalse(rendered["raw_model_messages_stored"])
        self.assertFalse(rendered["hidden_reasoning_stored"])
        self.assertFalse(rendered["tool_arguments_stored"])
        self.assertFalse(rendered["provider_credentials_stored"])
        self.assertFalse(rendered["p01_internal_state_stored"])
        self.assertEqual(snapshot.exact_revision, REV)
        self.assertEqual(len(snapshot.snapshot_digest), 64)
        self.assertFalse(REAL_DURABLE_RUN_STORE_CONFIGURED)
        self.assertFalse(AUTO_RESUME_FROM_B54_SNAPSHOT_SUPPORTED)
        self.assertFalse(B54_P01_INTERNAL_STATE_PERSISTENCE_SUPPORTED)

    def test_capture_requires_exact_cloud_run_dispatch_correlation(self):
        queue = queue_with_dispatch()
        local = RunProjection(
            run_id="run_1",
            task_id="task_1",
            status=ClawRunStatus.PREPARING,
            execution_mode=ExecutionMode.LOCAL,
        )
        with self.assertRaises(ContractError):
            RunPersistenceSnapshot.capture(
                run=local,
                dispatch=queue.projection("dispatch_1"),
                generation=1,
                saved_at=NOW,
            )
        other = RunProjection(
            run_id="run_other",
            task_id="task_1",
            status=ClawRunStatus.PREPARING,
            execution_mode=ExecutionMode.CLOUD,
        )
        with self.assertRaises(ContractError):
            RunPersistenceSnapshot.capture(
                run=other,
                dispatch=queue.projection("dispatch_1"),
                generation=1,
                saved_at=NOW,
            )


class RunSnapshotStoreTests(unittest.TestCase):
    def test_append_only_generation_and_compare_and_swap(self):
        queue = queue_with_dispatch()
        store = InMemoryRunSnapshotStore()
        first = capture(queue, generation=1)
        self.assertEqual(store.save(first, expected_generation=0), first)
        second = capture(queue, generation=2, saved_at=NOW + timedelta(seconds=1))
        with self.assertRaisesRegex(ContractError, "compare-and-swap"):
            store.save(second, expected_generation=0)
        self.assertEqual(store.save(second, expected_generation=1), second)
        self.assertEqual(store.history("run_1"), (first, second))

    def test_exact_same_generation_replay_is_idempotent_but_conflict_fails(self):
        queue = queue_with_dispatch()
        store = InMemoryRunSnapshotStore()
        first = capture(queue, generation=1)
        store.save(first, expected_generation=0)
        self.assertEqual(store.save(first, expected_generation=999), first)
        conflict = capture(
            queue,
            generation=1,
            saved_at=NOW + timedelta(seconds=1),
            summary="다른 상태",
        )
        with self.assertRaisesRegex(ContractError, "conflicts"):
            store.save(conflict, expected_generation=1)

    def test_terminal_snapshot_cannot_advance_or_resurrect(self):
        queue = queue_with_dispatch()
        queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=1,
            event_id="evt_1",
        )
        store = InMemoryRunSnapshotStore()
        completed = capture(queue, generation=1, status=ClawRunStatus.COMPLETED)
        store.save(completed, expected_generation=0)
        resurrected = capture(
            queue,
            generation=2,
            status=ClawRunStatus.RUNNING,
            saved_at=NOW + timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ContractError, "terminal"):
            store.save(resurrected, expected_generation=1)

    def test_p01_cursor_cannot_regress_switch_or_disappear(self):
        queue = queue_with_dispatch()
        queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=1,
            event_id="evt_1",
        )
        store = InMemoryRunSnapshotStore()
        first = capture(queue, generation=1, status=ClawRunStatus.RUNNING)
        store.save(first, expected_generation=0)
        queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=2,
            event_id="evt_2",
        )
        second = capture(
            queue,
            generation=2,
            status=ClawRunStatus.WAITING_APPROVAL,
            saved_at=NOW + timedelta(seconds=1),
        )
        store.save(second, expected_generation=1)

        disappeared = RunPersistenceSnapshot(
            run_id=second.run_id,
            task_id=second.task_id,
            generation=3,
            run_status=ClawRunStatus.WAITING_APPROVAL,
            execution_mode=second.execution_mode,
            repository_ref=second.repository_ref,
            exact_revision=second.exact_revision,
            summary=second.summary,
            changed_files=second.changed_files,
            dispatch_id=second.dispatch_id,
            dispatch_state=second.dispatch_state,
            worker_lease_id=second.worker_lease_id,
            worker_lease_expires_at=second.worker_lease_expires_at,
            cancellation_id=second.cancellation_id,
            p01_run_id=None,
            p01_last_sequence=None,
            p01_last_event_id=None,
            saved_at=NOW + timedelta(seconds=2),
        )
        with self.assertRaisesRegex(ContractError, "P01 run identity"):
            store.save(disappeared, expected_generation=2)

        switched = RunPersistenceSnapshot(
            run_id=second.run_id,
            task_id=second.task_id,
            generation=3,
            run_status=ClawRunStatus.RUNNING,
            execution_mode=second.execution_mode,
            repository_ref=second.repository_ref,
            exact_revision=second.exact_revision,
            summary=second.summary,
            changed_files=second.changed_files,
            dispatch_id=second.dispatch_id,
            dispatch_state=second.dispatch_state,
            worker_lease_id=second.worker_lease_id,
            worker_lease_expires_at=second.worker_lease_expires_at,
            cancellation_id=second.cancellation_id,
            p01_run_id="orch_other",
            p01_last_sequence=3,
            p01_last_event_id="evt_3",
            saved_at=NOW + timedelta(seconds=2),
        )
        with self.assertRaisesRegex(ContractError, "P01 run identity"):
            store.save(switched, expected_generation=2)

        regressed = RunPersistenceSnapshot(
            run_id=second.run_id,
            task_id=second.task_id,
            generation=3,
            run_status=ClawRunStatus.RUNNING,
            execution_mode=second.execution_mode,
            repository_ref=second.repository_ref,
            exact_revision=second.exact_revision,
            summary=second.summary,
            changed_files=second.changed_files,
            dispatch_id=second.dispatch_id,
            dispatch_state=second.dispatch_state,
            worker_lease_id=second.worker_lease_id,
            worker_lease_expires_at=second.worker_lease_expires_at,
            cancellation_id=second.cancellation_id,
            p01_run_id="orch_1",
            p01_last_sequence=1,
            p01_last_event_id="evt_1",
            saved_at=NOW + timedelta(seconds=2),
        )
        with self.assertRaisesRegex(ContractError, "cursor"):
            store.save(regressed, expected_generation=2)

    def test_cancellation_intent_cannot_disappear(self):
        queue = queue_with_dispatch()
        queue.request_cancellation(
            CancellationIntent(
                cancellation_id="cancel_1",
                dispatch_id="dispatch_1",
                run_id="run_1",
                requested_at=NOW,
                reason_ref="user-request:1",
            )
        )
        store = InMemoryRunSnapshotStore()
        first = capture(queue, generation=1)
        store.save(first, expected_generation=0)
        without_cancel = RunPersistenceSnapshot(
            run_id=first.run_id,
            task_id=first.task_id,
            generation=2,
            run_status=first.run_status,
            execution_mode=first.execution_mode,
            repository_ref=first.repository_ref,
            exact_revision=first.exact_revision,
            summary=first.summary,
            changed_files=first.changed_files,
            dispatch_id=first.dispatch_id,
            dispatch_state=first.dispatch_state,
            worker_lease_id=first.worker_lease_id,
            worker_lease_expires_at=first.worker_lease_expires_at,
            cancellation_id=None,
            p01_run_id=first.p01_run_id,
            p01_last_sequence=first.p01_last_sequence,
            p01_last_event_id=first.p01_last_event_id,
            saved_at=NOW + timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ContractError, "cancellation"):
            store.save(without_cancel, expected_generation=1)


class RestorePlanTests(unittest.TestCase):
    def test_queued_snapshot_requires_policy_review_not_auto_redispatch(self):
        snapshot = capture(queue_with_dispatch(), generation=1)
        plan = build_restore_plan(snapshot)
        self.assertEqual(plan.action, RestoreAction.POLICY_REQUEUE_REVIEW)
        self.assertFalse(plan.automatic_resume_allowed)
        self.assertFalse(plan.automatic_redispatch_allowed)

    def test_active_worker_lease_requires_lease_reconciliation(self):
        queue = queue_with_dispatch()
        queue.claim_next(worker_id="worker_1", now=NOW)
        plan = build_restore_plan(capture(queue, generation=1))
        self.assertEqual(plan.action, RestoreAction.RECONCILE_WORKER_LEASE)
        self.assertIsNotNone(plan.worker_lease_id)

    def test_p01_cursor_requires_p01_reconciliation(self):
        queue = queue_with_dispatch()
        queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=1,
            event_id="evt_1",
        )
        plan = build_restore_plan(capture(queue, generation=1, status=ClawRunStatus.RUNNING))
        self.assertEqual(plan.action, RestoreAction.RECONCILE_P01)
        self.assertEqual(plan.p01_run_id, "orch_1")
        self.assertEqual(plan.p01_last_sequence, 1)

    def test_cancellation_takes_precedence_over_p01_reconciliation(self):
        queue = queue_with_dispatch()
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
        plan = build_restore_plan(capture(queue, generation=1, status=ClawRunStatus.RUNNING))
        self.assertEqual(plan.action, RestoreAction.RECONCILE_CANCELLATION)
        self.assertEqual(plan.cancellation_id, "cancel_1")

    def test_terminal_snapshot_never_resumes(self):
        queue = queue_with_dispatch()
        plan = build_restore_plan(capture(queue, generation=1, status=ClawRunStatus.CANCELLED))
        self.assertEqual(plan.action, RestoreAction.NO_ACTION_TERMINAL)
        self.assertFalse(plan.automatic_resume_allowed)
        self.assertFalse(plan.automatic_redispatch_allowed)


if __name__ == "__main__":
    unittest.main()
