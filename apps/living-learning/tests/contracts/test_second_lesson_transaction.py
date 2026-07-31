"""Blocker E: the second-lesson operation is one atomic transaction.

On any failure after the claim: no new lesson, feedback unapplied, mastery
unchanged, no adaptation record, claim retryable, and the prior valid lesson is
preserved. Also verifies that two different feedbacks racing on the same prior
lesson produce exactly one second lesson (DB lesson-sequence uniqueness).
"""

from __future__ import annotations

import sqlite3
import threading

from tests.contracts.conftest import bootstrap_learner, make_pipeline


def _mastery_correct(db_path: str, learner_id: str) -> int:
    pipeline = make_pipeline(db_path)
    try:
        row = pipeline.conn.execute(
            "SELECT COALESCE(SUM(correct_count), 0) AS c FROM learner_mastery WHERE learner_id = ?",
            (learner_id,),
        ).fetchone()
        return int(row["c"])
    finally:
        pipeline.conn.close()


def test_second_lesson_failure_leaves_no_partial_state(file_db, monkeypatch):
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        lesson_id = pipeline.start_first_lesson(learner_id, concept_id)
        comp = pipeline.record_comprehension(lesson_id, learner_id, understood=True)
        fb = pipeline.record_feedback(lesson_id, learner_id, ["more_examples"])
        mastery_before = _mastery_correct(file_db, learner_id)

        import app.pipeline.service as service_module

        def failing_exercise(*args, **kwargs):
            raise sqlite3.OperationalError("injected")

        monkeypatch.setattr(service_module, "create_exercise", failing_exercise)

        try:
            pipeline.process_feedback_and_generate_second_lesson(
                lesson_id, learner_id, comp["response_id"], fb["feedback_id"]
            )
            assert False, "expected failure"
        except Exception:
            pass
    finally:
        pipeline.conn.close()

    # Verify post-failure state on a fresh connection.
    check = make_pipeline(file_db)
    try:
        # Only the original lesson remains.
        lessons = check.conn.execute(
            "SELECT generation_status FROM lessons WHERE learner_id = ?", (learner_id,)
        ).fetchall()
        assert len(lessons) == 1
        assert lessons[0]["generation_status"] == "pending_review"

        # Feedback unapplied.
        applied = check.conn.execute(
            "SELECT applied_status FROM feedback WHERE id = ?", (fb["feedback_id"],)
        ).fetchone()["applied_status"]
        assert applied == "not_applied"

        # No adaptation decision recorded.
        adapt = check.conn.execute(
            "SELECT count(*) AS c FROM adaptation_decisions WHERE learner_id = ?", (learner_id,)
        ).fetchone()["c"]
        assert adapt == 0
    finally:
        check.conn.close()

    # Mastery unchanged.
    assert _mastery_correct(file_db, learner_id) == mastery_before


def test_successful_second_lesson_is_atomic_and_complete(file_db):
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        lesson_id = pipeline.start_first_lesson(learner_id, concept_id)
        comp = pipeline.record_comprehension(lesson_id, learner_id, understood=True)
        fb = pipeline.record_feedback(lesson_id, learner_id, ["more_examples", "code_first"])

        result = pipeline.process_feedback_and_generate_second_lesson(
            lesson_id, learner_id, comp["response_id"], fb["feedback_id"]
        )
        assert result["adaptation_verified"] is True

        # Lesson, feedback application, and adaptation decision all persisted.
        lessons = pipeline.conn.execute(
            "SELECT * FROM lessons WHERE learner_id = ? ORDER BY lesson_number", (learner_id,)
        ).fetchall()
        assert len(lessons) == 2
        assert lessons[1]["lesson_number"] == 2
        assert lessons[1]["prior_lesson_id"] == lesson_id

        applied = pipeline.conn.execute(
            "SELECT applied_status, applied_to_lesson_id FROM feedback WHERE id = ?", (fb["feedback_id"],)
        ).fetchone()
        assert applied["applied_status"] == "applied_to_second"
        assert applied["applied_to_lesson_id"] == lessons[1]["id"]

        adapt = pipeline.conn.execute(
            "SELECT count(*) AS c FROM adaptation_decisions WHERE next_lesson_id = ?",
            (lessons[1]["id"],),
        ).fetchone()["c"]
        assert adapt >= 1
    finally:
        pipeline.conn.close()


def test_concurrent_different_feedback_same_prior_one_second_lesson(file_db):
    """Two different feedbacks racing on the same prior lesson: exactly one
    second lesson survives (lesson-sequence uniqueness), the other rolls back."""
    learner_id, concept_id = bootstrap_learner(file_db)
    setup = make_pipeline(file_db)
    try:
        lesson_id = setup.start_first_lesson(learner_id, concept_id)
        comp = setup.record_comprehension(lesson_id, learner_id, understood=False, free_text="hard")
        fb_a = setup.record_feedback(lesson_id, learner_id, ["more_examples"], idempotency_key="A")
        fb_b = setup.record_feedback(lesson_id, learner_id, ["code_first"], idempotency_key="B")
    finally:
        setup.conn.close()

    barrier = threading.Barrier(2)
    outcomes: list[object] = []
    lock = threading.Lock()

    def run(feedback_id: str, key: str):
        pipeline = make_pipeline(file_db)
        try:
            barrier.wait()
            result = pipeline.process_feedback_and_generate_second_lesson(
                lesson_id, learner_id, comp["response_id"], feedback_id, idempotency_key=key
            )
            with lock:
                outcomes.append(("ok", result["lesson_id"]))
        except Exception as exc:  # noqa: BLE001 - record any failure mode
            with lock:
                outcomes.append(("error", type(exc).__name__))
        finally:
            pipeline.conn.close()

    threads = [
        threading.Thread(target=run, args=(fb_a["feedback_id"], "sl-A")),
        threading.Thread(target=run, args=(fb_b["feedback_id"], "sl-B")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check = make_pipeline(file_db)
    try:
        second_lessons = check.conn.execute(
            "SELECT count(*) AS c FROM lessons WHERE learner_id = ? AND lesson_number = 2",
            (learner_id,),
        ).fetchone()["c"]
        # Exactly one second lesson exists regardless of interleaving.
        assert second_lessons == 1, f"outcomes={outcomes}"
    finally:
        check.conn.close()
