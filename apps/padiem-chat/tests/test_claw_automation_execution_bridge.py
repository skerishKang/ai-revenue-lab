"""#2833 S2F4B — canonical scheduled execution bridge tests.

NETWORK_FREE / ``PRODUCTION_MUTATION=0``: a recording fake stands in for the
already-composed P01 adapter (plus one real-adapter fail-closed probe with a
runner that must never be called). No provider, no transport, no model router,
no sandbox lease minting, no scheduler activation, no History/Task/Alert
write, no external send.

Proves the slice acceptance:

```text
SAME_SCHEDULED_RUN_ID_TO_P01   one occurrence -> one sched_run_<digest>
                               -> existing P01 execute() called exactly once
SECOND_RUN_ID=0                no second run id anywhere in the bridge
SECOND_DEDUP_AUTHORITY=0       occurrence claim stays the tick/store's
CANONICAL_*_REUSED             intent / ClawRun / P01 adapter all reused
SCOPE_PRESERVED                workspace / rule / requested revision
NO_DIRECT_PROVIDER_CALL        source-scan + counting runner never entered
NO_NEW_MODEL_ROUTER            source-scan
NO_NEW_SANDBOX_AUTHORITY       source-scan + real adapter fails closed
P01_FAILURE_FAILS_CLOSED       adapter error propagates unchanged
DUPLICATE_EXECUTION_HELPER=0   exactly one execution surface in the bridge
```
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path

import pytest

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
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
from kagent.contracts import ClawRunStatus, ContractError, ExecutionMode
from kagent.p01_adapter import (
    ClawOrchestrationOutcome,
    P01AdapterError,
    P01CoreOrchestrationAdapter,
)
from kagent.runs import ClawRun
from kagent.workspace_visibility import (
    TrustedWorkspaceMembershipProjection,
    WorkspaceRole,
)

from app import claw_automation_execution_bridge as bridge_module
from app.claw_automation_execution_bridge import (
    AutomationExecutionBridgeError,
    CanonicalScheduledExecutionPlan,
    P01ExecutionPort,
    execute_scheduled_occurrence,
    plan_canonical_scheduled_execution,
)

NOW = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
SCHED = NOW.replace(second=0, microsecond=0)
WORKSPACE = "workspace_a"
OTHER_WORKSPACE = "workspace_b"
RULE_ID = "rule_s2f4b_1"
REVISION = "a" * 40
INTENT_TASK = "Summarize the queued alerts for the on-call rotation"
REPO = "repo:padiem/ai-revenue-lab"
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")
MEMBERSHIP = TrustedWorkspaceMembershipProjection(
    membership_id="membership:owner",
    workspace_id=WORKSPACE,
    principal_ref="principal:user",
    role=WorkspaceRole.OWNER,
    authority_ref="control-plane:membership",
    issued_at=NOW - timedelta(hours=1),
    expires_at=NOW + timedelta(hours=1),
)

_BRIDGE_SOURCE = Path(bridge_module.__file__).read_text(encoding="utf-8")


def make_rule(
    *,
    rule_id=RULE_ID,
    workspace_id=WORKSPACE,
    execution_intent=None,
    enabled=True,
):
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="S2F4B display label",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.ALERT,
        enabled=enabled,
        execution_intent=execution_intent,
    )


def execution_intent() -> ClawAutomationExecutionIntent:
    return ClawAutomationExecutionIntent(
        task=INTENT_TASK,
        repository_ref=REPO,
        exact_revision=REVISION,
    )


def derived_run_id(*, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled=SCHED) -> str:
    return _derived_occurrence_id("sched_run", workspace_id, rule_id, scheduled)


def scheduled_row(
    *,
    run_id=None,
    workspace_id=WORKSPACE,
    rule_id=RULE_ID,
    scheduled=SCHED,
) -> ClawScheduledRun:
    return ClawScheduledRun(
        run_id=run_id or derived_run_id(workspace_id=workspace_id, rule_id=rule_id),
        workspace_id=workspace_id,
        rule_id=rule_id,
        status=ClawScheduledRunStatus.PENDING,
        scheduled_time=scheduled,
        started_at=scheduled,
    )


class RecordingP01Adapter:
    """Fake P01 port: records every execute() call and its exact arguments."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_with = fail_with

    async def execute(self, run, *, lease=None, product_tier=None):
        self.calls.append({"run": run, "lease": lease, "product_tier": product_tier})
        if self.fail_with is not None:
            raise self.fail_with
        return ClawOrchestrationOutcome(
            projection=run.projection(),
            answer=None,
            p01_run_id="p01_fake_run",
            p01_event_count=1,
        )


class CountingP01Runner:
    """Runner for the REAL adapter: must never be reached without a lease."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request):  # pragma: no cover - fail-closed proof
        self.calls += 1
        raise AssertionError("P01 runner must not be reached without a lease")


# ── SAME_SCHEDULED_RUN_ID_TO_P01 ────────────────────────────────────────────


async def test_execute_called_exactly_once_with_the_scheduled_run_id() -> None:
    rule = make_rule(execution_intent=execution_intent())
    row = scheduled_row()
    adapter = RecordingP01Adapter()

    outcome = await execute_scheduled_occurrence(
        rule=rule, scheduled_run=row, adapter=adapter
    )

    assert len(adapter.calls) == 1
    executed = adapter.calls[0]["run"]
    assert isinstance(executed, ClawRun)
    assert executed.run_id == row.run_id == derived_run_id()
    assert executed.run_id.startswith("sched_run_")
    assert outcome.projection.run_id == row.run_id
    assert adapter.calls[0]["lease"] is None
    assert adapter.calls[0]["product_tier"] is None


async def test_end_to_end_from_existing_tick_occurrence_to_p01() -> None:
    store = InMemoryClawAutomationStore()
    store.save_rule(make_rule(execution_intent=execution_intent()))
    receipt = ClawAutomationTickRuntime(store).tick(
        workspace_id=WORKSPACE, current_time=SCHED, membership=MEMBERSHIP
    )
    assert len(receipt.created_run_ids) == 1
    row = store.get_run(receipt.created_run_ids[0], WORKSPACE)
    assert row is not None
    rule = store.get_rule(RULE_ID, WORKSPACE)
    assert rule is not None

    adapter = RecordingP01Adapter()
    await execute_scheduled_occurrence(
        rule=rule, scheduled_run=row, adapter=adapter
    )

    assert len(adapter.calls) == 1
    assert adapter.calls[0]["run"].run_id == receipt.created_run_ids[0]
    # A second tick stays deduplicated by the existing occurrence claim — this
    # bridge adds no second dedup authority and never claims.
    replay = ClawAutomationTickRuntime(store).tick(
        workspace_id=WORKSPACE, current_time=SCHED, membership=MEMBERSHIP
    )
    assert replay.created_run_ids == ()
    assert replay.due_count == 0
    assert len(store.list_runs(WORKSPACE)) == 1


# ── CANONICAL REUSE ─────────────────────────────────────────────────────────


def test_plan_reuses_the_canonical_claw_run_and_intent() -> None:
    rule = make_rule(execution_intent=execution_intent())
    plan = plan_canonical_scheduled_execution(rule, scheduled_row())

    assert isinstance(plan, CanonicalScheduledExecutionPlan)
    assert isinstance(plan.run, ClawRun)
    assert plan.run.status is ClawRunStatus.QUEUED
    assert plan.intent is plan.run.intent
    assert plan.intent.source_surface == "automation"
    assert plan.intent.execution_mode is ExecutionMode.CLOUD
    assert plan.intent.requested_revision == REVISION
    assert plan.intent.task == INTENT_TASK
    assert plan.intent.repository_ref == REPO
    # Display labels are never reinterpreted as instruction.
    assert plan.intent.task != rule.name


def test_second_plan_never_mints_a_second_run_id() -> None:
    rule = make_rule(execution_intent=execution_intent())
    first = plan_canonical_scheduled_execution(rule, scheduled_row())
    second = plan_canonical_scheduled_execution(rule, scheduled_row())

    assert first.run.run_id == second.run.run_id == derived_run_id()
    assert not first.run.run_id.startswith("run_")


def test_existing_p01_adapter_structurally_satisfies_the_port() -> None:
    real = P01CoreOrchestrationAdapter(CountingP01Runner())
    fake = RecordingP01Adapter()

    assert isinstance(real, P01ExecutionPort)
    assert isinstance(fake, P01ExecutionPort)


# ── SCOPE PRESERVATION ──────────────────────────────────────────────────────


def test_workspace_and_rule_scope_are_preserved() -> None:
    rule = make_rule(execution_intent=execution_intent())
    plan = plan_canonical_scheduled_execution(rule, scheduled_row())

    assert plan.rule is rule
    assert plan.rule.workspace_id == WORKSPACE
    assert plan.scheduled_run.workspace_id == WORKSPACE
    assert plan.scheduled_run.rule_id == RULE_ID
    assert plan.run.run_id == derived_run_id()


async def test_requested_revision_is_preserved_end_to_end() -> None:
    rule = make_rule(execution_intent=execution_intent())
    adapter = RecordingP01Adapter()

    await execute_scheduled_occurrence(
        rule=rule, scheduled_run=scheduled_row(), adapter=adapter
    )

    intent = adapter.calls[0]["run"].intent
    assert intent.requested_revision == REVISION
    assert intent.execution_mode is ExecutionMode.CLOUD
    assert intent.source_surface == "automation"


# ── FAIL CLOSED ─────────────────────────────────────────────────────────────


async def test_run_id_mismatch_fails_closed_without_dispatch() -> None:
    rule = make_rule(execution_intent=execution_intent())
    # Same workspace and rule, but a run id derived from another instant: the
    # canonical digest and the row disagree, so execution must be refused.
    foreign = scheduled_row(
        run_id=derived_run_id(scheduled=SCHED + timedelta(minutes=1))
    )
    adapter = RecordingP01Adapter()

    with pytest.raises(AutomationExecutionBridgeError):
        await execute_scheduled_occurrence(
            rule=rule, scheduled_run=foreign, adapter=adapter
        )
    assert adapter.calls == []


async def test_workspace_and_rule_mismatch_fail_closed() -> None:
    rule = make_rule(execution_intent=execution_intent())
    adapter = RecordingP01Adapter()

    with pytest.raises(AutomationExecutionBridgeError):
        await execute_scheduled_occurrence(
            rule=rule,
            scheduled_run=scheduled_row(workspace_id=OTHER_WORKSPACE),
            adapter=adapter,
        )

    with pytest.raises(AutomationExecutionBridgeError):
        await execute_scheduled_occurrence(
            rule=rule,
            scheduled_run=scheduled_row(rule_id="rule_other"),
            adapter=adapter,
        )
    assert adapter.calls == []


async def test_legacy_rule_without_execution_intent_fails_closed() -> None:
    rule = make_rule(execution_intent=None)
    adapter = RecordingP01Adapter()

    with pytest.raises(ContractError):
        await execute_scheduled_occurrence(
            rule=rule, scheduled_run=scheduled_row(), adapter=adapter
        )
    assert adapter.calls == []


async def test_wrong_input_types_fail_closed() -> None:
    adapter = RecordingP01Adapter()

    with pytest.raises(AutomationExecutionBridgeError):
        plan_canonical_scheduled_execution("not-a-rule", scheduled_row())
    with pytest.raises(AutomationExecutionBridgeError):
        plan_canonical_scheduled_execution(
            make_rule(execution_intent=execution_intent()), "not-a-row"
        )
    with pytest.raises(AutomationExecutionBridgeError):
        await execute_scheduled_occurrence(
            rule=make_rule(execution_intent=execution_intent()),
            scheduled_run=scheduled_row(),
            adapter=object(),
        )
    assert adapter.calls == []


async def test_p01_failure_propagates_fail_closed() -> None:
    rule = make_rule(execution_intent=execution_intent())
    adapter = RecordingP01Adapter(
        fail_with=P01AdapterError("p01_execution_failed", "boom")
    )

    with pytest.raises(P01AdapterError):
        await execute_scheduled_occurrence(
            rule=rule, scheduled_run=scheduled_row(), adapter=adapter
        )
    # The attempt happened exactly once and was not converted into a success.
    assert len(adapter.calls) == 1


async def test_real_adapter_without_lease_fails_closed_before_runner() -> None:
    runner = CountingP01Runner()
    adapter = P01CoreOrchestrationAdapter(runner)
    rule = make_rule(execution_intent=execution_intent())

    with pytest.raises(P01AdapterError) as raised:
        await execute_scheduled_occurrence(
            rule=rule, scheduled_run=scheduled_row(), adapter=adapter
        )

    assert raised.value.code == "cloud_lease_required"
    assert raised.value.dispatch_class == "not_dispatched"
    # NO_DIRECT_PROVIDER_CALL / NO_NEW_SANDBOX_AUTHORITY: the existing adapter
    # refused before dispatch and this bridge minted no lease to get past it.
    assert runner.calls == 0


async def test_real_adapter_marks_the_canonical_run_failed_without_lease() -> None:
    runner = CountingP01Runner()
    adapter = P01CoreOrchestrationAdapter(runner)
    plan = plan_canonical_scheduled_execution(
        make_rule(execution_intent=execution_intent()), scheduled_row()
    )

    with pytest.raises(P01AdapterError):
        await adapter.execute(plan.run)

    assert plan.run.status is ClawRunStatus.FAILED
    assert runner.calls == 0


# ── ASYNC BOUNDARY ──────────────────────────────────────────────────────────


def test_sync_plan_and_async_execute_boundary() -> None:
    assert not inspect.iscoroutinefunction(plan_canonical_scheduled_execution)
    assert inspect.iscoroutinefunction(execute_scheduled_occurrence)
    # The sync plan runs with no event loop involved.
    plan = plan_canonical_scheduled_execution(
        make_rule(execution_intent=execution_intent()), scheduled_row()
    )
    assert plan.run.status is ClawRunStatus.QUEUED


# ── SOURCE-SCAN GUARDS ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "forbidden",
    [
        # SECOND_RUN_ID / no manual run-id helper
        "create_claw_run(",
        "execute_p01_claw_task(",
        "run_p01_task(",
        # ASYNC BOUNDARY: no private event loop
        "asyncio.run(",
        "asyncio.get_event_loop",
        # NO_NEW_SANDBOX_AUTHORITY / CALLER_MINTED_LEASE=NO
        "SandboxLeasePort",
        "SandboxLease(",
        "allocate(",
        "DeterministicFakeSandboxProvider",
        "UnconfiguredSandboxProvider",
        # SECOND_SCHEDULER_AUTHORITY=0
        "ClawAutomationTickRuntime",
        "FakeClawScheduler",
        "occurrence_key(",
        # SECOND_OWNER_AUTHORITY=0
        "resolve_owner",
        "ResolvedAutomationOwner",
        # later-slice surfaces stay out
        "record_claw_run(",
        "project_scheduled_run_output(",
        # NO_DIRECT_PROVIDER_CALL / NO_NEW_MODEL_ROUTER
        "active_route_for",
        "model_policy",
        "AgentProfile",
        "urllib",
        "httpx",
        "PadiemAiEngineClient",
        "P01EngineOrchestrationClient",
        "p01_adapter_from_environment",
    ],
)
def test_bridge_source_contains_no_forbidden_authority(forbidden: str) -> None:
    assert forbidden not in _BRIDGE_SOURCE


def test_duplicate_execution_helper_is_zero() -> None:
    assert _BRIDGE_SOURCE.count("adapter.execute(") == 1
    assert _BRIDGE_SOURCE.count("async def execute_scheduled_occurrence(") == 1
