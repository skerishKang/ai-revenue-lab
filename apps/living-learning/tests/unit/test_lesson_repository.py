"""Unit tests for lesson repository."""

import pytest
import sqlite3

from app.repositories import (
    create_learner,
    create_curriculum,
    create_concept,
    create_lesson,
    get_lesson_by_id,
    get_lessons_by_learner,
    update_lesson_status,
    close_lesson,
    reopen_lesson,
)


def test_create_lesson(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")

    lesson = create_lesson(
        conn,
        learner_id=learner.id,
        concept_id=concept.id,
        lesson_number=1,
        generation_status="generation_pending",
    )

    assert lesson.id.startswith("lesson_")
    assert lesson.learner_id == learner.id
    assert lesson.concept_id == concept.id
    assert lesson.lesson_number == 1
    assert lesson.generation_status == "generation_pending"
    assert lesson.publication_state == "pending"


def test_get_lesson_by_id(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")

    created = create_lesson(conn, learner_id=learner.id, concept_id=concept.id)
    fetched = get_lesson_by_id(conn, created.id)

    assert fetched is not None
    assert fetched.id == created.id


def test_update_lesson_status(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")

    lesson = create_lesson(conn, learner_id=learner.id, concept_id=concept.id)

    updated = update_lesson_status(
        conn,
        lesson.id,
        generation_status="pending_review",
        lesson_plan_json='{"title": "테스트"}',
    )

    assert updated is not None
    assert updated.generation_status == "pending_review"


def test_close_lesson(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")

    lesson = create_lesson(conn, learner_id=learner.id, concept_id=concept.id)

    closed = close_lesson(conn, lesson.id)

    assert closed is not None
    assert closed.publication_state == "closed"


def test_reopen_lesson_creates_new_lesson(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")

    lesson1 = create_lesson(
        conn, learner_id=learner.id, concept_id=concept.id, lesson_number=1
    )

    lesson2 = reopen_lesson(conn, lesson1.id)

    assert lesson2 is not None
    assert lesson2.id != lesson1.id
    assert lesson2.lesson_number == 2
    assert lesson2.prior_lesson_id == lesson1.id


def test_get_lessons_by_learner(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")

    create_lesson(conn, learner_id=learner.id, concept_id=concept.id, lesson_number=1)
    create_lesson(conn, learner_id=learner.id, concept_id=concept.id, lesson_number=2)

    lessons = get_lessons_by_learner(conn, learner.id)

    assert len(lessons) == 2