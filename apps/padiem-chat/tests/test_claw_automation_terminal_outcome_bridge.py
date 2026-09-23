"""#2918 S2F4C terminal P01 outcome projection behavior tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path

import pytest

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutput,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawAutomationTickRuntime,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
)
from kagent.contracts import ClawRunStatus, ContractError, RunProjection
from kagent.p01_adapter import ClawOrchestrationOutcome, P01AdapterError
from kagent.runs import ClawRun

from app import claw_automation_terminal_outcome_bridge as bridge_module
from app.claw_automation_execution_bridge import (
    AutomationExecutionBridgeError,
    plan_canonical_scheduled_execution,
)
from app.claw_automation_terminal_outcome_bridge import (
    ScheduledOutcomeProjectionError,
    execute_and_project_scheduled_occurrence,
    project_p01_outcome_to_scheduled_run,
)


NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
DONE = NOW + timedelta(minutes=1)
WORKSPACE = "workspace_a"
OTHER_WORKSPACE = "workspace_b"
RULE_ID = "rule_s2f4c_1"
REVISION = "b" * 40
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")


def make_rule(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    output_type: ClawAutomationOutputType = ClawAutomationOutputType.REPORT,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Daily bounded report",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=output_type,
        execution_intent=ClawAutomationExecutionIntent(
            task="Produce the scheduled bounded report",
            repository_ref="repo:padiem/ai-revenue-lab",
            exact_revision=REVISION,
        ),
    )


def scheduled_run(
    *,
    run_id: str | None = None,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    status: ClawScheduledRunStatus = ClawScheduledRunStatus.PENDING,
    output: ClawAutomationOutput | None = None,
) -> ClawScheduledRun:
    from kagent.claw_automation import _derived_occurrence_id

    derived = _derived_occurrence_id("sched_run", workspace_id, rule_id, NOW)
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
        scheduled_time=NOW,
        started_at=NOW,
        completed_at=DONE if terminal else None,
        output=output,
        error_message="failed" if status is ClawScheduledRunStatus.FAILED else None,
    )


class OutcomeAdapter:
    def __init__(self, *, status=ClawRunStatus.COMPLETED, answer="bounded P01 answer"):
        self.status = status
        self.answer = answer
        self.calls: list[ClawRun] = []

    async def execute(self, run, *, lease=None, product_tier=None):
        self.calls.append(run)
        if self.status is ClawRunStatus.FAILED:
            run.transition(ClawRunStatus.FAILED, summary="failure")
        elif self.status is ClawRunStatus.CANCELLED:
            run.transition(ClawRunStatus.CANCELLED, summary="cancelled")
        elif self.status is ClawRunStatus.COMPLETED:
            run.transition(ClawRunStatus.PREPARING, summary="prepared")
            run.transition(ClawRunStatus.RUNNING, summary="running")
            run.transition(ClawRunStatus.COMPLETED, summary="completed")
        return ClawOrchestrationOutcome(
            projection=run.projection(),
            answer=self.answer if self.status is ClawRunStatus.COMPLETED else None,
            p01_run_id="p01-correlated",
            p01_event_count=3,
        )


class RaisingAdapter:
    def __init__(self, *, cancellation=False):
        self.calls: list[ClawRun] = []
        self.cancellation = cancellation

    async def execute(self, run, *, lease=None, product_tier=None):
        self.calls.append(run)
        if self.cancellation:
            run.transition(ClawRunStatus.CANCELLED, summary="cancelled")
            raise asyncio.CancelledError()
        run.transition(ClawRunStatus.FAILED, summary="failed")
        raise P01AdapterError("p01_execution_failed", "safe failure")


def outcome_for(run: ClawRun, *, status=ClawRunStatus.COMPLETED, answer="bounded answer"):
    return ClawOrchestrationOutcome(
        projection=RunProjection(
            run_id=run.run_id,
            task_id=run.intent.task_id,
            status=status,
            execution_mode=run.intent.execution_mode,
        ),
        answer=answer,
        p01_run_id="p01-correlated",
        p01_event_count=3,
    )


def seed(store, rule=None, row=None):
    rule = rule or make_rule()
    row = row or scheduled_run()
    store.save_rule(rule)
    store.record_run(row)
    return rule, row


def test_completed_outcome_attaches_bounded_output_and_reuses_rule_type():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store, rule=make_rule(output_type=ClawAutomationOutputType.ALERT))
    plan = plan_canonical_scheduled_execution(rule, row)

    result = project_p01_outcome_to_scheduled_run(
        rule=rule,
        scheduled_run=row,
        outcome=outcome_for(plan.run),
        store=store,
        completed_at=DONE,
    )

    assert result.scheduled_run.run_id == row.run_id
    assert result.scheduled_run.status is ClawScheduledRunStatus.COMPLETED
    assert result.output is not None
    assert result.output.output_type is ClawAutomationOutputType.ALERT
    assert result.output.content == "bounded answer"
    assert result.output.workspace_id == WORKSPACE
    assert len(store.list_runs(WORKSPACE)) == 1


@pytest.mark.asyncio
async def test_existing_execution_and_projection_path_uses_one_run_id():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store)
    adapter = OutcomeAdapter()

    result = await execute_and_project_scheduled_occurrence(
        rule=rule,
        scheduled_run=row,
        adapter=adapter,
        store=store,
        completed_at=DONE,
    )

    assert len(adapter.calls) == 1
    assert adapter.calls[0].run_id == row.run_id
    assert result.scheduled_run.run_id == row.run_id
    assert result.scheduled_run.output is not None
    assert len(store.list_runs(WORKSPACE)) == 1


@pytest.mark.asyncio
async def test_sqlite_existing_row_projection_is_bounded_and_idempotent():
    store = SqliteClawAutomationStore(":memory:")
    try:
        rule, row = seed(store)
        first_adapter = OutcomeAdapter()
        first = await execute_and_project_scheduled_occurrence(
            rule=rule,
            scheduled_run=row,
            adapter=first_adapter,
            store=store,
            completed_at=DONE,
        )
        retry_adapter = OutcomeAdapter()
        second = await execute_and_project_scheduled_occurrence(
            rule=rule,
            scheduled_run=row,
            adapter=retry_adapter,
            store=store,
            completed_at=DONE + timedelta(minutes=1),
        )
        assert first.scheduled_run == second.scheduled_run
        assert first.scheduled_run.output is not None
        assert retry_adapter.calls == []
        assert len(store.list_runs(WORKSPACE)) == 1
    finally:
        store._db.close()


@pytest.mark.asyncio
async def test_exact_retry_is_idempotent_and_does_not_insert_row():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store)
    first_adapter = OutcomeAdapter()
    first = await execute_and_project_scheduled_occurrence(
        rule=rule, scheduled_run=row, adapter=first_adapter, store=store, completed_at=DONE
    )
    retry_adapter = OutcomeAdapter()
    second = await execute_and_project_scheduled_occurrence(
        rule=rule, scheduled_run=row, adapter=retry_adapter, store=store,
        completed_at=DONE + timedelta(minutes=5)
    )

    assert second.scheduled_run == first.scheduled_run
    assert len(first_adapter.calls) == 1
    assert retry_adapter.calls == []
    assert len(store.list_runs(WORKSPACE)) == 1


@pytest.mark.asyncio
async def test_failure_projects_failed_without_success_output():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store)

    with pytest.raises(P01AdapterError):
        await execute_and_project_scheduled_occurrence(
            rule=rule,
            scheduled_run=row,
            adapter=RaisingAdapter(),
            store=store,
            completed_at=DONE,
        )

    stored = store.get_run(row.run_id, WORKSPACE)
    assert stored is not None
    assert stored.status is ClawScheduledRunStatus.FAILED
    assert stored.output is None
    assert len(store.list_runs(WORKSPACE)) == 1


@pytest.mark.asyncio
async def test_cancellation_projects_cancelled_without_success_output():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store)

    with pytest.raises(asyncio.CancelledError):
        await execute_and_project_scheduled_occurrence(
            rule=rule,
            scheduled_run=row,
            adapter=RaisingAdapter(cancellation=True),
            store=store,
            completed_at=DONE,
        )

    stored = store.get_run(row.run_id, WORKSPACE)
    assert stored is not None
    assert stored.status is ClawScheduledRunStatus.CANCELLED
    assert stored.output is None


def test_failure_and_cancel_outcomes_project_lifecycle_only():
    for status, expected in (
        (ClawRunStatus.FAILED, ClawScheduledRunStatus.FAILED),
        (ClawRunStatus.CANCELLED, ClawScheduledRunStatus.CANCELLED),
    ):
        store = InMemoryClawAutomationStore()
        rule, row = seed(store)
        plan = plan_canonical_scheduled_execution(rule, row)
        result = project_p01_outcome_to_scheduled_run(
            rule=rule,
            scheduled_run=row,
            outcome=outcome_for(plan.run, status=status, answer="must be ignored"),
            store=store,
            completed_at=DONE,
        )
        assert result.scheduled_run.status is expected
        assert result.output is None
        assert result.scheduled_run.output is None


def test_empty_completed_answer_becomes_failed_not_fabricated_success():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store)
    plan = plan_canonical_scheduled_execution(rule, row)

    result = project_p01_outcome_to_scheduled_run(
        rule=rule,
        scheduled_run=row,
        outcome=outcome_for(plan.run, answer="   "),
        store=store,
        completed_at=DONE,
    )

    assert result.scheduled_run.status is ClawScheduledRunStatus.FAILED
    assert result.scheduled_run.output is None


def test_completed_row_without_output_can_receive_one_bounded_backfill():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store, row=scheduled_run(status=ClawScheduledRunStatus.COMPLETED))
    plan = plan_canonical_scheduled_execution(rule, row)

    result = project_p01_outcome_to_scheduled_run(
        rule=rule,
        scheduled_run=row,
        outcome=outcome_for(plan.run),
        store=store,
        completed_at=DONE,
    )

    assert result.scheduled_run.status is ClawScheduledRunStatus.COMPLETED
    assert result.scheduled_run.output is not None
    assert len(store.list_runs(WORKSPACE)) == 1


def test_run_id_correlation_mismatch_fails_closed_without_store_mutation():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store)
    plan = plan_canonical_scheduled_execution(rule, row)
    wrong = ClawRun.create("sched_run_foreign", plan.intent)

    with pytest.raises(ScheduledOutcomeProjectionError):
        project_p01_outcome_to_scheduled_run(
            rule=rule,
            scheduled_run=row,
            outcome=outcome_for(wrong),
            store=store,
            completed_at=DONE,
        )
    stored = store.get_run(row.run_id, WORKSPACE)
    assert stored is not None
    assert stored.status is ClawScheduledRunStatus.PENDING
    assert stored.output is None


def test_terminal_row_cannot_be_resurrected_or_downgraded():
    completed_output = ClawAutomationOutput(
        output_id="existing_output",
        workspace_id=WORKSPACE,
        output_type=ClawAutomationOutputType.REPORT,
        title="Daily bounded report",
        content="already complete",
    )
    store = InMemoryClawAutomationStore()
    rule, row = seed(
        store,
        row=scheduled_run(status=ClawScheduledRunStatus.COMPLETED, output=completed_output),
    )
    plan = plan_canonical_scheduled_execution(rule, row)

    with pytest.raises(ScheduledOutcomeProjectionError):
        project_p01_outcome_to_scheduled_run(
            rule=rule,
            scheduled_run=row,
            outcome=outcome_for(plan.run, status=ClawRunStatus.FAILED),
            store=store,
            completed_at=DONE,
        )
    stored = store.get_run(row.run_id, WORKSPACE)
    assert stored == row


def test_wrong_scope_and_foreign_row_fail_closed():
    store = InMemoryClawAutomationStore()
    rule, row = seed(store)
    plan = plan_canonical_scheduled_execution(rule, row)
    foreign_rule = make_rule(workspace_id=OTHER_WORKSPACE, rule_id="other_rule")

    with pytest.raises((ScheduledOutcomeProjectionError, AutomationExecutionBridgeError, ContractError)):
        project_p01_outcome_to_scheduled_run(
            rule=foreign_rule,
            scheduled_run=row,
            outcome=outcome_for(plan.run),
            store=store,
            completed_at=DONE,
        )
    assert len(store.list_runs(WORKSPACE)) == 1
    assert len(store.list_runs(OTHER_WORKSPACE)) == 0


def test_sync_projection_and_async_execution_boundaries():
    assert not inspect.iscoroutinefunction(project_p01_outcome_to_scheduled_run)
    assert inspect.iscoroutinefunction(execute_and_project_scheduled_occurrence)


def test_source_contains_no_new_authority_or_side_effect_surface():
    source = Path(bridge_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "record_run(",
        "create_claw_run(",
        "ClawAutomationTickRuntime",
        "FakeClawScheduler",
        "occurrence_key(",
        "resolve_owner",
        "ResolvedAutomationOwner",
        "project_scheduled_run_output(",
        "HistoryStore",
        "TaskAlert",
        "SandboxLeasePort",
        "asyncio.run(",
        "urllib",
        "httpx",
        "PadiemAiEngineClient",
        "active_route_for",
        "model_policy",
    ):
        assert forbidden not in source

    assert source.count("store.update_run_projection(") == 1
    assert source.count("execute_scheduled_occurrence(") == 1
