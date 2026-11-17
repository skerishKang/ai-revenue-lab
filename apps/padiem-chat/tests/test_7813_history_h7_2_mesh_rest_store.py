"""T3 H7-2 회귀 — MeshDispatchStore 나머지(P)가 이동 전과 같은 결과를 낸다 (#7813).

전후 비교는 이동 전 main(`153bfdea`)의 `D1HistoryStore`로 같은 흐름을 돌려 얻은
행·순서를 고정값으로 둔 것이다. `test_4139_mesh_original`의 sqlite/R2 시험
도구를 재사용한다.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import pathlib
import sqlite3
import textwrap
from types import SimpleNamespace

from app import history as history_entry
from app import history_store_core as core_module
from app import history_store_mesh as mesh_module
from app.history import D1HistoryStore
from test_4139_mesh_original import CONVERSATION, MIGRATIONS, OWNER, PrivateR2, _dispatch_kwargs
from test_7813_history_h4_store_core import PUBLIC_NAMES

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

H72_METHODS = {
    "oracle_mesh_lane_status", "consume_oracle_mesh_dispatch",
    "record_oracle_mesh_first_result", "mark_oracle_mesh_store_failed",
    "finish_oracle_mesh_dispatch", "store_oracle_mesh_original",
    "store_oracle_mesh_command_result", "store_oracle_mesh_original_bytes",
    "read_oracle_mesh_original", "get_oracle_mesh_dispatch_for_owner",
}

RAW = "A" * 20000
DIGEST = hashlib.sha256(RAW.encode()).hexdigest()
NONCE = "n" * 64
NONCE_SHA = hashlib.sha256(NONCE.encode()).hexdigest()
MSG_ID = "msg_" + "a" * 32
KEY = f"claw-model-context/v1/{CONVERSATION}/{MSG_ID}.utf8"


class _Statement:
    def __init__(self, path, sql):
        self.path, self.sql, self.values = path, sql, ()

    def bind(self, *values):
        self.values = values
        return self

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def first(self):
        conn = self._conn()
        try:
            row = conn.execute(self.sql, self.values).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    async def run(self):
        conn = self._conn()
        try:
            cursor = conn.execute(self.sql, self.values)
            conn.commit()
            return {"results": [dict(row) for row in cursor.fetchall()],
                    "meta": {"changes": cursor.rowcount}}
        finally:
            conn.close()


class _D1:
    def __init__(self, path):
        conn = sqlite3.connect(path)
        for migration in MIGRATIONS:
            conn.executescript(migration.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        self.path = path

    def prepare(self, sql):
        return _Statement(self.path, sql)

    async def batch(self, statements):
        return [await statement.run() for statement in statements]


def _store_and_bucket(tmp_path):
    bucket = PrivateR2()
    store = D1HistoryStore(_D1(str(tmp_path / "d1.sqlite3")), full_context_bucket=bucket)
    return store, bucket


def _snapshot(store):
    conn = sqlite3.connect(store.db.path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT state,result_sha256,result_bytes FROM oracle_mesh_dispatch").fetchall()
    conn.close()
    return [tuple(row) for row in rows]


def test_public_method_names_are_unchanged() -> None:
    assert {name for name in dir(D1HistoryStore) if not name.startswith("_")} == PUBLIC_NAMES
    assert D1HistoryStore.LANE_STATUS_NODE_LIMIT == mesh_module.MeshDispatchStore.LANE_STATUS_NODE_LIMIT


def test_mro_and_no_duplicate_definitions() -> None:
    assert [c.__name__ for c in D1HistoryStore.__mro__] == [
        "D1HistoryStore", "RunStore", "RunEventStore", "MeshDispatchStore",
        "ConversationStore", "AccountStore", "ApprovalHandoffStore", "StoreCore", "object",
    ]
    seen: dict[str, str] = {}
    for cls in (
        D1HistoryStore, mesh_module.MeshDispatchStore, core_module.StoreCore,
        history_entry.RunStore, history_entry.RunEventStore,
        history_entry.ConversationStore, history_entry.AccountStore,
        history_entry.ApprovalHandoffStore,
    ):
        for name in vars(cls):
            if name.startswith("__"):
                continue
            assert name not in seen, f"{name} defined in both {seen.get(name)} and {cls.__name__}"
            seen[name] = cls.__name__


def test_dependency_table_and_single_module_choice() -> None:
    own = {name for name in vars(mesh_module.MeshDispatchStore) if not name.startswith("__")}
    assert H72_METHODS <= own
    # P2는 같은 모듈에 합쳐졌고 남은 history.py의 L 잔여물만 조합으로 부른다.
    for method_name in H72_METHODS:
        source = textwrap.dedent(inspect.getsource(mesh_module.MeshDispatchStore.__dict__[method_name]))
        assert "self." in source or method_name == "oracle_mesh_lane_status"
    assert hasattr(D1HistoryStore, "_mesh_dispatch_pin")
    mesh_lines = len((APP / "history_store_mesh.py").read_text(encoding="utf-8").splitlines())
    assert mesh_lines < 1000, mesh_lines


def test_p_second_bundle_before_after_same_rows_and_order(tmp_path) -> None:
    store, bucket = _store_and_bucket(tmp_path)
    asyncio.run(store.record_claw_run(
        OWNER, "run-h72", "web", "txt_read", "probe", "pending",
        conversation_id=CONVERSATION))
    did = asyncio.run(store.create_oracle_mesh_dispatch(**_dispatch_kwargs(run_id="run-h72")))["dispatch_id"]

    lane = asyncio.run(store.oracle_mesh_lane_status())
    assert lane["unclaimed"]["count"] == 1 and lane["claimed"]["count"] == 0
    assert lane["nodes"][0]["node_ref"] == "node"
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=did, nonce_sha256=NONCE_SHA)) is True
    lane = asyncio.run(store.oracle_mesh_lane_status())
    assert lane["unclaimed"]["count"] == 0 and lane["claimed"]["count"] == 1

    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=did, content_sha256=DIGEST, content_bytes=len(RAW.encode()),
        termination="0")) is True
    assert _snapshot(store) == [("pending", DIGEST, len(RAW.encode()))]
    key = asyncio.run(store.store_oracle_mesh_original(
        user_id=OWNER, dispatch_id=did, conversation_id=CONVERSATION,
        message_id=MSG_ID, raw=RAW, expected_sha256=DIGEST,
        expected_bytes=len(RAW.encode())))
    assert key == KEY
    assert sorted(bucket.objects.keys()) == [KEY]
    assert asyncio.run(store.read_oracle_mesh_original(
        user_id=OWNER, dispatch_id=did, conversation_id=CONVERSATION,
        message_id=MSG_ID)) != RAW  # pinned original without a preview row: no fabricated full text
    assert asyncio.run(store.get_oracle_mesh_dispatch_for_owner(
        user_id=OWNER, dispatch_id=did))["dispatch_id"] == did
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=did, nonce=NONCE))["dispatch_id"] == did
    assert asyncio.run(store.finish_oracle_mesh_dispatch(
        dispatch_id=did, outcome="done")) is True
    assert _snapshot(store) == [("done", DIGEST, len(RAW.encode()))]


def test_finish_terminal_state_is_the_outcome(monkeypatch, tmp_path) -> None:
    store, _bucket = _store_and_bucket(tmp_path)
    asyncio.run(store.record_claw_run(
        OWNER, "run-term", "web", "txt_read", "probe", "pending",
        conversation_id=CONVERSATION))
    did = asyncio.run(store.create_oracle_mesh_dispatch(**_dispatch_kwargs(run_id="run-term")))["dispatch_id"]
    asyncio.run(store.claim_oracle_mesh_dispatch(dispatch_id=did, nonce_sha256=NONCE_SHA))
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=did, nonce=NONCE))["dispatch_id"] == did
    assert asyncio.run(store.finish_oracle_mesh_dispatch(
        dispatch_id=did, outcome="done")) is True
    assert _snapshot(store) == [("done", None, None)]


def test_file_size_caps() -> None:
    history_lines = len((APP / "history.py").read_text(encoding="utf-8").splitlines())
    assert history_lines <= 337, history_lines
