"""#8061 19차: shared setup for the Claw local task result projection tests.

The pairing of a real SQLite file shaped like D1 with the history store's
conversation/run writes is what eight test files share. The broker pieces stay
in the hub file — only the database handle, the account/conversation/message
helpers and the two subject constants travel here.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from app.history import PRODUCT_SCOPE_CHAT

APP_ROOT = Path(__file__).resolve().parents[2]

OWNER_SUBJECT = "owner-3139"
OTHER_SUBJECT = "other-3139"
WORKSPACE = "workspace.3139.1"


class _Statement:
    def __init__(self, connection, sql):
        self._connection = connection
        self._sql = sql
        self._values: tuple = ()

    def bind(self, *values):
        self._values = values
        return self

    async def run(self):
        # The app reads a SELECT through `run()` and expects D1's result shape:
        # rows under `results`, affected rows under `meta.rows_written`.
        cursor = self._connection.execute(self._sql, self._values)
        columns = [item[0] for item in cursor.description] if cursor.description else []
        if columns:
            rows = cursor.fetchall()
            return {"results": [dict(zip(columns, row)) for row in rows], "meta": {"rows_written": 0}}
        return {"results": [], "meta": {"rows_written": cursor.rowcount if cursor.rowcount >= 0 else 0}}

    async def first(self):
        # D1's `first()` resolves to the single row itself, not a result object.
        cursor = self._connection.execute(self._sql, self._values)
        rows = cursor.fetchall()
        columns = [item[0] for item in cursor.description] if cursor.description else []
        return dict(zip(columns, rows[0])) if rows else None

    async def all(self):
        # D1 shapes a multi-row result as an object carrying `results`, and the
        # store's reader depends on that, so the adapter must match it.
        cursor = self._connection.execute(self._sql, self._values)
        rows = cursor.fetchall()
        columns = [item[0] for item in cursor.description] if cursor.description else []
        return {"results": [dict(zip(columns, row)) for row in rows], "meta": {"rows_written": 0}}


class _SqliteD1:
    """A D1-shaped handle over a real SQLite file.

    `batch` is the call the exactly-once claim rests on, and D1 applies a batch
    as one unit, so this wraps it in BEGIN / COMMIT and rolls the whole unit
    back on any failure.
    """

    def __init__(self, path: Path):
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._path = path
        self.statements: list[str] = []

    def prepare(self, sql):
        self.statements.append(sql)
        return _Statement(self._connection, sql)

    async def batch(self, statements):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self._connection.execute(statement._sql, statement._values)
                columns = [item[0] for item in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if columns else []
                if columns:
                    results.append({"results": [dict(zip(columns, row)) for row in rows]})
                else:
                    results.append({"meta": {"rows_written": cursor.rowcount if cursor.rowcount >= 0 else 0}})
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")
        return results

    def close(self):
        self._connection.close()


def _open_database(path: Path, *, migrate: bool = True) -> _SqliteD1:
    db = _SqliteD1(path)
    if migrate:
        for migration in sorted((APP_ROOT / "migrations").glob("*.sql")):
            db._connection.executescript(migration.read_text(encoding="utf-8"))
    return db


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _accounts(history) -> dict[str, str]:
    """Both accounts exist before any conversation: the D1 foreign keys are real.

    The user id is whatever the existing authority derives from the subject; this
    test never invents one.
    """

    resolved = {}
    for subject, email in ((OWNER_SUBJECT, "owner@example.test"), (OTHER_SUBJECT, "other@example.test")):
        profile = _run(history.upsert_google_user(subject, email, f"user {subject}", ""))
        resolved[subject] = profile.id
    return resolved


def _conversation_with_run(history, *, owner: str, run_id: str, workspace_id: str = WORKSPACE) -> str:
    conversation_id = _run(history.append_exchange(owner, None, "로컬 러너로 이 작업을 실행해줘", "알겠습니다", product_scope=PRODUCT_SCOPE_CHAT))
    _run(
        history.record_claw_run(
            user_id=owner,
            run_id=run_id,
            channel="web",
            action="local_runner_task",
            title="bounded local task",
            status="running",
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )
    )
    return conversation_id


def _messages(history, conversation_id: str) -> list[dict]:
    return _run(
        history._all(
            "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY sequence_number ASC",
            conversation_id,
        )
    )
