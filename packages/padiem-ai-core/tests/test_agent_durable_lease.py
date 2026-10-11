"""#4194: durable run lease/checkpoint/cancellation contract (no model/network)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core.agent_durable_lease import (
    AgentDurableLeaseError,
    AgentRunLease,
    SQLiteAgentDurableRunLedger,
    DURABLE_LEDGER_AUTO_RETRIES_EXTERNAL_TOOLS,
    DURABLE_LEDGER_AUTHORIZES_APPROVAL,
    DURABLE_LEDGER_SUPPORTS_POST_TOOL_RESUME,
)
from padiem_ai_core.agent_execution_bridge import AgentPlanExecutor
from padiem_ai_core.agent_runtime import AgentRuntimeError
from padiem_ai_core import AgentPlan, AgentPlanStep, ToolRuntime

# Existing tested P01 authority fixtures; do NOT invent an authorization grant.
from test_agent_execution_bridge import (
    make_agent_def, make_compiled_profile, make_auth_ctx, make_calc_spec,
)

SHA = "a" * 64
OTHER = "b" * 64


class Clock:
    def __init__(self):
        self.current = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def __call__(self):
        return self.current

    def advance(self, seconds: float):
        self.current += timedelta(seconds=seconds)


@pytest.fixture
def context(tmp_path):
    clock = Clock()
    path = tmp_path / "owned-run.sqlite"
    ledger = SQLiteAgentDurableRunLedger(database_path=path, clock=clock)
    return ledger, clock, path


def start(ledger):
    return ledger.start(run_id="agent-run-one", owner_scope="ownerA:workspaceA",
                        request_fingerprint=SHA, worker_id="host1", lease_seconds=10)


def test_persists_across_reopen_and_fences_duplicate_dispatch(context):
    ledger, clock, path = context
    lease = start(ledger)
    ledger_again = SQLiteAgentDurableRunLedger(database_path=path, clock=clock)
    assert ledger_again.is_active(lease)
    with pytest.raises(AgentDurableLeaseError, match="already exists"):
        start(ledger_again)
    assert ledger_again.status(run_id=lease.run_id, owner_scope=lease.owner_scope,
                               request_fingerprint=SHA) == ("running", 1, 0)
    assert ledger_again.status(run_id=lease.run_id, owner_scope="ownerB:workspaceB",
                               request_fingerprint=SHA) is None
    assert ledger_again.status(run_id=lease.run_id, owner_scope=lease.owner_scope,
                               request_fingerprint=OTHER) is None


def test_heartbeat_renews_only_live_fenced_lease(context):
    ledger, clock, _ = context
    lease = start(ledger)
    clock.advance(8)
    assert ledger.heartbeat(lease, lease_seconds=10)
    clock.advance(9)
    assert ledger.is_active(lease)
    clock.advance(1)
    assert not ledger.is_active(lease)
    assert not ledger.heartbeat(lease)
    assert ledger.quarantine_expired() == 1
    assert ledger.status(run_id=lease.run_id, owner_scope=lease.owner_scope,
                         request_fingerprint=SHA) == ("needs_review", 2, 0)
    assert ledger.resume_prework(run_id=lease.run_id, owner_scope=lease.owner_scope,
                                request_fingerprint=SHA, worker_id="host2") is None


def test_just_expired_lease_fails_closed_on_exact_boundary(context):
    ledger, clock, _ = context
    lease = start(ledger)
    clock.advance(10)
    assert not ledger.is_active(lease)
    assert not ledger.checkpoint(lease, completed_step=1)
    assert not ledger.finish(lease, state="completed")
    assert ledger.quarantine_expired() == 1
    assert ledger.quarantine_expired() == 0


def test_cancellation_revokes_live_worker_and_never_resumes(context):
    ledger, clock, _ = context
    lease = start(ledger)
    assert not ledger.cancel(run_id=lease.run_id, owner_scope="intruder",
                             request_fingerprint=SHA)
    assert not ledger.cancel(run_id=lease.run_id, owner_scope=lease.owner_scope,
                             request_fingerprint=OTHER)
    assert ledger.cancel(run_id=lease.run_id, owner_scope=lease.owner_scope,
                         request_fingerprint=SHA)
    assert not ledger.is_active(lease)
    assert not ledger.heartbeat(lease)
    assert not ledger.finish(lease, state="completed")
    assert not ledger.cancel(run_id=lease.run_id, owner_scope=lease.owner_scope,
                             request_fingerprint=SHA)
    assert ledger.status(run_id=lease.run_id, owner_scope=lease.owner_scope,
                         request_fingerprint=SHA) == ("cancelled", 2, 0)


def test_prework_pause_resume_fences_old_host_and_is_one_shot(context):
    ledger, clock, _ = context
    first = start(ledger)
    assert ledger.pause_before_work(first)
    assert not ledger.is_active(first)
    assert ledger.resume_prework(run_id=first.run_id, owner_scope="other",
                                request_fingerprint=SHA, worker_id="host2") is None
    second = ledger.resume_prework(run_id=first.run_id, owner_scope=first.owner_scope,
                                   request_fingerprint=SHA, worker_id="host2")
    assert isinstance(second, AgentRunLease)
    assert second.epoch == 3
    assert not ledger.is_active(first)
    assert ledger.is_active(second)
    assert ledger.resume_prework(run_id=first.run_id, owner_scope=first.owner_scope,
                                request_fingerprint=SHA, worker_id="host3") is None
    assert ledger.finish(second, state="completed")
    assert not ledger.is_active(second)
    assert not ledger.pause_before_work(second)
    assert not ledger.finish(second, state="completed")


def test_checkpoint_tracks_progress_but_never_allows_post_tool_replay(context):
    ledger, _, _ = context
    lease = start(ledger)
    assert ledger.begin_execution(lease)  # dispatch irreversibly marks uncertain
    assert ledger.checkpoint(lease, completed_step=2)  # default marks uncertain
    assert not ledger.checkpoint(lease, completed_step=1)
    assert not ledger.pause_before_work(lease)
    assert ledger.status(run_id=lease.run_id, owner_scope=lease.owner_scope,
                         request_fingerprint=SHA) == ("running", 1, 2)
    assert ledger.finish(lease, state="awaiting_approval")
    assert ledger.resume_prework(run_id=lease.run_id, owner_scope=lease.owner_scope,
                                request_fingerprint=SHA, worker_id="host2") is None


def test_execution_guard_atomically_blocks_prework_reclaim(context):
    ledger, _, _ = context
    lease = start(ledger)
    guard = ledger.execution_guard(lease)
    assert guard()
    assert not ledger.pause_before_work(lease)
    # Cannot "downgrade" uncertainty after model or tool dispatch.
    assert ledger.checkpoint(lease, completed_step=0, side_effect_uncertain=False)
    assert not ledger.pause_before_work(lease)
    assert ledger.finish(lease, state="completed")
    assert not guard()


def test_only_step_zero_can_pause_even_if_no_side_effects(context):
    ledger, _, _ = context
    lease = start(ledger)
    assert ledger.checkpoint(lease, completed_step=1, side_effect_uncertain=False)
    assert not ledger.pause_before_work(lease)
    assert ledger.finish(lease, state="failed")
    assert not ledger.is_active(lease)


@pytest.mark.parametrize("duration", [0, -1, 3601, True, 2.0, "60"])
def test_invalid_lease_durations_fail_closed(context, duration):
    ledger, _, _ = context
    with pytest.raises(AgentDurableLeaseError):
        ledger.start(run_id="r", owner_scope="a", request_fingerprint=SHA,
                     worker_id="w", lease_seconds=duration)


def test_untrusted_identity_and_unsafe_storage_rejected(context, tmp_path):
    ledger, _, _ = context
    with pytest.raises(AgentDurableLeaseError):
        ledger.start(run_id="bad\nnewline", owner_scope="a",
                     request_fingerprint=SHA, worker_id="w")
    with pytest.raises(AgentDurableLeaseError):
        ledger.start(run_id="a", owner_scope="a", request_fingerprint="not-a-hash",
                     worker_id="w")
    with pytest.raises(AgentDurableLeaseError):
        SQLiteAgentDurableRunLedger(database_path=tmp_path / "missing" / "run.db")
    with pytest.raises(AgentDurableLeaseError):
        ledger.checkpoint(start(ledger), completed_step=True)
    assert not DURABLE_LEDGER_AUTO_RETRIES_EXTERNAL_TOOLS
    assert not DURABLE_LEDGER_AUTHORIZES_APPROVAL
    assert not DURABLE_LEDGER_SUPPORTS_POST_TOOL_RESUME


async def test_approved_agent_bridge_opt_in_guard_blocks_tool_after_cancel(context):
    ledger, _, _ = context
    lease = start(ledger)
    definition = make_agent_def()
    compiled = make_compiled_profile(definition)
    auth = make_auth_ctx(compiled.runtime_profile.id)
    runtime = ToolRuntime()
    count = 0

    async def handler(arguments):
        nonlocal count
        count += 1
        return {"ok": True}

    runtime.register(make_calc_spec(), handler)
    plan = AgentPlan(
        agent_id=definition.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Calculate", tool_id="calc"),),
    )
    ledger.cancel(run_id=lease.run_id, owner_scope=lease.owner_scope,
                  request_fingerprint=SHA)
    with pytest.raises(AgentRuntimeError, match="no longer active") as err:
        await AgentPlanExecutor().execute(
            plan=plan, definition=definition, compiled_profile=compiled,
            authorization=auth, tool_runtime=runtime, input_text="hello",
            run_id=lease.run_id, run_guard=ledger.execution_guard(lease),
        )
    assert err.value.code == "agent_run_fenced"
    assert count == 0


async def test_guard_detects_cancel_during_tool_without_second_dispatch(context):
    ledger, _, _ = context
    lease = start(ledger)
    definition = make_agent_def()
    compiled = make_compiled_profile(definition)
    auth = make_auth_ctx(compiled.runtime_profile.id)
    runtime = ToolRuntime()
    count = 0

    async def handler(arguments):
        nonlocal count
        count += 1
        ledger.cancel(run_id=lease.run_id, owner_scope=lease.owner_scope,
                      request_fingerprint=SHA)
        return {"result": 42}

    runtime.register(make_calc_spec(), handler)
    plan = AgentPlan(
        agent_id=definition.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Use tool", tool_id="calc"),
               AgentPlanStep(step_id="s2", objective="Synthesize", depends_on=("s1",))),
    )
    with pytest.raises(AgentRuntimeError) as err:
        await AgentPlanExecutor().execute(
            plan=plan, definition=definition, compiled_profile=compiled,
            authorization=auth, tool_runtime=runtime, input_text="hello",
            run_id=lease.run_id, run_guard=ledger.execution_guard(lease),
        )
    assert err.value.code == "agent_run_fenced"
    assert count == 1  # executed side effect is never replayed by Core
