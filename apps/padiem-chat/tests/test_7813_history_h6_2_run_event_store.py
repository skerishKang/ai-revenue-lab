"""T3 H6-2 회귀 — RunEventStore(O 나머지)가 이동 전과 같은 결과를 낸다 (#7813).

전후 비교는 이동 전 main(`043a3145`)의 `D1HistoryStore`로 같은 흐름을 돌려 얻은
행·순서를 고정값으로 두고 다시 실행한 값이 같은지 본다. 지역 sqlite만 쓴다.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import sqlite3
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import history as history_entry
from app import history_store_core as core_module
from app import history_store_run_events as events_module
from app import history_store_mesh as mesh_module
from app import history_store_runs as runs_module
from app.history import D1HistoryStore, HistoryError, PRODUCT_SCOPE_CHAT
from _support.history_public_names import PUBLIC_NAMES

APP = Path(__file__).resolve().parents[1] / "app"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

OWNER = "usr_" + "1" * 32
FIXED = "2026-11-17T00:00:00+00:00"
PAST = "2020-01-01T00:00:00+00:00"

H62_METHODS = {
    "append_command_result", "seal_run_terminal", "append_local_task_result",
    "append_step_result_message", "record_local_task_correlation",
    "get_local_task_correlation",
}

CORR = {
    "command_id": "cmd-1", "tool_request_ref": "tool-1", "request_id": "req-1",
    "revision_ref": "rev-1", "evidence_ref": None, "request_fingerprint": "fp-1",
}


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
        rows = [dict(row) for row in cursor.fetchall()]
        return SimpleNamespace(
            results=rows or None,
            meta={"changes": cursor.rowcount, "rows_written": cursor.rowcount},
        )


class _D1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        for name in (
            "001_auth_history.sql", "002_projects.sql", "009_claw_run_history.sql",
            "014_claw_run_history_conversation.sql", "015_claw_run_history_workspace.sql",
            "020_claw_local_task_correlation.sql", "042_conversation_product_scope.sql",
        ):
            self.conn.executescript((MIGRATIONS / name).read_text(encoding="utf8"))
        self.conn.execute(
            "INSERT INTO users(id,auth_provider,provider_subject,email,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (OWNER, "google", OWNER, OWNER + "@example.com", "2026-01-01", "2026-01-01"),
        )

    def prepare(self, sql):
        return _Statement(self.conn, sql)

    async def batch(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self.conn.execute(statement.sql, statement.params)
                rows = [dict(row) for row in cursor.fetchall()]
                results.append(SimpleNamespace(
                    results=rows or None,
                    meta={"changes": cursor.rowcount, "rows_written": cursor.rowcount},
                ))
            self.conn.execute("COMMIT")
            return results
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


def _store():
    return D1HistoryStore(_D1())


def _run_snapshot(db):
    rows = db.execute(
        "SELECT run_id,status,result_summary,created_at,updated_at FROM claw_run_history ORDER BY run_id"
    ).fetchall()
    return [tuple(row) for row in rows]


def _corr_snapshot(db):
    rows = db.execute(
        "SELECT user_id,run_id,command_id,tool_request_ref,request_id,revision_ref,evidence_ref,request_fingerprint "
        "FROM claw_local_task_correlation ORDER BY run_id"
    ).fetchall()
    return [tuple(row) for row in rows]


def test_public_method_names_are_unchanged() -> None:
    assert {name for name in dir(D1HistoryStore) if not name.startswith("_")} == PUBLIC_NAMES


def test_mro_is_fixed() -> None:
    assert [c.__name__ for c in D1HistoryStore.__mro__] == [
        "D1HistoryStore", "RunStore", "RunEventStore", "MeshDispatchStore", "ConversationStore", "AccountStore",
        "ApprovalHandoffStore", "StoreCore", "object",
    ]
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


def test_dependency_table_and_choice_rationale() -> None:
    own = {name for name in vars(events_module.RunEventStore) if not name.startswith("__")}
    assert own == H62_METHODS
    store = _store()
    for name in (
        "_first", "_run", "_all", "_dispatch", "_first", "db",
    ):
        assert hasattr(store, name), name
    # H6-2가 H6-1을 부르지 않는다(의존은 한 방향). 반대 방향은 조합으로 해결.
    assert not any(
        isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == "self" and node.attr in set(vars(runs_module.RunStore))
        for method in (events_module.RunEventStore.__dict__[n] for n in H62_METHODS)
        for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(method))))
    )
    for name in ("get_local_task_correlation", "append_command_result"):
        assert name in vars(events_module.RunEventStore)
        assert hasattr(D1HistoryStore, name)


def test_o_remainder_before_after_same_rows_and_order(monkeypatch) -> None:
    monkeypatch.setattr(events_module, "_now_iso", lambda: FIXED)
    monkeypatch.setattr(runs_module, "_now_iso", lambda: FIXED)
    store = _store()
    cid = asyncio.run(store.append_exchange(
        OWNER, None, "견적", "본문", product_scope=PRODUCT_SCOPE_CHAT))
    asyncio.run(store.record_claw_run(
        OWNER, "run-ev", "chat", "desktop_task", "실행", "running", conversation_id=cid))
    assert asyncio.run(store.record_local_task_correlation(
        user_id=OWNER, run_id="run-ev", command_id="cmd-1", tool_request_ref="tool-1",
        request_id="req-1", revision_ref="rev-1", request_fingerprint="fp-1")) is True
    assert asyncio.run(store.get_local_task_correlation(OWNER, "run-ev")) == CORR
    assert asyncio.run(store.record_local_task_correlation(
        user_id=OWNER, run_id="run-ev", command_id="cmd-1", tool_request_ref="tool-1",
        request_id="req-1", revision_ref="rev-1", request_fingerprint="fp-1")) is False
    assert asyncio.run(store.record_local_task_correlation(
        user_id=OWNER, run_id="run-ev", command_id="cmd-1", tool_request_ref="tool-1",
        request_id="req-1", revision_ref="rev-1", request_fingerprint="fp-1",
        evidence_ref="ev-1")) is True
    assert asyncio.run(store.get_local_task_correlation(OWNER, "run-ev")) == {
        **CORR, "evidence_ref": "ev-1",
    }
    with pytest.raises(HistoryError, match="already bound to a different command"):
        asyncio.run(store.record_local_task_correlation(
            user_id=OWNER, run_id="run-ev", command_id="cmd-other", tool_request_ref="t2",
            request_id="r2", revision_ref="v2", request_fingerprint="f2"))
    store.db.conn.execute(
        "UPDATE claw_run_history SET updated_at=? WHERE run_id=?", (PAST, "run-ev"))
    assert asyncio.run(store.seal_run_terminal(
        user_id=OWNER, run_id="run-ev", summary="실패 요약", status="failed")) is True
    assert asyncio.run(store.seal_run_terminal(
        user_id=OWNER, run_id="run-ev", summary="다시", status="failed")) is True
    assert _run_snapshot(store.db.conn) == [
        ("run-ev", "failed", "실패 요약", FIXED, FIXED),
    ]
    assert _corr_snapshot(store.db.conn) == [(
        OWNER, "run-ev", "cmd-1", "tool-1", "req-1", "rev-1", "ev-1", "fp-1",
    )]
    assert [row[0] for row in store.db.conn.execute(
        "SELECT content FROM messages ORDER BY content").fetchall()] == ["견적", "본문"]


def test_seal_refreshes_updated_at_for_ttl(monkeypatch) -> None:
    monkeypatch.setattr(events_module, "_now_iso", lambda: FIXED)
    monkeypatch.setattr(runs_module, "_now_iso", lambda: FIXED)
    store = _store()
    cid = asyncio.run(store.append_exchange(
        OWNER, None, "견적", "본문", product_scope=PRODUCT_SCOPE_CHAT))
    asyncio.run(store.record_claw_run(
        OWNER, "run-ttl", "chat", "desktop_task", "실행", "running", conversation_id=cid))
    store.db.conn.execute(
        "UPDATE claw_run_history SET created_at=?, updated_at=? WHERE run_id=?",
        (PAST, PAST, "run-ttl"))
    asyncio.run(store.seal_run_terminal(
        user_id=OWNER, run_id="run-ttl", summary="끝", status="failed"))
    row = store.db.conn.execute(
        "SELECT created_at, updated_at FROM claw_run_history WHERE run_id=?", ("run-ttl",)
    ).fetchone()
    assert row["created_at"] == PAST
    assert row["updated_at"] == FIXED
    assert row["updated_at"] != row["created_at"]


def test_file_size_caps() -> None:
    history_lines = len((APP / "history.py").read_text(encoding="utf-8").splitlines())
    runs_lines = len((APP / "history_store_runs.py").read_text(encoding="utf-8").splitlines())
    events_lines = len((APP / "history_store_run_events.py").read_text(encoding="utf-8").splitlines())
    assert history_lines <= 1230, history_lines
    assert runs_lines < 1000, runs_lines
    assert events_lines < 1000, events_lines
