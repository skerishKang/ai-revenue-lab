"""#2833 S2F4B — canonical scheduled execution bridge to the existing P01 adapter.

CONNECTS an occurrence the trusted trigger path already claimed to the existing
P01 execution path, without minting any new identity or authority:

```text
existing ClawScheduledRun (claimed occurrence row)
+ existing ClawAutomationRule (S2F1 execution intent)
        |
        v  canonical_claw_run_for_occurrence()      (existing S2F2 helper)
existing ClawRun(run_id = sched_run_<digest>)       (QUEUED lifecycle container)
        |
        v  await <the existing P01 adapter>.execute(run, ...)   (existing P01)
```

Invariants pinned here:

* ``SECOND_RUN_ID=0`` — the ClawRun handed to P01 is the occurrence-derived
  ``sched_run_<digest>``; the manual ``create_claw_run`` helper and every
  ``run_<uuid>`` generator are refused surfaces of this module.
* ``SECOND_DEDUP_AUTHORITY=0`` — the existing occurrence claim stays the only
  dedup authority; this bridge neither claims, nor re-checks, nor re-records
  claims.
* ``SECOND_SCHEDULER_AUTHORITY=0`` — no scheduling and no due-occurrence math:
  callers hand in an occurrence the existing tick/trigger path materialized.
* ``SECOND_OWNER_AUTHORITY=0`` — no owner resolution; ``owner_ref`` is never
  read here.
* ``SECOND_P01_AUTHORITY=0`` — execution is the already-composed
  ``P01CoreOrchestrationAdapter``; no runner, client, model router, or
  provider transport is constructed in this module.
* ``NEW_SANDBOX_AUTHORITY=NO`` / ``CALLER_MINTED_LEASE=NO`` — no sandbox lease
  is ever minted here. An already-issued lease may be passed through unchanged;
  without one the existing adapter fails closed (``cloud_lease_required``)
  before any dispatch.
* ASYNC BOUNDARY — ``plan_canonical_scheduled_execution`` is plain sync code
  for the sync scheduler world; ``execute_scheduled_occurrence`` is an
  ``async def`` that must be awaited on the caller's event loop. This module
  never starts a private event loop and never converts a sync scheduler
  authority into an execution authority.

Non-goals (later slices): terminal output attachment (#2914), History write,
Task/Alert projection invocation, real cloud scheduler activation, Production
cron registration, external send/write, any provider call, any Production
mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from kagent.claw_automation import (
    ClawAutomationRule,
    ClawScheduledRun,
    canonical_claw_run_for_occurrence,
)
from kagent.contracts import ClawTaskIntent, SandboxLease
from kagent.p01_adapter import ClawOrchestrationOutcome
from kagent.runs import ClawRun


class AutomationExecutionBridgeError(RuntimeError):
    """Fail-closed refusal raised before any P01 dispatch attempt."""


@runtime_checkable
class P01ExecutionPort(Protocol):
    """Structural surface of the existing P01 adapter.

    ``P01CoreOrchestrationAdapter`` satisfies this as-is; a test fake may stand
    in so the composition itself, not the Engine transport, is under test.
    """

    async def execute(
        self,
        run: ClawRun,
        *,
        lease: SandboxLease | None = None,
        product_tier: Any | None = None,
    ) -> ClawOrchestrationOutcome: ...


@dataclass(frozen=True, slots=True)
class CanonicalScheduledExecutionPlan:
    """Side-effect-free bridge material for exactly one scheduled occurrence."""

    rule: ClawAutomationRule
    scheduled_run: ClawScheduledRun
    run: ClawRun

    @property
    def intent(self) -> ClawTaskIntent:
        return self.run.intent


def plan_canonical_scheduled_execution(
    rule: ClawAutomationRule,
    scheduled_run: ClawScheduledRun,
) -> CanonicalScheduledExecutionPlan:
    """Build (never dispatch) the canonical ClawRun for one existing occurrence.

    Sync and pure: no I/O, no event loop, no store write, no occurrence claim,
    no owner resolution. The run id is derived by the existing canonical helper
    from the occurrence identity and then checked against the scheduled row, so
    a mismatched row fails closed instead of executing under a foreign id.
    """

    if not isinstance(rule, ClawAutomationRule):
        raise AutomationExecutionBridgeError("rule must be a ClawAutomationRule")
    if not isinstance(scheduled_run, ClawScheduledRun):
        raise AutomationExecutionBridgeError(
            "scheduled_run must be a ClawScheduledRun"
        )
    if scheduled_run.workspace_id != rule.workspace_id:
        raise AutomationExecutionBridgeError(
            "scheduled run workspace does not match the rule workspace"
        )
    if scheduled_run.rule_id != rule.rule_id:
        raise AutomationExecutionBridgeError(
            "scheduled run rule does not match the rule"
        )
    # Existing S2F2 authority: derives sched_run_<digest> and the canonical
    # automation intent from the occurrence identity. A legacy rule without an
    # execution intent raises the canonical ContractError — fail closed here,
    # never inferred by this bridge.
    run, _intent = canonical_claw_run_for_occurrence(
        rule, scheduled_run.scheduled_time
    )
    if run.run_id != scheduled_run.run_id:
        raise AutomationExecutionBridgeError(
            "canonical run id does not match the scheduled occurrence run id"
        )
    return CanonicalScheduledExecutionPlan(
        rule=rule, scheduled_run=scheduled_run, run=run
    )


async def execute_scheduled_occurrence(
    *,
    rule: ClawAutomationRule,
    scheduled_run: ClawScheduledRun,
    adapter: P01ExecutionPort,
    lease: SandboxLease | None = None,
    product_tier: Any | None = None,
) -> ClawOrchestrationOutcome:
    """Hand the canonical ClawRun to the existing P01 adapter, exactly once.

    ``adapter`` must already be composed by an existing authority (the Worker
    binding composition or the environment composition); this bridge composes
    nothing. ``lease`` is pass-through only: a lease for a different run is
    refused here, and the absence of a lease is left for the existing adapter's
    own cloud fail-closed rule. A P01 failure propagates unchanged so the
    occurrence fails closed rather than being reported as a success.
    """

    if not callable(getattr(adapter, "execute", None)):
        raise AutomationExecutionBridgeError(
            "adapter must expose an async execute method"
        )
    plan = plan_canonical_scheduled_execution(rule, scheduled_run)
    if lease is not None and lease.run_id != plan.run.run_id:
        raise AutomationExecutionBridgeError(
            "sandbox lease does not belong to the canonical scheduled run"
        )
    return await adapter.execute(plan.run, lease=lease, product_tier=product_tier)


__all__ = [
    "AutomationExecutionBridgeError",
    "CanonicalScheduledExecutionPlan",
    "P01ExecutionPort",
    "execute_scheduled_occurrence",
    "plan_canonical_scheduled_execution",
]
