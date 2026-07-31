"""Unit tests for feedback repository."""

import pytest
import sqlite3

from app.repositories import (
    create_learner,
    create_curriculum,
    create_concept,
    create_lesson,
    create_feedback,
    get_feedback_by_id,
    get_feedback_by_lesson,
    mark_feedback_applied,
    is_feedback_applied,
    is_feedback_for_learner,
)


def test_create_feedback(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")
    lesson = create_lesson(conn, learner_id=learner.id, concept_id=concept.id)

    feedback = create_feedback(
        conn,
        lesson_id=lesson.id,
        learner_id=learner.id,
        direction_choices=["more_examples", "code_first"],
        free_text="더 많은 예제 부탁",
    )

    assert feedback.id.startswith("fb_")
    assert feedback.lesson_id == lesson.id
    assert feedback.learner_id == learner.id
    assert feedback.direction_choices == ["more_examples", "code_first"]
    assert feedback.applied_status == "not_applied"


def test_feedback_exactly_once(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")
    lesson = create_lesson(conn, learner_id=learner.id, concept_id=concept.id)

    fb1 = create_feedback(
        conn,
        lesson_id=lesson.id,
        learner_id=learner.id,
        lesson_generation=1,
        direction_choices=["more_examples"],
    )

    fb2 = create_feedback(
        conn,
        lesson_id=lesson.id,
        learner_id=learner.id,
        lesson_generation=1,
        direction_choices=["more_examples"],
    )

    assert fb1.id == fb2.id


def test_mark_feedback_applied(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")
    lesson1 = create_lesson(conn, learner_id=learner.id, concept_id=concept.id)
    lesson2 = create_lesson(
        conn, learner_id=learner.id, concept_id=concept.id, lesson_number=2
    )

    feedback = create_feedback(conn, lesson_id=lesson1.id, learner_id=learner.id)

    result = mark_feedback_applied(conn, feedback.id, lesson2.id)
    assert result is True

    updated = get_feedback_by_id(conn, feedback.id)
    assert updated is not None
    assert updated.applied_status == "applied_to_second"
    assert updated.applied_to_lesson_id == lesson2.id


def test_is_feedback_applied(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")
    lesson1 = create_lesson(conn, learner_id=learner.id, concept_id=concept.id)
    lesson2 = create_lesson(
        conn, learner_id=learner.id, concept_id=concept.id, lesson_number=2
    )

    feedback = create_feedback(conn, lesson_id=lesson1.id, learner_id=learner.id)

    assert is_feedback_applied(conn, feedback.id) is False

    mark_feedback_applied(conn, feedback.id, lesson2.id)

    assert is_feedback_applied(conn, feedback.id) is True


def test_is_feedback_for_learner(conn: sqlite3.Connection) -> None:
    learner1 = create_learner(conn, topic="Python 기초", display_name="학습자1")
    learner2 = create_learner(conn, topic="Python 기초", display_name="학습자2")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")
    lesson = create_lesson(conn, learner_id=learner1.id, concept_id=concept.id)

    feedback = create_feedback(conn, lesson_id=lesson.id, learner_id=learner1.id)

    assert is_feedback_for_learner(conn, feedback.id, learner1.id) is True
    assert is_feedback_for_learner(conn, feedback.id, learner2.id) is False