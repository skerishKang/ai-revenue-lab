"""#5734 stage 2 / #5882 PR-E — a persisted project file is bounded by D1, not by a character count.

Core stopped refusing a document for its length, so an over-long body is no
longer rejected by the document validator. The `project_files` table then still
declared `CHECK(content_chars <= 40000)` (migrations 003, 068, 069), and that was
a real D1 constraint: without a pre-flight at the same number the body reached D1
and failed as a constraint error instead of the route's own 422.

#5882 PR-E replaced that arbitrary character ceiling with the platform's actual
bound, D1's per-row size. Migration 077 declares

    CHECK(length(CAST(content_text AS BLOB)) <= 2097152)

so the question "does this row fit" is asked in the unit D1 measures. A 200,000
character body — which the old CHECK refused, although it is only ~200 KB of a
~2 MB row — is now stored.
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
    PROJECT_FILE_MAX_TEXT_BYTES,
    ProjectFileLimitError,
)

MIGRATION_SET = (
    "001_auth_history.sql",
    "002_projects.sql",
    "003_project_files.sql",
    "068_project_files_extracted_media.sql",
    "069_project_files_image_media.sql",
    "075_project_files_country.sql",
    "077_project_files_text_byte_bound.sql",
)

#: A long document the retired 40,000-character ceiling refused. Korean costs 3
#: UTF-8 bytes, so 200,000 characters is ~600 KB — still a quarter of D1's row.
LONG_BODY_CHARS = 200_000


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


def test_the_stored_schema_itself_refuses_a_body_past_the_d1_row(database_copy: Path) -> None:
    db = sqlite3.connect(database_copy)
    # 2 MiB + 1 byte of ASCII: past D1's per-row limit, so the row must not land.
    over = "x" * (PROJECT_FILE_MAX_TEXT_BYTES + 1)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO project_files (id, project_id, user_id, name, media_type, "
            "content_text, content_chars, created_at, updated_at) "
            "VALUES ('pf_1', ?, ?, 'notes.txt', 'text/plain', ?, ?, "
            "'2026-10-26T00:00:00Z', '2026-10-26T00:00:00Z')",
            (PID, UID, over, len(over)),
        )
    db.close()


def test_a_long_body_the_old_character_ceiling_refused_is_now_stored(database_copy: Path) -> None:
    """#5882 PR-E — 200,000 characters is not a storage problem, so it is not refused."""

    store = D1ProjectFileStore(SqliteD1(database_copy))
    long_body = "가" * LONG_BODY_CHARS
    assert len(long_body) > 40_000, "the retired ceiling must be the point of this test"

    async def journey():
        created = await store.create_file(UID, PID, "긴문서.txt", "text/plain", long_body)
        return await store.get_file(UID, PID, created.id)

    fetched = asyncio.run(journey())
    assert fetched is not None
    assert fetched.content_chars == LONG_BODY_CHARS
    assert fetched.content_text == long_body, "the body must survive storage unchanged"


def test_the_store_checks_the_row_byte_ceiling_before_it_writes(database_copy: Path) -> None:
    store = D1ProjectFileStore(SqliteD1(database_copy))
    over = "x" * (PROJECT_FILE_MAX_TEXT_BYTES + 1)

    async def journey():
        with pytest.raises(ProjectFileLimitError) as refused:
            await store.create_file(UID, PID, "notes.txt", "text/plain", over)
        # The refusal is the platform bound with the way out, in Korean.
        message = str(refused.value)
        assert "너무 길어요" in message
        assert "나눠서" in message or "파일" in message
        created = await store.create_file(UID, PID, "notes.txt", "text/plain", "x" * 1000)
        return await store.get_file(UID, PID, created.id), store

    fetched, store = asyncio.run(journey())
    assert fetched is not None
    listed = asyncio.run(store.list_files(UID, PID))
    assert len(listed) == 1, "the refused body must not leave a row behind"


def test_migration_077_keeps_every_row_index_and_foreign_key(tmp_path: Path) -> None:
    """A CHECK change is a table rebuild, so the copy step is the risk."""

    path = tmp_path / "chat.sqlite3"
    db = sqlite3.connect(path)
    _apply(
        db,
        "001_auth_history.sql",
        "002_projects.sql",
        "003_project_files.sql",
        "068_project_files_extracted_media.sql",
        "069_project_files_image_media.sql",
        "075_project_files_country.sql",
    )
    _seed_owner(db)
    db.execute(
        "INSERT INTO project_files (id, project_id, user_id, name, media_type, "
        "content_text, content_chars, created_at, updated_at, country) "
        "VALUES ('pfa_1', ?, ?, 'notes.txt', 'text/plain', 'hello', 5, "
        "'2026-10-25T00:00:00Z', '2026-10-25T00:00:00Z', 'us')",
        (PID, UID),
    )
    db.commit()

    _apply(db, "077_project_files_text_byte_bound.sql")

    indexes = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'project_files'"
        )
    }
    assert {"idx_project_files_owner_project", "idx_project_files_project_updated"} <= indexes
    row = db.execute(
        "SELECT content_text, content_chars, country FROM project_files WHERE id = 'pfa_1'"
    ).fetchone()
    assert row == ("hello", 5, "us"), "the rebuild must copy text, count and country"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_the_guard_mirrors_the_stored_row_ceiling(database_copy: Path) -> None:
    db = sqlite3.connect(database_copy)
    schema = db.execute("SELECT sql FROM sqlite_master WHERE name = 'project_files'").fetchone()[0]
    db.close()
    assert f"length(CAST(content_text AS BLOB)) <= {PROJECT_FILE_MAX_TEXT_BYTES}" in schema
    assert "content_chars <= 40000" not in schema, "the arbitrary character ceiling is retired"
