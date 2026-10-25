"""#5115 — the project_files schema must accept the extracted/* media types.

The binary project-file upload path stores the EXTRACTED TEXT of a PDF/DOCX
with media_type ``extracted/pdf`` / ``extracted/docx``
(app/project_files.py: ``_extracted_media_type`` and the ``create_file``
extracted/ branch). Migration 003's CHECK allowed only the four text media
types, so every binary upload failed the INSERT with an IntegrityError ->
HTTP 503 on any D1 running the shipped schema. The COM2 native runtime
measured it live against the published generation copy (2026-10-23) during
the #5115 large-file E2E; the repo's binary-upload tests missed it because
they run on in-memory fakes without the schema.

Migration 068 widens the CHECK. These tests run against a REAL sqlite file
carrying migrations 001+002+003 (and 068 on top where stated), exercising
the REAL ``D1ProjectFileStore`` — the gap that let this ship is closed here.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
UID = "usr_" + "a" * 32
PID = "prj_" + "a" * 32


class _Statement:
    def __init__(self, db: sqlite3.Connection, sql: str, values: tuple) -> None:
        self._db = db
        self._sql = sql
        self._values = values

    async def first(self):
        def run():
            row = self._db.execute(self._sql, self._values).fetchone()
            return dict(row) if row is not None else None
        return await asyncio.to_thread(run)

    async def run(self):
        def run():
            cur = self._db.execute(self._sql, self._values)
            try:
                rows = [dict(row) for row in cur.fetchall()]
            except sqlite3.Error:
                rows = []
            # D1's run() result carries the rows on .results; the store's
            # _rows_from_result reads exactly that shape.
            return SimpleNamespace(results=rows)
        return await asyncio.to_thread(run)


class SqliteD1:
    """The prepare/bind/first/run surface D1ProjectFileStore uses."""

    def __init__(self, path: Path) -> None:
        # check_same_thread=False: the store's statements run in worker
        # threads (asyncio.to_thread), the deployed LocalSQLiteD1 opens a
        # fresh connection per call instead — a single shared connection is
        # fine here because the tests are sequential.
        self._db = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row

    def prepare(self, sql: str):
        return _Bound(self, sql)


class _Bound:
    def __init__(self, d1: SqliteD1, sql: str) -> None:
        self._d1 = d1
        self._sql = sql
        self._values: tuple = ()

    def bind(self, *values):
        self._values = values
        return self

    async def first(self):
        return await _Statement(self._d1._db, self._sql, self._values).first()

    async def run(self):
        return await _Statement(self._d1._db, self._sql, self._values).run()


def _apply(db: sqlite3.Connection, *names: str) -> None:
    for name in names:
        db.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    db.commit()


def _seed_owner(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
        "picture_url, created_at, updated_at) "
        "VALUES (?, 'google', ?, ?, 'schema probe', '', "
        "'2026-10-25T00:00:00Z', '2026-10-25T00:00:00Z')",
        (UID, UID, "schema-probe@example.test"),
    )
    db.execute(
        "INSERT INTO projects (id, user_id, name, instructions, created_at, updated_at) "
        "VALUES (?, ?, 'schema probe project', '', '2026-10-25T00:00:00Z', '2026-10-25T00:00:00Z')",
        (PID, UID),
    )
    db.commit()


def test_the_003_schema_rejects_the_extracted_media_the_app_writes(tmp_path) -> None:
    """The defect, documented: migration 003's CHECK refuses extracted/pdf."""
    db = sqlite3.connect(tmp_path / "chat.sqlite3")
    _apply(db, "001_auth_history.sql", "002_projects.sql", "003_project_files.sql")
    _seed_owner(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO project_files (id, project_id, user_id, name, media_type, "
            "content_text, content_chars, created_at, updated_at) "
            "VALUES ('pfa_1', ?, ?, 'probe.pdf', 'extracted/pdf', 'x' * 30, 30, "
            "'2026-10-25T00:00:00Z', '2026-10-25T00:00:00Z')",
            (PID, UID),
        )


def test_migration_068_widens_the_check_and_keeps_the_rows(tmp_path) -> None:
    db = sqlite3.connect(tmp_path / "chat.sqlite3")
    _apply(db, "001_auth_history.sql", "002_projects.sql", "003_project_files.sql")
    _seed_owner(db)
    db.execute(
        "INSERT INTO project_files (id, project_id, user_id, name, media_type, "
        "content_text, content_chars, created_at, updated_at) "
        "VALUES ('pfa_1', ?, ?, 'notes.txt', 'text/plain', 'x' * 30, 30, "
        "'2026-10-25T00:00:00Z', '2026-10-25T00:00:00Z')",
        (PID, UID),
    )
    db.commit()
    _apply(db, "068_project_files_extracted_media.sql")
    indexes = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'project_files'")}
    assert {"idx_project_files_owner_project", "idx_project_files_project_updated"} <= indexes

    row = db.execute("SELECT COUNT(*) FROM project_files").fetchone()
    assert row[0] == 1, "the rebuild must carry every existing row"
    schema = db.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'project_files'"
    ).fetchone()[0]
    for media in ("extracted/pdf", "extracted/docx"):
        assert media in schema
    for media in ("text/plain", "text/markdown", "text/csv", "application/json"):
        assert media in schema


def test_the_real_store_writes_extracted_pdf_after_068(tmp_path) -> None:
    """The REAL D1ProjectFileStore on a REAL migrated sqlite file.

    This is the path the binary upload route drives; before 068 the INSERT
    raised IntegrityError and the route answered 503.
    """
    from app.project_files import D1ProjectFileStore

    db = sqlite3.connect(tmp_path / "chat.sqlite3")
    _apply(
        db,
        "001_auth_history.sql", "002_projects.sql", "003_project_files.sql",
        "068_project_files_extracted_media.sql",
    )
    _seed_owner(db)
    db.close()

    d1 = SqliteD1(tmp_path / "chat.sqlite3")
    store = D1ProjectFileStore(d1)

    async def journey():
        created = await store.create_file(
            UID, PID, "probe.pdf", "extracted/pdf", "PADIEM extracted probe " * 2,
        )
        fetched = await store.get_file(UID, PID, created.id)
        listed = await store.list_files(UID, PID)
        return created, fetched, listed

    created, fetched, listed = asyncio.run(journey())
    assert created.media_type == "extracted/pdf"
    assert fetched is not None and fetched.media_type == "extracted/pdf"
    assert [item.id for item in listed] == [created.id]


def test_migration_069_keeps_all_project_file_indexes_and_rows(tmp_path) -> None:
    db = sqlite3.connect(tmp_path / "chat.sqlite3")
    _apply(db, "001_auth_history.sql", "002_projects.sql", "003_project_files.sql")
    _seed_owner(db)
    db.execute(
        "INSERT INTO project_files (id, project_id, user_id, name, media_type, "
        "content_text, content_chars, created_at, updated_at) "
        "VALUES ('pfa_1', ?, ?, 'notes.txt', 'text/plain', 'hello', 5, "
        "'2026-10-25T00:00:00Z', '2026-10-25T00:00:00Z')",
        (PID, UID),
    )
    db.commit()
    _apply(db, "068_project_files_extracted_media.sql", "069_project_files_image_media.sql")
    indexes = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'project_files'"
    )}
    assert {"idx_project_files_owner_project", "idx_project_files_project_updated"} <= indexes
    assert db.execute("SELECT content_text FROM project_files WHERE id = 'pfa_1'").fetchone()[0] == "hello"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
