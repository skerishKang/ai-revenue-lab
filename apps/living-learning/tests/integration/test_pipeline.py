"""Integration tests for full Living Learning workflow."""

from __future__ import annotations

import json

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
    get_learner_by_id,
)
from app.domain.models import LessonPlan


@pytest.fixture
def pipeline(conn: sqlite3.Connection) -> LessonPipeline:
    return LessonPipeline(conn, MockProvider())


def test_full_first_lesson_workflow(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(
        topic="Python 기초",
        example_preference="code_first",
        theory_density="balanced",
        jargon_level="simplified",
        review_question_count=3,
    )

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]
    session_id = result["session_id"]

    assert learner_id.startswith("lr_")
    assert curriculum_id.startswith("curr_")
    assert session_id.startswith("sess_")

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    assert len(concepts) == 4

    concept_id = concepts[0]["id"]

    lesson_id = pipeline.start_first_lesson(
        learner_id=learner_id,
        concept_id=concept_id,
    )

    lesson = get_lesson_by_id(conn, lesson_id)
    assert lesson is not None
    assert lesson.generation_status == "pending_review"
    assert lesson.lesson_plan_json != "{}"
    assert lesson.lesson_content_json != "{}"

    content_data = json.loads(lesson.lesson_content_json)
    has_content = (
        len(content_data.get("sections", [])) > 0 or
        len(content_data.get("review_questions", [])) > 0 or
        len(content_data.get("code_examples", [])) > 0
    )
    assert has_content, "Lesson content should have sections, review questions, or code examples"


def test_feedback_and_second_lesson_workflow(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

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
        lesson_plan_json='{"title": "원본 레슨", "sections": [{"section_id": "s1", "title": "섹션1", "description": "설명", "emphasis": "중요"}]}',
        lesson_content_json='{"title": "원본 컨텐츠", "sections": [], "review_questions": [], "code_examples": []}',
    )

    comp_result = pipeline.record_comprehension(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        understood=True,
        difficulty_rating=3,
        free_text="좋은 수업이었습니다",
    )
    assert comp_result["success"] is True

    feedback_result = pipeline.record_feedback(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        direction_choices=["more_examples", "code_first"],
        free_text="더 많은 예제와 코드를 먼저 보여주세요",
    )
    feedback_id = feedback_result["feedback_id"]

    second_result = pipeline.process_feedback_and_generate_second_lesson(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        comprehension_response_id=comp_result["response_id"],
        feedback_id=feedback_id,
    )

    lesson2_id = second_result["lesson_id"]
    assert second_result["adaptation_verified"] is True

    lesson2 = get_lesson_by_id(conn, lesson2_id)
    assert lesson2 is not None
    assert lesson2.lesson_number == 2
    assert lesson2.prior_lesson_id == lesson1.id
    assert "more_examples" in lesson2.adaptation_summary


def test_feedback_idempotency(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

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

    feedback1 = pipeline.record_feedback(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        direction_choices=["more_examples"],
    )
    feedback1_id = feedback1["feedback_id"]

    comp_result = pipeline.record_comprehension(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        understood=True,
    )

    second_result = pipeline.process_feedback_and_generate_second_lesson(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        comprehension_response_id=comp_result["response_id"],
        feedback_id=feedback1_id,
    )

    from app.pipeline.errors import FeedbackAlreadyAppliedError
    with pytest.raises(FeedbackAlreadyAppliedError):
        pipeline.process_feedback_and_generate_second_lesson(
            lesson_id=lesson1.id,
            learner_id=learner_id,
            comprehension_response_id=comp_result["response_id"],
            feedback_id=feedback1_id,
        )


def test_comprehension_response(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

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

    response_result = pipeline.record_comprehension(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        understood=True,
        difficulty_rating=3,
        free_text="좋은 설명이었습니다",
    )

    assert response_result["success"] is True
    assert response_result["response_id"].startswith("comp_")


def test_close_and_reopen_lesson(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

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

    result = pipeline.finalize_and_close(
        lesson_id=lesson1.id,
        learner_id=learner_id,
    )

    assert result["status"] == "closed"
    assert result["prompt_tokens"] >= 0
    assert result["completion_tokens"] >= 0

    lesson = get_lesson_by_id(conn, lesson1.id)
    assert lesson is not None
    assert lesson.publication_state == "closed"


def test_learner_progress(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    create_lesson(conn, learner_id=learner_id, concept_id=concept_id, lesson_number=1)
    create_lesson(conn, learner_id=learner_id, concept_id=concept_id, lesson_number=2)

    progress = pipeline.get_learner_progress(learner_id=learner_id)

    assert progress["learner_id"] == learner_id
    assert progress["total_lessons"] == 2


def test_idempotency_key_prevents_duplicate(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

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


def test_second_lesson_requires_comprehension(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

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

    feedback_result = pipeline.record_feedback(
        lesson_id=lesson1.id,
        learner_id=learner_id,
        direction_choices=["more_examples"],
    )

    from app.pipeline.errors import ComprehensionRequiredError
    with pytest.raises(ComprehensionRequiredError):
        pipeline.process_feedback_and_generate_second_lesson(
            lesson_id=lesson1.id,
            learner_id=learner_id,
            comprehension_response_id="nonexistent",
            feedback_id=feedback_result["feedback_id"],
        )


def test_foreign_learner_rejection(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result1 = pipeline.create_learner_and_session(topic="Python 기초")
    result2 = pipeline.create_learner_and_session(topic="Python 기초")

    learner1_id = result1["learner_id"]
    learner2_id = result2["learner_id"]
    curriculum_id = result1["curriculum_id"]

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    lesson1 = create_lesson(conn, learner_id=learner1_id, concept_id=concept_id, lesson_number=1)

    from app.pipeline.errors import ForeignFeedbackError
    with pytest.raises(ForeignFeedbackError):
        pipeline.record_comprehension(
            lesson_id=lesson1.id,
            learner_id=learner2_id,
            understood=True,
        )


def test_inactive_learner_rejection(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

    conn.execute(
        "UPDATE learners SET status = 'deleted' WHERE id = ?",
        (learner_id,),
    )
    conn.commit()

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    concept_id = concepts[0]["id"]

    from app.pipeline.errors import LearnerInactiveError
    with pytest.raises(LearnerInactiveError):
        pipeline.start_first_lesson(
            learner_id=learner_id,
            concept_id=concept_id,
        )


def test_prerequisite_not_met(
    conn: sqlite3.Connection, pipeline: LessonPipeline
) -> None:
    result = pipeline.create_learner_and_session(topic="Python 기초")

    learner_id = result["learner_id"]
    curriculum_id = result["curriculum_id"]

    concepts = conn.execute(
        "SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()

    conditionals_id = concepts[2]["id"]

    from app.pipeline.errors import PrerequisiteNotMetError
    with pytest.raises(PrerequisiteNotMetError):
        pipeline.start_first_lesson(
            learner_id=learner_id,
            concept_id=conditionals_id,
        )