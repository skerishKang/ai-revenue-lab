"""Shared prep for the B66 conversation-isolation contracts (#8061 20차).

The #4657 hub builds a real SQLite database from the migrations and hands out
one D1-shaped binding plus the two owners every isolation test uses. The hub
test and its direct consumers receive this from here, so no test file imports
another test file.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

OWNER = "usr_" + "a" * 32
OTHER_OWNER = "usr_" + "b" * 32
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


class D1Statement:
    def __init__(self, connection, sql, values=()):
        self.conn, self.sql, self.values = connection, sql, values

    def bind(self, *values):
        return D1Statement(self.conn, self.sql, values)

    async def first(self):
        row = self.conn.execute(self.sql, self.values).fetchone()
        return dict(row) if row is not None else None

    async def run(self):
        cursor = self.conn.execute(self.sql, self.values)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class D1Sqlite:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return D1Statement(self.connection, sql)


def setup_database():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for migration in (
        "001_auth_history.sql",
        "002_projects.sql",
        "042_conversation_product_scope.sql",
        "105_conversation_soft_delete.sql",
    ):
        db.executescript((MIGRATIONS / migration).read_text(encoding="utf8"))
    for owner in (OWNER, OTHER_OWNER):
        db.execute(
            "INSERT INTO users(id,auth_provider,provider_subject,email,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (owner, "google", owner, owner + "@example.com", "2026-10-14", "2026-10-14"),
        )
    db.commit()
    return db
