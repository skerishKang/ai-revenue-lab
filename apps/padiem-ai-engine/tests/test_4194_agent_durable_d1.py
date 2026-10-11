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


def test_engine_identity_composition_gate_default_off_and_explicit_on(sql):
    from worker_identity import _agent_skill_service_for_env
    from app.service import ServiceContractError
    db, _ = sql
    fx = Fixture()
    common = dict(
        runtime_factory=lambda app_id: fx.provider,
        binding_resolver=lambda app_id: fx.binding if app_id == APP_ID else None,
    )
    ordinary = _agent_skill_service_for_env({}, **common)
    assert ordinary._agent_run_ledger is None
    selected = _agent_skill_service_for_env(
        {"PADIEM_ENGINE_AGENT_DURABLE_ENABLED": "true",
         "ENGINE_CONTINUATION": SQLiteD1(db)},
        **common,
    )
    assert isinstance(selected._agent_run_ledger, D1AgentRunLedger)
    with pytest.raises(ServiceContractError):
        _agent_skill_service_for_env(
            {"PADIEM_ENGINE_AGENT_DURABLE_ENABLED": "true"}, **common
        )
