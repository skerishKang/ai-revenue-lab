"""#7543 — one worker stages a chat_pcq run, another promotes and reads it.

The run row and its staged turn are in the shared SQLite store; no run state is
held in a worker's process memory. Both app instances see the same result.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT
from app.history_ids import validate_chat_pc_run_id

RUN = "chat_pcq_" + "a" * 32
OWNER = "usr_" + "b" * 32
CID = "chat_" + "c" * 32
WS = "personal"


class _Store:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.store = D1HistoryStore(SqliteD1(self.conn, threaded=True))

    def close(self):
        self.conn.close()


def _prepare(path: Path) -> None:
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        for sql in (
            """CREATE TABLE IF NOT EXISTS conversations (
                 id TEXT PRIMARY KEY, user_id TEXT, project_id TEXT, title TEXT,
                 created_at TEXT, updated_at TEXT, product_scope TEXT, deleted_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS messages (
                 id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT,
                 sequence_number INTEGER, created_at TEXT, updated_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS claw_run_history (
                 id TEXT PRIMARY KEY, user_id TEXT, run_id TEXT, channel TEXT, action TEXT,
                 title TEXT, status TEXT, created_at TEXT, updated_at TEXT,
                 result_summary TEXT, artifact_document_id TEXT, artifact_filename TEXT,
                 artifact_media_type TEXT, conversation_id TEXT, workspace_id TEXT)""",
        ):
            conn.execute(sql)
        conn.execute(
            "INSERT OR IGNORE INTO conversations "
            "(id, user_id, project_id, title, created_at, updated_at, product_scope, deleted_at) "
            "VALUES (?, ?, NULL, 'unit', '2026-11-23T00:00:00Z', '2026-11-23T00:00:00Z', ?, NULL)",
            ("chat_" + "c" * 32, "usr_" + "b" * 32, PRODUCT_SCOPE_CHAT),
        )
    finally:
        conn.close()


def test_run_staged_on_one_worker_is_promoted_and_read_on_the_other(tmp_path):
    path = tmp_path / "chat.sqlite3"
    _prepare(path)
    first = _Store(path)
    second = _Store(path)
    try:
        validate_chat_pc_run_id(RUN)

        async def scenario():
            await first.store.begin_chat_stream_turn(
                user_id=OWNER, run_id=RUN, workspace_id=WS,
                user_text="폴더 목록 보여줘", conversation_id=CID,
            )
            # Staging does not create the run row yet.
            assert await second.store.get_claw_run(OWNER, RUN) is None

            promoted = await second.store.promote_chat_stream_pc_run(
                user_id=OWNER, run_id=RUN, workspace_id=WS, action="pc_files_query",
            )
            assert isinstance(promoted, dict) and promoted["status"] == "pending"

            for store in (first.store, second.store):
                row = await store.get_claw_run(OWNER, RUN)
                assert row is not None and row["run_id"] == RUN
                assert row["conversation_id"] == CID
                assert row["action"] == "pc_files_query"

        asyncio.run(scenario())
    finally:
        first.close()
        second.close()
