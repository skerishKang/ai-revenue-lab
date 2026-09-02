from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.background_dispatch import (
    B54_AGENT_STATE_CHECKPOINT_SUPPORTED,
    B54_RECOVERY_ENGINE_SUPPORTED,
    B54_RETRY_ENGINE_SUPPORTED,
    REAL_QUEUE_DEPLOYMENT_SUPPORTED,
    BackgroundDispatchRequest,
    CancellationIntent,
    DispatchState,
    InMemoryBackgroundDispatchQueue,
    WorkerLeaseState,
)
from kagent.contracts import ContractError, ExecutionMode


NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)
REV = "abcdef1234567890abcdef1234567890abcdef12"


def request(dispatch_id: str = "dispatch_1", run_id: str = "run_1", *, at: datetime = NOW) -> BackgroundDispatchRequest:
    return BackgroundDispatchRequest(
        dispatch_id=dispatch_id,
        run_id=run_id,
        repository_ref="skerishKang/example",
        exact_revision=REV,
        requested_at=at,
    )


class BackgroundDispatchContractTests(unittest.TestCase):
    def test_cloud_and_exact_revision_are_mandatory(self):
        with self.assertRaises(ContractError):
            BackgroundDispatchRequest(
                dispatch_id="dispatch_local",
                run_id="run_local",
                repository_ref="repo",
                exact_revision=REV,
                requested_at=NOW,
                execution_mode=ExecutionMode.LOCAL,
            )
        with self.assertRaises(ContractError):
            BackgroundDispatchRequest(
                dispatch_id="dispatch_branch",
                run_id="run_branch",
                repository_ref="repo",
                exact_revision="main",
                requested_at=NOW,
            )

    def test_reference_fields_reject_credential_like_material(self):
        with self.assertRaises(ContractError):
            BackgroundDispatchRequest(
                dispatch_id="dispatch_secret",
                run_id="run_secret",
                repository_ref="token=fixturevalue",
                exact_revision=REV,
                requested_at=NOW,
            )
        with self.assertRaises(ContractError):
            CancellationIntent(
                cancellation_id="cancel_secret",
                dispatch_id="dispatch_1",
                run_id="run_1",
                requested_at=NOW,
                reason_ref="api_key=fixturevalue",
            )

    def test_safe_projection_has_no_execution_or_retry_authority(self):
        queue = InMemoryBackgroundDispatchQueue()
        queue.enqueue(request())
        rendered = queue.projection("dispatch_1").safe_dict()
        self.assertFalse(rendered["claw_running_claimed"])
        self.assertEqual(rendered["retry_authority"], "p01")
        self.assertEqual(rendered["recovery_authority"], "p01")
        self.assertNotIn("tool_arguments", rendered)
        self.assertNotIn("hidden_state", rendered)
        self.assertFalse(REAL_QUEUE_DEPLOYMENT_SUPPORTED)
        self.assertFalse(B54_RETRY_ENGINE_SUPPORTED)
        self.assertFalse(B54_RECOVERY_ENGINE_SUPPORTED)
        self.assertFalse(B54_AGENT_STATE_CHECKPOINT_SUPPORTED)


class BackgroundDispatchQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = InMemoryBackgroundDispatchQueue()

    def test_enqueue_is_one_dispatch_per_run_and_ids_are_unique(self):
        self.queue.enqueue(request())
        with self.assertRaises(ContractError):
            self.queue.enqueue(request())
        with self.assertRaises(ContractError):
            self.queue.enqueue(request("dispatch_2", "run_1"))

    def test_claim_order_is_deterministic_and_one_active_lease_per_dispatch(self):
        self.queue.enqueue(request("dispatch_later", "run_later", at=NOW + timedelta(seconds=1)))
        self.queue.enqueue(request("dispatch_first", "run_first", at=NOW))
        first = self.queue.claim_next(worker_id="worker_a", now=NOW + timedelta(seconds=2))
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.dispatch_id, "dispatch_first")
        second = self.queue.claim_next(worker_id="worker_b", now=NOW + timedelta(seconds=2))
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(second.dispatch_id, "dispatch_later")
        self.assertIsNone(self.queue.claim_next(worker_id="worker_c", now=NOW + timedelta(seconds=2)))

    def test_acknowledgement_does_not_claim_claw_running(self):
        self.queue.enqueue(request())
        lease = self.queue.claim_next(worker_id="worker_a", now=NOW)
        assert lease is not None
        acknowledged = self.queue.acknowledge(lease_id=lease.lease_id, now=NOW + timedelta(seconds=1))
        self.assertIsNotNone(acknowledged.acknowledged_at)
        projection = self.queue.projection("dispatch_1")
        self.assertEqual(projection.state, DispatchState.ACKNOWLEDGED)
        self.assertFalse(projection.safe_dict()["claw_running_claimed"])

    def test_heartbeat_extends_only_live_lease_and_expired_lease_cannot_heartbeat(self):
        self.queue.enqueue(request())
        lease = self.queue.claim_next(worker_id="worker_a", now=NOW, ttl_seconds=30)
        assert lease is not None
        heartbeat = self.queue.heartbeat(
            lease_id=lease.lease_id,
            now=NOW + timedelta(seconds=10),
            ttl_seconds=60,
        )
        self.assertEqual(heartbeat.heartbeat_at, NOW + timedelta(seconds=10))
        self.assertEqual(heartbeat.expires_at, NOW + timedelta(seconds=70))
        self.queue.expire(lease_id=lease.lease_id, now=NOW + timedelta(seconds=71))
        with self.assertRaises(ContractError):
            self.queue.heartbeat(lease_id=lease.lease_id, now=NOW + timedelta(seconds=72))

    def test_unacknowledged_expiry_requeues_but_acknowledged_expiry_requires_reconciliation(self):
        self.queue.enqueue(request())
        lease = self.queue.claim_next(worker_id="worker_a", now=NOW, ttl_seconds=30)
        assert lease is not None
        expired = self.queue.expire(lease_id=lease.lease_id, now=NOW + timedelta(seconds=30))
        self.assertEqual(expired.state, WorkerLeaseState.EXPIRED)
        self.assertEqual(self.queue.projection("dispatch_1").state, DispatchState.QUEUED)
        replacement = self.queue.claim_next(worker_id="worker_b", now=NOW + timedelta(seconds=31), ttl_seconds=30)
        assert replacement is not None
        self.queue.acknowledge(lease_id=replacement.lease_id, now=NOW + timedelta(seconds=32))
        self.queue.expire(lease_id=replacement.lease_id, now=NOW + timedelta(seconds=61))
        self.assertEqual(
            self.queue.projection("dispatch_1").state,
            DispatchState.RECONCILIATION_REQUIRED,
        )
        self.assertIsNone(self.queue.claim_next(worker_id="worker_c", now=NOW + timedelta(seconds=62)))

    def test_release_before_ack_requeues_but_after_ack_does_not_silently_redispatch(self):
        self.queue.enqueue(request())
        lease = self.queue.claim_next(worker_id="worker_a", now=NOW)
        assert lease is not None
        self.queue.release(lease_id=lease.lease_id, now=NOW + timedelta(seconds=1))
        self.assertEqual(self.queue.projection("dispatch_1").state, DispatchState.QUEUED)
        replacement = self.queue.claim_next(worker_id="worker_b", now=NOW + timedelta(seconds=2))
        assert replacement is not None
        self.queue.acknowledge(lease_id=replacement.lease_id, now=NOW + timedelta(seconds=3))
        self.queue.release(lease_id=replacement.lease_id, now=NOW + timedelta(seconds=4))
        self.assertEqual(
            self.queue.projection("dispatch_1").state,
            DispatchState.RECONCILIATION_REQUIRED,
        )

    def test_cancellation_is_intent_only_and_idempotent_only_for_exact_replay(self):
        self.queue.enqueue(request())
        intent = CancellationIntent(
            cancellation_id="cancel_1",
            dispatch_id="dispatch_1",
            run_id="run_1",
            requested_at=NOW,
            reason_ref="user-request:1",
        )
        self.assertEqual(self.queue.request_cancellation(intent), intent)
        self.assertEqual(self.queue.request_cancellation(intent), intent)
        projection = self.queue.projection("dispatch_1")
        self.assertEqual(projection.state, DispatchState.CANCELLATION_REQUESTED)
        self.assertFalse(projection.cancellation.safe_dict()["canonical_cancellation_confirmed"])
        with self.assertRaises(ContractError):
            self.queue.request_cancellation(
                CancellationIntent(
                    cancellation_id="cancel_2",
                    dispatch_id="dispatch_1",
                    run_id="run_1",
                    requested_at=NOW,
                    reason_ref="different-request:2",
                )
            )

    def test_cancellation_cannot_cross_run(self):
        self.queue.enqueue(request())
        with self.assertRaises(ContractError):
            self.queue.request_cancellation(
                CancellationIntent(
                    cancellation_id="cancel_cross",
                    dispatch_id="dispatch_1",
                    run_id="run_other",
                    requested_at=NOW,
                    reason_ref="user-request:cross",
                )
            )

    def test_p01_cursor_binds_run_and_requires_contiguous_sequence(self):
        self.queue.enqueue(request())
        first = self.queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=1,
            event_id="evt_1",
        )
        self.assertEqual(first.last_sequence, 1)
        self.assertEqual(
            self.queue.record_p01_cursor(
                dispatch_id="dispatch_1",
                p01_run_id="orch_1",
                sequence=1,
                event_id="evt_1",
            ),
            first,
        )
        second = self.queue.record_p01_cursor(
            dispatch_id="dispatch_1",
            p01_run_id="orch_1",
            sequence=2,
            event_id="evt_2",
        )
        self.assertEqual(second.last_sequence, 2)
        with self.assertRaises(ContractError):
            self.queue.record_p01_cursor(
                dispatch_id="dispatch_1",
                p01_run_id="orch_1",
                sequence=4,
                event_id="evt_4",
            )
        with self.assertRaises(ContractError):
            self.queue.record_p01_cursor(
                dispatch_id="dispatch_1",
                p01_run_id="orch_other",
                sequence=3,
                event_id="evt_3",
            )
        with self.assertRaises(ContractError):
            self.queue.record_p01_cursor(
                dispatch_id="dispatch_1",
                p01_run_id="orch_1",
                sequence=2,
                event_id="evt_conflict",
            )

    def test_first_cursor_cannot_skip_run_started_sequence(self):
        self.queue.enqueue(request())
        with self.assertRaises(ContractError):
            self.queue.record_p01_cursor(
                dispatch_id="dispatch_1",
                p01_run_id="orch_1",
                sequence=2,
                event_id="evt_2",
            )


if __name__ == "__main__":
    unittest.main()
