"""Blocker B: a failed claim must not stay pending forever.

On generation/validation/transaction failure the claim is transitioned to
``failed_retryable`` and a later retry can reclaim it and complete normally. A
bounded lease also lets a stale ``pending`` claim (crashed owner) be reclaimed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.operation import OperationIdentity, TASK_SECOND_LESSON
from app.repositories import (
    STATUS_COMPLETED,
    STATUS_FAILED_RETRYABLE,
    STATUS_PENDING,
    claim_operation,
    complete_operation,
    fail_operation,
    get_operation,
)

from tests.contracts.conftest import make_pipeline


def _identity(key: str) -> OperationIdentity:
    return OperationIdentity(
        task_type=TASK_SECOND_LESSON,
        learner_id="L1",
        client_idempotency_key=key,
        prior_lesson_id="lesson_prior",
        comprehension_response_id="resp_1",
        feedback_id="fb_1",
    )


def test_failure_transitions_claim_to_retryable(file_db):
    pipeline = make_pipeline(file_db)
    try:
        identity = _identity("k-fail")
        pipeline._begin_immediate()
        outcome = claim_operation(pipeline.conn, identity)
        pipeline.conn.commit()
        assert outcome.acquired

        # Simulate a generation/transaction failure: recover the claim.
        pipeline._begin_immediate()
        fail_operation(pipeline.conn, identity.operation_key, terminal=False)
        pipeline.conn.commit()

        rec = get_operation(pipeline.conn, identity.operation_key)
        assert rec.status == STATUS_FAILED_RETRYABLE
    finally:
        pipeline.conn.close()


def test_retryable_claim_can_be_reclaimed_and_completed(file_db):
    pipeline = make_pipeline(file_db)
    try:
        identity = _identity("k-retry")
        pipeline._begin_immediate()
        assert claim_operation(pipeline.conn, identity).acquired
        pipeline.conn.commit()

        # First attempt fails -> retryable.
        pipeline._begin_immediate()
        fail_operation(pipeline.conn, identity.operation_key, terminal=False)
        pipeline.conn.commit()

        # A retry reclaims the failed_retryable claim.
        pipeline._begin_immediate()
        outcome = claim_operation(pipeline.conn, identity)
        pipeline.conn.commit()
        assert outcome.acquired
        assert outcome.record.attempt_number == 2

        # The retry completes successfully.
        pipeline._begin_immediate()
        complete_operation(pipeline.conn, identity.operation_key, result_json='{"lesson_id": "L2"}')
        pipeline.conn.commit()

        rec = get_operation(pipeline.conn, identity.operation_key)
        assert rec.status == STATUS_COMPLETED
    finally:
        pipeline.conn.close()


def test_stale_pending_claim_is_reclaimable_after_lease(file_db):
    pipeline = make_pipeline(file_db)
    try:
        identity = _identity("k-stale")
        # Claim with a 1-second lease.
        pipeline._begin_immediate()
        assert claim_operation(pipeline.conn, identity, lease_ttl_seconds=1).acquired
        pipeline.conn.commit()

        # Immediately, another owner sees an active (non-stale) claim -> conflict.
        pipeline._begin_immediate()
        assert claim_operation(pipeline.conn, identity, lease_ttl_seconds=1).conflict
        pipeline.conn.commit()

        # After the lease expires, the claim can be reclaimed.
        future = datetime.now(timezone.utc) + timedelta(seconds=5)
        pipeline._begin_immediate()
        outcome = claim_operation(pipeline.conn, identity, lease_ttl_seconds=1, now=future)
        pipeline.conn.commit()
        assert outcome.acquired
    finally:
        pipeline.conn.close()


def test_terminal_failure_is_not_reclaimable(file_db):
    pipeline = make_pipeline(file_db)
    try:
        identity = _identity("k-terminal")
        pipeline._begin_immediate()
        assert claim_operation(pipeline.conn, identity).acquired
        pipeline.conn.commit()

        pipeline._begin_immediate()
        fail_operation(pipeline.conn, identity.operation_key, terminal=True)
        pipeline.conn.commit()

        pipeline._begin_immediate()
        outcome = claim_operation(pipeline.conn, identity)
        pipeline.conn.commit()
        assert outcome.terminal
        assert not outcome.acquired
    finally:
        pipeline.conn.close()
