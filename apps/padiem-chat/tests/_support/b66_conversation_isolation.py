"""#8061 20차: shared setup for the B66 conversation isolation tests.

The in-memory SQLite database built from the app's migrations (with the two
owners pre-inserted) and the thin D1-shaped handle over it are what eight test
files share. The store under test and its product-scope vocabulary stay with
the tests that exercise them.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

# tests/_support/x.py → apps/padiem-chat: the same root the hub file computed
# from one directory less deep.
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

OWNER = "usr_" + "a" * 32
OTHER_OWNER = "usr_" + "b" * 32


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
