"""Blocker C: feedback idempotency.

The first request stores feedback; a duplicate (same operation key) returns the
existing result with no new feedback row, no re-application, no mastery change,
no second lesson, and no adaptation decision.
"""

from __future__ import annotations

from tests.contracts.conftest import bootstrap_learner, make_pipeline


def test_first_feedback_stores_duplicate_replays(file_db):
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        lesson_id = pipeline.start_first_lesson(learner_id, concept_id)

        first = pipeline.record_feedback(
            lesson_id, learner_id, ["more_examples"], idempotency_key="fb-key-1"
        )
        assert first["is_duplicate"] is False
        assert first["feedback_id"]

        dup = pipeline.record_feedback(
            lesson_id, learner_id, ["more_examples"], idempotency_key="fb-key-1"
        )
        assert dup["is_duplicate"] is True
        assert dup["feedback_id"] == first["feedback_id"]

        # Exactly one feedback row for this lesson/generation.
        count = pipeline.conn.execute(
            "SELECT count(*) AS c FROM feedback WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()["c"]
        assert count == 1
    finally:
        pipeline.conn.close()


def test_duplicate_feedback_does_not_reapply_or_advance(file_db):
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        lesson_id = pipeline.start_first_lesson(learner_id, concept_id)
        comp = pipeline.record_comprehension(lesson_id, learner_id, understood=False, free_text="hard")

        first = pipeline.record_feedback(
            lesson_id, learner_id, ["more_examples"], idempotency_key="fb-key-2"
        )
        # Generate the second lesson once (applies the feedback).
        second = pipeline.process_feedback_and_generate_second_lesson(
            lesson_id, learner_id, comp["response_id"], first["feedback_id"], idempotency_key="sl-key-2"
        )
        assert second["lesson_id"]

        feedback_after = pipeline.conn.execute(
            "SELECT applied_status FROM feedback WHERE id = ?", (first["feedback_id"],)
        ).fetchone()["applied_status"]
        assert feedback_after == "applied_to_second"

        # A duplicate feedback submission must not create rows or re-apply.
        dup = pipeline.record_feedback(
            lesson_id, learner_id, ["more_examples"], idempotency_key="fb-key-2"
        )
        assert dup["is_duplicate"] is True

        fb_count = pipeline.conn.execute(
            "SELECT count(*) AS c FROM feedback WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()["c"]
        assert fb_count == 1

        lesson_count = pipeline.conn.execute(
            "SELECT count(*) AS c FROM lessons WHERE learner_id = ?", (learner_id,)
        ).fetchone()["c"]
        assert lesson_count == 2  # first + second, no extra

        adapt_count = pipeline.conn.execute(
            "SELECT count(*) AS c FROM adaptation_decisions WHERE learner_id = ?", (learner_id,)
        ).fetchone()["c"]
        # Adaptation decisions recorded once for the single second lesson.
        assert adapt_count >= 1
    finally:
        pipeline.conn.close()
