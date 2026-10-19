"""#3936: physical-Engine-free, cross-connection approval claim CAS proof.

Each contender gets an independent SQLite connection, as separate D1 Workers
would. A shared Python lock or one SQLite connection would not prove the
storage-owned winner election. No provider/Production calls are made.
"""
from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

from app.history import D1HistoryStore, HistoryConflict

ROOT = Path(__file__).resolve().parents[1]
OWNER = "usr_" + "7" * 32
OTHER = "usr_" + "8" * 32
RUN = "run_3936_atomic_decision"
WORKSPACE = "tenant_test"
REF = "cont_real_engine_ref"
PAUSE = "pause_real_engine_ref"
FINGERPRINT = "a" * 64


class _Stmt:
    def __init__(self, conn, sql, args=()):
        self.conn, self.sql, self.args = conn, sql, args

    def bind(self, *values):
        return _Stmt(self.conn, self.sql, values)

    async def first(self):
        result = self.conn.execute(self.sql, self.args).fetchone()
        return dict(result) if result is not None else None

    async def run(self):
        cursor = self.conn.execute(self.sql, self.args)
        return {"results": [dict(r) for r in cursor.fetchall()]}


class _D1:
    def __init__(self, conn):
        self.conn = conn

    def prepare(self, sql):
        return _Stmt(self.conn, sql)


def _connect(path):
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _seed(path):
    conn = _connect(path)
    try:
        conn.executescript((ROOT / "migrations/016_claw_approval_handoff.sql").read_text())
        conn.executescript((ROOT / "migrations/017_claw_approval_handoff_consumption.sql").read_text())
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO claw_approval_handoff "
            "(id,user_id,run_id,workspace_id,conversation_id,continuation_ref,"
            "pause_id,pause_expires_at,trusted_request_json,trusted_request_fingerprint,"
            "created_at,p01_run_id,consumed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            ("handoff_test", OWNER, RUN, WORKSPACE, None, REF, PAUSE,
             "2099-01-01T00:00:00+00:00", "{}", FINGERPRINT,
             "2026-10-14T00:00:00+00:00", "orch_test"),
        )
    finally:
        conn.close()


def _claim(path, barrier=None, owner=OWNER, workspace=WORKSPACE,
           ref=REF, pause=PAUSE, fingerprint=FINGERPRINT):
    conn = _connect(path)
    try:
        if barrier is not None:
            barrier.wait(timeout=10)
        return asyncio.run(D1HistoryStore(_D1(conn)).claim_claw_approval_handoff(
            user_id=owner, run_id=RUN, workspace_id=workspace,
            continuation_ref=ref, pause_id=pause,
            trusted_request_fingerprint=fingerprint,
        ))
    finally:
        conn.close()


def test_one_atomic_claim_across_independent_d1_connections():
    with TemporaryDirectory(prefix="claw_3936_") as directory:
        path = str(Path(directory) / "handoff.sqlite")
        _seed(path)
        for _ in range(8):
            conn = _connect(path)
            try:
                conn.execute("UPDATE claw_approval_handoff SET consumed_at=NULL WHERE id='handoff_test'")
            finally:
                conn.close()
            barrier = Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: _claim(path, barrier), range(2)))
            winner = [value for value in outcomes if isinstance(value, str)]
            assert len(winner) == 1
            assert winner[0].startswith("decision_claim:")
            assert outcomes.count(None) == 1
            assert _claim(path) is None


def test_claim_scoped_and_stale_release_cannot_reopen_after_final():
    with TemporaryDirectory(prefix="claw_3936_") as directory:
        path = str(Path(directory) / "handoff.sqlite")
        _seed(path)
        for override in (
            {"owner": OTHER},
            {"workspace": "tenant_other"},
            {"ref": "cont_other"},
            {"pause": "pause_other"},
            {"fingerprint": "b" * 64},
        ):
            assert _claim(path, **override) is None
        token = _claim(path)
        assert token
        conn = _connect(path)
        try:
            store = D1HistoryStore(_D1(conn))
            async def exercise():
                assert not await store.release_claw_approval_claim(
                    user_id=OWNER, run_id=RUN, workspace_id=WORKSPACE,
                    claim_token="decision_claim:stale",
                )
                assert await store.finalize_claw_approval_claim(
                    user_id=OWNER, run_id=RUN, workspace_id=WORKSPACE,
                    claim_token=token,
                )
                assert not await store.release_claw_approval_claim(
                    user_id=OWNER, run_id=RUN, workspace_id=WORKSPACE,
                    claim_token=token,
                )
                assert not await store.finalize_claw_approval_claim(
                    user_id=OWNER, run_id=RUN, workspace_id=WORKSPACE,
                    claim_token=token,
                )
            asyncio.run(exercise())
            assert _claim(path) is None
        finally:
            conn.close()


def test_only_verified_not_dispatched_release_reopens_original_pause():
    with TemporaryDirectory(prefix="claw_3936_") as directory:
        path = str(Path(directory) / "handoff.sqlite")
        _seed(path)
        token = _claim(path)
        assert token
        conn = _connect(path)
        try:
            store = D1HistoryStore(_D1(conn))
            assert asyncio.run(store.release_claw_approval_claim(
                user_id=OWNER, run_id=RUN, workspace_id=WORKSPACE,
                claim_token=token,
            ))
            assert _claim(path) is not None
        finally:
            conn.close()


def test_expired_pause_is_rejected_at_atomic_claim_boundary():
    with TemporaryDirectory(prefix="claw_3936_") as directory:
        path = str(Path(directory) / "handoff.sqlite")
        _seed(path)
        conn = _connect(path)
        try:
            conn.execute(
                "UPDATE claw_approval_handoff SET pause_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", "handoff_test"),
            )
        finally:
            conn.close()
        assert _claim(path) is None
