"""#2833 S2F5B — recovery-safe PENDING occurrence execution composition.

COMPOSITION BOUNDARY ONLY. Every authority this lane needs already exists on
main; this module composes them, and the only new seam is the store's
conditional execution claim (``ClawAutomationStore.claim_execution``).

Canonical path:

```text
trusted ClawAutomationTrigger
        |
        v  existing ClawAutomationTriggerBoundary.handle()      (#2894)
existing durable tick / existing occurrence_key dedup            (#2940)
        |
        +--> newly created PENDING rows
        |
        +--> bounded recovery scan of EXISTING PENDING rows in the same workspace
                 (current rule + enablement + membership validity + the existing
                  occurrence-derived sched_run_<digest> identity)
        |
        v  existing ClawAutomationOwnerResolver.resolve_owner()
        |
        v  existing-store atomic PENDING -> RUNNING execution claim
        |
        v  existing execute_and_project_scheduled_occurrence()   (#2915/#2922)
        |
        v  existing project_terminal_scheduled_run_to_history()  (#2927)
        v  existing project_terminal_scheduled_run_to_task_alert() (#2933)
```

Why the claim exists. After #2940 a durable tick can claim a ``PENDING`` row and
the process can die before executing it. The next trigger deduplicates that
occurrence, so a composition that executes only ``created_run_ids`` would strand
the row forever; blindly re-running a ``RUNNING`` row would duplicate P01 side
effects. The claim resolves both: exactly one caller turns ``PENDING`` into
``RUNNING``, and ``RUNNING``/``COMPLETED``/``FAILED``/``CANCELLED`` are never
dispatched again.

Invariants pinned here:

* ``PENDING_RECOVERY=YES`` — stranded ``PENDING`` rows in the trigger's own
  workspace are recovered, bounded by an explicit per-trigger maximum that is
  reported in the receipt. No other workspace is enumerated, no catch-up
  occurrence is created, and no future row is executed.
* ``AT_MOST_ONE_EXECUTION_CLAIM=YES`` — the claim is the existing scheduled-run
  row and status column. No new lock table, claim token, lease row, dedup key or
  run id is introduced, and the composition mints no sandbox lease.
* ``RUNNING_REDISPATCH=0`` / ``TERMINAL_P01_REDISPATCH=0`` — a ``RUNNING`` row is
  reported as bounded unresolved work and is deliberately NOT reconciled in this
  slice: a stuck row is preferred over duplicated external side effects. A
  terminal row is only ever retried through the existing projections.
* ``SECOND_*_AUTHORITY=0`` — scheduler, run id, dedup, owner, P01, history,
  session and Task/Alert authority all stay with their existing owners. This
  module constructs no Engine client, model router, provider transport, runner
  or record shape.
* OWNER IS RESOLVED, NEVER INFERRED — the rule's ``owner_ref`` is opaque
  provenance only. It is resolved through the existing owner authority, and a
  missing, foreign, expired or mismatched owner/session fails closed before the
  claim and before any dispatch. No client/browser identity enters this path.
* A DISPATCHABLE-BUT-UNAUTHORIZED ROW STAYS ``PENDING``. Because the owner check
  precedes the claim, a row whose owner cannot be resolved is never claimed and is
  never terminalized by this module. It is reported in
  ``failed_before_dispatch_run_ids`` on every trigger and remains recoverable once
  the owner authority can resolve it. Fabricating a terminal state for it would
  require a terminalization authority this slice deliberately does not create.
* EXTERNAL_SEND=0 / PROVIDER_CALLS=0 / CONNECTOR_WRITE=0 / REAL_SANDBOX_ALLOCATIONS=0
  / PRODUCTION_SCHEDULER_ACTIVATION=0 / PRODUCTION_MUTATION=0 — no path in this
  module can raise any of them. Actual cloud cron registration and Production
  scheduler activation are NOT part of this slice.
* A projection-authority failure propagates unchanged. This composition never
  swallows an authority error and never reports an unexecuted dispatch as done.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from kagent.claw_automation import (
    ClawAutomationOutput,
    ClawAutomationRule,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    ContractError,
    _aware_utc,
    _derived_occurrence_id,
    _safe_id,
)
from kagent.claw_automation_trigger import (
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
)
from kagent.contracts import SandboxLease
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection

from .claw_automation_execution_bridge import P01ExecutionPort
from .claw_automation_history_bridge import project_terminal_scheduled_run_to_history
from .claw_automation_owner_resolution import (
    ClawAutomationOwnerResolver,
    ResolvedAutomationOwner,
)
from .claw_automation_projection_bridge import ClawTaskAlertProjectionStore
from .claw_automation_task_alert_bridge import project_terminal_scheduled_run_to_task_alert
from .claw_automation_terminal_outcome_bridge import (
    execute_and_project_scheduled_occurrence,
)
from .history import HistoryStore

__all__ = [
    "BackgroundExecutionCompositionError",
    "BackgroundExecutionReceipt",
    "BackgroundExecutionStore",
    "compose_background_execution",
]

# Fail closed on status evolution: only statuses explicitly classified as
# terminal may be treated as "never dispatched again". A new enum member is
# rejected until this allow-list and its contract test are deliberately updated.
_TERMINAL_STATUSES = frozenset(
    {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }
)

# One trigger may recover at most this many stranded rows by default. The bound
# is explicit so a single trigger can never drain an unbounded backlog, and it is
# reported in the receipt rather than being an invisible constant.
_DEFAULT_RECOVERY_BOUND = 8
_MAX_RECOVERY_BOUND = 64

_ID_TUPLE_FIELDS = (
    "newly_claimed_run_ids",
    "recovered_pending_run_ids",
    "execution_claimed_run_ids",
    "terminal_run_ids",
    "projection_only_run_ids",
    "running_unresolved_run_ids",
    "failed_before_dispatch_run_ids",
    "dispatch_failed_run_ids",
)


class BackgroundExecutionCompositionError(RuntimeError):
    """Fail-closed refusal raised before any dispatch attempt."""


class BackgroundExecutionStore(Protocol):
    """The existing automation-store surface this composition consumes.

    Every method here already belongs to ``ClawAutomationStore``; this Protocol
    only names the subset the composition needs, so a store that cannot serve it
    fails closed early instead of halfway through a trigger.
    """

    def list_runs(self, workspace_id: str) -> list[ClawScheduledRun]: ...

    def get_run(
        self, run_id: str, workspace_id: str
    ) -> ClawScheduledRun | None: ...

    def get_rule(
        self, rule_id: str, workspace_id: str
    ) -> ClawAutomationRule | None: ...

    def claim_execution(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
    ) -> ClawScheduledRun | None: ...

    def update_run_projection(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
        status: ClawScheduledRunStatus,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        output: ClawAutomationOutput | None = None,
    ) -> ClawScheduledRun: ...


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class BackgroundExecutionReceipt:
    """Bounded, non-secret evidence for exactly one composed trigger.

    Counts and canonical run ids only: no output body, no provider payload, no
    credential material, no tenant/subject id, no owner internals and no tool
    arguments. It answers only "what did this trigger claim, execute and
    project", never "what did the run produce".
    """

    workspace_id: str
    trigger_id: str
    observed_at: datetime
    recovery_bound: int
    newly_claimed_run_ids: tuple[str, ...]
    recovered_pending_run_ids: tuple[str, ...]
    execution_claimed_run_ids: tuple[str, ...]
    terminal_run_ids: tuple[str, ...]
    projection_only_run_ids: tuple[str, ...]
    running_unresolved_run_ids: tuple[str, ...]
    failed_before_dispatch_run_ids: tuple[str, ...]
    # Additive to the slice's pinned receipt list. A P01 dispatch that raised has
    # already been terminalized by the existing terminal bridge, so it must not be
    # reported as a successful terminal row; this field is the truthful bucket for
    # it. It stays bounded to ids and counts like every other field.
    dispatch_failed_run_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "trigger_id", _safe_id(self.trigger_id, "trigger_id"))
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        bound = self.recovery_bound
        if isinstance(bound, bool) or not isinstance(bound, int) or bound < 0:
            raise BackgroundExecutionCompositionError(
                "recovery_bound must be a non-negative integer"
            )
        for field_name in _ID_TUPLE_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, tuple):
                raise BackgroundExecutionCompositionError(f"{field_name} must be a tuple")
            normalised = tuple(_safe_id(item, field_name) for item in value)
            object.__setattr__(self, field_name, normalised)
            if len(normalised) != len(set(normalised)):
                raise BackgroundExecutionCompositionError(
                    f"{field_name} must not contain duplicates"
                )
        if not set(self.dispatch_failed_run_ids) <= set(self.execution_claimed_run_ids):
            raise BackgroundExecutionCompositionError(
                "a dispatch failure requires a held execution claim"
            )
        if not set(self.projection_only_run_ids) <= set(self.terminal_run_ids):
            raise BackgroundExecutionCompositionError(
                "a projection-only retry requires a terminal scheduled row"
            )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "trigger_id": self.trigger_id,
            "observed_at": _iso(self.observed_at),
            "recovery_bound": self.recovery_bound,
            "newly_claimed_run_ids": list(self.newly_claimed_run_ids),
            "recovered_pending_run_ids": list(self.recovered_pending_run_ids),
            "execution_claimed_run_ids": list(self.execution_claimed_run_ids),
            "terminal_run_ids": list(self.terminal_run_ids),
            "projection_only_run_ids": list(self.projection_only_run_ids),
            "running_unresolved_run_ids": list(self.running_unresolved_run_ids),
            "failed_before_dispatch_run_ids": list(self.failed_before_dispatch_run_ids),
            "dispatch_failed_run_ids": list(self.dispatch_failed_run_ids),
            # Side-effect locks for this slice. They are constants, not claims: the
            # composition has no path that could raise them.
            "provider_calls": 0,
            "external_sends": 0,
            "connector_writes": 0,
            "real_sandbox_allocations": 0,
            "second_scheduler_authority": 0,
            "second_run_id": 0,
            "second_dedup_authority": 0,
            "second_owner_authority": 0,
            "second_p01_authority": 0,
            "second_history_store": 0,
            "second_session_authority": 0,
            "second_task_alert_authority": 0,
            "running_auto_redispatch": 0,
            "terminal_p01_redispatch": 0,
            "production_scheduler_activation": 0,
            "production_mutation": 0,
            "client_asserted_authority": False,
        }


def _require_trigger(trigger: object) -> ClawAutomationTrigger:
    if not isinstance(trigger, ClawAutomationTrigger):
        raise BackgroundExecutionCompositionError(
            "compose_background_execution accepts a ClawAutomationTrigger only"
        )
    return trigger


def _require_boundary(boundary: object) -> ClawAutomationTriggerBoundary:
    if not isinstance(boundary, ClawAutomationTriggerBoundary):
        raise BackgroundExecutionCompositionError(
            "the existing trusted trigger boundary is required; "
            "no scheduler authority is created here"
        )
    return boundary


def _bounded_recovery_bound(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackgroundExecutionCompositionError("recovery_bound must be an integer")
    if value < 0 or value > _MAX_RECOVERY_BOUND:
        raise BackgroundExecutionCompositionError(
            f"recovery_bound must be between 0 and {_MAX_RECOVERY_BOUND}"
        )
    return value


def _rows_for_ids(
    *,
    store: BackgroundExecutionStore,
    run_ids: tuple[str, ...],
    workspace_id: str,
) -> list[ClawScheduledRun]:
    """Resolve the rows the trusted tick just claimed, or fail closed.

    A claimed occurrence the store cannot resolve is an authority violation, not
    a skip: the tick and this composition share one store, so a missing row means
    the composition is looking at the wrong authority.
    """

    rows: list[ClawScheduledRun] = []
    for run_id in run_ids:
        row = store.get_run(run_id, workspace_id)
        if row is None or row.workspace_id != workspace_id:
            raise BackgroundExecutionCompositionError(
                "the trusted tick claimed a run the automation store cannot resolve"
            )
        rows.append(row)
    return rows


def _recoverable_pending_rows(
    *,
    store: BackgroundExecutionStore,
    workspace_id: str,
    observed_at: datetime,
    membership: TrustedWorkspaceMembershipProjection,
    exclude: frozenset[str],
    bound: int,
) -> list[ClawScheduledRun]:
    """Bounded scan for PENDING rows stranded by an interrupted earlier trigger.

    Reuses the existing ``list_runs(workspace_id)`` read surface and filters only
    rows that are still legitimately executable now: same workspace, not already
    claimed by this trigger, not in the future, backed by a current enabled rule
    with the same identity, covered by the trigger's CURRENT membership projection,
    and still carrying the existing occurrence-derived ``sched_run_<digest>``
    identity.

    Membership is evaluated at the observed instant only, deliberately: the
    projection is a bounded authorization for the workspace, and a row stranded
    longer ago than one projection lifetime would otherwise be unrecoverable by
    construction. The row's own occurrence instant was authorized by the tick that
    originally claimed it; this scan adds no second membership rule.

    Rows failing any filter are left exactly as they are: this scan never repairs,
    re-claims, re-schedules or terminalizes anything.
    """

    candidates: list[ClawScheduledRun] = []
    for run in store.list_runs(workspace_id):
        if run.status is not ClawScheduledRunStatus.PENDING:
            continue
        if run.workspace_id != workspace_id or run.run_id in exclude:
            continue
        if run.scheduled_time > observed_at:
            continue
        rule = store.get_rule(run.rule_id, workspace_id)
        if rule is None:
            continue
        if rule.workspace_id != workspace_id or rule.rule_id != run.rule_id:
            continue
        if not rule.enabled:
            continue
        if not membership.valid_at(observed_at):
            continue
        expected = _derived_occurrence_id(
            "sched_run", workspace_id, run.rule_id, run.scheduled_time
        )
        if run.run_id != expected:
            continue
        candidates.append(run)
    candidates.sort(key=lambda run: (run.scheduled_time, run.run_id))
    return candidates[:bound]


def _current_enabled_rule(
    *,
    store: BackgroundExecutionStore,
    run: ClawScheduledRun,
    workspace_id: str,
) -> ClawAutomationRule | None:
    """Re-read the rule immediately before dispatch, or refuse the candidate."""

    rule = store.get_rule(run.rule_id, workspace_id)
    if rule is None:
        return None
    if rule.workspace_id != workspace_id or rule.rule_id != run.rule_id:
        return None
    if not rule.enabled:
        return None
    return rule


async def _resolve_owner_or_none(
    *,
    resolver: ClawAutomationOwnerResolver,
    rule: ClawAutomationRule,
    workspace_id: str,
    observed_at: datetime,
) -> ResolvedAutomationOwner | None:
    """Resolve the rule's opaque owner provenance, or fail closed.

    ``owner_ref`` grants no execution authority by itself: it is resolved through
    the existing owner authority and the current canonical session. A missing,
    foreign, expired or mismatched owner/session -- and an unavailable authority --
    all collapse into one non-disclosing refusal, so this path never becomes an
    oracle for another tenant's owner state.
    """

    if not callable(getattr(resolver, "resolve_owner", None)):
        raise BackgroundExecutionCompositionError(
            "owner resolution authority is unavailable; "
            "no execution may proceed without it"
        )
    if rule.owner_ref is None:
        return None
    try:
        owner = await resolver.resolve_owner(
            owner_ref=rule.owner_ref,
            workspace_id=workspace_id,
            now=observed_at,
        )
    except Exception:
        return None
    if not isinstance(owner, ResolvedAutomationOwner):
        return None
    if owner.workspace_id != workspace_id:
        return None
    return owner


async def _project_terminal_run(
    *,
    rule: ClawAutomationRule,
    scheduled_run: ClawScheduledRun,
    owner: ResolvedAutomationOwner,
    history_store: HistoryStore,
    task_alert_store: ClawTaskAlertProjectionStore,
) -> None:
    """Reuse the existing terminal projections for one already-terminal row.

    Run history first, then Task/Alert. Both authorities own their own
    idempotency, their own record shape and their own refusal surface, and both
    are read-only for a row whose output type materializes no record.
    """

    await project_terminal_scheduled_run_to_history(
        rule=rule,
        scheduled_run=scheduled_run,
        owner=owner,
        store=history_store,
    )
    await project_terminal_scheduled_run_to_task_alert(
        rule=rule,
        scheduled_run=scheduled_run,
        owner=owner,
        store=task_alert_store,
    )


async def compose_background_execution(
    *,
    trigger: ClawAutomationTrigger,
    boundary: ClawAutomationTriggerBoundary,
    store: BackgroundExecutionStore,
    adapter: P01ExecutionPort,
    owner_resolver: ClawAutomationOwnerResolver,
    history_store: HistoryStore,
    task_alert_store: ClawTaskAlertProjectionStore,
    recovery_bound: int = _DEFAULT_RECOVERY_BOUND,
    lease: SandboxLease | None = None,
    product_tier: Any | None = None,
    completed_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> BackgroundExecutionReceipt:
    """Execute one trusted trigger through the existing chain, safely.

    The trigger is handled by the existing trusted boundary, so the existing
    durable tick remains the only occurrence claim and the existing
    ``occurrence_key`` remains the only dedup authority. This function then
    composes, for the newly claimed rows plus a bounded set of stranded PENDING
    rows in the same workspace: existing owner resolution, the existing-store
    execution claim, existing canonical P01 execution and the existing terminal
    projections.

    Per-candidate work is fail-closed and bounded. A candidate that cannot be
    dispatched (owner refusal, lost claim, unexpected store state) is recorded and
    the remaining candidates still run, so one poisoned row cannot stop a
    workspace's recovery. A P01 dispatch failure is recorded separately: the
    existing terminal bridge has already terminalized that row, and this function
    does not re-terminalize it, re-dispatch it, or report it as a success.

    ``lease`` is pass-through only. This composition never mints a sandbox lease,
    and when no already-authorized lease exists the existing P01 adapter keeps its
    own fail-closed rule.
    """

    checked_trigger = _require_trigger(trigger)
    checked_boundary = _require_boundary(boundary)
    bound = _bounded_recovery_bound(recovery_bound)

    workspace_id = checked_trigger.workspace_id
    observed_at = checked_trigger.observed_at
    membership = checked_trigger.membership
    if not isinstance(membership, TrustedWorkspaceMembershipProjection):
        raise BackgroundExecutionCompositionError(
            "trigger requires a trusted workspace membership projection"
        )
    if membership.workspace_id != workspace_id:
        raise BackgroundExecutionCompositionError(
            "trigger membership projection does not cover the trigger workspace"
        )

    # 1. Existing trusted boundary -> existing durable tick -> existing dedup.
    tick = checked_boundary.handle(checked_trigger)
    newly_claimed = tuple(tick.created_run_ids)
    candidates = _rows_for_ids(
        store=store, run_ids=newly_claimed, workspace_id=workspace_id
    )

    # 2. Bounded recovery of PENDING rows stranded by an interrupted trigger.
    recovered = _recoverable_pending_rows(
        store=store,
        workspace_id=workspace_id,
        observed_at=observed_at,
        membership=membership,
        exclude=frozenset(newly_claimed),
        bound=bound,
    )

    execution_claimed: list[str] = []
    terminal: list[str] = []
    projection_only: list[str] = []
    running_unresolved: list[str] = []
    failed_before_dispatch: list[str] = []
    dispatch_failed: list[str] = []

    for run in (*candidates, *recovered):
        rule = _current_enabled_rule(store=store, run=run, workspace_id=workspace_id)
        if rule is None:
            # Filtered out by the scan, or the rule stopped being executable
            # between the scan and now. It is not a failure: nothing was claimed.
            continue
        owner = await _resolve_owner_or_none(
            resolver=owner_resolver,
            rule=rule,
            workspace_id=workspace_id,
            observed_at=observed_at,
        )
        if owner is None:
            failed_before_dispatch.append(run.run_id)
            continue

        try:
            claimed = store.claim_execution(
                run_id=run.run_id,
                workspace_id=workspace_id,
                rule_id=run.rule_id,
                scheduled_time=run.scheduled_time,
            )
        except ContractError:
            failed_before_dispatch.append(run.run_id)
            continue

        if claimed is None:
            # NOT_CLAIMED: another caller owns this row, or it is already beyond
            # PENDING. Classify from the row itself, never by dispatching again.
            current = store.get_run(run.run_id, workspace_id)
            if current is None:
                failed_before_dispatch.append(run.run_id)
                continue
            if current.status is ClawScheduledRunStatus.RUNNING:
                running_unresolved.append(run.run_id)
                continue
            if current.status in _TERMINAL_STATUSES:
                projection_only.append(run.run_id)
                terminal.append(run.run_id)
                await _project_terminal_run(
                    rule=rule,
                    scheduled_run=current,
                    owner=owner,
                    history_store=history_store,
                    task_alert_store=task_alert_store,
                )
                continue
            failed_before_dispatch.append(run.run_id)
            continue

        execution_claimed.append(run.run_id)
        try:
            projection = await execute_and_project_scheduled_occurrence(
                rule=rule,
                scheduled_run=claimed,
                adapter=adapter,
                store=store,
                lease=lease,
                product_tier=product_tier,
                completed_at=completed_at,
                clock=clock,
            )
        except Exception:
            # The existing terminal bridge has already terminalized this row. Do
            # not re-terminalize, do not re-dispatch, and do not report success.
            dispatch_failed.append(run.run_id)
            current = store.get_run(run.run_id, workspace_id)
            if current is not None and current.status in _TERMINAL_STATUSES:
                terminal.append(run.run_id)
                await _project_terminal_run(
                    rule=rule,
                    scheduled_run=current,
                    owner=owner,
                    history_store=history_store,
                    task_alert_store=task_alert_store,
                )
            continue

        terminal.append(run.run_id)
        await _project_terminal_run(
            rule=rule,
            scheduled_run=projection.scheduled_run,
            owner=owner,
            history_store=history_store,
            task_alert_store=task_alert_store,
        )

    return BackgroundExecutionReceipt(
        workspace_id=workspace_id,
        trigger_id=checked_trigger.trigger_id,
        observed_at=observed_at,
        recovery_bound=bound,
        newly_claimed_run_ids=newly_claimed,
        recovered_pending_run_ids=tuple(run.run_id for run in recovered),
        execution_claimed_run_ids=tuple(execution_claimed),
        terminal_run_ids=tuple(terminal),
        projection_only_run_ids=tuple(projection_only),
        running_unresolved_run_ids=tuple(running_unresolved),
        failed_before_dispatch_run_ids=tuple(failed_before_dispatch),
        dispatch_failed_run_ids=tuple(dispatch_failed),
    )
