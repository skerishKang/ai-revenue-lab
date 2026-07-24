"""P0: stale-owner fencing.

Once a claim's lease expires and another owner reclaims it, the stale owner can
neither complete nor fail the operation — its fenced CAS (owner_token +
fencing_version) matches zero rows and raises ``LostClaimOwnershipError``. A
stale owner's product writes roll back, so only the current owner's result
becomes product state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.operation import OperationIdentity, TASK_SECOND_LESSON
from app.pipeline.errors import LostClaimOwnershipError
from app.repositories import (
    STATUS_COMPLETED,
    claim_operation,
    complete_operation,
    fail_operation,
    get_operation,
)

from tests.contracts.conftest import bootstrap_learner, make_pipeline


def _identity(key: str) -> OperationIdentity:
    return OperationIdentity(
        task_type=TASK_SECOND_LESSON,
        learner_id="L1",
        client_idempotency_key=key,
        prior_lesson_id="lesson_prior",
        comprehension_response_id="resp_1",
        feedback_id="fb_1",
    )


def _expire_lease(pipeline, operation_key: str) -> None:
    past = (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    pipeline.conn.execute(
        "UPDATE idempotency_requests SET lease_expires_at = ? WHERE key_value = ?",
        (past, operation_key),
    )
    pipeline.conn.commit()


def _reclaim(pipeline, identity: OperationIdentity):
    future = datetime.now(timezone.utc) + timedelta(seconds=5)
    pipeline._begin_immediate()
    outcome = claim_operation(pipeline.conn, identity, lease_ttl_seconds=300, now=future)
    pipeline.conn.commit()
    return outcome


def test_stale_owner_cannot_complete_reclaimed_claim(file_db):
    a = make_pipeline(file_db)
    b = make_pipeline(file_db)
    try:
        identity = _identity("so-complete")
        # A acquires (fencing 1).
        a._begin_immediate()
        handle_a = claim_operation(a.conn, identity).handle
        a.conn.commit()

        # A's lease expires; B reclaims (fencing 2, new owner token).
        _expire_lease(a, identity.operation_key)
        outcome_b = _reclaim(b, identity)
        assert outcome_b.acquired
        assert outcome_b.handle.fencing_version == 2

        # A (stale) tries to complete -> rejected.
        a._begin_immediate()
        with pytest.raises(LostClaimOwnershipError):
            complete_operation(a.conn, handle_a, result_json='{"owner": "A"}')
        a.conn.rollback()

        # B completes successfully; only B's result exists.
        b._begin_immediate()
        complete_operation(b.conn, outcome_b.handle, result_json='{"owner": "B"}')
        b.conn.commit()

        rec = get_operation(a.conn, identity.operation_key)
        assert rec.status == STATUS_COMPLETED
        assert rec.result_json == '{"owner": "B"}'
    finally:
        a.conn.close()
        b.conn.close()


def test_stale_owner_cannot_fail_reclaimed_claim(file_db):
    a = make_pipeline(file_db)
    b = make_pipeline(file_db)
    try:
        identity = _identity("so-fail")
        a._begin_immediate()
        handle_a = claim_operation(a.conn, identity).handle
        a.conn.commit()

        _expire_lease(a, identity.operation_key)
        outcome_b = _reclaim(b, identity)
        assert outcome_b.acquired

        # A (stale) tries to fail the claim -> rejected (cannot clobber B's claim).
        a._begin_immediate()
        with pytest.raises(LostClaimOwnershipError):
            fail_operation(a.conn, handle_a, terminal=False)
        a.conn.rollback()

        # The claim is still pending under B's ownership (not failed by A).
        rec = get_operation(a.conn, identity.operation_key)
        assert rec.status == "pending"
        assert rec.fencing_version == 2
    finally:
        a.conn.close()
        b.conn.close()


def test_current_owner_can_complete_after_reclaim(file_db):
    a = make_pipeline(file_db)
    b = make_pipeline(file_db)
    try:
        identity = _identity("so-current")
        a._begin_immediate()
        claim_operation(a.conn, identity)
        a.conn.commit()

        _expire_lease(a, identity.operation_key)
        outcome_b = _reclaim(b, identity)
        assert outcome_b.acquired

        # The current owner (B) completes normally.
        b._begin_immediate()
        complete_operation(b.conn, outcome_b.handle, result_json='{"lesson_id": "L_B"}')
        b.conn.commit()

        rec = get_operation(a.conn, identity.operation_key)
        assert rec.status == STATUS_COMPLETED
        assert rec.result_json == '{"lesson_id": "L_B"}'
    finally:
        a.conn.close()
        b.conn.close()


def test_stale_owner_product_writes_rollback(file_db):
    """A stale owner runs the full second-lesson persist; its completion CAS
    fails, so the whole product transaction (lesson, feedback application,
    mastery, adaptation) rolls back. Only the current owner (B) creates the
    second lesson."""
    learner_id, concept_id = bootstrap_learner(file_db)
    setup = make_pipeline(file_db)
    try:
        lesson_id = setup.start_first_lesson(learner_id, concept_id)
        comp = setup.record_comprehension(lesson_id, learner_id, understood=False, free_text="hard")
        fb = setup.record_feedback(lesson_id, learner_id, ["more_examples"], idempotency_key="pw-fb")
    finally:
        setup.conn.close()

    identity = OperationIdentity(
        task_type=TASK_SECOND_LESSON,
        learner_id=learner_id,
        client_idempotency_key="pw-key",
        prior_lesson_id=lesson_id,
        comprehension_response_id=comp["response_id"],
        feedback_id=fb["feedback_id"],
    )

    a = make_pipeline(file_db)
    b = make_pipeline(file_db)
    try:
        from app.repositories import get_feedback_by_id, get_lesson_by_id

        original_lesson = get_lesson_by_id(a.conn, lesson_id)
        feedback = get_feedback_by_id(a.conn, fb["feedback_id"])
        comprehension = a.conn.execute(
            "SELECT * FROM comprehension_responses WHERE id = ?", (comp["response_id"],)
        ).fetchone()

        # A acquires the claim (fencing 1).
        a._begin_immediate()
        handle_a = claim_operation(a.conn, identity).handle
        a.conn.commit()

        # A's lease expires; B reclaims (fencing 2).
        _expire_lease(a, identity.operation_key)
        outcome_b = _reclaim(b, identity)
        assert outcome_b.acquired
        assert outcome_b.handle.fencing_version == 2

        # A (stale) runs the full second-lesson generation+persist. The provider
        # generation succeeds, but the fenced completion CAS fails and the entire
        # product transaction rolls back.
        with pytest.raises(LostClaimOwnershipError):
            a._generate_adapted_content(
                lesson_id="lesson_stale_A",
                learner_id=learner_id,
                original_lesson=original_lesson,
                feedback=feedback,
                comprehension=comprehension,
                handle=handle_a,
            )

        # A's lesson was rolled back: still only the first lesson exists.
        count_a = a.conn.execute(
            "SELECT count(*) AS c FROM lessons WHERE learner_id = ?", (learner_id,)
        ).fetchone()["c"]
        assert count_a == 1
        # Feedback remains unapplied (A's CAS rolled back).
        applied = a.conn.execute(
            "SELECT applied_status FROM feedback WHERE id = ?", (fb["feedback_id"],)
        ).fetchone()["applied_status"]
        assert applied == "not_applied"
        # No adaptation decision from A.
        adapt_a = a.conn.execute(
            "SELECT count(*) AS c FROM adaptation_decisions WHERE learner_id = ?", (learner_id,)
        ).fetchone()["c"]
        assert adapt_a == 0

        # B (current owner) generates the second lesson successfully.
        new_lesson_id = b._generate_adapted_content(
            lesson_id="lesson_owner_B",
            learner_id=learner_id,
            original_lesson=original_lesson,
            feedback=feedback,
            comprehension=comprehension,
            handle=outcome_b.handle,
        )
        assert new_lesson_id == "lesson_owner_B"

        # Exactly one second lesson (B's) exists.
        second = b.conn.execute(
            "SELECT count(*) AS c FROM lessons WHERE learner_id = ? AND lesson_number = 2",
            (learner_id,),
        ).fetchone()["c"]
        assert second == 1
        # The claim is completed with B's result.
        rec = get_operation(b.conn, identity.operation_key)
        assert rec.status == STATUS_COMPLETED
    finally:
        a.conn.close()
        b.conn.close()
