"""T3 H5-2 회귀 — ConversationStore(N)가 StoreCore 조합으로 같은 결과를 낸다 (#7813)."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from app import history as history_entry
from app import history_store_accounts as accounts_module
from app import history_store_conversations as conv_module
from app import history_store_core as core_module
from app import history_store_handoff as handoff_module
from app import history_store_runs as runs_module
from app import history_store_run_events as events_module
from app import history_store_mesh as mesh_module
from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT
from test_7813_history_h4_store_core import PUBLIC_NAMES

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32


class _Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return _Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class _D1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for name in ("001_auth_history.sql", "002_projects.sql", "042_conversation_product_scope.sql", "105_conversation_soft_delete.sql"):
            self.conn.executescript((migrations / name).read_text(encoding="utf8"))
        for owner in (OWNER, OTHER):
            self.conn.execute(
                "INSERT INTO users(id,auth_provider,provider_subject,email,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (owner, "google", owner, owner + "@example.com", "2026-10-14", "2026-10-14"),
            )
        self.conn.commit()

    def prepare(self, sql):
        return _Statement(self, sql)

    async def batch(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self.conn.execute(statement.sql, statement.params)
                results.append(SimpleNamespace(
                    results=[dict(row) for row in cursor.fetchall()],
                    meta={"changes": cursor.rowcount},
                ))
            self.conn.execute("COMMIT")
            return results
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


def _store() -> D1HistoryStore:
    return D1HistoryStore(_D1())


def test_public_method_names_are_unchanged() -> None:
    assert {name for name in dir(D1HistoryStore) if not name.startswith("_")} == PUBLIC_NAMES


def test_mro_is_fixed() -> None:
    assert [c.__name__ for c in D1HistoryStore.__mro__] == [
        "D1HistoryStore", "RunStore", "RunEventStore", "MeshDispatchStore", "ConversationStore", "AccountStore",
        "ApprovalHandoffStore", "StoreCore", "object",
    ]
    assert history_entry.RunStore is runs_module.RunStore
    assert history_entry.RunEventStore is events_module.RunEventStore
    assert history_entry.MeshDispatchStore is mesh_module.MeshDispatchStore
    assert history_entry.ConversationStore is conv_module.ConversationStore
    assert history_entry.AccountStore is accounts_module.AccountStore
    assert history_entry.StoreCore is core_module.StoreCore
    assert history_entry.ApprovalHandoffStore is handoff_module.ApprovalHandoffStore


def test_no_duplicate_method_definitions_across_areas() -> None:
    seen: dict[str, str] = {}
    for cls in (D1HistoryStore, runs_module.RunStore, events_module.RunEventStore, mesh_module.MeshDispatchStore, conv_module.ConversationStore,
                accounts_module.AccountStore, handoff_module.ApprovalHandoffStore, core_module.StoreCore):
        for name in vars(cls):
            if name.startswith("__"):
                continue
            assert name not in seen, f"{name} defined in both {seen.get(name)} and {cls.__name__}"
            seen[name] = cls.__name__


def test_conversation_create_list_search_update_delete() -> None:
    store = _store()
    cid = asyncio.run(store.append_exchange(
        OWNER, None, "파디엠 견적 요청", "합성 응답 본문", product_scope=PRODUCT_SCOPE_CHAT,
    ))
    assert cid.startswith("chat_")
    listed = asyncio.run(store.list_conversations(OWNER, product_scope=PRODUCT_SCOPE_CHAT))
    assert [row["id"] for row in listed] == [cid]
    assert listed[0]["title"] == "파디엠 견적 요청"
    found = asyncio.run(store.search_conversations(OWNER, "견적", product_scope=PRODUCT_SCOPE_CHAT))
    assert [row["id"] for row in found] == [cid]
    detail = asyncio.run(store.get_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT))
    assert detail is not None and detail["messages"][0]["content"] == "파디엠 견적 요청"
    assert asyncio.run(store.get_conversation(OTHER, cid, product_scope=PRODUCT_SCOPE_CHAT)) is None
    updated = asyncio.run(store.update_conversation(
        OWNER, cid, title="새 제목", product_scope=PRODUCT_SCOPE_CHAT,
    ))
    assert updated is not None and updated["title"] == "새 제목"
    assert asyncio.run(store.update_conversation(
        OTHER, cid, title="탈취", product_scope=PRODUCT_SCOPE_CHAT,
    )) is None
    assert asyncio.run(store.delete_conversation(OTHER, cid, product_scope=PRODUCT_SCOPE_CHAT)) is False
    assert asyncio.run(store.delete_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT)) is True
    assert asyncio.run(store.list_conversations(OWNER, product_scope=PRODUCT_SCOPE_CHAT)) == []


def test_project_create_list_delete() -> None:
    store = _store()
    project = asyncio.run(store.create_project(OWNER, "내 프로젝트", "선호 지침"))
    assert project.id.startswith("proj_") and project.name == "내 프로젝트"
    assert asyncio.run(store.get_project(OWNER, project.id)) == project
    assert asyncio.run(store.get_project(OTHER, project.id)) is None
    listed = asyncio.run(store.list_projects(OWNER))
    assert [p.id for p in listed] == [project.id]
    page_projects, next_cursor = asyncio.run(store.list_projects_page(OWNER))
    assert page_projects[0].id == project.id
    assert next_cursor is None
    assert asyncio.run(store.delete_project(OTHER, project.id)) is False
    assert asyncio.run(store.delete_project(OWNER, project.id)) is True
    assert asyncio.run(store.list_projects(OWNER)) == []
