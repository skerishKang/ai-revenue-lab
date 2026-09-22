"""#2833 S2F3A — workspace linkage on the canonical Claw run-history authority.

NETWORK_FREE: no live D1, no provider call, no background scheduler, no
production mutation. Uses an in-memory D1 double over the exact
``claw_run_history`` statements ``D1HistoryStore`` issues
(prepare / bind / run / first / all).

Contract under test:
  * ``record_claw_run(..., workspace_id=None)`` is additive; legacy callers and
    the conversation/artifact/result-summary contracts are unchanged.
  * the ``(user_id, run_id)`` upsert is idempotent — one history record per run.
  * workspace linkage is immutable: NULL -> W backfill, same W update,
    incoming None preserves W, W_A -> W_B fails closed.
  * ``list_recent_claw_runs(workspace_id=...)`` is an exact tenant filter that
    excludes foreign workspaces and legacy NULL rows.
  * ``workspace_id`` never leaks into the public projection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import history as history_module
from app.history import D1HistoryStore, HistoryError

USER_ID = "usr_" + "7" * 32
WORKSPACE_A = "ws-alpha"
WORKSPACE_B = "ws-beta"


class _FakeStatement:
    def __init__(self, db: "_FakeD1", sql: str) -> None:
        self._db = db
        self._sql = " ".join(sql.split())
        self._values: tuple[Any, ...] = ()

    def bind(self, *values: Any) -> "_FakeStatement":
        self._values = values
        return self

    def _where_names(self) -> list[str]:
        where = self._sql.split(" WHERE ", 1)[1]
        where = where.split(" ORDER BY ", 1)[0]
        return [c[: c.index("=")].strip() for c in where.split(" AND ")]

    async def run(self) -> dict[str, Any]:
        sql = self._sql
        if sql.startswith("INSERT INTO claw_run_history"):
            cols = [c.strip() for c in sql[sql.index("(") + 1: sql.index(")")].split(",")]
            row = {col: value for col, value in zip(cols, self._values)}
            self._db.rows[row["run_id"]] = row
            return {"success": True, "meta": {"changes": 1}}
        if sql.startswith("UPDATE claw_run_history"):
            set_part = sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            set_cols = [p.split("=")[0].strip() for p in set_part.split(",")]
            names = self._where_names()
            where_values = self._values[len(set_cols):]
            for row in self._db.rows.values():
                if all(row.get(n) == v for n, v in zip(names, where_values)):
                    for col, value in zip(set_cols, self._values[: len(set_cols)]):
                        row[col] = value
                    break
            return {"success": True, "meta": {"changes": 1}}
        if sql.startswith("SELECT"):
            names = self._where_names()
            cond_values = self._values[: len(names)]
            limit = self._values[-1] if "LIMIT ?" in sql else None
            rows = [
                dict(row)
                for row in self._db.rows.values()
                if all(row.get(n) == v for n, v in zip(names, cond_values))
            ]
            rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            if limit is not None:
                rows = rows[: int(limit)]
            return {"success": True, "results": rows}
        raise AssertionError(f"unexpected SQL for run(): {sql!r}")

    async def first(self) -> dict[str, Any] | None:
        names = self._where_names()
        for row in self._db.rows.values():
            if all(row.get(n) == v for n, v in zip(names, self._values)):
                return dict(row)
        return None


class _FakeD1:
    """Minimal in-memory D1 double: prepare / bind / run / first only."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def prepare(self, sql: str) -> _FakeStatement:
        return _FakeStatement(self, sql)


def _store() -> D1HistoryStore:
    return D1HistoryStore(_FakeD1())


async def _record(
    store: D1HistoryStore,
    run_id: str,
    *,
    workspace_id: str | None = None,
    conversation_id: str | None = None,
    status: str = "completed",
    summary: str | None = None,
    artifact_document_id: str | None = None,
    artifact_filename: str | None = None,
    artifact_media_type: str | None = None,
) -> None:
    await store.record_claw_run(
        USER_ID,
        run_id,
        "claw_automation",
        "scheduled_check",
        "Scheduled check",
        status,
        result_summary=summary,
        artifact_document_id=artifact_document_id,
        artifact_filename=artifact_filename,
        artifact_media_type=artifact_media_type,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )


async def test_legacy_row_without_workspace_still_reads() -> None:
    store = _store()
    await _record(store, "run-legacy")
    rows = await store.list_recent_claw_runs(USER_ID)
    assert [r["run_id"] for r in rows] == ["run-legacy"]


async def test_record_with_workspace_roundtrip_and_upsert_is_idempotent() -> None:
    store = _store()
    await _record(store, "run-1", workspace_id=WORKSPACE_A, status="running")
    await _record(store, "run-1", workspace_id=WORKSPACE_A, status="completed")
    scoped = await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A)
    assert [r["run_id"] for r in scoped] == ["run-1"]
    assert scoped[0]["status"] == "completed"


async def test_null_to_workspace_backfill_allowed() -> None:
    store = _store()
    await _record(store, "run-backfill")  # legacy: workspace_id NULL
    await _record(store, "run-backfill", workspace_id=WORKSPACE_A)
    assert [r["run_id"] for r in await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A)] == ["run-backfill"]
    assert await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_B) == []


async def test_same_workspace_update_allowed() -> None:
    store = _store()
    await _record(store, "run-same", workspace_id=WORKSPACE_A, status="running")
    await _record(store, "run-same", workspace_id=WORKSPACE_A, status="completed")
    rows = await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A)
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"


async def test_incoming_none_preserves_existing_workspace() -> None:
    store = _store()
    await _record(store, "run-preserve", workspace_id=WORKSPACE_A)
    await _record(store, "run-preserve")  # incoming workspace None must not erase
    assert [r["run_id"] for r in await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A)] == ["run-preserve"]


async def test_workspace_transfer_is_rejected() -> None:
    store = _store()
    await _record(store, "run-transfer", workspace_id=WORKSPACE_A)
    with pytest.raises(HistoryError):
        await _record(store, "run-transfer", workspace_id=WORKSPACE_B)
    # The linkage is preserved unchanged.
    assert [r["run_id"] for r in await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A)] == ["run-transfer"]
    assert await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_B) == []


async def test_list_without_workspace_keeps_legacy_behavior() -> None:
    store = _store()
    await _record(store, "run-legacy")
    await _record(store, "run-a", workspace_id=WORKSPACE_A)
    await _record(store, "run-b", workspace_id=WORKSPACE_B)
    rows = await store.list_recent_claw_runs(USER_ID)
    assert sorted(r["run_id"] for r in rows) == ["run-a", "run-b", "run-legacy"]


async def test_tenant_filter_excludes_foreign_workspace_and_legacy_null() -> None:
    store = _store()
    await _record(store, "run-legacy")
    await _record(store, "run-a", workspace_id=WORKSPACE_A)
    await _record(store, "run-b", workspace_id=WORKSPACE_B)
    only_a = await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A)
    assert [r["run_id"] for r in only_a] == ["run-a"]
    only_b = await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_B)
    assert [r["run_id"] for r in only_b] == ["run-b"]


async def test_two_workspaces_never_cross_disclosed() -> None:
    store = _store()
    await _record(store, "run-a", workspace_id=WORKSPACE_A)
    await _record(store, "run-b", workspace_id=WORKSPACE_B)
    a_ids = {r["run_id"] for r in await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A)}
    b_ids = {r["run_id"] for r in await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_B)}
    assert a_ids == {"run-a"}
    assert b_ids == {"run-b"}
    assert a_ids.isdisjoint(b_ids)


async def test_workspace_id_not_in_public_projection() -> None:
    store = _store()
    await _record(store, "run-a", workspace_id=WORKSPACE_A)
    rows = await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A)
    assert rows
    for row in rows:
        assert "workspace_id" not in row


async def test_conversation_linkage_contract_preserved() -> None:
    store = _store()
    conversation_a = "chat_" + "a1" * 16
    conversation_b = "chat_" + "b2" * 16
    await _record(store, "run-conv", workspace_id=WORKSPACE_A, conversation_id=conversation_a)
    # same linkage -> no-op
    await _record(store, "run-conv", workspace_id=WORKSPACE_A, conversation_id=conversation_a)
    # transfer to a different conversation -> fail closed
    with pytest.raises(HistoryError):
        await _record(store, "run-conv", workspace_id=WORKSPACE_A, conversation_id=conversation_b)
    # legacy NULL -> one-time backfill allowed
    await _record(store, "run-conv-backfill", workspace_id=WORKSPACE_A)
    await _record(store, "run-conv-backfill", workspace_id=WORKSPACE_A, conversation_id=conversation_a)


async def test_artifact_fields_and_result_summary_bound_preserved() -> None:
    store = _store()
    long_summary = "x" * 500
    await _record(
        store,
        "run-artifact",
        workspace_id=WORKSPACE_A,
        summary=long_summary,
        artifact_document_id="doc_" + "c" * 32,
        artifact_filename="report.pdf",
        artifact_media_type="application/pdf",
    )
    row = (await store.list_recent_claw_runs(USER_ID, workspace_id=WORKSPACE_A))[0]
    assert row["result_summary"] == "x" * history_module.MAX_RUN_RESULT_SUMMARY_CHARS
    assert row["artifact"] == {
        "document_id": "doc_" + "c" * 32,
        "filename": "report.pdf",
        "media_type": "application/pdf",
    }


async def test_workspace_id_shape_is_validated_with_canonical_grammar() -> None:
    store = _store()
    with pytest.raises(ValueError):
        await _record(store, "run-bad", workspace_id="bad workspace id")


def test_migration_is_additive_workspace_column() -> None:
    """Exactly one migration adds the nullable workspace_id column, additively."""

    migrations_dir = Path(history_module.__file__).resolve().parents[1] / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))
    names = [p.name for p in migration_files]
    assert "015_claw_run_history_workspace.sql" in names
    content = (migrations_dir / "015_claw_run_history_workspace.sql").read_text(encoding="utf-8").lower()
    assert "alter table claw_run_history add column workspace_id text;" in content
    assert "create table" not in content
    assert "drop table" not in content
    assert "delete from" not in content
    assert "foreign key" not in content
