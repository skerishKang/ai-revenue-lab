"""#4657: B66 dialogue and Chat/Claw dialogue are isolated in BOTH directions.

These run against the real `D1HistoryStore` on a real SQLite database built from
the migrations, so the isolation is proven at the data-access boundary rather
than by a Python post-filter. Owner scoping alone is not enough here: the same
account owns conversations for more than one product, and every query used to
filter by `user_id` only.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import unittest

from app.b66_conversation_store import B66ConversationStore
from app.history import (
    D1HistoryStore,
    HistoryForbidden,
    PRODUCT_SCOPE_B66,
    PRODUCT_SCOPE_CHAT,
)

OWNER = "usr_" + "a" * 32
OTHER_OWNER = "usr_" + "b" * 32
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


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


class ConversationProductIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = setup_database()
        self.store = D1HistoryStore(D1Sqlite(self.db))
        self.b66 = B66ConversationStore(self.store)

    def tearDown(self):
        self.db.close()

    def chat_conversation(self, title="채팅 대화", owner=OWNER):
        return asyncio.run(self.store.append_exchange(
            owner, None, title, "채팅 응답", product_scope=PRODUCT_SCOPE_CHAT,
        ))

    def b66_conversation(self, text="철근 견적 알려줘", owner=OWNER):
        return asyncio.run(self.b66.record_turn(owner, text, "네, 알려드릴게요"))

    def row_scope(self, conversation_id):
        row = self.db.execute(
            "SELECT product_scope FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        return None if row is None else row["product_scope"]

    # ── direction 1: B66 must not reach Chat/Claw dialogue ──────────────

    def test_b66_cannot_list_read_delete_or_continue_a_chat_conversation(self):
        chat_id = self.chat_conversation()
        assert self.row_scope(chat_id) == PRODUCT_SCOPE_CHAT

        assert asyncio.run(self.b66.list_recent(OWNER)) == []
        assert asyncio.run(self.b66.load(OWNER, chat_id)) is None
        assert asyncio.run(self.b66.delete(OWNER, chat_id)) is False
        with self.assertRaises(HistoryForbidden):
            asyncio.run(self.b66.record_turn(
                OWNER, "이어쓰기 시도", "응답", conversation_id=chat_id,
            ))

        # The Chat conversation is untouched and still fully readable by Chat.
        still_there = asyncio.run(self.store.get_conversation(
            OWNER, chat_id, product_scope=PRODUCT_SCOPE_CHAT,
        ))
        assert still_there is not None
        assert len(still_there["messages"]) == 2

    def test_a_chat_conversation_never_appears_in_b66_search(self):
        self.chat_conversation(title="철근 시세 채팅")
        assert asyncio.run(self.b66.search(OWNER, "철근")) == []

    # ── direction 2: Chat/Claw must not reach B66 dialogue ──────────────

    def test_chat_cannot_list_read_delete_or_continue_a_b66_conversation(self):
        b66_id = self.b66_conversation()
        assert self.row_scope(b66_id) == PRODUCT_SCOPE_B66

        listed = asyncio.run(self.store.list_conversations(
            OWNER, product_scope=PRODUCT_SCOPE_CHAT,
        ))
        assert [row["id"] for row in listed] == []
        assert asyncio.run(self.store.get_conversation(
            OWNER, b66_id, product_scope=PRODUCT_SCOPE_CHAT,
        )) is None
        assert asyncio.run(self.store.delete_conversation(
            OWNER, b66_id, product_scope=PRODUCT_SCOPE_CHAT,
        )) is False
        with self.assertRaises(HistoryForbidden):
            asyncio.run(self.store.append_exchange(
                OWNER, b66_id, "이어쓰기", "응답", product_scope=PRODUCT_SCOPE_CHAT,
            ))

        # The B66 conversation survives and is still readable by B66.
        assert asyncio.run(self.b66.load(OWNER, b66_id)) is not None

    def test_a_b66_conversation_never_appears_in_chat_search(self):
        self.b66_conversation(text="철근 시세 알려줘")
        assert asyncio.run(self.store.search_conversations(
            OWNER, "철근", product_scope=PRODUCT_SCOPE_CHAT,
        )) == []

    # ── mixed pagination and search windows ────────────────────────────

    def test_mixed_conversations_stay_separated_under_a_wide_limit(self):
        chat_ids = {self.chat_conversation(title=f"채팅 {i}") for i in range(3)}
        b66_ids = {self.b66_conversation(text=f"철근 견적 {i}") for i in range(4)}

        chat_listed = asyncio.run(self.store.list_conversations(
            OWNER, product_scope=PRODUCT_SCOPE_CHAT, limit=50,
        ))
        b66_listed = asyncio.run(self.b66.list_recent(OWNER, limit=50))

        assert {row["id"] for row in chat_listed} == chat_ids
        assert {row["conversation_id"] for row in b66_listed} == b66_ids
        # A wide limit must not let one product's rows fill the other's window.
        assert not ({row["id"] for row in chat_listed} & b66_ids)

    def test_search_results_are_not_consumed_by_the_other_products_rows(self):
        # Both products hold rows matching the same term.
        chat_ids = {self.chat_conversation(title=f"철근 채팅 {i}") for i in range(2)}
        b66_ids = {self.b66_conversation(text=f"철근 견적 {i}") for i in range(3)}

        chat_hits = asyncio.run(self.store.search_conversations(
            OWNER, "철근", product_scope=PRODUCT_SCOPE_CHAT,
        ))
        b66_hits = asyncio.run(self.b66.search(OWNER, "철근"))

        assert {row["id"] for row in chat_hits} == chat_ids
        assert {row["conversation_id"] for row in b66_hits} == b66_ids

    def test_a_limited_search_window_is_filled_by_its_own_product_only(self):
        for i in range(3):
            self.chat_conversation(title=f"철근 채팅 {i}")
        b66_ids = {self.b66_conversation(text=f"철근 견적 {i}") for i in range(2)}

        # limit=2 with 3 matching Chat rows and 2 matching B66 rows: B66 must
        # still return both of its own rows, not an empty window.
        hits = asyncio.run(self.b66.search(OWNER, "철근", limit=2))
        assert {row["conversation_id"] for row in hits} == b66_ids

    # ── owner isolation still holds inside a product ───────────────────

    def test_another_owners_b66_conversation_is_not_reachable(self):
        foreign = self.b66_conversation(owner=OTHER_OWNER)
        assert asyncio.run(self.b66.list_recent(OWNER)) == []
        assert asyncio.run(self.b66.load(OWNER, foreign)) is None
        assert asyncio.run(self.b66.delete(OWNER, foreign)) is False
        assert asyncio.run(self.b66.load(OTHER_OWNER, foreign)) is not None

    # ── the discriminator itself fails closed ──────────────────────────

    def test_an_unknown_or_missing_product_scope_is_refused(self):
        chat_id = self.chat_conversation()
        for bad in (None, "", "b66-evil", "b62-chat ", 7):
            with self.assertRaises(HistoryForbidden):
                asyncio.run(self.store.list_conversations(OWNER, product_scope=bad))
            with self.assertRaises(HistoryForbidden):
                asyncio.run(self.store.get_conversation(
                    OWNER, chat_id, product_scope=bad,
                ))
            with self.assertRaises(HistoryForbidden):
                asyncio.run(self.store.delete_conversation(
                    OWNER, chat_id, product_scope=bad,
                ))

    def test_a_legacy_row_is_backfilled_to_the_chat_scope(self):
        """The migration preserves Chat/Claw continuity, not B66 visibility."""
        self.db.execute(
            "INSERT INTO conversations(id,user_id,title,created_at,updated_at) "
            "VALUES (?,?,?,?,?)",
            ("chat_legacy_4657", OWNER, "레거시 대화", "2026-10-14", "2026-10-14"),
        )
        self.db.commit()
        assert self.row_scope("chat_legacy_4657") == PRODUCT_SCOPE_CHAT
        assert asyncio.run(self.b66.load(OWNER, "chat_legacy_4657")) is None
        assert asyncio.run(self.store.get_conversation(
            OWNER, "chat_legacy_4657", product_scope=PRODUCT_SCOPE_CHAT,
        )) is not None
