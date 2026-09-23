"""#2929 S2F4E terminal scheduled-run → existing Task/Alert authority tests.

NETWORK_FREE: no scheduler, no P01 dispatch, no provider call, no run-history or
session write, no production mutation. Uses an in-memory double of the existing
``claw_task_alert`` store surface that counts every read and write, so "zero
write" claims are measured, never asserted from prose.

Covers the required behavior: only a COMPLETED run with an explicit
TASK_PROPOSAL/ALERT output materializes exactly one existing-authority record;
the owner must already be a resolved trusted owner context; a non-terminal row is
refused before any store access; the occurrence identity is the existing
``sched_run_<digest>``; retries stay idempotent and never reopen a user-mutated
task or alert status; and this slice writes no history and no session.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone, date
from pathlib import Path

import pytest

from kagent.claw_automation import (
    ClawAutomationOutput,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    _derived_occurrence_id,
)
from kagent.claw_memory import (
    ClawAlert,
    ClawAlertKind,
    ClawAlertSeverity,
    ClawAlertStatus,
    ClawFollowupTask,
    ClawTaskStatus,
)

from app import claw_automation_task_alert_bridge as bridge_module
from app.claw_automation_owner_resolution import ResolvedAutomationOwner
from app.claw_automation_projection_bridge import (
    AutomationProjectionError,
    _deterministic_id,
)
from app.claw_automation_task_alert_bridge import (
    ScheduledTaskAlertProjectionError,
    project_terminal_scheduled_run_to_task_alert,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
WORKSPACE = "workspace_a"
FOREIGN_WORKSPACE = "workspace_b"
RULE_ID = "rule_s2f4e_1"
OWNER_USER = "usr_" + "7" * 32
RAW_CONTENT = "RAW-OUTPUT-CONTENT-SHOULD-NOT-PERSIST"
_AUTO = object()
_UNSET = object()
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")


# ── fixtures ────────────────────────────────────────────────────────────────


def make_rule(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    output_type: ClawAutomationOutputType = ClawAutomationOutputType.TASK_PROPOSAL,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Daily check",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=output_type,
        owner_ref="owner:opaque:provenance:1",
    )


def scheduled_run(
    *,
    rule: ClawAutomationRule | None = None,
    status: ClawScheduledRunStatus = ClawScheduledRunStatus.COMPLETED,
    output=_AUTO,
    run_id: str | None = None,
    workspace_id: str | None = None,
    rule_id: str | None = None,
) -> ClawScheduledRun:
    rule = rule or make_rule()
    workspace = workspace_id if workspace_id is not None else rule.workspace_id
    owner_rule_id = rule_id if rule_id is not None else rule.rule_id
    derived = _derived_occurrence_id("sched_run", workspace, owner_rule_id, NOW)
    terminal = status in {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }
    if output is _AUTO:
        output = (
            ClawAutomationOutput(
                output_id="scheduled_output_s2f4e",
                workspace_id=workspace,
                output_type=rule.output_type,
                title="Daily check result",
                content=RAW_CONTENT,
            )
            if status is ClawScheduledRunStatus.COMPLETED
            else None
        )
    return ClawScheduledRun(
        run_id=run_id if run_id is not None else derived,
        workspace_id=workspace,
        rule_id=owner_rule_id,
        status=status,
        scheduled_time=NOW,
        started_at=NOW,
        completed_at=NOW if terminal else None,
        output=output,
    )


def make_owner(*, workspace_id: str = WORKSPACE) -> ResolvedAutomationOwner:
    return ResolvedAutomationOwner(
        workspace_id=workspace_id,
        owner_ref="owner:opaque:0001",
        product_user_id=OWNER_USER,
        member_id="member_0001",
        canonical_subject_id="subject:padiem:user:123",
    )


class MemoryTaskAlertStore:
    """Counting double of the existing task/alert store surface."""

    def __init__(self, *, drop: str | None = None) -> None:
        self.tasks: dict[str, ClawFollowupTask] = {}
        self.alerts: dict[str, ClawAlert] = {}
        self.reads = 0
        self.writes = 0
        self.add_task_calls = 0
        self.add_alert_calls = 0
        if drop is not None:
            setattr(self, drop, None)

    async def get_task(self, task_id: str, *, workspace_id: str) -> ClawFollowupTask | None:
        self.reads += 1
        task = self.tasks.get(task_id)
        return task if task is not None and task.workspace_id == workspace_id else None

    async def get_alert(
        self, alert_id: str, *, workspace_id: str, member_id: str | None = None
    ) -> ClawAlert | None:
        self.reads += 1
        alert = self.alerts.get(alert_id)
        if alert is None or alert.workspace_id != workspace_id:
            return None
        if member_id is not None and not alert.is_visible_to(member_id):
            return None
        return alert

    async def add_task(self, task: ClawFollowupTask) -> ClawFollowupTask:
        self.writes += 1
        self.add_task_calls += 1
        self.tasks[task.task_id] = task
        return task

    async def add_alert(self, alert: ClawAlert) -> ClawAlert:
        self.writes += 1
        self.add_alert_calls += 1
        self.alerts[alert.alert_id] = alert
        return alert


async def _project(
    store,
    *,
    rule=_UNSET,
    row=_UNSET,
    owner=_UNSET,
):
    return await project_terminal_scheduled_run_to_task_alert(
        rule=make_rule() if rule is _UNSET else rule,
        scheduled_run=scheduled_run() if row is _UNSET else row,
        owner=make_owner() if owner is _UNSET else owner,
        store=store,
    )


def _seed_task(*, store: MemoryTaskAlertStore, rule, row, status: ClawTaskStatus) -> ClawFollowupTask:
    task = ClawFollowupTask(
        task_id=_deterministic_id(WORKSPACE, row.run_id, "task"),
        workspace_id=WORKSPACE,
        member_id=make_owner().member_id,
        title=row.output.title,
        status=status,
        created_at=NOW,
        due_date=date(2026, 9, 24),
        source_id=row.run_id,
        linked_ref=rule.rule_id,
    )
    store.tasks[task.task_id] = task
    return task


def _seed_alert(*, store: MemoryTaskAlertStore, row, status: ClawAlertStatus) -> ClawAlert:
    alert = ClawAlert(
        alert_id=_deterministic_id(WORKSPACE, row.run_id, "alert"),
        workspace_id=WORKSPACE,
        kind=ClawAlertKind.AUTOMATION,
        severity=ClawAlertSeverity.INFO,
        title=row.output.title,
        created_at=NOW,
        status=status,
        visible_to_members=(make_owner().member_id,),
    )
    store.alerts[alert.alert_id] = alert
    return alert


# ── TASK_PROPOSAL / ALERT completed paths ───────────────────────────────────


async def test_task_proposal_completed_projects_exactly_one_open_task():
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    row = scheduled_run(rule=rule)

    result = await _project(store, rule=rule, row=row)

    assert result.run_id == row.run_id
    assert result.status is ClawScheduledRunStatus.COMPLETED
    assert result.created_kind == "task"
    assert result.created is True
    assert result.record_id == _deterministic_id(WORKSPACE, row.run_id, "task")
    assert store.writes == 1
    assert store.alerts == {}
    (task,) = store.tasks.values()
    assert task.status is ClawTaskStatus.OPEN
    assert task.workspace_id == WORKSPACE
    assert task.member_id == make_owner().member_id
    assert task.source_id == row.run_id
    assert task.linked_ref == rule.rule_id
    assert task.created_at == row.completed_at
    assert RAW_CONTENT not in task.title


async def test_alert_completed_projects_exactly_one_active_alert():
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.ALERT)
    row = scheduled_run(rule=rule)

    result = await _project(store, rule=rule, row=row)

    assert result.created_kind == "alert"
    assert result.created is True
    assert result.record_id == _deterministic_id(WORKSPACE, row.run_id, "alert")
    assert store.writes == 1
    assert store.tasks == {}
    (alert,) = store.alerts.values()
    assert alert.status is ClawAlertStatus.ACTIVE
    assert alert.kind is ClawAlertKind.AUTOMATION
    assert alert.severity is ClawAlertSeverity.INFO
    assert alert.workspace_id == WORKSPACE
    assert tuple(alert.visible_to_members) == (make_owner().member_id,)
    assert alert.title == row.output.title


@pytest.mark.parametrize(
    "output_type", [ClawAutomationOutputType.REPORT, ClawAutomationOutputType.DRAFT]
)
async def test_report_or_draft_completed_is_a_no_op_with_zero_writes(output_type):
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=output_type)
    row = scheduled_run(rule=rule)

    result = await _project(store, rule=rule, row=row)

    assert result.created is False
    assert result.created_kind is None
    assert result.record_id is None
    assert store.writes == 0
    assert store.reads == 0
    assert store.tasks == {}
    assert store.alerts == {}


@pytest.mark.parametrize(
    "status",
    [ClawScheduledRunStatus.FAILED, ClawScheduledRunStatus.CANCELLED],
)
async def test_failed_and_cancelled_terminal_rows_are_no_ops_with_zero_writes(status):
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.ALERT)
    row = scheduled_run(rule=rule, status=status)

    result = await _project(store, rule=rule, row=row)

    assert result.created is False
    assert result.created_kind is None
    assert result.status is status
    assert store.writes == 0
    assert store.reads == 0


@pytest.mark.parametrize(
    "status", [ClawScheduledRunStatus.PENDING, ClawScheduledRunStatus.RUNNING]
)
async def test_non_terminal_rows_fail_closed_before_any_store_access(status):
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    row = scheduled_run(rule=rule, status=status)

    with pytest.raises(ScheduledTaskAlertProjectionError):
        await _project(store, rule=rule, row=row)

    assert store.reads == 0
    assert store.writes == 0
    assert store.tasks == {}
    assert store.alerts == {}


@pytest.mark.parametrize(
    "status",
    [
        ClawScheduledRunStatus.PENDING,
        ClawScheduledRunStatus.RUNNING,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    ],
)
@pytest.mark.parametrize(
    "output_type",
    [
        ClawAutomationOutputType.TASK_PROPOSAL,
        ClawAutomationOutputType.ALERT,
        ClawAutomationOutputType.REPORT,
        ClawAutomationOutputType.DRAFT,
    ],
)
async def test_no_non_completed_status_ever_records_a_write(status, output_type):
    """The COMPLETED-only rule holds for every status × output-type combination."""

    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=output_type)
    row = scheduled_run(rule=rule, status=status, output=None)

    try:
        await _project(store, rule=rule, row=row)
    except ScheduledTaskAlertProjectionError:
        pass

    assert store.writes == 0


# ── authority / fail-closed guards ─────────────────────────────────────────


@pytest.mark.parametrize("bad_owner", [None, {}, OWNER_USER, object()])
async def test_unresolved_owner_is_never_accepted(bad_owner):
    store = MemoryTaskAlertStore()

    with pytest.raises(ScheduledTaskAlertProjectionError):
        await _project(store, owner=bad_owner)

    assert store.reads == 0
    assert store.writes == 0


async def test_foreign_workspace_owner_fails_closed_without_write():
    store = MemoryTaskAlertStore()
    foreign_owner = make_owner(workspace_id=FOREIGN_WORKSPACE)

    with pytest.raises((ScheduledTaskAlertProjectionError, AutomationProjectionError)):
        await _project(store, owner=foreign_owner)

    assert store.writes == 0


@pytest.mark.parametrize("bad_rule", [None, {}, "rule_s2f4e_1"])
async def test_untyped_rule_fails_closed_without_write(bad_rule):
    store = MemoryTaskAlertStore()

    with pytest.raises(ScheduledTaskAlertProjectionError):
        await _project(store, rule=bad_rule)

    assert store.writes == 0


@pytest.mark.parametrize("bad_row", [None, {}, "sched_run_deadbeef"])
async def test_untyped_scheduled_row_fails_closed_without_write(bad_row):
    store = MemoryTaskAlertStore()

    with pytest.raises(ScheduledTaskAlertProjectionError):
        await project_terminal_scheduled_run_to_task_alert(
            rule=make_rule(),
            scheduled_run=bad_row,
            owner=make_owner(),
            store=store,
        )

    assert store.writes == 0


async def test_rule_run_mismatch_fails_closed_without_write():
    store = MemoryTaskAlertStore()
    rule = make_rule()
    foreign_rule = make_rule(rule_id="rule_other", workspace_id=FOREIGN_WORKSPACE)
    row = scheduled_run(rule=foreign_rule)

    with pytest.raises(ScheduledTaskAlertProjectionError):
        await _project(store, rule=rule, row=row)

    assert store.reads == 0
    assert store.writes == 0


async def test_non_canonical_run_id_fails_closed_without_write():
    store = MemoryTaskAlertStore()
    rule = make_rule()
    row = scheduled_run(rule=rule, run_id="run_" + "a" * 32)

    with pytest.raises(ScheduledTaskAlertProjectionError):
        await _project(store, rule=rule, row=row)

    assert store.reads == 0
    assert store.writes == 0


async def test_output_type_mismatch_fails_closed_without_write():
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    row = scheduled_run(
        rule=rule,
        output=ClawAutomationOutput(
            output_id="scheduled_output_mismatch",
            workspace_id=WORKSPACE,
            output_type=ClawAutomationOutputType.ALERT,
            title="Mismatched output",
            content=RAW_CONTENT,
        ),
    )

    with pytest.raises(AutomationProjectionError):
        await _project(store, rule=rule, row=row)

    assert store.writes == 0


@pytest.mark.parametrize("dropped", ["get_task", "get_alert", "add_task", "add_alert"])
async def test_store_without_the_existing_surface_fails_closed_before_io(dropped):
    store = MemoryTaskAlertStore(drop=dropped)

    with pytest.raises(ScheduledTaskAlertProjectionError):
        await _project(store)

    assert store.reads == 0
    assert store.writes == 0


async def test_completed_row_without_output_fails_closed_without_write():
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    row = scheduled_run(rule=rule, output=None)

    with pytest.raises(AutomationProjectionError):
        await _project(store, rule=rule, row=row)

    assert store.writes == 0


# ── idempotency + user-mutated status preservation ─────────────────────────


async def test_duplicate_task_projection_never_creates_a_second_task():
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    row = scheduled_run(rule=rule)

    first = await _project(store, rule=rule, row=row)
    second = await _project(store, rule=rule, row=row)

    assert first.created is True
    assert second.created is False
    assert second.record_id == first.record_id
    assert store.add_task_calls == 1
    assert len(store.tasks) == 1
    assert store.alerts == {}


async def test_duplicate_alert_projection_never_creates_a_second_alert():
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.ALERT)
    row = scheduled_run(rule=rule)

    first = await _project(store, rule=rule, row=row)
    second = await _project(store, rule=rule, row=row)

    assert first.created is True
    assert second.created is False
    assert second.record_id == first.record_id
    assert store.add_alert_calls == 1
    assert len(store.alerts) == 1
    assert store.tasks == {}


@pytest.mark.parametrize("status", [ClawTaskStatus.DONE, ClawTaskStatus.CANCELLED])
async def test_user_mutated_task_status_is_never_reopened(status):
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    row = scheduled_run(rule=rule)
    seeded = _seed_task(store=store, rule=rule, row=row, status=status)

    result = await _project(store, rule=rule, row=row)

    assert result.created is False
    assert store.add_task_calls == 0
    assert store.tasks[seeded.task_id].status is status


async def test_user_dismissed_alert_status_is_never_reopened():
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.ALERT)
    row = scheduled_run(rule=rule)
    seeded = _seed_alert(store=store, row=row, status=ClawAlertStatus.DISMISSED)

    result = await _project(store, rule=rule, row=row)

    assert result.created is False
    assert store.add_alert_calls == 0
    assert store.alerts[seeded.alert_id].status is ClawAlertStatus.DISMISSED


async def test_existing_record_with_foreign_identity_fails_closed():
    store = MemoryTaskAlertStore()
    rule = make_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    row = scheduled_run(rule=rule)
    seeded = _seed_task(store=store, rule=rule, row=row, status=ClawTaskStatus.OPEN)
    store.tasks[seeded.task_id] = ClawFollowupTask(
        task_id=seeded.task_id,
        workspace_id=WORKSPACE,
        member_id="member_other",
        title=seeded.title,
        status=seeded.status,
        created_at=seeded.created_at,
        due_date=None,
        source_id=seeded.source_id,
        linked_ref=seeded.linked_ref,
    )

    with pytest.raises(AutomationProjectionError):
        await _project(store, rule=rule, row=row)

    assert store.add_task_calls == 0


# ── boundary + source contract ─────────────────────────────────────────────


def test_projection_is_async_and_guards_are_sync():
    assert inspect.iscoroutinefunction(project_terminal_scheduled_run_to_task_alert)
    assert not inspect.iscoroutinefunction(bridge_module._require_terminal)
    assert not inspect.iscoroutinefunction(bridge_module._require_owner)
    assert not inspect.iscoroutinefunction(bridge_module._require_store)
    assert not inspect.iscoroutinefunction(bridge_module._require_canonical_occurrence)


def test_source_delegates_to_the_existing_authority_and_adds_no_second_authority():
    source = Path(bridge_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        # second persistence / record-shape authority
        "D1ClawTaskAlertStore",
        "INSERT INTO",
        "add_task(",
        "add_alert(",
        "ClawFollowupTask(",
        "ClawAlert(",
        "set_task_status(",
        "set_alert_status(",
        # second run identity / scheduler authority
        "create_claw_run(",
        "occurrence_key(",
        "ClawAutomationTickRuntime",
        "FakeClawScheduler",
        "claim_occurrence(",
        "occurrence_claim(",
        # second owner authority
        "resolve_owner",
        "ClawAutomationOwnerResolver",
        "AutomationOwnerAuthority",
        ".owner_ref",
        # history / session authority (already owned by the #2924 slice)
        "record_claw_run",
        "HistoryStore",
        "get_conversation",
        "validate_conversation_id",
        "conversation_id",
        "append_exchange",
        # execution / provider / sandbox
        "execute_scheduled_occurrence(",
        "update_run_projection(",
        "SandboxLease",
        "PadiemAiEngineClient",
        "httpx",
        "urllib",
        "requests.",
        "asyncio.run(",
    ):
        assert forbidden not in source

    # Exactly one delegation path, and the existing occurrence identity helper.
    assert source.count("project_scheduled_run_output(") == 1
    assert source.count("_derived_occurrence_id(") == 1
    assert "await project_scheduled_run_output(" in source


def test_composition_seam_is_the_only_new_surface():
    public = sorted(
        name for name in vars(bridge_module) if not name.startswith("_")
    )
    assert "project_terminal_scheduled_run_to_task_alert" in public
    assert "ScheduledTaskAlertProjection" in public
    assert "ScheduledTaskAlertProjectionError" in public
    # No store/table/scheduler/session authority was minted by this module.
    assert not hasattr(bridge_module, "D1ClawTaskAlertStore")
    assert not hasattr(bridge_module, "HistoryStore")
    assert not hasattr(bridge_module, "ClawAutomationOwnerResolver")
    assert not hasattr(bridge_module, "project_terminal_scheduled_run_to_history")
