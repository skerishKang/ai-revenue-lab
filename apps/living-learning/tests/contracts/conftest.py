"""Shared fixtures for the Phase 1 repair contract suites.

These tests use file-backed SQLite databases (close/reopen across connections)
and real concurrent execution (threads) to prove the atomicity, recovery, and
single-transaction contracts. Zero network access.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from app.ai.mock import MockProvider
from app.config import Settings
from app.db import apply_migrations
from app.pipeline.service import LessonPipeline


@pytest.fixture
def file_db() -> str:
    """A file-backed database with all migrations applied."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    apply_migrations(path)
    yield path
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        except PermissionError:
            pass


@pytest.fixture
def settings_factory(file_db):
    def _make(**overrides) -> Settings:
        return Settings(database_url=file_db, provider_type="mock", provider_model="mock-fixture", **overrides)

    return _make


def make_pipeline(db_path: str, provider: MockProvider | None = None) -> LessonPipeline:
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    settings = Settings(database_url=db_path, provider_type="mock", provider_model="mock-fixture")
    return LessonPipeline(conn, provider or MockProvider(), settings)


def bootstrap_learner(db_path: str, topic: str = "Python") -> tuple[str, str]:
    """Create a learner + session and return (learner_id, first_concept_id)."""
    pipeline = make_pipeline(db_path)
    try:
        data = pipeline.create_learner_and_session(topic=topic)
        concept_id = pipeline.conn.execute(
            "SELECT id FROM concepts WHERE name = 'variables'"
        ).fetchone()[0]
        return data["learner_id"], concept_id
    finally:
        pipeline.conn.close()
