"""Fixture loading for the real B66 conversation slot migration."""
from __future__ import annotations

import re
from pathlib import Path
from sqlite3 import Connection

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "041_b66_ai_conversation.sql"
_SQL_COMMENT_RE = re.compile(r"--[^\n]*")


def executable_statements(sql: str) -> list[str]:
    """Statement-level view: strip SQL line comments and split on semicolons."""
    without_comments = "\n".join(
        _SQL_COMMENT_RE.sub("", line) for line in sql.splitlines()
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def migration_statements() -> list[str]:
    return executable_statements(MIGRATION.read_text(encoding="utf-8"))


def apply_migration(db: Connection) -> None:
    """Apply the actual migration to the caller's isolated SQLite fixture."""
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
