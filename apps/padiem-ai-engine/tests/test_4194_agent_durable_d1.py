"""#4194: Engine D1 lease and trusted Agent/Skill execution integration tests.

Uses real SQLite SQL/migration with a D1-shaped async adapter; no network or
Cloudflare deployment. Existing Agent authority fixture is preserved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import sqlite3

import pytest

from app.agent_durable_d1 import D1AgentRunLedger
from padiem_ai_core.agent_durable_lease import AgentDurableLeaseError
from tests.test_agent_skill_service import Fixture, APP_ID, SUBJECT_ID
from tests.test_agent_skill_continuation import ContinuationFixture, _pause, APP_ID as CONT_APP

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "0011_engine_agent_durable_runs.sql"
FP = "a" * 64


class D1Statement:
    def __init__(self, db, sql, *, lie=False):
        self.db, self.sql, self.args, self.lie = db, sql, (), lie

    def bind(self, *args):
        self.args = args
        return self

    async def first(self):
        row = self.db.execute(self.sql, self.args).fetchone()
        return dict(row) if row else None

    async def run(self):
        cur = self.db.execute(self.sql, self.args)
        if self.lie:
            return {"success": False, "meta": {"changes": 1}}
        return {"success": True, "meta": {"changes": cur.rowcount}}


class SQLiteD1:
    def __init__(self, db, *, lie=False):
        self.db, self.lie = db, lie

    def prepare(self, sql):
        return D1Statement(self.db, sql, lie=self.lie)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def sql(tmp_path):
    path = tmp_path / "engine-d1.sqlite"
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    yield db, path
    db.close()


async def test_d1_run_persists_across_adapter_recreation_and_fences_others(sql):
    db, _ = sql
    clock = Clock()
    one = D1AgentRunLedger(SQLiteD1(db), clock=clock)
    lease = await one.start(run_id="run-a", owner_scope="ownerA", request_fingerprint=FP,
                            worker_id="host1", lease_seconds=60)
    assert await one.is_active(lease)
    with pytest.raises(AgentDurableLeaseError):
        await one.start(run_id="run-a", owner_scope="ownerB", request_fingerprint=FP,
                        worker_id="host2")
    two = D1AgentRunLedger(SQLiteD1(db), clock=clock)
    assert await two.is_active(lease)
    assert await two.status(run_id="run-a", owner_scope="ownerB", request_fingerprint=FP) is None
    assert await two.status(run_id="run-a", owner_scope="ownerA", request_fingerprint="b"*64) is None
    assert await two.begin_execution(lease)
    assert not await two.pause_before_work(lease)
    assert await two.checkpoint(lease, completed_step=1)
    assert not await two.checkpoint(lease, completed_step=0)
    clock.tick(59)
    assert await two.heartbeat(lease, lease_seconds=60)
    clock.tick(60)
    assert not await two.is_active(lease)
    assert not await two.finish(lease, state="completed")
    await two.quarantine_expired()
    assert await one.status(run_id="run-a", owner_scope="ownerA", request_fingerprint=FP) == ("needs_review", 2, 1)


async def test_d1_prework_fresh_epoch_and_cancel_revokes_worker(sql):
    db, _ = sql
    ledger = D1AgentRunLedger(SQLiteD1(db), clock=Clock())
    old = await ledger.start(run_id="r-1", owner_scope="owner", request_fingerprint=FP, worker_id="w1")
    assert await ledger.pause_before_work(old)
    new = await ledger.resume_prework(run_id="r-1", owner_scope="owner",
                                      request_fingerprint=FP, worker_id="w2")
    assert new is not None and new.epoch == 3
    assert not await ledger.is_active(old)
    assert not await ledger.resume_prework(run_id="r-1", owner_scope="owner",
                                             request_fingerprint=FP, worker_id="w3")
    assert not await ledger.cancel(run_id="r-1", owner_scope="intruder", request_fingerprint=FP)
    assert await ledger.cancel(run_id="r-1", owner_scope="owner", request_fingerprint=FP)
    assert not await ledger.begin_execution(new)


async def test_migration_missing_is_a_safe_failure_not_hidden_mock(sql):
    db, _ = sql
    db.execute("DROP TABLE padiem_engine_agent_runs_v1")
    ledger = D1AgentRunLedger(SQLiteD1(db))
    with pytest.raises(AgentDurableLeaseError, match="unavailable"):
        await ledger.start(run_id="id-1", owner_scope="owner", request_fingerprint=FP,
                           worker_id="host")


async def test_d1_failure_status_with_forged_changes_is_rejected(sql):
    db, _ = sql
    ledger = D1AgentRunLedger(SQLiteD1(db, lie=True))
    with pytest.raises(AgentDurableLeaseError):
        await ledger.start(run_id="r", owner_scope="owner", request_fingerprint=FP,
                           worker_id="host")


async def test_engine_real_agent_skill_with_d1_guard_stores_terminal_no_private_data(sql):
    db, _ = sql
    fx = Fixture()
    fx.service._agent_run_ledger = D1AgentRunLedger(SQLiteD1(db))
    response = await fx.service.run_payload(fx.payload())
    assert response.status_code == 200, response.body
    assert response.body["agent_skill"]["run_status"] == "completed"
    assert fx.handler_calls == 1
    assert fx.provider.calls == 0
    rows = db.execute("SELECT * FROM padiem_engine_agent_runs_v1").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["status"] == "completed"
    assert row["side_effect_uncertain"] == 1
    assert row["checkpoint_step"] == 1  # post-tool monotonic D1 progress persisted
    assert row["epoch"] == 2
    assert row["owner_scope"] == "scope_" + hashlib.sha256(
        (APP_ID + ":" + SUBJECT_ID).encode("utf-8")
    ).hexdigest()
    assert row["request_fingerprint"] != FP
    joined = " ".join(str(v) for v in row.values())
    assert "PRIVATE-TOOL-ARGUMENT" not in joined
    assert "PRIVATE-TOOL-OUTPUT" not in joined
    assert "sk-test-secret" not in joined


async def test_engine_missing_schema_fails_before_tool_dispatch(sql):
    db, _ = sql
    db.execute("DROP TABLE padiem_engine_agent_runs_v1")
    fx = Fixture()
    fx.service._agent_run_ledger = D1AgentRunLedger(SQLiteD1(db))
    response = await fx.service.run_payload(fx.payload())
    assert response.status_code == 503, response.body
    assert response.body["error"]["code"] == "agent_run_lease_unavailable"
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0


def test_worker_identity_source_feature_gate_is_off_by_default():
    # Pyodide worker_identity imports js/workers and cannot run under CPython.
    # Check its fail-closed composition contract here; real Worker probes in CI.
    source = (Path(__file__).resolve().parents[1] / "worker_identity.py").read_text(
        encoding="utf-8"
    )
    assert 'PADIEM_ENGINE_AGENT_DURABLE_ENABLED' in source
    assert '== "true"' in source
    assert "db = legacy_worker._binding_value(env, ENGINE_CONTINUATION_BINDING_NAME)" in source
    assert "agent_run_ledger = D1AgentRunLedger(db)" in source
    assert "agent_run_ledger=agent_run_ledger" in source
    assert '"agent_run_lease_unavailable"' in source

async def test_live_agent_approval_resume_uses_fresh_d1_epoch_and_one_tool(sql):
    db, _ = sql
    fx = ContinuationFixture()
    ledger = D1AgentRunLedger(SQLiteD1(db))
    fx.service._agent_run_ledger = ledger
    fx.service._continuation._agent_run_ledger = ledger

    ref, pause_id = await _pause(fx)
    first = db.execute(
        "SELECT run_id,status,epoch,checkpoint_step FROM padiem_engine_agent_runs_v1"
    ).fetchone()
    assert first["run_id"].startswith("arun_")
    assert (first["status"], first["epoch"], first["checkpoint_step"]) == ("awaiting_approval", 2, 0)
    stored = fx.store.resolve(app_id=CONT_APP, continuation_ref=ref)
    assert stored.pause.run_id == first["run_id"]

    fx.approve_pause_tool()
    response = await fx.service.resume_payload(
        fx.payload(continuation_ref=ref, decision=fx.decision(pause_id))
    )
    assert response.status_code == 200, response.body
    assert response.body["agent_skill"]["run_status"] == "completed"
    assert fx.handler_calls == 1 and fx.provider.calls == 0
    second = db.execute(
        "SELECT status,epoch,checkpoint_step,side_effect_uncertain FROM padiem_engine_agent_runs_v1"
    ).fetchone()
    assert (second["status"], second["epoch"], second["checkpoint_step"],
            second["side_effect_uncertain"]) == ("completed", 4, 1, 1)
    replay = await fx.service.resume_payload(
        fx.payload(continuation_ref=ref, decision=fx.decision(pause_id))
    )
    assert replay.status_code == 409
    assert fx.handler_calls == 1


async def test_live_agent_pause_cancel_revokes_d1_without_dispatch(sql):
    db, _ = sql
    fx = ContinuationFixture()
    ledger = D1AgentRunLedger(SQLiteD1(db))
    fx.service._agent_run_ledger = ledger
    fx.service._continuation._agent_run_ledger = ledger
    ref, pause_id = await _pause(fx)
    run_id = fx.store.resolve(app_id=CONT_APP, continuation_ref=ref).pause.run_id

    response = await fx.service.cancel_payload(
        {"app_id": CONT_APP, "continuation_ref": ref, "reason": "user_cancelled"}
    )
    assert response.status_code == 200, response.body
    row = db.execute(
        "SELECT status,epoch,checkpoint_step FROM padiem_engine_agent_runs_v1 "
        "WHERE run_id=?", (run_id,)
    ).fetchone()
    assert (row["status"], row["epoch"], row["checkpoint_step"]) == ("cancelled", 3, 0)
    assert fx.handler_calls == 0 and fx.provider.calls == 0
    fx.approve_pause_tool()
    resumed = await fx.service.resume_payload(
        fx.payload(continuation_ref=ref, decision=fx.decision(pause_id))
    )
    assert resumed.status_code == 409
    assert fx.handler_calls == 0


async def test_missing_d1_lease_cannot_falsely_finish_approval_cancel(sql):
    db, _ = sql
    fx = ContinuationFixture()
    ledger = D1AgentRunLedger(SQLiteD1(db))
    fx.service._agent_run_ledger = ledger
    fx.service._continuation._agent_run_ledger = ledger
    ref, _ = await _pause(fx)
    db.execute("DELETE FROM padiem_engine_agent_runs_v1")

    cancelled = await fx.service.cancel_payload(
        {"app_id": CONT_APP, "continuation_ref": ref, "reason": "user_cancelled"}
    )
    assert cancelled.status_code == 503
    assert cancelled.body["error"]["code"] == "agent_run_lease_unavailable"
    assert fx.store.resolve(app_id=CONT_APP, continuation_ref=ref).state == "active"
    assert fx.handler_calls == 0


async def test_approved_resume_without_d1_record_fails_before_tool(sql):
    db, _ = sql
    fx = ContinuationFixture()
    ledger = D1AgentRunLedger(SQLiteD1(db))
    fx.service._agent_run_ledger = ledger
    fx.service._continuation._agent_run_ledger = ledger
    ref, pause_id = await _pause(fx)
    fx.approve_pause_tool()
    db.execute("DELETE FROM padiem_engine_agent_runs_v1")
    response = await fx.service.resume_payload(
        fx.payload(continuation_ref=ref, decision=fx.decision(pause_id))
    )
    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_run_lease_unavailable"
    assert fx.store.resolve(app_id=CONT_APP, continuation_ref=ref).state == "active"
    assert fx.handler_calls == 0

async def test_approved_resume_wrong_server_owner_fails_closed(sql):
    db, _ = sql
    fx = ContinuationFixture()
    ledger = D1AgentRunLedger(SQLiteD1(db))
    fx.service._agent_run_ledger = ledger
    fx.service._continuation._agent_run_ledger = ledger
    ref, _ = await _pause(fx)
    run_id = fx.store.resolve(app_id=CONT_APP, continuation_ref=ref).pause.run_id

    with pytest.raises(AgentDurableLeaseError):
        await ledger.resume_approved_pause(
            run_id=run_id, owner_scope="scope_" + "b" * 64,
            worker_id="eng_" + "a" * 24, completed_step=0,
        )
    row = db.execute(
        "SELECT status,epoch FROM padiem_engine_agent_runs_v1 WHERE run_id=?",
        (run_id,),
    ).fetchone()
    assert (row["status"], row["epoch"]) == ("awaiting_approval", 2)
    assert fx.handler_calls == 0


async def test_denied_approval_revokes_d1_without_tool_dispatch(sql):
    db, _ = sql
    fx = ContinuationFixture()
    ledger = D1AgentRunLedger(SQLiteD1(db))
    fx.service._agent_run_ledger = ledger
    fx.service._continuation._agent_run_ledger = ledger
    ref, pause_id = await _pause(fx)
    response = await fx.service.resume_payload(
        fx.payload(continuation_ref=ref, decision=fx.decision(pause_id, outcome="denied"))
    )
    assert response.status_code == 409, response.body
    assert response.body["error"]["code"] == "approval_denied"
    row = db.execute(
        "SELECT status,epoch FROM padiem_engine_agent_runs_v1"
    ).fetchone()
    assert (row["status"], row["epoch"]) == ("cancelled", 3)
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0


async def test_legacy_untracked_pause_is_not_falsely_resumable_in_durable_mode(sql):
    db, _ = sql
    fx = ContinuationFixture()
    ref, pause_id = await _pause(fx)
    assert db.execute(
        "SELECT COUNT(*) FROM padiem_engine_agent_runs_v1"
    ).fetchone()[0] == 0
    ledger = D1AgentRunLedger(SQLiteD1(db))
    fx.service._agent_run_ledger = ledger
    fx.service._continuation._agent_run_ledger = ledger
    fx.approve_pause_tool()
    response = await fx.service.resume_payload(
        fx.payload(continuation_ref=ref, decision=fx.decision(pause_id))
    )
    assert response.status_code == 503, response.body
    assert response.body["error"]["code"] == "agent_run_lease_unavailable"
    assert fx.handler_calls == 0
