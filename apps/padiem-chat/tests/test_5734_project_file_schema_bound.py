"""#5734 stage 2 — a persisted project file keeps the storage schema's own ceiling.

Core stopped refusing a document for its length, so an over-long body is no
longer rejected by the document validator. The `project_files` table still
declares `CHECK(content_chars <= 40000)` (migrations 003, 068, 069), and that is
a real D1 constraint: without a pre-flight at the same number the body reached
D1 and failed as a constraint error instead of the route's own 422. An ephemeral
composer attachment is not persisted and stays uncapped.
"""
from __future__ import annotations

import asyncio
import shutil
import sqlite3
from pathlib import Path

import pytest
from test_5115_project_files_extracted_schema import PID, UID, SqliteD1, _apply, _seed_owner

from app.project_files import (
    D1ProjectFileStore,
    PROJECT_FILE_MAX_CONTENT_CHARS,
    ProjectFileLimitError,
)

MIGRATION_SET = (
    "001_auth_history.sql",
    "002_projects.sql",
    "003_project_files.sql",
    "068_project_files_extracted_media.sql",
    "069_project_files_image_media.sql",
    "075_project_files_country.sql",
)


@pytest.fixture(scope="module")
def migrated_database(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("5734-schema") / "chat.sqlite3"
    db = sqlite3.connect(path)
    _apply(db, *MIGRATION_SET)
    _seed_owner(db)
    db.close()
    return path


@pytest.fixture
def database_copy(migrated_database: Path, tmp_path: Path) -> Path:
    target = tmp_path / "chat.sqlite3"
    shutil.copyfile(migrated_database, target)
    return target


def test_the_stored_schema_itself_refuses_an_over_long_body(database_copy: Path) -> None:
    db = sqlite3.connect(database_copy)
    over = "x" * (PROJECT_FILE_MAX_CONTENT_CHARS + 1)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO project_files (id, project_id, user_id, name, media_type, "
            "content_text, content_chars, created_at, updated_at) "
            "VALUES ('pf_1', ?, ?, 'notes.txt', 'text/plain', ?, ?, "
            "'2026-10-26T00:00:00Z', '2026-10-26T00:00:00Z')",
            (PID, UID, over, len(over)),
        )
    db.close()


def test_the_store_checks_the_schema_ceiling_before_it_writes(database_copy: Path) -> None:
    store = D1ProjectFileStore(SqliteD1(database_copy))

    async def journey():
        with pytest.raises(ProjectFileLimitError):
            await store.create_file(UID, PID, "notes.txt", "text/plain", "x" * (PROJECT_FILE_MAX_CONTENT_CHARS + 1))
        created = await store.create_file(UID, PID, "notes.txt", "text/plain", "x" * PROJECT_FILE_MAX_CONTENT_CHARS)
        return await store.get_file(UID, PID, created.id), store

    fetched, store = asyncio.run(journey())
    assert fetched is not None
    assert fetched.content_chars == PROJECT_FILE_MAX_CONTENT_CHARS
    listed = asyncio.run(store.list_files(UID, PID))
    assert len(listed) == 1, "the refused body must not leave a row behind"


def test_the_guard_mirrors_the_stored_ceiling(database_copy: Path) -> None:
    db = sqlite3.connect(database_copy)
    schema = db.execute("SELECT sql FROM sqlite_master WHERE name = 'project_files'").fetchone()[0]
    db.close()
    assert f"content_chars <= {PROJECT_FILE_MAX_CONTENT_CHARS}" in schema
