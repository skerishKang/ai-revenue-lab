"""T3 H5-1 회귀 — AccountStore(M)가 StoreCore 조합으로 같은 결과를 낸다 (#7813).

공개 메서드 이름 집합은 H4 시험의 PUBLIC_NAMES를 그대로 쓰며, 여기서는
MRO와 영역 간 중복 정의를 고정한다. 지역·모의만 사용한다.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from app import history as history_entry
from app import history_store_accounts as accounts_module
from app import history_store_core as core_module
from app import history_store_handoff as handoff_module
from app import history_store_runs as runs_module
from app import history_store_run_events as events_module
from app import history_store_mesh as mesh_module
from app.history import D1HistoryStore
from _support.history_public_names import PUBLIC_NAMES

EMAIL = "member@example.test"
USERNAME = "member1"
HASH = "pbkdf2:fake-hash-for-h5-test"


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
        for name in ("001_auth_history.sql", "012_password_auth.sql", "101_password_rpc_service_ids.sql"):
            self.conn.executescript((migrations / name).read_text(encoding="utf8"))

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
    assert history_entry.AccountStore is accounts_module.AccountStore
    assert history_entry.StoreCore is core_module.StoreCore
    assert history_entry.ApprovalHandoffStore is handoff_module.ApprovalHandoffStore


def test_no_duplicate_method_definitions_across_areas() -> None:
    seen: dict[str, str] = {}
    for cls in (D1HistoryStore, runs_module.RunStore, events_module.RunEventStore, mesh_module.MeshDispatchStore, history_entry.ConversationStore, accounts_module.AccountStore, handoff_module.ApprovalHandoffStore, core_module.StoreCore):
        for name in vars(cls):
            if name.startswith("__"):
                continue
            assert name not in seen, f"{name} defined in both {seen.get(name)} and {cls.__name__}"
            seen[name] = cls.__name__


def test_register_find_and_user_row() -> None:
    store = _store()
    profile = asyncio.run(store.register_password_user(USERNAME, EMAIL, "표시 이름", HASH))
    assert profile.email == EMAIL and profile.id.startswith("usr_")
    assert asyncio.run(store.user_row_exists(profile.id)) is True
    assert asyncio.run(store.get_user(profile.id)) == profile
    by_email = asyncio.run(store.find_password_credential(EMAIL))
    by_name = asyncio.run(store.find_password_credential(USERNAME))
    assert by_email is not None and by_name is not None
    assert by_email.user == profile and by_email.username == USERNAME
    assert by_email.password_hash == HASH and by_email.failed_attempts == 0
    assert by_name.user.id == profile.id
    assert asyncio.run(store.find_password_credential("nobody@example.test")) is None


def test_upsert_google_user_and_shared_user() -> None:
    store = _store()
    profile = asyncio.run(store.upsert_google_user("subject-1", "g@example.test", " 구글 이름", "pic"))
    assert profile.email == "g@example.test" and profile.display_name == "구글 이름"
    again = asyncio.run(store.upsert_google_user("subject-1", "g2@example.test", "새 이름", "pic2"))
    assert again.id == profile.id and again.email == "g2@example.test"
    shared_id = "usr_" + "1" * 32
    shared = asyncio.run(store.upsert_shared_user(shared_id, "sub_abc-1", "s@example.test", "", ""))
    assert shared.id == shared_id and shared.display_name == "s"


def test_password_failure_lock_and_release_flow() -> None:
    store = _store()
    profile = asyncio.run(store.register_password_user(USERNAME, EMAIL, "이름", HASH))
    uid = profile.id
    assert asyncio.run(store.increment_password_failures(uid)) == 1
    assert asyncio.run(store.increment_password_failures(uid)) == 2
    asyncio.run(store.record_password_failure(uid, 5, None))
    cred = asyncio.run(store.find_password_credential(EMAIL))
    assert cred is not None and cred.failed_attempts == 5 and cred.locked_until is None
    asyncio.run(store.lock_password_credential(uid, lock_until="2099-01-01T00:00:00+00:00", min_failures=5))
    cred = asyncio.run(store.find_password_credential(EMAIL))
    assert cred is not None and cred.locked_until == "2099-01-01T00:00:00+00:00"
    # Lapsed lock: count restarts at one only while the exact lock is stored.
    assert asyncio.run(store.restart_password_failures_after_lapsed_lock(
        uid, expected_locked_until="2099-01-01T00:00:00+00:00",
    )) is True
    cred = asyncio.run(store.find_password_credential(EMAIL))
    assert cred is not None and cred.failed_attempts == 1 and cred.locked_until is None
    assert asyncio.run(store.restart_password_failures_after_lapsed_lock(
        uid, expected_locked_until="2099-01-01T00:00:00+00:00",
    )) is False  # already restarted: second call does not re-trigger
    asyncio.run(store.reset_password_failures(uid))
    cred = asyncio.run(store.find_password_credential(EMAIL))
    assert cred is not None and cred.failed_attempts == 0


def test_consume_service_id_rejects_replay() -> None:
    store = _store()
    exp = "2099-01-01T00:00:00+00:00"
    assert asyncio.run(store.consume_service_id("svc-1", exp)) is True
    assert asyncio.run(store.consume_service_id("svc-1", exp)) is False
    assert asyncio.run(store.consume_service_id("svc-2", exp)) is True
