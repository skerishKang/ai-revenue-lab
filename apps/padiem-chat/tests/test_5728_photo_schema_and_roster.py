"""#5728 — the photo persistence schema contract.

The merged image-store slice wrote image rows (media_type image/*,
content_chars 0) through a D1 whose shipped CHECK — migrations 003 and 068 —
allowed neither: every insert failed with sqlite3.IntegrityError on the real
database while the in-memory store tests passed. These tests run the actual
migration chain (003 → 068 → 069) against a real SQLite so the schema can
never silently drift away from what the upload path writes again.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.project_files import BINARY_PROJECT_FILE_MEDIA, IMAGE_PROJECT_FILE_MEDIA

CHAT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = CHAT_ROOT / "migrations"


def _apply_chain() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    # Migration 003 references users/projects; the referencing rows are not
    # exercised here, so minimal parent tables stand in for their migrations.
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, user_id TEXT)")
    for name in ("003_project_files.sql", "068_project_files_extracted_media.sql", "069_project_files_image_media.sql"):
        conn.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    return conn


def test_the_migration_chain_admits_the_stored_image_row_shape() -> None:
    conn = _apply_chain()

    conn.execute("INSERT INTO users (id) VALUES ('u1')")
    conn.execute("INSERT INTO projects (id, user_id) VALUES ('p1', 'u1')")
    # An image original: declared media type, no text — exactly what the
    # upload route writes through store.create_file(uid, pid, name, type, "").
    conn.execute(
        "INSERT INTO project_files (id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at) "
        "VALUES ('file_a', 'p1', 'u1', '행사 사진.png', 'image/png', '', 0, 't1', 't1')"
    )
    # A text document keeps the strict positive floor.
    conn.execute(
        "INSERT INTO project_files (id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at) "
        "VALUES ('file_b', 'p1', 'u1', '초안.txt', 'text/plain', '본문', 2, 't2', 't2')"
    )
    for media in ("image/jpeg", "image/webp", "extracted/pdf", "extracted/docx"):
        # Extracted documents always carry their parsed text (> 0 — the route
        # refuses empty extractions); only the image originals are 0-length.
        chars = 0 if media.startswith("image/") else 12
        conn.execute(
            "INSERT INTO project_files (id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at) "
            f"VALUES ('file_{media.replace('/', '_').replace('+', '_')}', 'p1', 'u1', 'x', '{media}', '{'x' * chars}', {chars}, 't3', 't3')"
        )


def test_the_migration_chain_still_rejects_an_empty_text_document() -> None:
    conn = _apply_chain()
    conn.execute("INSERT INTO users (id) VALUES ('u1')")
    conn.execute("INSERT INTO projects (id, user_id) VALUES ('p1', 'u1')")
    try:
        conn.execute(
            "INSERT INTO project_files (id, project_id, user_id, name, media_type, content_text, content_chars, created_at, updated_at) "
            "VALUES ('file_bad', 'p1', 'u1', '빈문서.txt', 'text/plain', '', 0, 't1', 't1')"
        )
    except sqlite3.IntegrityError:
        return
    raise AssertionError("an empty text document must keep failing the schema floor")


def test_the_schema_covers_every_media_type_the_upload_path_writes() -> None:
    """The #5115/#5763 lesson, made load-bearing: the shipped CHECK must
    accept every media type the store can hold — the image originals (stored
    under their own type) plus the text and extracted types — or production
    fails while every in-memory test passes. BINARY_PROJECT_FILE_MEDIA's
    application/pdf and .../docx are UPLOAD types only: the route never
    stores them, it stores their extracted/* forms."""
    sql = (MIGRATIONS / "069_project_files_image_media.sql").read_text(encoding="utf-8")
    check = sql[sql.index("CHECK(media_type IN ("):sql.index("))")]
    stored_media = (
        IMAGE_PROJECT_FILE_MEDIA
        | {"extracted/pdf", "extracted/docx", "text/plain", "text/markdown", "text/csv", "application/json"}
    )
    for media in sorted(stored_media):
        assert f"'{media}'" in check, f"migration 069 CHECK is missing {media}"
    assert "content_chars >= 0" in sql
