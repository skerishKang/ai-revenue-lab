"""#5226 — concurrent Chat/Claw/Project-File saves must stay consistent.

The storage defect this pins down is a read-then-write race on the message
sequence number. The sequence used to be read with ``MAX(sequence_number)`` in
one statement and written in a later one, so two appends to the same
conversation could claim the same number; and the user row and the assistant
row were two separate statements, so a failure between them left a half
written turn behind while the cleanup removed the R2 original of a row that had
actually landed.

The doubles below are a real SQLite database behind the Cloudflare D1
interface, so the schema's own ``UNIQUE(conversation_id, sequence_number)`` and
``messages``/``project_files`` constraints are the authority the tests measure
against. The gate forces a deterministic interleaving: every writer that
reaches the gated statement waits until the configured number of writers have
arrived, so both contenders act on the same pre-write state.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from app.history import (
    MAX_HISTORY_MESSAGE_CHARS,
    PRODUCT_SCOPE_CHAT,
    D1HistoryStore,
)
from app.project_files import D1ProjectFileStore, ProjectFileError

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION_NAMES = (
    "001_auth_history.sql",
    "002_projects.sql",
    "003_project_files.sql",
    "009_claw_run_history.sql",
    "014_claw_run_history_conversation.sql",
    "015_claw_run_history_workspace.sql",
    "042_conversation_product_scope.sql",
)

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
CONVERSATION = "chat_" + "c" * 32
PROJECT = "proj_" + "d" * 32
FOREIGN_PROJECT = "proj_" + "e" * 32
WORKSPACE = "ws_5226"

#: Long enough that the stored preview is a truncated marker and the canonical
#: full original lives in R2, which is what makes a D1/R2 mismatch visible.
USER_TEXT = "USER-ORIGINAL-" + ("u" * 9000)
ASSISTANT_TEXT = "ASSISTANT-ORIGINAL-" + ("a" * 9000)
USER_TEXT_2 = "USER-ORIGINAL-2-" + ("u" * 9000)
ASSISTANT_TEXT_2 = "ASSISTANT-ORIGINAL-2-" + ("a" * 9000)


class _Gate:
    """Rendezvous: hold every writer at a gated statement until N have arrived."""

    def __init__(self, parties: int) -> None:
        self.parties = parties
        self.arrived = 0
        self._released = asyncio.Event()

    async def wait(self) -> None:
        self.arrived += 1
        if self.arrived >= self.parties:
            self._released.set()
        await self._released.wait()


class _SqliteD1:
    """Cloudflare D1 interface over one SQLite connection.

    ``gate`` suspends every writer that reaches a matching statement until the
    configured number of writers have arrived, which is how the tests pin a
    deterministic interleaving. ``fault`` raises for a chosen statement, which
    is how a write that fails between two rows is reproduced.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        gate: Callable[[str], bool] | None = None,
        gate_parties: int = 2,
        fault: Callable[[str, tuple], bool] | None = None,
    ) -> None:
        self.conn = conn
        self.gate = gate
        self.gate_parties = gate_parties
        self.fault = fault
        self._rendezvous: _Gate | None = None
        self.statements: list[str] = []

    def prepare(self, sql: str) -> "_SqliteD1Statement":
        return _SqliteD1Statement(self, sql)

    async def batch(self, statements: list["_SqliteD1Statement"]) -> list[Any]:
        """One atomic D1 transaction, the same contract the Cloudflare binding has.

        A statement that returns a result set reports ``results``; a statement
        that does not reports ``meta.rows_written`` instead. This is the shape
        the repository's other D1 doubles already use, so the store's readers
        see the same contract here.
        """
        results: list[Any] = []
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                cursor = self.conn.execute(statement._sql, statement._values)
                columns = [item[0] for item in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if columns else []
                if columns:
                    results.append({"results": [dict(zip(columns, row)) for row in rows]})
                else:
                    written = cursor.rowcount if cursor.rowcount >= 0 else 0
                    results.append({"meta": {"rows_written": written}})
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return results

    async def execute(self, sql: str, values: tuple) -> dict[str, Any]:
        self.statements.append(sql)
        if self.gate is not None and self.gate(sql):
            if self._rendezvous is None:
                self._rendezvous = _Gate(self.gate_parties)
            await self._rendezvous.wait()
        if self.fault is not None and self.fault(sql, values):
            raise sqlite3.IntegrityError("simulated concurrent write conflict")
        cursor = self.conn.execute(sql, values)
        rows = [dict(row) for row in cursor.fetchall()]
        return {"results": rows, "success": True, "meta": {"changes": cursor.rowcount}}


class _SqliteD1Statement:
    def __init__(self, db: _SqliteD1, sql: str, values: tuple = ()) -> None:
        self._db = db
        self._sql = sql
        self._values = values

    def bind(self, *values: Any) -> "_SqliteD1Statement":
        return _SqliteD1Statement(self._db, self._sql, values)

    async def run(self) -> dict[str, Any]:
        return await self._db.execute(self._sql, self._values)

    async def first(self) -> dict[str, Any] | None:
        result = await self._db.execute(self._sql, self._values)
        rows = result["results"]
        return rows[0] if rows else None

    async def all(self) -> list[dict[str, Any]]:
        result = await self._db.execute(self._sql, self._values)
        return list(result["results"])


class _PrivateR2:
    """Private full-context bucket double; keys are server-derived only."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, key: str, payload: bytes, **_kwargs: Any) -> None:
        self.objects[key] = bytes(payload)

    async def get(self, key: str) -> Any:
        data = self.objects.get(key)
        if data is None:
            return None
        return SimpleNamespace(size=len(data), arrayBuffer=lambda: data)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    for name in MIGRATION_NAMES:
        conn.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
        "VALUES (?, 'google', ?, ?, '', '', '2026-10-20T00:00:00.000Z', '2026-10-20T00:00:00.000Z')",
        (OWNER, "subject-owner", "owner@example.test"),
    )
    conn.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
        "VALUES (?, 'google', ?, ?, '', '', '2026-10-20T00:00:00.000Z', '2026-10-20T00:00:00.000Z')",
        (OTHER, "subject-other", "other@example.test"),
    )
    conn.execute(
        "INSERT INTO projects (id, user_id, name, instructions, created_at, updated_at) VALUES (?, ?, ?, '', ?, ?)",
        (PROJECT, OWNER, "owner project", "t0", "t0"),
    )
    conn.execute(
        "INSERT INTO projects (id, user_id, name, instructions, created_at, updated_at) VALUES (?, ?, ?, '', ?, ?)",
        (FOREIGN_PROJECT, OTHER, "other project", "t0", "t0"),
    )
    conn.execute(
        "INSERT INTO conversations (id, user_id, project_id, title, created_at, updated_at, product_scope) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?)",
        (CONVERSATION, OWNER, "seeded", "t0", "t0", PRODUCT_SCOPE_CHAT),
    )
    return conn


def _history_store(conn: sqlite3.Connection, **kwargs: Any) -> tuple[D1HistoryStore, _PrivateR2]:
    bucket = _PrivateR2()
    return D1HistoryStore(_SqliteD1(conn, **kwargs), full_context_bucket=bucket), bucket


def _messages(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, conversation_id, sequence_number, role, content FROM messages "
            "WHERE conversation_id=? ORDER BY sequence_number ASC",
            (CONVERSATION,),
        )
    ]


def _carries_assistant_text(sql: str, values: tuple) -> bool:
    """Fault that fails the write carrying the assistant half of an exchange."""
    return any(isinstance(value, str) and "ASSISTANT-ORIGINAL" in value for value in values)


def _fails_conversation_timestamp(sql: str, values: tuple) -> bool:
    """Fault that fails the conversation timestamp update, after the rows landed."""
    return sql.startswith("UPDATE conversations SET updated_at")


# ---------------------------------------------------------------------------
# Chat: the exchange append
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_appends_to_one_conversation_both_persist() -> None:
    """Two appends to one conversation must not collide on the sequence number."""
    conn = _database()
    store, bucket = _history_store(
        conn,
        gate=lambda sql: "INSERT INTO messages" in sql,
        gate_parties=2,
    )

    first, second = await asyncio.gather(
        store.append_exchange(OWNER, CONVERSATION, USER_TEXT, ASSISTANT_TEXT, product_scope=PRODUCT_SCOPE_CHAT),
        store.append_exchange(OWNER, CONVERSATION, USER_TEXT_2, ASSISTANT_TEXT_2, product_scope=PRODUCT_SCOPE_CHAT),
    )

    assert first == second == CONVERSATION
    rows = _messages(conn)
    # Every turn is complete and the numbering is gapless and unique.
    assert [row["sequence_number"] for row in rows] == [0, 1, 2, 3]
    assert [row["role"] for row in rows] == ["user", "assistant", "user", "assistant"]
    assert len({row["id"] for row in rows}) == 4
    # Each exchange kept its own user/assistant pair, side by side.
    assert [row["role"] for row in rows[0:2]] == ["user", "assistant"]
    assert [row["role"] for row in rows[2:4]] == ["user", "assistant"]
    # Every stored row keeps its R2 original: no orphan and no missing object.
    assert len(bucket.objects) == 4
    assert bucket.deleted == []

    context = await store.get_conversation_model_context(OWNER, CONVERSATION, product_scope=PRODUCT_SCOPE_CHAT)
    contents = [message["content"] for message in context["messages"]]
    assert sorted(contents) == sorted([USER_TEXT, ASSISTANT_TEXT, USER_TEXT_2, ASSISTANT_TEXT_2])
    # Each exchange's user turn is immediately followed by its own answer.
    for user_text, assistant_text in ((USER_TEXT, ASSISTANT_TEXT), (USER_TEXT_2, ASSISTANT_TEXT_2)):
        position = contents.index(user_text)
        assert contents[position + 1] == assistant_text


@pytest.mark.asyncio
async def test_failed_exchange_leaves_no_row_and_no_orphan_r2_object() -> None:
    """A failed exchange must not leave a half turn or a preview-only row."""
    conn = _database()
    store, bucket = _history_store(conn, fault=_carries_assistant_text)

    with pytest.raises(sqlite3.IntegrityError):
        await store.append_exchange(OWNER, CONVERSATION, USER_TEXT, ASSISTANT_TEXT, product_scope=PRODUCT_SCOPE_CHAT)

    # No half written turn: the user row and the assistant row land together.
    assert _messages(conn) == []
    # No orphan R2 object: the full original is removed with the row.
    assert bucket.objects == {}
    # The stored conversation is still readable as a whole.
    context = await store.get_conversation_model_context(OWNER, CONVERSATION, product_scope=PRODUCT_SCOPE_CHAT)
    assert context["messages"] == []


@pytest.mark.asyncio
async def test_first_exchange_failure_leaves_no_empty_conversation() -> None:
    """A first turn that never landed must not leave an empty conversation."""
    conn = _database()
    store, bucket = _history_store(conn, fault=_carries_assistant_text)
    before = list(conn.execute("SELECT id FROM conversations"))

    with pytest.raises(sqlite3.IntegrityError):
        await store.append_exchange(OWNER, None, USER_TEXT, ASSISTANT_TEXT, product_scope=PRODUCT_SCOPE_CHAT)

    after = list(conn.execute("SELECT id FROM conversations"))
    assert [dict(row)["id"] for row in after] == [dict(row)["id"] for row in before]
    assert _messages(conn) == []
    assert bucket.objects == {}


@pytest.mark.asyncio
async def test_a_failure_after_the_rows_landed_keeps_the_r2_original() -> None:
    """A failure after the rows landed must not strip their R2 original.

    The stored preview is a truncated marker; the canonical full original lives
    in R2. If a later statement fails and the cleanup removes the original of a
    row that did land, that row can never be restored for the model again.
    """
    conn = _database()
    store, bucket = _history_store(conn, fault=_fails_conversation_timestamp)

    with pytest.raises(sqlite3.IntegrityError):
        await store.append_exchange(OWNER, CONVERSATION, USER_TEXT, ASSISTANT_TEXT, product_scope=PRODUCT_SCOPE_CHAT)

    # The rows did land, so their full originals must still be there.
    rows = _messages(conn)
    assert len(rows) == 2
    assert len(bucket.objects) == 2
    # And the stored conversation is still restorable for the model.
    context = await store.get_conversation_model_context(OWNER, CONVERSATION, product_scope=PRODUCT_SCOPE_CHAT)
    assert [message["content"] for message in context["messages"]] == [USER_TEXT, ASSISTANT_TEXT]


@pytest.mark.asyncio
async def test_conversation_append_still_refuses_a_foreign_conversation() -> None:
    """The ownership boundary is unchanged by the atomic write."""
    conn = _database()
    store, _bucket = _history_store(conn)

    with pytest.raises(Exception):
        await store.append_exchange(OTHER, CONVERSATION, USER_TEXT, ASSISTANT_TEXT, product_scope=PRODUCT_SCOPE_CHAT)
    assert _messages(conn) == []


# ---------------------------------------------------------------------------
# Claw: the pending user turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_claw_pending_turns_both_persist() -> None:
    """Two pending Claw turns on one conversation must not collide."""
    conn = _database()
    store, bucket = _history_store(
        conn,
        gate=lambda sql: "INSERT INTO messages" in sql,
        gate_parties=2,
    )

    await asyncio.gather(
        store.record_txt_pending_run(
            user_id=OWNER, run_id="run_5226_a", workspace_id=WORKSPACE,
            user_text=USER_TEXT, conversation_id=CONVERSATION,
        ),
        store.record_txt_pending_run(
            user_id=OWNER, run_id="run_5226_b", workspace_id=WORKSPACE,
            user_text=USER_TEXT_2, conversation_id=CONVERSATION,
        ),
    )

    rows = _messages(conn)
    assert [row["sequence_number"] for row in rows] == [0, 1]
    assert [row["role"] for row in rows] == ["user", "user"]
    assert len({row["id"] for row in rows}) == 2
    # Both pending runs are recorded, so neither turn is stranded.
    runs = list(conn.execute(
        "SELECT run_id, status FROM claw_run_history WHERE user_id=? AND conversation_id=? ORDER BY run_id",
        (OWNER, CONVERSATION),
    ))
    assert [dict(row)["run_id"] for row in runs] == ["run_5226_a", "run_5226_b"]
    assert all(row["status"] == "pending" for row in runs)
    # Both full originals are still stored.
    assert len(bucket.objects) == 2


@pytest.mark.asyncio
async def test_claw_pending_turn_keeps_exactly_once_result_append() -> None:
    """The existing exactly-once result contract is preserved."""
    conn = _database()
    store, _bucket = _history_store(conn)

    await store.record_txt_pending_run(
        user_id=OWNER, run_id="run_5226_once", workspace_id=WORKSPACE,
        user_text=USER_TEXT, conversation_id=CONVERSATION,
    )
    appended = await store.append_local_task_result(
        user_id=OWNER, run_id="run_5226_once", message_id="msg_" + "1" * 32,
        summary="done", content="result body", status="completed",
    )
    repeated = await store.append_local_task_result(
        user_id=OWNER, run_id="run_5226_once", message_id="msg_" + "1" * 32,
        summary="done", content="result body", status="completed",
    )

    assert appended is True
    assert repeated is False
    rows = _messages(conn)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert [row["sequence_number"] for row in rows] == [0, 1]


# ---------------------------------------------------------------------------
# Project files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_file_cannot_be_stored_under_another_owners_project() -> None:
    """The save-time ownership condition cannot be bypassed."""
    conn = _database()
    store = D1ProjectFileStore(_SqliteD1(conn))

    with pytest.raises(ProjectFileError):
        await store.create_file(OWNER, FOREIGN_PROJECT, "notes.txt", "text/plain", "hello")

    rows = list(conn.execute("SELECT id, project_id, user_id FROM project_files"))
    assert rows == []


@pytest.mark.asyncio
async def test_project_file_cannot_be_stored_without_a_project() -> None:
    conn = _database()
    store = D1ProjectFileStore(_SqliteD1(conn))

    with pytest.raises(ProjectFileError):
        await store.create_file(OWNER, "proj_" + "9" * 32, "notes.txt", "text/plain", "hello")

    rows = list(conn.execute("SELECT id FROM project_files"))
    assert rows == []


@pytest.mark.asyncio
async def test_two_concurrent_project_file_adds_both_persist_in_their_own_project() -> None:
    conn = _database()
    store = D1ProjectFileStore(_SqliteD1(conn))

    created = await asyncio.gather(
        store.create_file(OWNER, PROJECT, "one.txt", "text/plain", "first body"),
        store.create_file(OWNER, PROJECT, "two.txt", "text/plain", "second body"),
    )

    assert len({record.id for record in created}) == 2
    stored = list(conn.execute("SELECT id, project_id, user_id, name, created_at FROM project_files"))
    assert sorted(row["name"] for row in stored) == ["one.txt", "two.txt"]
    assert {row["project_id"] for row in stored} == {PROJECT}
    assert {row["user_id"] for row in stored} == {OWNER}

    listed = await store.list_files(OWNER, PROJECT)
    assert sorted(record.name for record in listed) == ["one.txt", "two.txt"]
    # The list keeps its keyset order: created_at ascending, then id.
    created_at = {row["id"]: row["created_at"] for row in stored}
    assert [record.id for record in listed] == sorted(created_at, key=lambda fid: (created_at[fid], fid))
    # Another owner sees nothing of this project's files.
    assert await store.list_files(OTHER, PROJECT) == []
    assert await store.get_file(OWNER, FOREIGN_PROJECT, created[0].id) is None


@pytest.mark.asyncio
async def test_project_file_creation_keeps_the_bounded_media_contract() -> None:
    conn = _database()
    store = D1ProjectFileStore(_SqliteD1(conn))

    record = await store.create_file(OWNER, PROJECT, "notes.txt", "text/plain", "hello")
    assert record.content_chars == len("hello")
    assert record.project_id == PROJECT

    with pytest.raises(Exception):
        await store.create_file(OWNER, PROJECT, "notes.txt", "application/json", "not json")
    assert len(list(conn.execute("SELECT id FROM project_files"))) == 1
