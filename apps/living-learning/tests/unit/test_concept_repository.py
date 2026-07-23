"""Unit tests for concept repository and prerequisites."""

import pytest
import sqlite3

from app.repositories import (
    create_learner,
    create_curriculum,
    create_concept,
    get_concept_by_id,
    get_concepts_by_curriculum,
    validate_prerequisites,
    upsert_mastery,
)


def test_create_concept(conn: sqlite3.Connection) -> None:
    curriculum = create_curriculum(conn, topic="Python 기초")

    concept = create_concept(
        conn,
        curriculum_id=curriculum.id,
        name="variables",
        description="변수와 값 이해하기",
        prerequisites=[],
        sequence_order=0,
    )

    assert concept.id.startswith("concept_")
    assert concept.name == "variables"
    assert concept.curriculum_id == curriculum.id


def test_get_concepts_by_curriculum(conn: sqlite3.Connection) -> None:
    curriculum = create_curriculum(conn, topic="Python 기초")

    create_concept(conn, curriculum_id=curriculum.id, name="variables", sequence_order=0)
    create_concept(
        conn, curriculum_id=curriculum.id, name="values", sequence_order=1
    )

    concepts = get_concepts_by_curriculum(conn, curriculum.id)

    assert len(concepts) == 2
    assert concepts[0].sequence_order < concepts[1].sequence_order


def test_validate_prerequisites_no_prereqs(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")

    concept = create_concept(
        conn, curriculum_id=curriculum.id, name="variables", prerequisites=[]
    )

    valid, missing = validate_prerequisites(conn, concept.id, learner.id)

    assert valid is True
    assert missing == []


def test_validate_prerequisites_missing(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")

    prereq = create_concept(
        conn, curriculum_id=curriculum.id, name="prerequisite", prerequisites=[]
    )
    concept = create_concept(
        conn,
        curriculum_id=curriculum.id,
        name="main",
        prerequisites=[prereq.id],
    )

    valid, missing = validate_prerequisites(conn, concept.id, learner.id)

    assert valid is False
    assert prereq.id in missing


def test_validate_prerequisites_satisfied(conn: sqlite3.Connection) -> None:
    learner = create_learner(conn, topic="Python 기초")
    curriculum = create_curriculum(conn, topic="Python 기초")

    prereq = create_concept(
        conn, curriculum_id=curriculum.id, name="prerequisite", prerequisites=[]
    )
    concept = create_concept(
        conn,
        curriculum_id=curriculum.id,
        name="main",
        prerequisites=[prereq.id],
    )

    upsert_mastery(conn, learner_id=learner.id, concept_id=prereq.id, mastery_level="proficient")

    valid, missing = validate_prerequisites(conn, concept.id, learner.id)

    assert valid is True
    assert missing == []