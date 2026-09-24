"""#2833 S2F5B — recovery-safe PENDING occurrence execution composition tests.

NETWORK_FREE: no scheduler activation, no provider call, no external send, no
connector write, no real sandbox allocation, no Production mutation. The
composition is driven against the REAL in-memory automation store, the REAL
durable tick runtime, the REAL trusted trigger boundary and the REAL owner
resolver, so what is proven is the composition itself, not a stub of it.

Covers the slice's required behavior: one trusted trigger claims and executes one
PENDING occurrence through the existing chain; a duplicate trigger produces no
second occurrence or dispatch; a pre-existing stranded PENDING row is recovered
while a future one is not; a disabled rule and an inactive membership are not
executed; a missing or foreign owner fails closed before P01; exactly one of two
claimants wins; a RUNNING row is never redispatched and a terminal row is only
ever retried through the existing projections; REPORT/DRAFT writes no Task/Alert
while TASK_PROPOSAL/ALERT delegates to the existing authority; a P01 failure
terminalizes only through the existing terminal bridge; and no second authority
of any kind is introduced.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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
    _derived_occurrence_id,
)
from kagent.claw_automation_trigger import (
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
)
from kagent.claw_memory import ClawAlert, ClawFollowupTask
from kagent.contracts import ClawRunStatus
from kagent.p01_adapter import ClawOrchestrationOutcome, P01AdapterError
from kagent.runs import ClawRun
from kagent.workspace_visibility import (
    TrustedWorkspaceMembershipProjection,
    WorkspaceRole,
)
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

from app import claw_automation_terminal_outcome_bridge as terminal_bridge_module
from app.claw_automation_background_execution import (
    BackgroundExecutionCompositionError,
    compose_background_execution,
)
from app.claw_automation_owner_resolution import (
    ClawAutomationOwnerResolver,
    TrustedAutomationOwnerProjection,
)
from app.control_plane_identity_shadow import IdentityShadowRecord

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
EARLIER = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
FUTURE = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
WORKSPACE = "tenant_0123456789abcdef0123456789abcdef"
FOREIGN_WORKSPACE = "tenant_fedcba9876543210fedcba9876543210"
RULE_ID = "rule_s2f5b_1"
FOREIGN_RULE_ID = "rule_s2f5b_foreign"
REVISION = "b" * 40
OWNER_REF = "owner:opaque:provenance:1"
OWNER_USER = "usr_" + "7" * 32
FOREIGN_USER = "usr_" + "f" * 32
MEMBER = "member_0001"
SUBJECT = "sub_0123456789abcdef0123456789abcdef"
FOREIGN_SUBJECT = "sub_fedcba9876543210fedcba9876543210"
SESSION = "authsession:b62:123"
AUTHORITY_REF = "authority:owner:registry"
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")
MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "claw_automation_background_execution.py"
)


# ── fixtures ────────────────────────────────────────────────────────────────


def make_rule(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    output_type: ClawAutomationOutputType = ClawAutomationOutputType.ALERT,
    owner_ref: str | None = OWNER_REF,
    canonical_subject_id: str | None = SUBJECT,
    enabled: bool = True,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Daily automation check",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=output_type,
        enabled=enabled,
        owner_ref=owner_ref,
        canonical_subject_id=canonical_subject_id,
        execution_intent=ClawAutomationExecutionIntent(
            task="Produce the scheduled bounded check",
            repository_ref="repo:padiem/ai-revenue-lab",
            exact_revision=REVISION,
        ),
    )


def scheduled_run(
    *,
    rule: ClawAutomationRule | None = None,
    scheduled_time: datetime = NOW,
    status: ClawScheduledRunStatus = ClawScheduledRunStatus.PENDING,
) -> ClawScheduledRun:
    rule = rule or make_rule()
    terminal = status in {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }
    return ClawScheduledRun(
        run_id=_derived_occurrence_id(
            "sched_run", rule.workspace_id, rule.rule_id, scheduled_time
        ),
        workspace_id=rule.workspace_id,
        rule_id=rule.rule_id,
        status=status,
        scheduled_time=scheduled_time,
        started_at=scheduled_time,
        completed_at=scheduled_time if terminal else None,
    )


def membership(
    *,
    workspace_id: str = WORKSPACE,
    at: datetime = NOW,
    issued_offset_hours: int = -1,
    expires_offset_hours: int = 1,
) -> TrustedWorkspaceMembershipProjection:
    return TrustedWorkspaceMembershipProjection(
        membership_id="membership:owner",
        workspace_id=workspace_id,
        principal_ref=SUBJECT,
        role=WorkspaceRole.OWNER,
        authority_ref="control-plane:membership",
        issued_at=at + timedelta(hours=issued_offset_hours),
        expires_at=at + timedelta(hours=expires_offset_hours),
    )


def make_trigger(
    *,
    workspace_id: str = WORKSPACE,
    observed_at: datetime = NOW,
    membership_projection: object = None,
) -> ClawAutomationTrigger:
    if membership_projection is None:
        membership_projection = membership(workspace_id=workspace_id, at=observed_at)
    return ClawAutomationTrigger(
        trigger_id="trigger:cloud_cron",
        correlation_id="corr:0001",
        workspace_id=workspace_id,
        observed_at=observed_at,
        membership=membership_projection,
    )


class _OwnerAuthority:
    def __init__(self, projection=None) -> None:
        self.projection = projection
        self.calls: list[tuple[str, str]] = []

    def resolve_automation_owner(self, *, owner_ref, workspace_id, now):
        self.calls.append((owner_ref, workspace_id))
        return self.projection


class _SessionAuthority:
    def __init__(self, session=None) -> None:
        self.session = session
        self.calls: list[str] = []

    def resolve_auth_session(self, *, session_id):
        self.calls.append(session_id)
        return self.session


class _ShadowStore:
    def __init__(self, record=None) -> None:
        self.record = record

    async def save_projection(self, value):  # pragma: no cover - never called
        raise AssertionError("owner resolution must never write the shadow store")

    async def load_projection(self, product_user_id):
        if self.record is not None and self.record.product_user_id == product_user_id:
            return self.record
        return None


def _session(*, subject: str = SUBJECT) -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id=SESSION,
        product_id="b62",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=2),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )


def _shadow(*, subject: str = SUBJECT) -> IdentityShadowRecord:
    return IdentityShadowRecord(
        product_user_id=OWNER_USER,
        canonical_subject_id=subject,
        auth_session_id=SESSION,
        session_revision=1,
        session_state="active",
        session_expires_at=NOW + timedelta(hours=2),
        observed_at=NOW - timedelta(minutes=5),
    )


def _owner_projection(
    *,
    workspace_id: str = WORKSPACE,
    product_user_id: str = OWNER_USER,
    subject: str = SUBJECT,
) -> TrustedAutomationOwnerProjection:
    return TrustedAutomationOwnerProjection(
        owner_ref=OWNER_REF,
        workspace_id=workspace_id,
        product_user_id=product_user_id,
        member_id=MEMBER,
        canonical_subject_id=subject,
        authority_ref=AUTHORITY_REF,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )


def resolver(
    *,
    workspace_id: str = WORKSPACE,
    product_user_id: str = OWNER_USER,
    subject: str = SUBJECT,
    projection: object = ...,
) -> ClawAutomationOwnerResolver:
    if projection is ...:
        projection = _owner_projection(
            workspace_id=workspace_id, product_user_id=product_user_id, subject=subject
        )
    return ClawAutomationOwnerResolver(
        owner_authority=_OwnerAuthority(projection),
        session_authority=_SessionAuthority(_session(subject=subject)),
        shadow_store=_ShadowStore(_shadow(subject=subject)),
    )


def unavailable_resolver() -> ClawAutomationOwnerResolver:
    return ClawAutomationOwnerResolver(
        owner_authority=None, session_authority=None, shadow_store=None
    )


class OutcomeAdapter:
    """Deterministic P01 double that returns a terminal orchestration outcome."""

    def __init__(self, *, status: ClawRunStatus = ClawRunStatus.COMPLETED) -> None:
        self.status = status
        self.calls: list[ClawRun] = []

    async def execute(self, run, *, lease=None, product_tier=None):
        self.calls.append(run)
        if self.status is ClawRunStatus.FAILED:
            run.transition(ClawRunStatus.FAILED, summary="failed")
        elif self.status is ClawRunStatus.CANCELLED:
            run.transition(ClawRunStatus.CANCELLED, summary="cancelled")
        else:
            run.transition(ClawRunStatus.PREPARING, summary="prepared")
            run.transition(ClawRunStatus.RUNNING, summary="running")
            run.transition(ClawRunStatus.COMPLETED, summary="completed")
        return ClawOrchestrationOutcome(
            projection=run.projection(),
            answer="bounded P01 answer" if self.status is ClawRunStatus.COMPLETED else None,
            p01_run_id="p01-correlated",
            p01_event_count=3,
        )


class RaisingAdapter:
    def __init__(self, *, cancellation: bool = False) -> None:
        self.calls: list[ClawRun] = []
        self.cancellation = cancellation

    async def execute(self, run, *, lease=None, product_tier=None):
        self.calls.append(run)
        if self.cancellation:
            run.transition(ClawRunStatus.CANCELLED, summary="cancelled")
            raise asyncio.CancelledError()
        run.transition(ClawRunStatus.FAILED, summary="failed")
        raise P01AdapterError("p01_execution_failed", "safe failure")


class RecordingHistoryStore:
    """Contract double mirroring the existing (user_id, run_id) upsert."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.record_calls: list[dict] = []

    async def record_claw_run(self, **kwargs) -> None:
        self.record_calls.append(kwargs)
        self.rows[(kwargs["user_id"], kwargs["run_id"])] = dict(kwargs)


class RecordingTaskAlertStore:
    """Counting double of the existing Task/Alert store surface."""

    def __init__(self) -> None:
        self.tasks: dict[str, ClawFollowupTask] = {}
        self.alerts: dict[str, ClawAlert] = {}
        self.reads = 0
        self.writes = 0
        self.add_task_calls = 0
        self.add_alert_calls = 0

    async def get_task(self, task_id: str, *, workspace_id: str):
        self.reads += 1
        task = self.tasks.get(task_id)
        return task if task is not None and task.workspace_id == workspace_id else None

    async def get_alert(self, alert_id: str, *, workspace_id: str, member_id=None):
        self.reads += 1
        alert = self.alerts.get(alert_id)
        if alert is None or alert.workspace_id != workspace_id:
            return None
        if member_id is not None and not alert.is_visible_to(member_id):
            return None
        return alert

    async def add_task(self, task: ClawFollowupTask):
        self.writes += 1
        self.add_task_calls += 1
        self.tasks[task.task_id] = task
        return task

    async def add_alert(self, alert: ClawAlert):
        self.writes += 1
        self.add_alert_calls += 1
        self.alerts[alert.alert_id] = alert
        return alert


class CompetingClaimantStore:
    """Delegates to the real store after letting another claimant win first."""

    def __init__(self, inner, *, mode: str) -> None:
        self._inner = inner
        self._mode = mode
        self.competing_calls = 0

    def _win_first(self, run: ClawScheduledRun) -> None:
        if self._mode == "running":
            self._inner.update_run_projection(
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                rule_id=run.rule_id,
                scheduled_time=run.scheduled_time,
                status=ClawScheduledRunStatus.RUNNING,
            )
            return
        rule = self._inner.get_rule(run.rule_id, run.workspace_id)
        self._inner.update_run_projection(
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            rule_id=run.rule_id,
            scheduled_time=run.scheduled_time,
            status=ClawScheduledRunStatus.COMPLETED,
            completed_at=NOW,
            output=ClawAutomationOutput(
                output_id="scheduled_output_race",
                workspace_id=run.workspace_id,
                output_type=rule.output_type,
                title=rule.name,
                content="bounded race answer",
            ),
        )

    def claim_execution(self, *, run_id, workspace_id, rule_id, scheduled_time):
        self.competing_calls += 1
        row = self._inner.get_run(run_id, workspace_id)
        if row is not None:
            self._win_first(row)
        return self._inner.claim_execution(
            run_id=run_id,
            workspace_id=workspace_id,
            rule_id=rule_id,
            scheduled_time=scheduled_time,
        )

    def __getattr__(self, name):
        return getattr(self._inner, name)


class ProjectionFailingStore:
    """Delegate every authority except the terminal projection write."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def update_run_projection(self, **kwargs):
        raise RuntimeError("projection authority failed")

    def __getattr__(self, name):
        return getattr(self._inner, name)


class Harness:
    """One real store + real tick + real boundary, plus deterministic doubles."""

    def __init__(self, *, adapter=None, owner_resolver=None, store=None) -> None:
        self.store = store or InMemoryClawAutomationStore()
        self.runtime = ClawAutomationTickRuntime(self.store)
        self.boundary = ClawAutomationTriggerBoundary(self.runtime)
        self.adapter = adapter or OutcomeAdapter()
        self.owner_resolver = owner_resolver or resolver()
        self.history = RecordingHistoryStore()
        self.task_alert = RecordingTaskAlertStore()

    async def compose(self, trigger, *, recovery_bound=8, store=None, **kwargs):
        return await compose_background_execution(
            trigger=trigger,
            boundary=self.boundary,
            store=store if store is not None else self.store,
            adapter=self.adapter,
            owner_resolver=self.owner_resolver,
            history_store=self.history,
            task_alert_store=self.task_alert,
            recovery_bound=recovery_bound,
            completed_at=NOW,
            **kwargs,
        )


def run_id_for(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    scheduled_time: datetime = NOW,
) -> str:
    return _derived_occurrence_id("sched_run", workspace_id, rule_id, scheduled_time)


def seed_pending(store, *, rule=None, scheduled_time: datetime = NOW):
    rule = rule or make_rule()
    store.save_rule(rule)
    row = scheduled_run(rule=rule, scheduled_time=scheduled_time)
    store.record_run(row)
    return rule, row


def source_text() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


# ── 1. one trusted trigger claims and executes one occurrence ───────────────


async def test_trusted_trigger_claims_and_executes_one_occurrence():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)

    receipt = await harness.compose(make_trigger())

    expected = run_id_for()
    assert receipt.newly_claimed_run_ids == (expected,)
    assert receipt.execution_claimed_run_ids == (expected,)
    assert receipt.terminal_run_ids == (expected,)
    assert receipt.recovered_pending_run_ids == ()
    assert receipt.running_unresolved_run_ids == ()
    assert receipt.failed_before_dispatch_run_ids == ()
    assert receipt.dispatch_failed_run_ids == ()
    assert len(harness.adapter.calls) == 1
    assert harness.adapter.calls[0].run_id == expected
    assert harness.store.get_run(expected, WORKSPACE).status is ClawScheduledRunStatus.COMPLETED


async def test_legacy_rule_is_not_background_dispatched():
    harness = Harness()
    legacy = make_rule(canonical_subject_id=None)
    harness.store.save_rule(legacy)

    receipt = await harness.compose(make_trigger())

    assert receipt.execution_claimed_run_ids == ()
    assert receipt.failed_before_dispatch_run_ids == ()
    assert harness.store.get_run(run_id_for(), WORKSPACE) is None


async def test_execution_projects_into_existing_history_and_task_alert():
    harness = Harness()
    harness.store.save_rule(make_rule(output_type=ClawAutomationOutputType.ALERT))

    await harness.compose(make_trigger())

    expected = run_id_for()
    assert len(harness.history.record_calls) == 1
    record = harness.history.record_calls[0]
    assert record["run_id"] == expected
    assert record["user_id"] == OWNER_USER
    assert record["status"] == "completed"
    assert record["workspace_id"] == WORKSPACE
    assert harness.task_alert.add_alert_calls == 1
    assert harness.task_alert.add_task_calls == 0


# ── 2. duplicate trigger -----------------------------------------------------


async def test_duplicate_trigger_produces_no_second_occurrence_or_dispatch():
    harness = Harness()
    harness.store.save_rule(make_rule())
    trigger = make_trigger()

    first = await harness.compose(trigger)
    second = await harness.compose(trigger)

    assert first.newly_claimed_run_ids == (run_id_for(),)
    assert second.newly_claimed_run_ids == ()
    assert second.execution_claimed_run_ids == ()
    assert len(harness.adapter.calls) == 1
    assert len(harness.store.list_runs(WORKSPACE)) == 1


# ── 3. recovery of a stranded PENDING row ------------------------------------


async def test_stranded_pending_row_is_recovered_and_executed():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    stranded = scheduled_run(rule=rule, scheduled_time=EARLIER)
    harness.store.record_run(stranded)

    receipt = await harness.compose(make_trigger())

    assert receipt.recovered_pending_run_ids == (stranded.run_id,)
    assert stranded.run_id in receipt.execution_claimed_run_ids
    assert stranded.run_id in receipt.terminal_run_ids
    executed = [run.run_id for run in harness.adapter.calls]
    assert stranded.run_id in executed
    assert harness.store.get_run(stranded.run_id, WORKSPACE).status is (
        ClawScheduledRunStatus.COMPLETED
    )


async def test_recovery_bound_is_reported_and_enforced():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    stranded = [
        scheduled_run(rule=rule, scheduled_time=EARLIER - timedelta(days=offset))
        for offset in range(4)
    ]
    for row in stranded:
        harness.store.record_run(row)

    receipt = await harness.compose(make_trigger(), recovery_bound=2)

    assert receipt.recovery_bound == 2
    assert len(receipt.recovered_pending_run_ids) == 2
    assert set(receipt.recovered_pending_run_ids) == {
        row.run_id for row in sorted(stranded, key=lambda r: r.scheduled_time)[:2]
    }


async def test_future_pending_row_is_not_executed():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    future = scheduled_run(rule=rule, scheduled_time=FUTURE)
    harness.store.record_run(future)

    receipt = await harness.compose(make_trigger())

    assert future.run_id not in receipt.recovered_pending_run_ids
    assert future.run_id not in receipt.execution_claimed_run_ids
    assert future.run_id not in {run.run_id for run in harness.adapter.calls}
    assert harness.store.get_run(future.run_id, WORKSPACE).status is (
        ClawScheduledRunStatus.PENDING
    )


async def test_other_workspace_pending_row_is_not_enumerated():
    harness = Harness()
    foreign_rule = make_rule(workspace_id=FOREIGN_WORKSPACE, rule_id=FOREIGN_RULE_ID)
    harness.store.save_rule(foreign_rule)
    foreign_row = scheduled_run(rule=foreign_rule, scheduled_time=EARLIER)
    harness.store.record_run(foreign_row)
    harness.store.save_rule(make_rule())

    receipt = await harness.compose(make_trigger())

    assert foreign_row.run_id not in receipt.recovered_pending_run_ids
    assert foreign_row.run_id not in receipt.execution_claimed_run_ids
    assert foreign_row.run_id not in {run.run_id for run in harness.adapter.calls}
    assert harness.store.get_run(foreign_row.run_id, FOREIGN_WORKSPACE).status is (
        ClawScheduledRunStatus.PENDING
    )


# ── 4/5. filtered candidates ------------------------------------------------


async def test_disabled_rule_is_not_executed():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    row = scheduled_run(rule=rule, scheduled_time=EARLIER)
    harness.store.record_run(row)
    harness.store.set_rule_enabled(WORKSPACE, RULE_ID, False)

    receipt = await harness.compose(make_trigger())

    assert receipt.recovered_pending_run_ids == ()
    assert receipt.execution_claimed_run_ids == ()
    assert harness.adapter.calls == []
    assert harness.store.get_run(row.run_id, WORKSPACE).status is (
        ClawScheduledRunStatus.PENDING
    )


@pytest.mark.parametrize("issued_offset_hours,expires_offset_hours", [(-3, -2), (1, 3)])
async def test_inactive_membership_is_not_executed(issued_offset_hours, expires_offset_hours):
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    row = scheduled_run(rule=rule, scheduled_time=EARLIER)
    harness.store.record_run(row)
    inactive = membership(
        at=NOW,
        issued_offset_hours=issued_offset_hours,
        expires_offset_hours=expires_offset_hours,
    )

    receipt = await harness.compose(
        make_trigger(membership_projection=inactive)
    )

    assert receipt.newly_claimed_run_ids == ()
    assert receipt.recovered_pending_run_ids == ()
    assert harness.adapter.calls == []
    assert harness.store.get_run(row.run_id, WORKSPACE).status is (
        ClawScheduledRunStatus.PENDING
    )


# ── 6. owner authority fails closed before P01 ------------------------------


async def test_absent_owner_provenance_fails_before_p01():
    harness = Harness()
    rule = make_rule(owner_ref=None)
    harness.store.save_rule(rule)

    receipt = await harness.compose(make_trigger())

    expected = run_id_for()
    assert receipt.failed_before_dispatch_run_ids == (expected,)
    assert receipt.execution_claimed_run_ids == ()
    assert harness.adapter.calls == []
    assert harness.store.get_run(expected, WORKSPACE).status is (
        ClawScheduledRunStatus.PENDING
    )


async def test_owner_refused_row_stays_pending_and_is_reported_every_trigger():
    harness = Harness()
    rule = make_rule(owner_ref=None)
    harness.store.save_rule(rule)
    trigger = make_trigger()

    first = await harness.compose(trigger)
    second = await harness.compose(trigger)

    expected = run_id_for()
    assert first.failed_before_dispatch_run_ids == (expected,)
    assert second.failed_before_dispatch_run_ids == (expected,)
    assert second.execution_claimed_run_ids == ()
    assert harness.adapter.calls == []
    assert harness.store.get_run(expected, WORKSPACE).status is (
        ClawScheduledRunStatus.PENDING
    )


async def test_foreign_owner_projection_fails_before_p01():
    harness = Harness(owner_resolver=resolver(workspace_id=FOREIGN_WORKSPACE))
    harness.store.save_rule(make_rule())

    receipt = await harness.compose(make_trigger())

    assert receipt.failed_before_dispatch_run_ids == (run_id_for(),)
    assert harness.adapter.calls == []
    assert harness.store.get_run(run_id_for(), WORKSPACE).status is (
        ClawScheduledRunStatus.PENDING
    )


async def test_mismatched_owner_subject_fails_before_p01():
    harness = Harness(
        owner_resolver=resolver(projection=_owner_projection(subject=FOREIGN_SUBJECT))
    )
    harness.store.save_rule(make_rule())

    receipt = await harness.compose(make_trigger())

    assert receipt.failed_before_dispatch_run_ids == (run_id_for(),)
    assert harness.adapter.calls == []


async def test_unavailable_owner_authority_fails_before_p01():
    harness = Harness(owner_resolver=unavailable_resolver())
    harness.store.save_rule(make_rule())

    receipt = await harness.compose(make_trigger())

    assert receipt.failed_before_dispatch_run_ids == (run_id_for(),)
    assert harness.adapter.calls == []


# ── 7/8/9. claim races -------------------------------------------------------


async def test_lost_claim_on_a_running_row_is_reported_unresolved():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    racing = CompetingClaimantStore(harness.store, mode="running")

    receipt = await harness.compose(make_trigger(), store=racing)

    expected = run_id_for()
    assert racing.competing_calls == 1
    assert receipt.running_unresolved_run_ids == (expected,)
    assert receipt.execution_claimed_run_ids == ()
    assert harness.adapter.calls == []
    assert harness.store.get_run(expected, WORKSPACE).status is (
        ClawScheduledRunStatus.RUNNING
    )


async def test_running_row_is_never_redispatched():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    running = scheduled_run(rule=rule, status=ClawScheduledRunStatus.RUNNING)
    harness.store.record_run(running)

    receipt = await harness.compose(make_trigger())

    assert harness.adapter.calls == []
    assert receipt.execution_claimed_run_ids == ()
    assert running.run_id not in receipt.terminal_run_ids
    assert harness.store.get_run(running.run_id, WORKSPACE).status is (
        ClawScheduledRunStatus.RUNNING
    )


async def test_terminal_row_is_never_redispatched():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    completed = scheduled_run(rule=rule, status=ClawScheduledRunStatus.COMPLETED)
    harness.store.record_run(completed)

    receipt = await harness.compose(make_trigger())

    assert harness.adapter.calls == []
    assert receipt.execution_claimed_run_ids == ()
    assert receipt.terminal_run_ids == ()
    assert harness.store.get_run(completed.run_id, WORKSPACE).status is (
        ClawScheduledRunStatus.COMPLETED
    )


async def test_terminal_row_reached_by_race_is_projection_only_retry():
    harness = Harness()
    rule = make_rule(output_type=ClawAutomationOutputType.ALERT)
    harness.store.save_rule(rule)
    racing = CompetingClaimantStore(harness.store, mode="terminal")

    receipt = await harness.compose(make_trigger(), store=racing)

    expected = run_id_for()
    assert racing.competing_calls == 1
    assert receipt.projection_only_run_ids == (expected,)
    assert receipt.terminal_run_ids == (expected,)
    assert receipt.execution_claimed_run_ids == ()
    assert harness.adapter.calls == []
    assert [call["run_id"] for call in harness.history.record_calls] == [expected]
    assert harness.task_alert.add_alert_calls == 1


async def test_projection_only_retry_is_idempotent_and_preserves_one_record():
    harness = Harness()
    rule = make_rule(output_type=ClawAutomationOutputType.ALERT)
    harness.store.save_rule(rule)
    racing = CompetingClaimantStore(harness.store, mode="terminal")

    await harness.compose(make_trigger(), store=racing)
    await harness.compose(make_trigger(), store=racing)

    expected = run_id_for()
    assert len(harness.history.rows) == 1
    assert harness.history.rows[(OWNER_USER, expected)]["status"] == "completed"
    assert harness.task_alert.add_alert_calls == 1
    assert len(harness.task_alert.alerts) == 1
    assert harness.adapter.calls == []


# ── 10. Task/Alert output routing -------------------------------------------


@pytest.mark.parametrize("output_type", [ClawAutomationOutputType.REPORT, ClawAutomationOutputType.DRAFT])
async def test_completed_report_or_draft_writes_no_task_alert(output_type):
    harness = Harness()
    harness.store.save_rule(make_rule(output_type=output_type))

    await harness.compose(make_trigger())

    assert harness.task_alert.writes == 0
    assert harness.task_alert.reads == 0
    assert len(harness.history.record_calls) == 1


@pytest.mark.parametrize(
    "output_type,expected_task,expected_alert",
    [
        (ClawAutomationOutputType.TASK_PROPOSAL, 1, 0),
        (ClawAutomationOutputType.ALERT, 0, 1),
    ],
)
async def test_completed_proposal_or_alert_delegates_to_existing_authority(
    output_type, expected_task, expected_alert
):
    harness = Harness()
    harness.store.save_rule(make_rule(output_type=output_type))

    await harness.compose(make_trigger())

    assert harness.task_alert.add_task_calls == expected_task
    assert harness.task_alert.add_alert_calls == expected_alert


# ── 11. P01 failure / cancellation ------------------------------------------


async def test_p01_failure_terminalizes_only_through_existing_bridge():
    harness = Harness(adapter=RaisingAdapter())
    harness.store.save_rule(make_rule())

    receipt = await harness.compose(make_trigger())

    expected = run_id_for()
    assert receipt.dispatch_failed_run_ids == (expected,)
    assert receipt.terminal_run_ids == (expected,)
    stored = harness.store.get_run(expected, WORKSPACE)
    assert stored.status is ClawScheduledRunStatus.FAILED
    assert stored.error_message == terminal_bridge_module._FAILED_MESSAGE
    assert harness.task_alert.writes == 0
    assert [call["status"] for call in harness.history.record_calls] == ["failed"]


async def test_projection_authority_failure_propagates_instead_of_becoming_dispatch_failure():
    harness = Harness()
    harness.store.save_rule(make_rule())
    failing_store = ProjectionFailingStore(harness.store)

    with pytest.raises(RuntimeError, match="projection authority failed"):
        await harness.compose(make_trigger(), store=failing_store)

    expected = run_id_for()
    assert [run.run_id for run in harness.adapter.calls] == [expected]
    assert harness.store.get_run(expected, WORKSPACE).status is (
        ClawScheduledRunStatus.RUNNING
    )
    assert harness.history.record_calls == []
    assert harness.task_alert.writes == 0


async def test_failed_run_produces_no_task_alert_creation():
    harness = Harness(adapter=RaisingAdapter())
    harness.store.save_rule(make_rule(output_type=ClawAutomationOutputType.TASK_PROPOSAL))

    await harness.compose(make_trigger())

    assert harness.task_alert.add_task_calls == 0
    assert harness.task_alert.add_alert_calls == 0
    assert harness.task_alert.writes == 0


async def test_cancellation_propagates_and_creates_no_task_alert():
    harness = Harness(adapter=RaisingAdapter(cancellation=True))
    harness.store.save_rule(make_rule(output_type=ClawAutomationOutputType.ALERT))

    with pytest.raises(asyncio.CancelledError):
        await harness.compose(make_trigger())

    assert harness.store.get_run(run_id_for(), WORKSPACE).status is (
        ClawScheduledRunStatus.CANCELLED
    )
    assert harness.task_alert.writes == 0


async def test_one_poisoned_candidate_does_not_stop_the_others():
    harness = Harness(adapter=RaisingAdapter())
    rule = make_rule()
    harness.store.save_rule(rule)
    stranded = scheduled_run(rule=rule, scheduled_time=EARLIER)
    harness.store.record_run(stranded)

    receipt = await harness.compose(make_trigger())

    assert len(receipt.dispatch_failed_run_ids) == 2
    assert set(receipt.dispatch_failed_run_ids) == {stranded.run_id, run_id_for()}


# ── 12. input validation -----------------------------------------------------


@pytest.mark.parametrize("bad", [None, {"workspace_id": WORKSPACE}, "trigger", 0, False])
async def test_non_trigger_input_is_refused(bad):
    harness = Harness()

    with pytest.raises(BackgroundExecutionCompositionError):
        await harness.compose(bad)


@pytest.mark.parametrize("bad", [65, -1, True, 1.5, "8"])
async def test_recovery_bound_is_bounded(bad):
    harness = Harness()
    harness.store.save_rule(make_rule())

    with pytest.raises(BackgroundExecutionCompositionError):
        await harness.compose(make_trigger(), recovery_bound=bad)


async def test_zero_recovery_bound_disables_recovery_without_failing():
    harness = Harness()
    rule = make_rule()
    harness.store.save_rule(rule)
    stranded = scheduled_run(rule=rule, scheduled_time=EARLIER)
    harness.store.record_run(stranded)

    receipt = await harness.compose(make_trigger(), recovery_bound=0)

    assert receipt.recovery_bound == 0
    assert receipt.recovered_pending_run_ids == ()
    assert stranded.run_id not in {run.run_id for run in harness.adapter.calls}
    assert harness.store.get_run(stranded.run_id, WORKSPACE).status is (
        ClawScheduledRunStatus.PENDING
    )


async def test_membership_for_another_workspace_is_refused():
    harness = Harness()

    with pytest.raises(BackgroundExecutionCompositionError):
        await harness.compose(
            make_trigger(membership_projection=membership(workspace_id=FOREIGN_WORKSPACE))
        )


async def test_boundary_without_a_tick_runtime_is_refused():
    harness = Harness()
    harness.store.save_rule(make_rule())

    with pytest.raises(Exception):
        await compose_background_execution(
            trigger=make_trigger(),
            boundary=object(),
            store=harness.store,
            adapter=harness.adapter,
            owner_resolver=harness.owner_resolver,
            history_store=harness.history,
            task_alert_store=harness.task_alert,
        )


# ── 13. receipt hygiene and no second authority -----------------------------


async def test_receipt_is_bounded_ids_only_and_locks_every_side_effect():
    harness = Harness()
    harness.store.save_rule(make_rule())

    payload = (await harness.compose(make_trigger())).safe_dict()

    assert payload["provider_calls"] == 0
    assert payload["external_sends"] == 0
    assert payload["connector_writes"] == 0
    assert payload["real_sandbox_allocations"] == 0
    assert payload["second_scheduler_authority"] == 0
    assert payload["second_run_id"] == 0
    assert payload["second_dedup_authority"] == 0
    assert payload["second_owner_authority"] == 0
    assert payload["second_p01_authority"] == 0
    assert payload["second_history_store"] == 0
    assert payload["second_session_authority"] == 0
    assert payload["second_task_alert_authority"] == 0
    assert payload["running_auto_redispatch"] == 0
    assert payload["terminal_p01_redispatch"] == 0
    assert payload["production_scheduler_activation"] == 0
    assert payload["production_mutation"] == 0
    for marker in ("secret", "credential", "api_key", "product_user_id", "canonical_subject_id"):
        assert marker not in repr(payload)


def test_receipt_rejects_duplicate_and_inconsistent_ids():
    from app.claw_automation_background_execution import BackgroundExecutionReceipt

    base = dict(
        workspace_id=WORKSPACE,
        trigger_id="trigger:cloud_cron",
        observed_at=NOW,
        recovery_bound=1,
        newly_claimed_run_ids=(),
        recovered_pending_run_ids=(),
        execution_claimed_run_ids=(),
        terminal_run_ids=(),
        projection_only_run_ids=(),
        running_unresolved_run_ids=(),
        failed_before_dispatch_run_ids=(),
        dispatch_failed_run_ids=(),
    )
    assert BackgroundExecutionReceipt(**base).recovery_bound == 1
    with pytest.raises(BackgroundExecutionCompositionError):
        BackgroundExecutionReceipt(**{**base, "terminal_run_ids": ("run_a", "run_a")})
    with pytest.raises(BackgroundExecutionCompositionError):
        BackgroundExecutionReceipt(**{**base, "dispatch_failed_run_ids": ("run_a",)})
    with pytest.raises(BackgroundExecutionCompositionError):
        BackgroundExecutionReceipt(
            **{**base, "projection_only_run_ids": ("run_a",), "terminal_run_ids": ()}
        )


def test_source_reuses_existing_authorities_and_adds_no_new_one():
    source = source_text()

    for reused in (
        "from .claw_automation_execution_bridge import P01ExecutionPort",
        "execute_and_project_scheduled_occurrence",
        "project_terminal_scheduled_run_to_history",
        "project_terminal_scheduled_run_to_task_alert",
        "ClawAutomationOwnerResolver",
    ):
        assert reused in source
    for forbidden in (
        "uuid4",
        "CREATE TABLE",
        "SandboxLease(",
        "import httpx",
        "import requests",
        "import socket",
        "store.update_run_projection(",
        "def project_terminal",
        "ClawRun(",
    ):
        assert forbidden not in source


def test_adapter_receives_only_the_canonical_occurrence_identity():
    adapter = OutcomeAdapter()
    harness = Harness(adapter=adapter)
    harness.store.save_rule(make_rule())

    asyncio.run(harness.compose(make_trigger()))

    assert [run.run_id for run in adapter.calls] == [run_id_for()]


def test_module_declares_no_claim_or_lease_authority():
    source = source_text()

    assert "claim_execution" in source
    assert "new_claim_token" not in source
    assert "lock_table" not in source
