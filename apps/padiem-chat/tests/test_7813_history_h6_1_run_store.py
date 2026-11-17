"""T3 H6-1 회귀 — RunStore(O 첫 묶음)가 이동 전과 같은 실행 기록 결과를 낸다 (#7813).

전후 비교는 이동 전 main(`b421195a`)의 `D1HistoryStore`로 같은 흐름을 돌려
얻은 행·순서를 여기 고정값으로 두고 다시 실행한 값이 같은지 본다. 지역 sqlite만 쓴다.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app import history as history_entry
from app import history_store_core as core_module
from app import history_store_runs as runs_module
from app import history_store_run_events as events_module
from app import history_store_mesh as mesh_module
from app.history import D1HistoryStore
from test_7813_history_h4_store_core import PUBLIC_NAMES

APP = Path(__file__).resolve().parents[1] / "app"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

OWNER = "usr_" + "1" * 32
OTHER = "usr_" + "2" * 32
FIXED = "2026-11-17T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00.000Z"
PAST = "2020-01-01T00:00:00+00:00"

H61_METHODS = {
    "record_txt_pending_run", "create_web_xlsx_p01_run", "_chat_stream_turn",
    "begin_chat_stream_turn", "read_pc_session_confirmation_turn",
    "promote_chat_stream_pc_run", "finish_chat_stream_turn",
    "record_chat_pc_drive_run", "ensure_claw_automation_conversation",
    "record_claw_run", "list_recent_claw_runs", "update_claw_run_status",
    "consume_pc_command_confirmation", "expire_stale_confirmation_cards",
    "get_pc_run_scope", "get_pc_run_scope_notice", "pin_pc_run_scope",
    "get_claw_run", "get_claw_run_for_artifact_document",
    "get_claw_run_result_message", "get_claw_run_result",
}

COLUMNS = (
    "user_id", "run_id", "channel", "action", "title", "status",
    "created_at", "updated_at", "result_summary", "artifact_document_id",
    "artifact_filename", "artifact_media_type", "conversation_id", "workspace_id",
)


class _Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return _Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.execute(self.sql, self.params)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class _D1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        for name in (
            "001_auth_history.sql", "002_projects.sql", "009_claw_run_history.sql",
            "014_claw_run_history_conversation.sql", "015_claw_run_history_workspace.sql",
            "042_conversation_product_scope.sql",
        ):
            self.conn.executescript((MIGRATIONS / name).read_text(encoding="utf8"))

    def prepare(self, sql):
        return _Statement(self.conn, sql)

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


def _snapshot(db):
    rows = db.execute(
        "SELECT " + ",".join(COLUMNS) + " FROM claw_run_history ORDER BY run_id, created_at"
    ).fetchall()
    return [tuple(row[c] for c in COLUMNS) for row in rows]


def _store():
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


def test_no_duplicate_method_definitions_across_areas() -> None:
    seen: dict[str, str] = {}
    for cls in (
        D1HistoryStore, runs_module.RunStore, events_module.RunEventStore, mesh_module.MeshDispatchStore,
        history_entry.ConversationStore, history_entry.AccountStore,
        history_entry.ApprovalHandoffStore, core_module.StoreCore,
    ):
        for name in vars(cls):
            if name.startswith("__"):
                continue
            assert name not in seen, f"{name} defined in both {seen.get(name)} and {cls.__name__}"
            seen[name] = cls.__name__


def test_dependency_table() -> None:
    own = {name for name in vars(runs_module.RunStore) if not name.startswith("__")}
    assert own == H61_METHODS
    # StoreCore helpers/attributes the moved O methods use remain reachable.
    store = _store()
    for name in (
        "_first", "_run", "_all", "_dispatch", "_verified", "_put_full_message",
        "_delete_full_keys", "_delete_orphan_full_keys", "_read_full_message",
        "db", "run_ownership", "full_context_bucket", "mesh_command_output_max_bytes",
    ):
        assert hasattr(store, name), name
    # Cross-region calls stay on D1HistoryStore (later unpull targets).
    for name, area in (
        ("get_conversation", "ConversationStore(N)"),
        ("get_local_task_correlation", "RunEventStore(O H6-2)"),
    ):
        assert name not in vars(runs_module.RunStore), (name, area)
        assert hasattr(D1HistoryStore, name), (name, area)


def test_o_flow_before_after_same_rows_and_order(monkeypatch) -> None:
    monkeypatch.setattr(runs_module, "_now_iso", lambda: FIXED)
    store = _store()
    asyncio.run(store.record_claw_run(OWNER, "run-alpha", "chat", "txt", "첫 실행", "running"))
    assert _snapshot(store.db.conn) == [(
        OWNER, "run-alpha", "chat", "txt", "첫 실행", "running", FIXED, FIXED,
        None, None, None, None, None, None,
    )]
    asyncio.run(store.record_claw_run(OWNER, "run-alpha", "chat", "txt", "다시 기록", "waiting_approval"))
    assert _snapshot(store.db.conn) == [(
        OWNER, "run-alpha", "chat", "txt", "다시 기록", "waiting_approval", FIXED, FIXED,
        None, None, None, None, None, None,
    )]
    got = asyncio.run(store.get_claw_run(OWNER, "run-alpha"))
    got.pop("id", None)
    assert got == {
        "run_id": "run-alpha", "status": "waiting_approval", "result_summary": None,
        "conversation_id": None, "workspace_id": None, "updated_at": FIXED, "action": "txt",
    }
    assert asyncio.run(store.update_claw_run_status(OWNER, "run-alpha", "done", "요약")) is True
    assert _snapshot(store.db.conn) == [(
        OWNER, "run-alpha", "chat", "txt", "다시 기록", "done", FIXED, FIXED,
        "요약", None, None, None, None, None,
    )]
    assert asyncio.run(store.list_recent_claw_runs(OWNER)) == [{
        "run_id": "run-alpha", "channel": "chat", "action": "txt", "title": "다시 기록",
        "status": "done", "created_at": FIXED, "updated_at": FIXED,
        "result_summary": "요약", "artifact": None, "session": None,
    }]
    asyncio.run(store.record_claw_run(OWNER, "run-beta", "chat", "pc_command", "만료 대상", "waiting_approval"))
    store.db.conn.execute(
        "UPDATE claw_run_history SET created_at=?, updated_at=? WHERE run_id=?",
        (PAST, PAST, "run-beta"),
    )
    assert asyncio.run(store.expire_stale_confirmation_cards(
        OWNER, now=datetime(2099, 1, 1, tzinfo=timezone.utc))) == 1
    assert _snapshot(store.db.conn) == [
        (OWNER, "run-alpha", "chat", "txt", "다시 기록", "done", FIXED, FIXED,
         "요약", None, None, None, None, None),
        (OWNER, "run-beta", "chat", "pc_command", "만료 대상", "timed_out", PAST, FUTURE,
         None, None, None, None, None, None),
    ]


def test_record_claw_run_refreshes_updated_at_for_ttl(monkeypatch) -> None:
    # #7885 TTL reads updated_at: a replay must move it to now without touching created_at.
    monkeypatch.setattr(runs_module, "_now_iso", lambda: FIXED)
    store = _store()
    asyncio.run(store.record_claw_run(OWNER, "run-ttl", "chat", "txt", "처음", "running"))
    store.db.conn.execute(
        "UPDATE claw_run_history SET created_at=?, updated_at=? WHERE run_id=?",
        (PAST, PAST, "run-ttl"),
    )
    asyncio.run(store.record_claw_run(OWNER, "run-ttl", "chat", "txt", "재기록", "running"))
    row = store.db.conn.execute(
        "SELECT created_at, updated_at FROM claw_run_history WHERE run_id=?", ("run-ttl",)
    ).fetchone()
    assert row["created_at"] == PAST
    assert row["updated_at"] == FIXED
    assert row["updated_at"] != row["created_at"]


def test_history_and_new_module_line_caps() -> None:
    history_lines = len((APP / "history.py").read_text(encoding="utf-8").splitlines())
    runs_lines = len((APP / "history_store_runs.py").read_text(encoding="utf-8").splitlines())
    assert history_lines <= 1230, history_lines
    assert runs_lines < 1000, runs_lines
