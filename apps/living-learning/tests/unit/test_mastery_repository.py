"""Unit tests for mastery repository."""

import pytest
import sqlite3

from app.repositories import (
    create_learner,
    create_curriculum,
    create_concept,
    upsert_mastery,
    get_mastery,
    get_all_mastery_for_learner,
)


def test_upsert_mastery_new(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")

    mastery = upsert_mastery(
        conn,
        learner_id=learner.id,
        concept_id=concept.id,
        mastery_level="beginning",
    )

    assert mastery.id.startswith("mstr_")
    assert mastery.learner_id == learner.id
    assert mastery.concept_id == concept.id
    assert mastery.mastery_level == "beginning"


def test_upsert_mastery_updates_level(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")
    concept = create_concept(conn, curriculum_id=curriculum.id, name="variables")

    upsert_mastery(
        conn,
        learner_id=learner.id,
        concept_id=concept.id,
        practice_increment=3,
        correct_increment=2,
    )

    mastery = get_mastery(conn, learner.id, concept.id)

    assert mastery is not None
    assert mastery.mastery_level == "developing"


def test_get_all_mastery_for_learner(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")

    c1 = create_concept(conn, curriculum_id=curriculum.id, name="variables")
    c2 = create_concept(conn, curriculum_id=curriculum.id, name="values")

    upsert_mastery(conn, learner_id=learner.id, concept_id=c1.id)
    upsert_mastery(conn, learner_id=learner.id, concept_id=c2.id)

    all_mastery = get_all_mastery_for_learner(conn, learner.id)

    assert len(all_mastery) == 2