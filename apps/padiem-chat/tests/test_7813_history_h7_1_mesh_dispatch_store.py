"""T3 H7-1 회귀 — MeshDispatchStore(P 첫 묶음)가 이동 전과 같은 결과를 낸다 (#7813).

전후 비교는 이동 전 main(`be48cb24`)의 `D1HistoryStore`로 같은 흐름을 돌려 얻은
행·순서를 고정값으로 둔 것이다. 지역 sqlite만 쓴다.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import pathlib
import sqlite3
import textwrap
from types import SimpleNamespace

import pytest

from app import history as history_entry
from app import history_store_core as core_module
from app import history_store_mesh as mesh_module
from app import history_store_run_events as events_module
from app import history_store_runs as runs_module
from app.history import D1HistoryStore
from test_7813_history_h4_store_core import PUBLIC_NAMES

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations"

OWNER = "usr_" + "1" * 32
FUTURE = "2099-01-01T00:00:00+00:00"

H71_METHODS = {
    "create_oracle_mesh_dispatch", "oldest_pending_oracle_mesh_dispatch",
    "settle_unredeliverable_oracle_mesh_claims", "claim_oracle_mesh_dispatch",
    "renew_oracle_mesh_claim", "cancel_oracle_mesh_dispatches_for_run",
    "oracle_mesh_dispatch_cancellation", "oracle_mesh_node_live_claims",
}

MIGRATION_FILES = (
    "001_auth_history.sql", "002_projects.sql", "009_claw_run_history.sql",
    "014_claw_run_history_conversation.sql", "015_claw_run_history_workspace.sql",
    "020_claw_local_task_correlation.sql", "042_conversation_product_scope.sql",
    "047_oracle_mesh_dispatch.sql", "048_oracle_mesh_command.sql",
    "049_oracle_mesh_command_result_meta.sql", "063_oracle_mesh_dispatch_tool_call_scope.sql",
    "074_oracle_mesh_dispatch_claim_lease.sql", "102_oracle_mesh_dispatch_user_mode.sql",
    "112_oracle_mesh_dispatch_read_only.sql",
)

CREATE = dict(
    user_id=OWNER, run_id="run-mesh", command_id="cmd-m", tool_request_ref="tool-m",
    request_id="req-m", revision_ref="rev-m", evidence_ref=None, request_fingerprint="fp-m",
    account_ref="acct-m", workspace_ref="ws-m", device_id="dev-m", binding_ref=None,
    node_ref="node-m", root_ref="/root", path_relative="a.txt", file_path="/root/a.txt",
    expires_at=FUTURE,
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
        rows = [dict(row) for row in cursor.fetchall()]
        return SimpleNamespace(
            results=rows or None,
            meta={"changes": cursor.rowcount, "rows_written": cursor.rowcount},
        )


class _D1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        for name in MIGRATION_FILES:
            self.conn.executescript((MIGRATIONS / name).read_text(encoding="utf8"))

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


def _snapshot(db):
    rows = db.execute(
        "SELECT user_id,run_id,command_id,node_ref,state,expires_at FROM oracle_mesh_dispatch ORDER BY run_id"
    ).fetchall()
    return [tuple(row) for row in rows]


def test_public_method_names_are_unchanged() -> None:
    assert {name for name in dir(D1HistoryStore) if not name.startswith("_")} == PUBLIC_NAMES


def test_mro_is_fixed() -> None:
    assert [c.__name__ for c in D1HistoryStore.__mro__] == [
        "D1HistoryStore", "RunStore", "RunEventStore", "MeshDispatchStore",
        "ConversationStore", "AccountStore", "ApprovalHandoffStore", "StoreCore", "object",
    ]
    assert history_entry.MeshDispatchStore is mesh_module.MeshDispatchStore


def test_no_duplicate_method_definitions_across_areas() -> None:
    seen: dict[str, str] = {}
    for cls in (
        D1HistoryStore, runs_module.RunStore, events_module.RunEventStore,
        mesh_module.MeshDispatchStore, history_entry.ConversationStore,
        history_entry.AccountStore, history_entry.ApprovalHandoffStore, core_module.StoreCore,
    ):
        for name in vars(cls):
            if name.startswith("__"):
                continue
            assert name not in seen, f"{name} defined in both {seen.get(name)} and {cls.__name__}"
            seen[name] = cls.__name__


def test_dependency_table() -> None:
    own = {name for name in vars(mesh_module.MeshDispatchStore) if not name.startswith("__")}
    assert H71_METHODS <= own  # H7-2에서 같은 모듈에 나머지 10개가 합쳐졌다
    assert len(own) == 19  # 18개 메서드 + LANE_STATUS_NODE_LIMIT
    store = _store()
    for name in ("_first", "_run", "_all", "_dispatch", "db"):
        assert hasattr(store, name), name
    # P1은 P2 메서드를 부르지 않는다. 예전 L 잔여물 _run_is_owned은 조합으로 해결.
    p2 = {name for name in vars(D1HistoryStore) if name.startswith("oracle_mesh_lane_status") or name.startswith("consume_oracle_mesh") or name.startswith("store_oracle_mesh") or name.startswith("read_oracle_mesh")}
    for method_name in H71_METHODS:
        source = textwrap.dedent(inspect.getsource(mesh_module.MeshDispatchStore.__dict__[method_name]))
        called = {node.attr for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                  and node.value.id == "self"}
        assert not (called & p2), (method_name, called & p2)
    assert hasattr(D1HistoryStore, "_run_is_owned")


def test_p_first_bundle_before_after_same_rows_and_order() -> None:
    store = _store()
    asyncio.run(store.record_claw_run(
        OWNER, "run-mesh", "chat", "pc_browser_query", "실행", "running"))
    created = asyncio.run(store.create_oracle_mesh_dispatch(**CREATE))
    assert created["dispatch_id"].startswith("dsp_")
    assert (created["kind"], created["command_id"], created["node_ref"],
            created["state"], created["expires_at"]) == (
        "read", "cmd-m", "node-m", "pending", FUTURE)
    assert _snapshot(store.db.conn) == [(
        OWNER, "run-mesh", "cmd-m", "node-m", "pending", FUTURE,
    )]
    oldest = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert oldest["dispatch_id"] == created["dispatch_id"]
    did = created["dispatch_id"]
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=did, nonce_sha256="n" * 64)) is True
    claimed = store.db.conn.execute(
        "SELECT claimed_until FROM oracle_mesh_dispatch WHERE dispatch_id=?", (did,)
    ).fetchone()[0]
    assert claimed is not None
    renewed = asyncio.run(store.renew_oracle_mesh_claim(
        dispatch_id=did, nonce_sha256="n" * 64))
    assert renewed and renewed.endswith("Z")
    assert store.db.conn.execute(
        "SELECT claimed_until FROM oracle_mesh_dispatch WHERE dispatch_id=?", (did,)
    ).fetchone()[0] == renewed
    assert asyncio.run(store.oracle_mesh_node_live_claims(node_ref="node-m")) == 1
    assert asyncio.run(store.cancel_oracle_mesh_dispatches_for_run(
        user_id=OWNER, run_id="run-mesh")) == 1
    assert asyncio.run(store.oracle_mesh_dispatch_cancellation(dispatch_id=did)) is True
    assert asyncio.run(store.settle_unredeliverable_oracle_mesh_claims()) == 0
    assert _snapshot(store.db.conn) == [(
        OWNER, "run-mesh", "cmd-m", "node-m", "pending", FUTURE,
    )]


def test_file_size_caps() -> None:
    history_lines = len((APP / "history.py").read_text(encoding="utf-8").splitlines())
    mesh_lines = len((APP / "history_store_mesh.py").read_text(encoding="utf-8").splitlines())
    assert history_lines <= 337, history_lines  # 실측 237 + 100
    assert mesh_lines < 1000, mesh_lines
