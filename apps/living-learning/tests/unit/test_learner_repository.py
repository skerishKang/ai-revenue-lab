"""Unit tests for learner repository."""

import pytest
import sqlite3

from app.repositories import (
    create_learner,
    get_learner_by_id,
    update_learner_preferences,
)


def test_create_learner(conn: sqlite3.Connection) -> None:
    learner = create_learner(
        conn,
        topic="Python 기초",
        display_name="테스트학습자",
        target_duration_minutes=10,
        example_preference="code_first",
    )
    assert learner.id.startswith("lr_")
    assert learner.topic == "Python 기초"
    assert learner.display_name == "테스트학습자"
    assert learner.status == "active"


def test_get_learner_by_id(conn: sqlite3.Connection) -> None:
    created = create_learner(conn, topic="Python 기초")
    fetched = get_learner_by_id(conn, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.topic == "Python 기초"


def test_get_learner_by_id_not_found(conn: sqlite3.Connection) -> None:
    result = get_learner_by_id(conn, "nonexistent")
    assert result is None


def test_update_learner_preferences(conn: sqlite3.Connection) -> None:
    learner = create_learner(
        conn,
        topic="Python 기초",
        example_preference="theory_first",
    )
    updated = update_learner_preferences(
        conn,
        learner.id,
        example_preference="code_first",
        review_question_count=5,
    )
    assert updated is not None
    assert updated.example_preference == "code_first"
    assert updated.review_question_count == 5