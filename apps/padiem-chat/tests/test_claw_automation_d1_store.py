"""#2983 B62 Worker D1 persistence adapter for the canonical Claw automation store.

Behavior proofs for ``D1ClawAutomationStore`` against an in-memory SQLite double
that conforms to the Cloudflare D1 interface (``prepare``/``bind``/``run``/``first``/
``all``/``batch``). The adapter must reuse the kernel's single domain contract
(``kagent.claw_automation``) and add NO second authority, NO runtime DDL, NO caller
SQL, NO lock table, NO claim token and NO scheduler.

One domain contract, two durable homes: these tests deliberately exercise the same
rule/run/occurrence/proposal vocabulary the reference ``SqliteClawAutomationStore``
uses, so any drift between the two homes is a failure here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import inspect
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutput,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationStore,
    ClawAutomationTarget,
    ClawNotificationChannel,
    ClawNotificationPreference,
    ClawNotificationProposal,
    ClawApprovalGate,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    InMemoryClawAutomationStore,
    _derived_occurrence_id,
    occurrence_key,
)
from kagent.contracts import ContractError

from app import claw_automation_store as store_module
from app.claw_automation_store import D1ClawAutomationStore


NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
DONE = NOW + timedelta(minutes=5)
WORKSPACE = "workspace_a"
OTHER_WORKSPACE = "workspace_b"
RULE_ID = "rule_claw_1"
OTHER_RULE = "rule_claw_2"
REVISION = "a" * 40
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")

STORE_PATH = Path(__file__).resolve().parent.parent / "app" / "claw_automation_store.py"
MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "migrations" / "018_claw_automation_durable_store.sql"
)


# ---------------------------------------------------------------------------
# D1 interface double (mirrors the calendar test double, adds `batch`)
# ---------------------------------------------------------------------------


class SqliteD1Binding:
    """In-memory SQLite adapter conforming to the Cloudflare D1 interface."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or sqlite3.connect(
            ":memory:", check_same_thread=False, isolation_level=None
        )
        self.conn.row_factory = sqlite3.Row

    def prepare(self, sql: str) -> "SqliteD1Statement":
        return SqliteD1Statement(self.conn, sql)

    async def batch(self, statements: list["SqliteD1Statement"]) -> list[SimpleNamespace]:
        results: list[SimpleNamespace] = []
        for statement in statements:
            cursor = self.conn.cursor()
            cursor.execute(statement.sql, statement.params)
            try:
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                rows = []
            results.append(
                SimpleNamespace(results=[dict(r) for r in rows], success=True)
            )
        return results


class SqliteD1Statement:
    def __init__(
        self,
        conn: sqlite3.Connection,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> None:
        self.conn = conn
        self.sql = sql
        self.params = params

    def bind(self, *values: Any) -> "SqliteD1Statement":
        return SqliteD1Statement(self.conn, self.sql, values)

    async def run(self) -> dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        return {"success": True}

    async def first(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    async def all(self) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


@pytest.fixture
def d1_db() -> SqliteD1Binding:
    binding = SqliteD1Binding()
    binding.conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    return binding


@pytest.fixture
def d1_store(d1_db: SqliteD1Binding) -> D1ClawAutomationStore:
    return D1ClawAutomationStore(d1_db)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def make_rule(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    owner_ref: str | None = None,
    execution_intent: ClawAutomationExecutionIntent | None = None,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Daily bounded report",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.REPORT,
        notification_channels=(
            ClawNotificationPreference(
                channel=ClawNotificationChannel.WEB_ALERT_INBOX, enabled=True
            ),
        ),
        owner_ref=owner_ref,
        execution_intent=execution_intent
        or ClawAutomationExecutionIntent(
            task="Produce the scheduled bounded report",
            repository_ref="repo:padiem/ai-revenue-lab",
            exact_revision=REVISION,
        ),
    )


def scheduled_run(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    scheduled_time: datetime = NOW,
    status: ClawScheduledRunStatus = ClawScheduledRunStatus.PENDING,
    run_id: str | None = None,
    output: ClawAutomationOutput | None = None,
) -> ClawScheduledRun:
    derived = _derived_occurrence_id("sched_run", workspace_id, rule_id, scheduled_time)
    terminal = status in {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }
    return ClawScheduledRun(
        run_id=run_id or derived,
        workspace_id=workspace_id,
        rule_id=rule_id,
        status=status,
        scheduled_time=scheduled_time,
        started_at=scheduled_time,
        completed_at=DONE if terminal else None,
        output=output,
        error_message="boom" if status is ClawScheduledRunStatus.FAILED else None,
    )


def make_output(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    run_id: str = "run_x",
    proposals: tuple[ClawNotificationProposal, ...] = (),
) -> ClawAutomationOutput:
    return ClawAutomationOutput(
        output_id=f"out_{run_id}",
        workspace_id=workspace_id,
        output_type=ClawAutomationOutputType.REPORT,
        title="Report",
        content="bounded answer",
        proposals=proposals,
    )


def make_proposal(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    proposal_id: str = "p1",
) -> ClawNotificationProposal:
    return ClawNotificationProposal(
        proposal_id=proposal_id,
        workspace_id=workspace_id,
        rule_id=rule_id,
        channel=ClawNotificationChannel.WEB_ALERT_INBOX,
        title="Approve report",
        summary="Needs sign-off",
        approval_gate=ClawApprovalGate(
            approval_required=True,
            reason="needs sign-off",
            suggested_action="approve",
        ),
    )


# ===========================================================================
# 1. Wiring / protocol / readiness
# ===========================================================================


def test_d1_store_requires_binding() -> None:
    with pytest.raises(ValueError, match="D1 binding .* is required"):
        D1ClawAutomationStore(None)


def test_d1_store_conforms_to_protocol(d1_store: D1ClawAutomationStore) -> None:
    # ClawAutomationStore is a static Protocol (not runtime_checkable), so assert
    # the structural contract the composition layer relies on.
    for method in (
        "save_rule",
        "get_rule",
        "list_rules",
        "update_rule",
        "set_rule_enabled",
        "record_run",
        "get_run",
        "get_run_for_occurrence",
        "list_runs",
        "list_proposals",
        "claim_execution",
        "update_run_projection",
    ):
        assert hasattr(d1_store, method) and callable(getattr(d1_store, method)), method


def test_d1_store_methods_are_async(d1_store: D1ClawAutomationStore) -> None:
    for method in (
        "save_rule",
        "get_rule",
        "list_rules",
        "update_rule",
        "set_rule_enabled",
        "record_run",
        "get_run",
        "get_run_for_occurrence",
        "list_runs",
        "list_proposals",
        "claim_execution",
        "update_run_projection",
    ):
        assert inspect.iscoroutinefunction(getattr(d1_store, method)), method


def test_readiness_flags_are_explicitly_false() -> None:
    assert store_module.RUNTIME_CREATE_TABLE is False
    assert store_module.CALLER_SUPPLIED_SQL is False
    assert store_module.CALLER_LIST_ALL_WORKSPACES is False
    assert store_module.BACKGROUND_SCHEDULER is False
    assert store_module.REAL_CLOUD_CRON_REGISTRATION is False
    assert store_module.PRODUCTION_SCHEDULER_ACTIVATION is False
    assert store_module.SECOND_DEDUP_AUTHORITY is False
    assert store_module.EXECUTION_CLAIM_NEW_LOCK_TABLE is False
    assert store_module.EXECUTION_CLAIM_NEW_CLAIM_TOKEN is False
    assert store_module.ONE_OCCURRENCE_MAX_CANONICAL_RUNS == 1


def test_adapter_has_no_runtime_ddl_or_caller_sql() -> None:
    source = STORE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "CREATE TABLE",
        "CREATE INDEX",
        "ALTER TABLE",
        "DROP TABLE",
        "executescript",
        "conn.execute",
        "PRAGMA",
        "VACUUM",
    ):
        assert forbidden not in source, forbidden


# ===========================================================================
# 2. Rule persistence + workspace isolation + immutability
# ===========================================================================


@pytest.mark.asyncio
async def test_save_and_get_rule_roundtrip(d1_store: D1ClawAutomationStore) -> None:
    rule = make_rule(owner_ref="owner:alice")
    await d1_store.save_rule(rule)
    fetched = await d1_store.get_rule(RULE_ID, WORKSPACE)
    assert fetched is not None
    assert fetched.rule_id == RULE_ID
    assert fetched.workspace_id == WORKSPACE
    assert fetched.name == "Daily bounded report"
    assert fetched.schedule.expression == "0 9 * * *"
    assert fetched.owner_ref == "owner:alice"
    assert fetched.execution_intent is not None
    assert fetched.execution_intent.exact_revision == REVISION


@pytest.mark.asyncio
async def test_get_rule_wrong_workspace_returns_none(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    assert await d1_store.get_rule(RULE_ID, OTHER_WORKSPACE) is None


@pytest.mark.asyncio
async def test_list_rules_scoped_to_workspace(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule(workspace_id=WORKSPACE, rule_id=RULE_ID))
    await d1_store.save_rule(make_rule(workspace_id=OTHER_WORKSPACE, rule_id=OTHER_RULE))
    ws_a = await d1_store.list_rules(WORKSPACE)
    ws_b = await d1_store.list_rules(OTHER_WORKSPACE)
    assert {r.rule_id for r in ws_a} == {RULE_ID}
    assert {r.rule_id for r in ws_b} == {OTHER_RULE}


@pytest.mark.asyncio
async def test_update_rule_name_keeps_owner_and_intent(d1_store: D1ClawAutomationStore) -> None:
    rule = make_rule(owner_ref="owner:alice")
    await d1_store.save_rule(rule)
    updated = ClawAutomationRule(
        rule_id=rule.rule_id,
        workspace_id=rule.workspace_id,
        name="Renamed report",
        schedule=rule.schedule,
        target_source=rule.target_source,
        output_type=rule.output_type,
        enabled=rule.enabled,
        notification_channels=rule.notification_channels,
        owner_ref=rule.owner_ref,
        execution_intent=rule.execution_intent,
    )
    await d1_store.update_rule(updated)
    fetched = await d1_store.get_rule(RULE_ID, WORKSPACE)
    assert fetched is not None
    assert fetched.name == "Renamed report"
    assert fetched.owner_ref == "owner:alice"


@pytest.mark.asyncio
async def test_set_rule_enabled_toggles(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    disabled = await d1_store.set_rule_enabled(WORKSPACE, RULE_ID, False)
    assert disabled.enabled is False
    reenabled = await d1_store.set_rule_enabled(WORKSPACE, RULE_ID, True)
    assert reenabled.enabled is True


@pytest.mark.asyncio
async def test_save_rule_owner_ref_immutable(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule(owner_ref="owner:alice"))
    rogue = make_rule(owner_ref="owner:bob")
    with pytest.raises(ContractError):
        await d1_store.save_rule(rogue)


@pytest.mark.asyncio
async def test_save_rule_execution_intent_immutable(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    rogue = make_rule(
        execution_intent=ClawAutomationExecutionIntent(
            task="different task",
            repository_ref="repo:other/repo",
            exact_revision="b" * 40,
        )
    )
    with pytest.raises(ContractError):
        await d1_store.save_rule(rogue)


@pytest.mark.asyncio
async def test_save_rule_workspace_mismatch_rejected(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule(workspace_id=WORKSPACE, rule_id=RULE_ID))
    rogue = make_rule(workspace_id=OTHER_WORKSPACE, rule_id=RULE_ID)
    with pytest.raises(ContractError):
        await d1_store.save_rule(rogue)


# ===========================================================================
# 3. Run persistence + workspace isolation
# ===========================================================================


@pytest.mark.asyncio
async def test_record_run_creates_canonical_run(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    saved = await d1_store.record_run(run)
    assert saved.run_id == run.run_id
    assert saved.status is ClawScheduledRunStatus.PENDING
    fetched = await d1_store.get_run(run.run_id, WORKSPACE)
    assert fetched is not None
    assert fetched.workspace_id == WORKSPACE
    assert fetched.rule_id == RULE_ID


@pytest.mark.asyncio
async def test_get_run_wrong_workspace_returns_none(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    assert await d1_store.get_run(run.run_id, OTHER_WORKSPACE) is None


@pytest.mark.asyncio
async def test_list_runs_scoped_to_workspace(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule(workspace_id=WORKSPACE, rule_id=RULE_ID))
    await d1_store.save_rule(make_rule(workspace_id=OTHER_WORKSPACE, rule_id=OTHER_RULE))
    await d1_store.record_run(scheduled_run(workspace_id=WORKSPACE, rule_id=RULE_ID))
    await d1_store.record_run(
        scheduled_run(workspace_id=OTHER_WORKSPACE, rule_id=OTHER_RULE, scheduled_time=NOW)
    )
    ws_a = await d1_store.list_runs(WORKSPACE)
    ws_b = await d1_store.list_runs(OTHER_WORKSPACE)
    assert len(ws_a) == 1
    assert len(ws_b) == 1
    assert ws_a[0].workspace_id == WORKSPACE
    assert ws_b[0].workspace_id == OTHER_WORKSPACE


@pytest.mark.asyncio
async def test_get_run_for_occurrence_cross_workspace_none(
    d1_store: D1ClawAutomationStore,
) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    key = occurrence_key(WORKSPACE, RULE_ID, NOW)
    # Same key, foreign workspace -> non-disclosing None.
    assert await d1_store.get_run_for_occurrence(key, OTHER_WORKSPACE) is None
    assert await d1_store.get_run_for_occurrence(key, WORKSPACE) is not None


# ===========================================================================
# 4. One occurrence -> one canonical run (dedup authority is the PK)
# ===========================================================================


@pytest.mark.asyncio
async def test_record_run_idempotent_same_occurrence(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    first = await d1_store.record_run(run)
    second = await d1_store.record_run(run)
    assert first.run_id == second.run_id
    rows = await d1_store.list_runs(WORKSPACE)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_record_run_distinct_occurrence_distinct_run(
    d1_store: D1ClawAutomationStore,
) -> None:
    await d1_store.save_rule(make_rule())
    a = scheduled_run(scheduled_time=NOW)
    b = scheduled_run(scheduled_time=NOW + timedelta(hours=1))
    await d1_store.record_run(a)
    await d1_store.record_run(b)
    rows = await d1_store.list_runs(WORKSPACE)
    assert len(rows) == 2
    assert {r.run_id for r in rows} == {a.run_id, b.run_id}


@pytest.mark.asyncio
async def test_concurrent_record_run_same_occurrence_single_row() -> None:
    class YieldingBatchBinding(SqliteD1Binding):
        """Force both contenders past their pre-read before either batch mutates."""

        def __init__(self) -> None:
            super().__init__()
            self.batch_arrivals = 0

        async def batch(
            self, statements: list["SqliteD1Statement"]
        ) -> list[SimpleNamespace]:
            self.batch_arrivals += 1
            # record_run performs its existing-row / occurrence pre-reads before
            # entering batch(). Yield here so a second task reaches the same point
            # against the same empty occurrence state. The two atomic batches then
            # race on the single occurrence_key primary-key authority.
            await asyncio.sleep(0)
            return await super().batch(statements)

    binding = YieldingBatchBinding()
    binding.conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    store = D1ClawAutomationStore(binding)
    await store.save_rule(make_rule())
    binding.batch_arrivals = 0

    run = scheduled_run()
    one, two = await asyncio.gather(store.record_run(run), store.record_run(run))

    # Both tasks reached the mutation boundary from the same pre-mutation state,
    # yet only one canonical run exists and the loser adopts its run id.
    assert binding.batch_arrivals == 2
    assert one.run_id == two.run_id == run.run_id
    rows = await store.list_runs(WORKSPACE)
    assert [row.run_id for row in rows] == [run.run_id]
    assert await store.get_run_for_occurrence(
        occurrence_key(WORKSPACE, RULE_ID, NOW), WORKSPACE
    ) == rows[0]


@pytest.mark.asyncio
async def test_one_occurrence_max_canonical_runs(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    await d1_store.record_run(run)
    await d1_store.record_run(run)
    rows = await d1_store.list_runs(WORKSPACE)
    assert len(rows) == store_module.ONE_OCCURRENCE_MAX_CANONICAL_RUNS


# ===========================================================================
# 5. Execution claim: at-most-once, never reclaims RUNNING/terminal
# ===========================================================================


@pytest.mark.asyncio
async def test_claim_execution_pending_to_running(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    claimed = await d1_store.claim_execution(
        run_id=run.run_id,
        workspace_id=WORKSPACE,
        rule_id=RULE_ID,
        scheduled_time=NOW,
    )
    assert claimed is not None
    assert claimed.status is ClawScheduledRunStatus.RUNNING
    reread = await d1_store.get_run(run.run_id, WORKSPACE)
    assert reread is not None
    assert reread.status is ClawScheduledRunStatus.RUNNING


@pytest.mark.asyncio
async def test_claim_execution_at_most_once(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    first = await d1_store.claim_execution(
        run_id=run.run_id, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled_time=NOW
    )
    assert first is not None
    second = await d1_store.claim_execution(
        run_id=run.run_id, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled_time=NOW
    )
    # The run is now RUNNING; a second claim must NOT be claimed again.
    assert second is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_status",
    [
        ClawScheduledRunStatus.RUNNING,
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    ],
)
async def test_claim_execution_never_reclaims(
    d1_store: D1ClawAutomationStore, terminal_status: ClawScheduledRunStatus
) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run(status=terminal_status)
    await d1_store.record_run(run)
    claimed = await d1_store.claim_execution(
        run_id=run.run_id, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled_time=NOW
    )
    # RUNNING / COMPLETED / FAILED / CANCELLED are never re-dispatched.
    assert claimed is None


@pytest.mark.asyncio
async def test_claim_execution_identity_mismatch_rejected(
    d1_store: D1ClawAutomationStore,
) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    with pytest.raises(ContractError):
        await d1_store.claim_execution(
            run_id=run.run_id,
            workspace_id=WORKSPACE,
            rule_id=OTHER_RULE,
            scheduled_time=NOW,
        )


@pytest.mark.asyncio
async def test_claim_execution_missing_run_rejected(
    d1_store: D1ClawAutomationStore,
) -> None:
    with pytest.raises(ContractError):
        await d1_store.claim_execution(
            run_id="nope", workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled_time=NOW
        )


# ===========================================================================
# 6. Terminal projection update (store-level guards)
# ===========================================================================


@pytest.mark.asyncio
async def test_update_run_projection_to_completed(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    updated = await d1_store.update_run_projection(
        run_id=run.run_id,
        workspace_id=WORKSPACE,
        rule_id=RULE_ID,
        scheduled_time=NOW,
        status=ClawScheduledRunStatus.COMPLETED,
        completed_at=DONE,
        output=make_output(run_id=run.run_id),
    )
    assert updated.status is ClawScheduledRunStatus.COMPLETED
    assert updated.completed_at is not None
    assert updated.output is not None
    assert updated.output.workspace_id == WORKSPACE


@pytest.mark.asyncio
async def test_update_run_projection_wrong_workspace_rejected(
    d1_store: D1ClawAutomationStore,
) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    with pytest.raises(ContractError):
        await d1_store.update_run_projection(
            run_id=run.run_id,
            workspace_id=OTHER_WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=NOW,
            status=ClawScheduledRunStatus.COMPLETED,
            completed_at=DONE,
        )


@pytest.mark.asyncio
async def test_update_run_projection_missing_run_rejected(
    d1_store: D1ClawAutomationStore,
) -> None:
    with pytest.raises(ContractError):
        await d1_store.update_run_projection(
            run_id="missing",
            workspace_id=WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=NOW,
            status=ClawScheduledRunStatus.COMPLETED,
            completed_at=DONE,
        )


@pytest.mark.asyncio
async def test_update_run_projection_output_workspace_mismatch_rejected(
    d1_store: D1ClawAutomationStore,
) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    with pytest.raises(ContractError):
        await d1_store.update_run_projection(
            run_id=run.run_id,
            workspace_id=WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=NOW,
            status=ClawScheduledRunStatus.COMPLETED,
            completed_at=DONE,
            output=make_output(workspace_id=OTHER_WORKSPACE, run_id=run.run_id),
        )


@pytest.mark.asyncio
async def test_update_run_projection_output_immutable_once_attached(
    d1_store: D1ClawAutomationStore,
) -> None:
    await d1_store.save_rule(make_rule())
    run = scheduled_run()
    await d1_store.record_run(run)
    await d1_store.update_run_projection(
        run_id=run.run_id,
        workspace_id=WORKSPACE,
        rule_id=RULE_ID,
        scheduled_time=NOW,
        status=ClawScheduledRunStatus.COMPLETED,
        completed_at=DONE,
        output=make_output(run_id=run.run_id),
    )
    # A second projection with a DIFFERENT output must be refused (immutability).
    with pytest.raises(ContractError):
        await d1_store.update_run_projection(
            run_id=run.run_id,
            workspace_id=WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=NOW,
            status=ClawScheduledRunStatus.COMPLETED,
            completed_at=DONE,
            output=make_output(run_id=run.run_id, proposals=(make_proposal(),)),
        )


# ===========================================================================
# 7. Proposal persistence + isolation
# ===========================================================================


@pytest.mark.asyncio
async def test_record_run_persists_scoped_proposals(d1_store: D1ClawAutomationStore) -> None:
    await d1_store.save_rule(make_rule())
    output = make_output(run_id="run_x", proposals=(make_proposal(),))
    run = scheduled_run(output=output)
    await d1_store.record_run(run)
    ws_a = await d1_store.list_proposals(WORKSPACE)
    ws_b = await d1_store.list_proposals(OTHER_WORKSPACE)
    assert len(ws_a) == 1
    assert ws_a[0].proposal_id == "p1"
    assert len(ws_b) == 0


# ===========================================================================
# 8. One domain contract, two durable homes (parity with reference store)
# ===========================================================================


@pytest.mark.asyncio
async def test_d1_store_parity_with_reference_store() -> None:
    """The D1 adapter and the reference in-memory store must agree on the
    canonical occurrence lifecycle, exercising the SAME kernel domain."""

    d1 = D1ClawAutomationStore(SqliteD1Binding())
    d1.db.conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    ref = InMemoryClawAutomationStore()

    rule = make_rule()
    await d1.save_rule(rule)
    ref.save_rule(rule)

    run = scheduled_run()
    d1_run = await d1.record_run(run)
    ref_run = ref.record_run(run)
    assert d1_run.run_id == ref_run.run_id

    d1_claimed = await d1.claim_execution(
        run_id=run.run_id, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled_time=NOW
    )
    ref_claimed = ref.claim_execution(
        run_id=run.run_id, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled_time=NOW
    )
    assert (d1_claimed is None) == (ref_claimed is None)
    if d1_claimed is not None:
        assert d1_claimed.status is ref_claimed.status

    # Second claim must be refused by both.
    assert (
        await d1.claim_execution(
            run_id=run.run_id, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled_time=NOW
        )
        is None
    )
    assert (
        ref.claim_execution(
            run_id=run.run_id, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled_time=NOW
        )
        is None
    )
