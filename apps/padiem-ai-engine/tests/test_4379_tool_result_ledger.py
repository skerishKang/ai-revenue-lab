"""#4379: the Engine's durable tool result ledger and the widened run row.

The Agent runtime keeps only a reference per settled tool result, so the payload
has to survive in the Engine's D1 store: unchanged, restorable after a resume,
and unreadable for a foreign owner scope. The durable run row must also accept
a checkpoint step beyond the retired 64-step ceiling.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent_tool_result_ledger import D1ToolResultLedger
from padiem_ai_core.agent_tool_result_ledger import ToolResultRef
from padiem_ai_core.contracts import RunStatus, ToolEvent
from padiem_ai_core.tool_runtime import ToolExecutionResult

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations" / "0012_engine_tool_results.sql"
)
RUN_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations" / "0011_engine_agent_durable_runs.sql"
)
WIDENED_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations" / "0013_engine_agent_run_checkpoint_step.sql"
)


class _Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()

    def bind(self, *args):
        self.args = args
        return self

    async def first(self):
        row = self.db.execute(self.sql, self.args).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.execute(self.sql, self.args)
        return {"success": True, "meta": {"changes": cursor.rowcount}}


class _D1:
    def __init__(self, db):
        self.db = db

    def prepare(self, sql):
        return _Statement(self.db, sql)


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    return db


def _result(text: str = "original payload") -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_id="tool.lookup",
        output={"result": text, "rows": [1, 2, 3]},
        event=ToolEvent(tool_id="tool.lookup", status=RunStatus.COMPLETED),
    )


def test_a_tool_result_round_trips_through_the_durable_ledger() -> None:
    db = _db()
    ledger = D1ToolResultLedger(_D1(db), owner_scope="owner:a")
    original = _result()
    ref = asyncio.run(ledger.append(
        run_id="run_1", step_index=3, ordinal=0, result=original,
    ))
    assert isinstance(ref, ToolResultRef)
    restored = asyncio.run(ledger.resolve(ref))
    assert restored.output_copy() == {"result": "original payload", "rows": [1, 2, 3]}
    assert restored.tool_id == "tool.lookup"


def test_a_foreign_owner_scope_cannot_resolve_the_result() -> None:
    db = _db()
    owner = D1ToolResultLedger(_D1(db), owner_scope="owner:a")
    other = D1ToolResultLedger(_D1(db), owner_scope="owner:b")
    ref = asyncio.run(owner.append(
        run_id="run_1", step_index=1, ordinal=0, result=_result(),
    ))
    with pytest.raises(Exception):
        asyncio.run(other.resolve(ref))


def test_the_durable_run_row_accepts_a_checkpoint_step_beyond_the_old_ceiling() -> None:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript(RUN_MIGRATION.read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO padiem_engine_agent_runs_v1 (run_id, owner_scope, "
        "request_fingerprint, worker_id, epoch, status, lease_until, heartbeat_at, "
        "checkpoint_step, side_effect_uncertain) "
        "VALUES ('run_1', 'owner:a', ?, 'worker', 1, 'running', 1.0, 1.0, 5, 0)",
        ("a" * 64,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        # The retired ceiling duplicated the Python step limit in D1.
        db.execute(
            "INSERT INTO padiem_engine_agent_runs_v1 (run_id, owner_scope, "
            "request_fingerprint, worker_id, epoch, status, lease_until, heartbeat_at, "
            "checkpoint_step, side_effect_uncertain) "
            "VALUES ('run_2', 'owner:a', ?, 'worker', 1, 'running', 1.0, 1.0, 101, 0)",
            ("a" * 64,),
        )
    # The widening migration removes that duplicated ceiling and keeps the rows.
    db.executescript(WIDENED_MIGRATION.read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO padiem_engine_agent_runs_v1 (run_id, owner_scope, "
        "request_fingerprint, worker_id, epoch, status, lease_until, heartbeat_at, "
        "checkpoint_step, side_effect_uncertain) "
        "VALUES ('run_3', 'owner:a', ?, 'worker', 1, 'running', 1.0, 1.0, 101, 0)",
        ("a" * 64,),
    )
    rows = db.execute(
        "SELECT run_id, checkpoint_step FROM padiem_engine_agent_runs_v1 "
        "ORDER BY run_id",
    ).fetchall()
    assert [(row["run_id"], row["checkpoint_step"]) for row in rows] == [
        ("run_1", 5), ("run_3", 101),
    ]
