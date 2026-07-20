"""Integration tests for full Living Learning workflow."""

from __future__ import annotations

import pytest
import sqlite3

from app.db import apply_migrations
from app.ai import MockProvider
from app.pipeline import LessonPipeline
from app.repositories import (
    create_learner,
    create_curriculum,
    create_concept,
    create_lesson,
    create_feedback,
    get_lesson_by_id,
    get_feedback_by_id,
    mark_feedback_applied,
    is_feedback_applied,
)
from app.domain.models import LessonPlan


@pytest.fixture
def pipeline(conn: sqlite3.Connection) -> LessonPipeline:
    return LessonPipeline(conn, MockProvider())


def test_full_first_lesson_workflow(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    learner_id, curriculum_id = pipeline.create_learner_and_session(
        topic="Python 기초",
        example_preference="code_first",
        theory_density="balanced",
        jargon_level="simplified",
        review_question_count=3,
    )

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    lesson_id = pipeline.start_first_lesson(
        learner_id=learner_id,
        concept_id=concept_id,
    )

    lesson = get_lesson_by_id(conn, lesson_id)
    assert lesson is not None
    assert lesson.generation_status == "pending_review"


def test_feedback_and_second_lesson_workflow(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    learner_id, curriculum_id = pipeline.create_learner_and_session(
        topic="Python 기초",
    )

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    lesson1 = create_lesson(
        conn,
        learner_id=learner_id,
        concept_id=concept_id,
        lesson_number=1,
        generation_status="pending_review",
        lesson_plan_json='{"title": "원본 레슨"}',
    )

    feedback = create_feedback(
        conn,
        lesson_id=lesson1.id,
        learner_id=learner_id,
        direction_choices=["more_examples", "code_first"],
        free_text="더 많은 예제와 코드를 먼저 보여주세요",
    )

    lesson2_id = pipeline.process_feedback_and_generate_second_lesson(
        feedback_id=feedback.id,
        learner_id=learner_id,
    )

    lesson2 = get_lesson_by_id(conn, lesson2_id)
    assert lesson2 is not None
    assert lesson2.lesson_number == 2
    assert lesson2.prior_lesson_id == lesson1.id
    assert "more_examples" in lesson2.adaptation_summary


def test_feedback_idempotency(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    learner_id, curriculum_id = pipeline.create_learner_and_session(
        topic="Python 기초",
    )

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    lesson1 = create_lesson(
        conn,
        learner_id=learner_id,
        concept_id=concept_id,
        lesson_number=1,
    )

    feedback = create_feedback(
        conn,
        lesson_id=lesson1.id,
        learner_id=learner_id,
        direction_choices=["more_examples"],
    )

    second_lesson = pipeline.process_feedback_and_generate_second_lesson(
        feedback_id=feedback.id,
        learner_id=learner_id,
    )

    from app.pipeline.errors import FeedbackAlreadyAppliedError
    with pytest.raises(FeedbackAlreadyAppliedError):
        pipeline.process_feedback_and_generate_second_lesson(
            feedback_id=feedback.id,
            learner_id=learner_id,
        )


def test_comprehension_response(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    learner_id, curriculum_id = pipeline.create_learner_and_session(
        topic="Python 기초",
    )

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    lesson1 = create_lesson(
        conn,
        learner_id=learner_id,
        concept_id=concept_id,
        lesson_number=1,
    )

    response_id = pipeline.record_comprehension(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        understood=True,
        difficulty_rating=3,
        free_text="좋은 설명이었습니다",
    )

    assert response_id.startswith("comp_")


def test_close_and_reopen_lesson(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    learner_id, curriculum_id = pipeline.create_learner_and_session(
        topic="Python 기초",
    )

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    lesson1 = create_lesson(
        conn,
        learner_id=learner_id,
        concept_id=concept_id,
        lesson_number=1,
    )

    result = pipeline.finalize_and_close(lesson_id=lesson1.id)

    assert result["status"] == "closed"
    assert result["prompt_tokens"] >= 0
    assert result["completion_tokens"] >= 0

    lesson = get_lesson_by_id(conn, lesson1.id)
    assert lesson is not None
    assert lesson.publication_state == "closed"


def test_learner_progress(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    learner_id, curriculum_id = pipeline.create_learner_and_session(
        topic="Python 기초",
    )

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    create_lesson(conn, learner_id=learner_id, concept_id=concept_id, lesson_number=1)
    create_lesson(conn, learner_id=learner_id, concept_id=concept_id, lesson_number=2)

    progress = pipeline.get_learner_progress(learner_id)

    assert progress["learner_id"] == learner_id
    assert progress["total_lessons"] == 2


def test_idempotency_key_prevents_duplicate(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    learner_id, curriculum_id = pipeline.create_learner_and_session(
        topic="Python 기초",
    )

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]
    idempotency_key = "unique-key-123"

    lesson1_id = pipeline.start_first_lesson(
        learner_id=learner_id,
        concept_id=concept_id,
        idempotency_key=idempotency_key,
    )

    lesson2_id = pipeline.start_first_lesson(
        learner_id=learner_id,
        concept_id=concept_id,
        idempotency_key=idempotency_key,
    )

    assert lesson1_id == lesson2_id