"""#2833 S2F3B — bounded Task/Alert output projection foundation tests.

NETWORK_FREE: no scheduler, no P01 dispatch, no provider call, no run-history
write, no production mutation. Uses an in-memory store double plus a minimal D1
double over the existing ``claw_task_alert`` store contract.

Covers the CENTRAL-fixed product decision (only explicit TASK_PROPOSAL/ALERT on a
COMPLETED run materialize a record), deterministic ids, idempotency that never
reopens a user-mutated status, workspace/member authority from the resolved
owner, and the fail-closed guards.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

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
)
from kagent.claw_memory import (
    ClawAlert,
    ClawAlertKind,
    ClawAlertSeverity,
    ClawAlertStatus,
    ClawFollowupTask,
    ClawMemoryError,
    ClawTaskStatus,
)
from kagent.core import redact_secrets

from app.claw_automation_owner_resolution import ResolvedAutomationOwner
from app.claw_automation_projection_bridge import (
    AutomationProjectionError,
    _deterministic_id,
    project_scheduled_run_output,
)

WS = "ws-1"
WS2 = "ws-2"
MEMBER = "member-1"
RULE_ID = "rule-1"
RUN_ID = "run-1"
RAW_CONTENT = "RAW-OUTPUT-CONTENT-SHOULD-NOT-PERSIST"
NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


# ── fixtures ────────────────────────────────────────────────────────────────


def _owner(*, workspace_id: str = WS, member_id: str = MEMBER) -> ResolvedAutomationOwner:
    return ResolvedAutomationOwner(
        workspace_id=workspace_id,
        owner_ref="owner-opaque-ref-1",
        product_user_id="usr_" + "7" * 32,
        member_id=member_id,
        canonical_subject_id="subject-opaque-1",
    )


def _rule(*, output_type: ClawAutomationOutputType, workspace_id: str = WS, rule_id: str = RULE_ID) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Daily check",
        schedule=ClawScheduleExpression(kind=ClawScheduleKind.INTERVAL, expression="15m"),
        target_source=ClawAutomationTarget.TASKS,
        output_type=output_type,
    )


def _output(*, output_type: ClawAutomationOutputType, workspace_id: str = WS, title: str = "Daily check result") -> ClawAutomationOutput:
    return ClawAutomationOutput(
        output_id="out-1",
        workspace_id=workspace_id,
        output_type=output_type,
        title=title,
        content=RAW_CONTENT,
    )


def _run(
    *,
    rule: ClawAutomationRule,
    status: ClawScheduledRunStatus,
    output: ClawAutomationOutput | None = None,
    workspace_id: str = WS,
    run_id: str = RUN_ID,
    completed_at: datetime | None = NOW,
) -> ClawScheduledRun:
    return ClawScheduledRun(
        run_id=run_id,
        workspace_id=workspace_id,
        rule_id=rule.rule_id,
        status=status,
        scheduled_time=NOW,
        started_at=NOW,
        completed_at=completed_at,
        output=output,
    )


class _MemoryStore:
    """In-memory double of the existing task/alert store surface."""

    def __init__(self) -> None:
        self.tasks: dict[str, ClawFollowupTask] = {}
        self.alerts: dict[str, ClawAlert] = {}

    async def get_task(
        self, task_id: str, *, workspace_id: str, member_id: str
    ) -> ClawFollowupTask | None:
        task = self.tasks.get(task_id)
        if task is None or task.workspace_id != workspace_id:
            return None
        return task if task.member_id == member_id else None

    async def get_alert(self, alert_id: str, *, workspace_id: str, member_id: str) -> ClawAlert | None:
        alert = self.alerts.get(alert_id)
        if alert is None or alert.workspace_id != workspace_id:
            return None
        return alert if alert.is_visible_to(member_id) else None

    async def add_task(self, task: ClawFollowupTask) -> ClawFollowupTask:
        self.tasks[task.task_id] = task
        return task

    async def add_alert(self, alert: ClawAlert) -> ClawAlert:
        self.alerts[alert.alert_id] = alert
        return alert


# ── Task mapping ─────────────────────────────────────────────────────────────


async def test_task_proposal_completed_creates_one_open_task() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL))

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert result.created_kind == "task"
    assert result.created is True
    assert len(store.tasks) == 1
    task = store.tasks[result.record_id]
    assert task.workspace_id == WS
    assert task.member_id == MEMBER
    assert task.status is ClawTaskStatus.OPEN
    assert task.source_id == RUN_ID
    assert task.linked_ref == RULE_ID
    assert task.due_date is None
    assert task.created_at == NOW
    assert len(store.alerts) == 0


async def test_same_run_second_projection_creates_no_second_task() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL))

    first = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    second = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert first.created is True
    assert second.created is False
    assert second.record_id == first.record_id
    assert len(store.tasks) == 1


async def test_existing_done_task_remains_done() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    output = _output(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=output)

    await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    task_id = _deterministic_id(WS, RUN_ID, "task")
    store.tasks[task_id] = ClawFollowupTask(
        task_id=task_id, workspace_id=WS, member_id=MEMBER, title=output.title,
        status=ClawTaskStatus.DONE, created_at=NOW, source_id=RUN_ID, linked_ref=RULE_ID,
    )

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert result.created is False
    assert store.tasks[task_id].status is ClawTaskStatus.DONE


async def test_existing_cancelled_task_remains_cancelled() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    output = _output(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=output)

    await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    task_id = _deterministic_id(WS, RUN_ID, "task")
    store.tasks[task_id] = ClawFollowupTask(
        task_id=task_id, workspace_id=WS, member_id=MEMBER, title=output.title,
        status=ClawTaskStatus.CANCELLED, created_at=NOW, source_id=RUN_ID, linked_ref=RULE_ID,
    )

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert result.created is False
    assert store.tasks[task_id].status is ClawTaskStatus.CANCELLED


# ── Alert mapping ────────────────────────────────────────────────────────────


async def test_alert_completed_creates_one_active_automation_alert() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.ALERT)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.ALERT))

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert result.created_kind == "alert"
    assert result.created is True
    assert len(store.alerts) == 1
    alert = store.alerts[result.record_id]
    assert alert.kind is ClawAlertKind.AUTOMATION
    assert alert.severity is ClawAlertSeverity.INFO
    assert alert.status is ClawAlertStatus.ACTIVE
    assert alert.workspace_id == WS
    assert alert.visible_to_members == (MEMBER,)
    assert alert.visible_to_all is False
    assert len(store.tasks) == 0


async def test_alert_projection_carries_the_run_and_rule_references() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.ALERT)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.ALERT))

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    # #5034: the click target is derived server-side from the run that produced
    # the alert, in run-then-rule order, exactly like the task projection.
    alert = store.alerts[result.record_id]
    assert alert.linked_refs == (RUN_ID, RULE_ID)


async def test_alert_projection_refuses_a_row_written_for_another_run() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.ALERT)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.ALERT))
    alert_id = _deterministic_id(WS, RUN_ID, "alert")
    store.alerts[alert_id] = ClawAlert(
        alert_id=alert_id, workspace_id=WS, kind=ClawAlertKind.AUTOMATION,
        severity=ClawAlertSeverity.INFO, title=run.output.title, created_at=NOW,
        visible_to_members=(MEMBER,), linked_refs=("run-other", RULE_ID),
    )

    # A row whose reference points somewhere else is a foreign identity: it is
    # refused instead of being silently repointed at this run.
    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    assert store.alerts[alert_id].linked_refs == ("run-other", RULE_ID)


async def test_same_run_second_projection_creates_no_second_alert() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.ALERT)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.ALERT))

    first = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    second = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert first.created is True
    assert second.created is False
    assert len(store.alerts) == 1


async def test_existing_dismissed_alert_remains_dismissed() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.ALERT)
    output = _output(output_type=ClawAutomationOutputType.ALERT)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=output)

    await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    alert_id = _deterministic_id(WS, RUN_ID, "alert")
    store.alerts[alert_id] = ClawAlert(
        alert_id=alert_id, workspace_id=WS, kind=ClawAlertKind.AUTOMATION,
        severity=ClawAlertSeverity.INFO, title=output.title, created_at=NOW,
        status=ClawAlertStatus.DISMISSED, visible_to_members=(MEMBER,),
        linked_refs=(RUN_ID, RULE_ID),
    )

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert result.created is False
    assert store.alerts[alert_id].status is ClawAlertStatus.DISMISSED


# ── No-op types ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("output_type", [ClawAutomationOutputType.REPORT, ClawAutomationOutputType.DRAFT])
async def test_report_and_draft_create_nothing(output_type: ClawAutomationOutputType) -> None:
    store = _MemoryStore()
    rule = _rule(output_type=output_type)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=output_type))

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert result.created_kind is None
    assert result.created is False
    assert len(store.tasks) == 0 and len(store.alerts) == 0


# ── No implicit error alert ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status",
    [
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
        ClawScheduledRunStatus.PENDING,
        ClawScheduledRunStatus.RUNNING,
    ],
)
async def test_non_completed_run_creates_nothing(status: ClawScheduledRunStatus) -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.ALERT)

    # FAILED/CANCELLED/PENDING/RUNNING must never create an implicit alert, even
    # when an ALERT-typed output happens to be present on the record.
    run = _run(rule=rule, status=status, output=_output(output_type=ClawAutomationOutputType.ALERT), completed_at=None)

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert result.created_kind is None
    assert result.created is False
    assert len(store.tasks) == 0 and len(store.alerts) == 0


# ── Fail closed ──────────────────────────────────────────────────────────────


async def test_foreign_workspace_owner_rejected() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL))

    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(workspace_id=WS2), rule=rule, run=run, store=store)
    assert len(store.tasks) == 0


async def test_rule_run_workspace_mismatch_rejected() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, workspace_id=WS2, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL))

    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)


async def test_rule_id_mismatch_rejected() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL, rule_id=RULE_ID)
    run = _run(rule=_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL, rule_id="rule-other"), status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL))
    # run.rule_id belongs to a different rule object than the one passed in.
    run = ClawScheduledRun(
        run_id=RUN_ID, workspace_id=WS, rule_id="rule-other", status=ClawScheduledRunStatus.COMPLETED,
        scheduled_time=NOW, started_at=NOW, completed_at=NOW,
        output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL),
    )

    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)


async def test_output_workspace_mismatch_rejected() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL, workspace_id=WS2))

    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)


async def test_output_type_mismatch_rejected() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.ALERT))

    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)


@pytest.mark.parametrize("output_type", [ClawAutomationOutputType.TASK_PROPOSAL, ClawAutomationOutputType.ALERT])
async def test_completed_output_run_without_output_rejected(output_type: ClawAutomationOutputType) -> None:
    store = _MemoryStore()
    rule = _rule(output_type=output_type)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=None)

    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)


async def test_missing_completed_at_rejected() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL), completed_at=None)

    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)


async def test_existing_deterministic_id_with_foreign_identity_rejected() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    output = _output(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=output)

    task_id = _deterministic_id(WS, RUN_ID, "task")
    store.tasks[task_id] = ClawFollowupTask(
        task_id=task_id, workspace_id=WS, member_id=MEMBER, title="a different immutable title",
        status=ClawTaskStatus.OPEN, created_at=NOW, source_id=RUN_ID, linked_ref=RULE_ID,
    )

    with pytest.raises(AutomationProjectionError):
        await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    # The existing record is not overwritten.
    assert store.tasks[task_id].title == "a different immutable title"


# ── Security ─────────────────────────────────────────────────────────────────


async def test_owner_ref_is_never_used_as_member_id() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL))

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    task = store.tasks[result.record_id]
    assert task.member_id == MEMBER
    assert task.member_id != "owner-opaque-ref-1"


async def test_raw_output_content_is_not_persisted() -> None:
    store = _MemoryStore()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL))

    await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    assert RAW_CONTENT not in json.dumps([t.safe_dict() for t in store.tasks.values()], default=str)


async def test_the_owners_own_title_is_stored_unchanged() -> None:
    """#5360: the owner's own business content is not masked by default.

    The record is the owner's own workspace-scoped task, and the diagnostic
    and log surfaces keep their own credential filtering.
    """
    store = _MemoryStore()
    raw_title = "Authorization: Bearer " + "a" * 24
    # Guard: the fixture must actually be secret-shaped for the canonical helper.
    assert redact_secrets(raw_title) != raw_title

    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL, title=raw_title))

    result = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)

    task = store.tasks[result.record_id]
    assert task.title == raw_title
    assert task.member_id == MEMBER
    assert task.workspace_id == WS


# ── D1 adapter proof ─────────────────────────────────────────────────────────


class _Statement:
    """Runs the store's own SQL through a D1-shaped surface over sqlite."""

    def __init__(self, conn, sql: str) -> None:
        self._conn = conn
        self._sql = sql
        self._values: tuple = ()

    def bind(self, *values) -> "_Statement":
        self._values = values
        return self

    async def run(self) -> dict:
        cur = self._conn.execute(self._sql, self._values)
        return {"success": True, "meta": {"changes": cur.rowcount}}

    async def first(self):
        row = self._conn.execute(self._sql, self._values).fetchone()
        return dict(row) if row else None

    async def all(self) -> list:
        return [dict(r) for r in self._conn.execute(self._sql, self._values).fetchall()]


class _FakeD1:
    """sqlite with migration 010, so the member predicate in the real WHERE
    clauses is what these tests observe."""

    def __init__(self) -> None:
        import sqlite3
        from pathlib import Path as _Path

        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        schema = _Path(__file__).resolve().parents[1] / "migrations" / "010_claw_task_alert.sql"
        self.conn.executescript(schema.read_text(encoding="utf-8"))

    @property
    def rows(self) -> dict:
        return {
            row["id"]: dict(row)
            for row in self.conn.execute("SELECT * FROM claw_task_alert").fetchall()
        }

    def prepare(self, sql: str) -> _Statement:
        return _Statement(self.conn, sql)


def _d1_store():
    from app.claw_task_alert_store import D1ClawTaskAlertStore

    db = _FakeD1()
    return D1ClawTaskAlertStore(db), db


async def test_d1_task_first_insert_then_duplicate_no_second_insert() -> None:
    store, db = _d1_store()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL))

    first = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    assert first.created is True
    assert len(db.rows) == 1

    second = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    assert second.created is False
    assert len(db.rows) == 1  # no second insert
    assert (
        await store.get_task(first.record_id, workspace_id=WS, member_id=_owner().member_id)
    ).status is ClawTaskStatus.OPEN


async def test_d1_alert_first_insert_then_duplicate_no_second_insert() -> None:
    store, db = _d1_store()
    rule = _rule(output_type=ClawAutomationOutputType.ALERT)
    run = _run(rule=rule, status=ClawScheduledRunStatus.COMPLETED, output=_output(output_type=ClawAutomationOutputType.ALERT))

    first = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    assert first.created is True
    assert len(db.rows) == 1

    second = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    assert second.created is False
    assert len(db.rows) == 1

    stored = await store.get_alert(first.record_id, workspace_id=WS, member_id=MEMBER)
    assert stored is not None and stored.kind is ClawAlertKind.AUTOMATION


# ── Deterministic id shape ───────────────────────────────────────────────────


def test_deterministic_ids_are_stable_and_distinct() -> None:
    task_id = _deterministic_id(WS, RUN_ID, "task")
    alert_id = _deterministic_id(WS, RUN_ID, "alert")
    assert task_id == _deterministic_id(WS, RUN_ID, "task")
    assert task_id != alert_id
    assert task_id.startswith("automation_task:") and len(task_id) == len("automation_task:") + 64
    assert alert_id.startswith("automation_alert:") and len(alert_id) == len("automation_alert:") + 64
    assert _deterministic_id(WS2, RUN_ID, "task") != task_id


async def test_d1_a_tenant_mate_cannot_read_or_replace_the_projected_task() -> None:
    """#2952 follow-up on the durable store: the projection row belongs to its member."""
    store, db = _d1_store()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(
        rule=rule,
        status=ClawScheduledRunStatus.COMPLETED,
        output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL),
    )

    first = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    assert first.created is True

    other = _owner(member_id="member_other_2952")
    assert await store.get_task(first.record_id, workspace_id=WS, member_id=other.member_id) is None
    with pytest.raises(ClawMemoryError):
        await store.set_task_status(
            first.record_id,
            ClawTaskStatus.DONE,
            workspace_id=WS,
            member_id=other.member_id,
        )

    again = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    assert again.created is False
    assert len(db.rows) == 1
    stored = await store.get_task(first.record_id, workspace_id=WS, member_id=_owner().member_id)
    assert stored is not None and stored.status is ClawTaskStatus.OPEN


async def test_d1_a_second_member_cannot_take_over_the_same_deterministic_row() -> None:
    """Same run, another member: the durable PRIMARY KEY refuses, nothing is rewritten."""
    from app.workspace_storage import WorkspaceStorageError

    store, db = _d1_store()
    rule = _rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL)
    run = _run(
        rule=rule,
        status=ClawScheduledRunStatus.COMPLETED,
        output=_output(output_type=ClawAutomationOutputType.TASK_PROPOSAL),
    )

    first = await project_scheduled_run_output(owner=_owner(), rule=rule, run=run, store=store)
    assert first.created is True

    other = _owner(member_id="member_other_2952")
    with pytest.raises(WorkspaceStorageError):
        await project_scheduled_run_output(owner=other, rule=rule, run=run, store=store)

    assert len(db.rows) == 1
    assert db.rows[first.record_id]["member_id"] == MEMBER
    assert db.rows[first.record_id]["status"] == ClawTaskStatus.OPEN.value
